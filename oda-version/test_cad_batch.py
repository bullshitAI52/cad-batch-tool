import argparse
import hashlib
from pathlib import Path
import tempfile
import unittest
import ezdxf
from cad_batch import transform, process, conservative_purge


class ProcessingTests(unittest.TestCase):
    def test_purge_unused_nested_resources(self):
        doc = ezdxf.new('R2018')
        doc.layers.new('Unused')
        child = doc.blocks.new('UnusedChild')
        child.add_line((0, 0), (1, 1), dxfattribs={'layer': 'Unused'})
        parent = doc.blocks.new('UnusedParent')
        parent.add_blockref('UnusedChild', (0, 0))
        doc.layers.new('Live')
        live = doc.blocks.new('LiveBlock')
        live.add_line((0, 0), (1, 1), dxfattribs={'layer': 'Live'})
        doc.modelspace().add_blockref('LiveBlock', (0, 0))
        report = conservative_purge(doc)
        self.assertEqual(set(report['removed_blocks']), {'UnusedParent', 'UnusedChild'})
        self.assertIn('Unused', report['removed_layers'])
        self.assertIn('Live', doc.layers)
        self.assertIn('LiveBlock', doc.blocks)
        self.assertFalse(doc.audit().has_errors)

    def test_purge_retains_header_handle_and_layout_refs(self):
        doc = ezdxf.new('R2018')
        for name in ('Current', 'Locked', 'ByHandle', 'Paper', 'Empty'):
            doc.layers.new(name)
        doc.header['$CLAYER'] = 'Current'
        doc.layers.get('Locked').lock()
        doc.layouts.new('Sheet').add_circle((0, 0), 1, dxfattribs={'layer': 'Paper'})
        record = doc.rootdict.add_xrecord('TEST_REFERENCE')
        record.reset([(330, doc.layers.get('ByHandle').dxf.handle)])
        report = conservative_purge(doc)
        self.assertIn('Empty', report['removed_layers'])
        for name in ('Current', 'Locked', 'ByHandle', 'Paper', '0', 'Defpoints'):
            self.assertIn(name, doc.layers)

    def test_custom_data_disables_cleanup(self):
        doc = ezdxf.new()
        doc.layers.new('Empty')
        doc.blocks.new('EmptyBlock')
        doc.appids.new('CUSTOM')
        entity = doc.modelspace().add_point((0, 0))
        entity.set_xdata('CUSTOM', [(1000, 'EmptyBlock')])
        report = conservative_purge(doc)
        self.assertTrue(report['warnings'])
        self.assertEqual(report['removed_blocks'], [])
        self.assertIn('Empty', doc.layers)

    def test_nested_blocks_and_layout(self):
        doc = ezdxf.new('R2018')
        doc.layers.new('A')
        inner = doc.blocks.new('inner')
        inner.add_line((0, 0), (1, 0), dxfattribs={'layer': 'A'})
        outer = doc.blocks.new('outer')
        outer.add_blockref('inner', (2, 0))
        doc.modelspace().add_blockref('outer', (10, 0))
        paper = doc.layouts.new('Sheet')
        paper.add_lwpolyline([(0, 0), (2, 0), (2, 2)], dxfattribs={'layer': 'A'})
        stats = transform(doc)
        self.assertEqual(stats['exploded'], 3)
        line = list(doc.modelspace())[0]
        self.assertEqual(line.dxftype(), 'LINE')
        self.assertAlmostEqual(line.dxf.start.x, 12)
        self.assertTrue(all(e.dxf.layer == '0' for e in paper))
        self.assertEqual(len(list(paper.query('LINE'))), 2)

    def test_preserve_sensitive_entities(self):
        doc = ezdxf.new()
        doc.layers.new('locked').lock()
        model = doc.modelspace()
        poly = model.add_lwpolyline([(0, 0), (1, 1)], dxfattribs={'layer': 'locked'})
        wide = model.add_lwpolyline([(0, 0), (1, 1)], dxfattribs={'const_width': 2})
        b = doc.blocks.new('attrs')
        b.add_attdef('TAG', (0, 0))
        ref = model.add_blockref('attrs', (0, 0))
        ref.add_attrib('TAG', 'value', (0, 0))
        x = doc.blocks.new('xref')
        x.block.dxf.flags = 4
        xref = model.add_blockref('xref', (0, 0))
        transform(doc)
        self.assertTrue(poly.is_alive and wide.is_alive and ref.is_alive and xref.is_alive)
        self.assertEqual(poly.dxf.layer, 'locked')
        self.assertEqual(ref.attribs[0].dxf.text, 'value')

    def test_source_unchanged_unique_output(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / '中文图纸.dxf'
            doc = ezdxf.new('R2018')
            doc.layers.new('Keep')
            doc.modelspace().add_line((0, 0), (1, 1), dxfattribs={'layer': 'Keep'})
            doc.saveas(src)
            before = hashlib.sha256(src.read_bytes()).digest()
            args = argparse.Namespace(dxf_only=True, passes=4, keep_layers=True)
            one = process(src, args)
            two = process(src, args)
            self.assertNotEqual(one, two)
            self.assertEqual(hashlib.sha256(src.read_bytes()).digest(), before)
            self.assertEqual(list(ezdxf.readfile(one).modelspace())[0].dxf.layer, 'Keep')


if __name__ == '__main__':
    unittest.main()
