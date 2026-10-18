"""Conservative DWG -> DXF -> DWG batch conversion; never saves the input."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid

import ezdxf
from ezdxf.addons import odafc
from ezdxf import blkrefs
from ezdxf.entities import DXFTagStorage
from ezdxf.lldxf.tagwriter import TagCollector


def conservative_purge(doc):
    """Fail closed for opaque data; only remove provably unused ordinary resources."""
    report = {'removed_blocks': [], 'removed_layers': [], 'retained_blocks': [],
              'retained_layers': [], 'warnings': []}
    def retained():
        report['retained_blocks'] = [b.name for b in doc.blocks]
        report['retained_layers'] = [layer.dxf.name for layer in doc.layers]
        return report

    for entity in doc.entitydb.values():
        if not entity.is_alive:
            continue
        if (isinstance(entity, DXFTagStorage) or entity.dxftype().startswith('ACAD_PROXY')
                or entity.xdata or entity.appdata or entity.has_extension_dict):
            report['warnings'].append('Cleanup skipped: custom, proxy or extended data may contain hidden references.')
            return retained()

    def references(kind):
        values = set()
        header_tags = TagCollector(dxfversion=doc.dxfversion)
        doc.header.export_dxf(header_tags)
        for tag in header_tags.tags:
            value = tag.value
            if isinstance(value, str):
                values.add(value.casefold())
        for entity in doc.entitydb.values():
            if not entity.is_alive:
                continue
            for tag in TagCollector.dxftags(entity, dxfversion=doc.dxfversion):
                # Exclude only a resource's own identifier, not its pointers.
                if kind == 'block' and entity.dxftype() in ('BLOCK', 'BLOCK_RECORD') and tag.code in (2, 3, 5):
                    continue
                if kind == 'layer' and entity.dxftype() == 'LAYER' and tag.code in (2, 5):
                    continue
                if isinstance(tag.value, str):
                    values.add(tag.value.casefold())
        return values

    try:
        # Recompute after each round: removing an unused parent can free its children.
        for _ in range(len(doc.blocks) + 1):
            refs = references('block')
            candidates = blkrefs.find_unreferenced_blocks(doc)
            removed = False
            for name in sorted(candidates):
                block = doc.blocks.get(name)
                if (block is None or name.startswith('*') or '|' in name
                        or block.block.dxf.flags & 12
                        or name.casefold() in refs):
                    continue
                try:
                    doc.blocks.delete_block(name, safe=True)
                except ezdxf.DXFBlockInUseError:
                    continue
                report['removed_blocks'].append(name)
                removed = True
            if not removed:
                break
        refs = references('layer')
        for layer in list(doc.layers):
            name = layer.dxf.name
            if (name.casefold() in ('0', 'defpoints') or '|' in name
                    or layer.dxf.flags & 16 or layer.is_locked()
                    or layer.is_frozen() or layer.is_off()
                    or name.casefold() in refs or layer.dxf.handle.casefold() in refs):
                continue
            doc.layers.remove(name)
            report['removed_layers'].append(name)
    except Exception as exc:
        # Do not save partial cleanup when reference analysis fails.
        raise RuntimeError(f'Cleanup reference analysis failed; output not saved: {exc}') from exc
    return retained()


def locked(doc, entity):
    name = entity.dxf.get('layer', '0')
    return name in doc.layers and doc.layers.get(name).is_locked()


def explode_candidate(entity):
    kind = entity.dxftype()
    if entity.has_extension_dict:
        return False
    if kind == 'INSERT':
        block = entity.block()
        return (block is not None and not (block.block.dxf.flags & 12)
                and not entity.attribs and entity.mcount == 1
                and entity.has_uniform_scaling
                and not block.block_record.has_extension_dict
                and not any(e.dxftype() == 'ATTDEF' for e in block))
    if kind == 'LWPOLYLINE':
        return not entity.has_width
    if kind == 'POLYLINE':
        return entity.is_2d_polyline and not any(
            v.dxf.get('start_width', 0) or v.dxf.get('end_width', 0)
            for v in entity.vertices
        ) and not (entity.dxf.get('default_start_width', 0) or entity.dxf.get('default_end_width', 0))
    return False


def transform(doc, passes=4, move_to_zero=True):
    stats = {'exploded': 0, 'moved_to_zero': 0, 'preserved': 0, 'warnings': []}
    for layout in doc.layouts:
        for _ in range(passes):
            changed = 0
            for entity in list(layout):
                if locked(doc, entity) or not explode_candidate(entity):
                    continue
                try:
                    skipped = []
                    if entity.dxftype() == 'INSERT':
                        pieces = list(entity.virtual_entities(
                            skipped_entity_callback=lambda e, reason: skipped.append(reason)))
                    else:
                        pieces = list(entity.virtual_entities())
                    if skipped or not pieces:
                        stats['warnings'].append('Preserved entity: incomplete/empty explosion')
                        continue
                    # Do not delete the original until all replacement entities exist.
                    added = []
                    try:
                        for piece in pieces:
                            layout.add_entity(piece)
                            added.append(piece)
                    except Exception:
                        for piece in added:
                            layout.delete_entity(piece)
                        raise
                    layout.delete_entity(entity)
                    changed += 1
                    stats['exploded'] += 1
                except Exception as exc:
                    stats['warnings'].append(f'Preserved entity after error: {exc}')
            if not changed:
                break
        for entity in layout:
            if (not move_to_zero or locked(doc, entity) or entity.dxftype() == 'INSERT'
                    or entity.has_extension_dict or entity.dxftype() == 'ACAD_PROXY_ENTITY'):
                stats['preserved'] += 1
            elif entity.dxf.hasattr('layer') and entity.dxf.layer != '0':
                entity.dxf.layer = '0'
                stats['moved_to_zero'] += 1
    # No blanket layer/block deletion: specialized objects may retain references.
    return stats


def configure_oda(path=None):
    if path:
        exe = Path(path).expanduser().resolve()
        if not exe.is_file():
            raise FileNotFoundError(f'ODA executable not found: {exe}')
        key = 'win_exec_path' if os.name == 'nt' else 'unix_exec_path'
        ezdxf.options.set('odafc-addon', key, str(exe))
    elif os.name == 'nt' and not odafc.is_installed():
        base = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'ODA'
        candidates = sorted(base.glob('**/ODAFileConverter.exe'))
        if candidates:
            ezdxf.options.set('odafc-addon', 'win_exec_path', str(candidates[-1]))


def process(source, args):
    source = Path(source).expanduser().resolve(strict=True)
    if source.suffix.lower() not in ('.dwg', '.dxf'):
        raise ValueError('Only DWG and DXF files are supported')
    if (source.suffix.lower() == '.dwg' or not args.dxf_only) and not odafc.is_installed():
        raise RuntimeError('Install ODA File Converter, then supply --oda-path or ODA_FILE_CONVERTER')
    suffix = '.dxf' if args.dxf_only else '.dwg'
    output = source.with_name(source.stem + '_oda_' + uuid.uuid4().hex[:10] + suffix)
    report = output.with_suffix(output.suffix + '.json')
    start = time.monotonic()
    details = {'source': str(source), 'output': str(output), 'status': 'failed'}
    try:
        print(f'Reading {source.name}', flush=True)
        doc = ezdxf.readfile(source) if source.suffix.lower() == '.dxf' else odafc.readfile(source, version='R2018', audit=False)
        details['processing'] = transform(doc, args.passes, not args.keep_layers)
        if not getattr(args, 'no_purge', False):
            details['cleanup'] = conservative_purge(doc)
        else:
            details['cleanup'] = {'disabled': True}
        if output.exists():
            raise FileExistsError('Output exists; refusing overwrite')
        print('Saving output...', flush=True)
        if args.dxf_only:
            # DXF testing mode retains its source version; no fake DWG conversion.
            doc.saveas(output)
            ezdxf.readfile(output)
        else:
            odafc.export_dwg(doc, output, version='R2004', audit=False, replace=False)
            with output.open('rb') as stream:
                if stream.read(6) != b'AC1018':
                    raise RuntimeError('Output is not a DWG 2004 file')
        details['status'] = 'ok_requires_visual_review'
        return output
    except Exception as exc:
        details['error'] = str(exc)
        raise
    finally:
        details['seconds'] = round(time.monotonic() - start, 2)
        report.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+')
    parser.add_argument('--oda-path', default=os.environ.get('ODA_FILE_CONVERTER'))
    parser.add_argument('--passes', type=int, choices=range(1, 21), default=4)
    parser.add_argument('--keep-layers', action='store_true', help='Preserve entity layer assignments')
    parser.add_argument('--no-purge', action='store_true', help='Disable conservative unused block/layer cleanup')
    parser.add_argument('--dxf-only', action='store_true', help='Write DXF instead of DWG; for testing')
    args = parser.parse_args()
    configure_oda(args.oda_path)
    failures = 0
    for source in args.files:
        try:
            print('OK:', process(source, args))
        except Exception as exc:
            failures += 1
            print(f'FAILED: {source}: {exc}', file=sys.stderr)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
