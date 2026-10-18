"""Conservative instance overlap analysis. Never modifies the drawing."""
from collections import defaultdict
from fnmatch import fnmatchcase
import hashlib
import itertools
import json
import math

from ezdxf.math import Matrix44

SUMMARY_HEADERS = ['文件路径', '空间/布局', '有效图层', '分类（规则匹配）', '原始块名',
                   '原始直接数量', '原始嵌套数量', '直接重复份数', '嵌套重复份数',
                   '去重后直接数量', '去重后嵌套数量', '疑似重复组数']
DETAIL_HEADERS = ['文件路径', '组编号', '判定', '空间/布局', '有效图层', '分类（规则匹配）',
                  '原始块名', '层级', '对象路径/阵列序号', 'X', 'Y', 'Z', '统计扣除', '依据']


def freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((k, freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if hasattr(value, 'xyz'):
        return tuple(value.xyz)
    return value


def properties(entity, exclude=()):
    return freeze({k: v for k, v in entity.dxf.all_existing_dxf_attribs().items()
                   if k not in {'handle', 'owner', *exclude}})


def opaque(entity):
    return bool(entity.has_extension_dict or entity.xdata or entity.appdata
                or entity.dxftype().startswith('ACAD_PROXY'))


def analyze(doc, source, scope='all', nested=True, tolerance=0.1, rules=(), limit=100000):
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('位置容差必须为大于零的有限数值（图纸单位）')
    instances, warnings = [], set()
    safe_cache, shape_cache = {}, {}

    def safe_definition(name, chain=()):
        key = name.casefold()
        if key in safe_cache:
            return safe_cache[key]
        if key in chain or len(chain) > 32:
            return False
        block = doc.blocks.get(name)
        if (block is None or name.startswith('*') or block.block.dxf.flags & 12
                or opaque(block.block_record) or opaque(block.block)):
            return False
        allowed = {'LINE','CIRCLE','ARC','ELLIPSE','LWPOLYLINE','POLYLINE','SPLINE',
                   'POINT','SOLID','TRACE','3DFACE','TEXT','MTEXT','ATTDEF','INSERT'}
        for e in block:
            if opaque(e) or e.dxftype() not in allowed:
                safe_cache[key] = False
                return False
            if e.dxftype() == 'INSERT' and not safe_definition(e.dxf.name, chain+(key,)):
                safe_cache[key] = False
                return False
        safe_cache[key] = True
        return True

    def shape(name):
        # Limited structural fingerprint for DIFFERENT names. Suspect only, never deduct.
        if name in shape_cache:
            return shape_cache[name]
        block = doc.blocks.get(name)
        signature = None
        if block is not None and not (block.block.dxf.flags & 12):
            parts = []
            for e in block:
                if e.dxftype() not in {'LINE','CIRCLE','ARC','LWPOLYLINE','POINT','SOLID','3DFACE'} or opaque(e):
                    break
                item = [e.dxftype(), properties(e, ('layer',))]
                if e.dxftype() == 'LWPOLYLINE':
                    item.append(tuple(tuple(v) for v in e.get_points()))
                parts.append(repr(item))
            else:
                if parts:
                    signature = hashlib.sha256(repr((tuple(block.block.dxf.base_point), sorted(parts))).encode()).hexdigest()
        shape_cache[name] = signature
        return signature

    def classify(name, layer):
        for rule in rules:
            if fnmatchcase(name.casefold(), rule.get('block','*').casefold()) and fnmatchcase(layer.casefold(), rule.get('layer','*').casefold()):
                return rule['category']
        return '未分类'

    def walk(ref, layout, parent, inherited_layer, chain, path, inherited_props, parent_safe):
        if len(instances) >= limit:
            raise ValueError('展开实例超过十万个，去重未完成；基础计数仍保留，请按布局拆分图纸')
        name = ref.dxf.name
        if name.casefold() in chain or len(chain) > 32:
            warnings.add('循环引用或超过32层嵌套：去重统计不完整')
            return
        block = ref.block()
        xref = block is not None and bool(block.block.dxf.flags & 12)
        refs = ref.multi_insert() if ref.mcount > 1 else (ref,)
        for index, occurrence in enumerate(refs):
            if len(instances) >= limit:
                raise ValueError('展开实例超过十万个，去重未完成；基础计数仍保留')
            matrix = occurrence.matrix44() * parent
            base = block.block.dxf.base_point if block is not None else (0,0,0)
            point = tuple(matrix.transform(base))
            layer = occurrence.dxf.get('layer','0')
            if chain and layer == '0':
                layer = inherited_layer
            attrs = []
            attr_safe = True
            for attrib in occurrence.attribs:
                attr_safe = attr_safe and not opaque(attrib)
                # Attribute coordinates are in the parent coordinate system.
                copy = attrib.copy()
                copy.transform(parent)
                attrs.append(properties(copy))
            appearance = properties(occurrence, ('insert','rotation','extrusion','xscale','yscale','zscale',
                                                 'row_count','column_count','row_spacing','column_spacing','layer','name'))
            context = inherited_props + ((name.casefold(), layer.casefold(), appearance, tuple(sorted(attrs, key=repr))),)
            safe = parent_safe and not opaque(ref) and attr_safe and safe_definition(name)
            item_path = path + (f'{ref.dxf.handle or "?"}[{index}]',)
            item = dict(name=name, layout=layout, layer=layer, category=classify(name,layer),
                        nested=bool(chain), point=point, matrix=tuple(matrix), context=context,
                        path='/'.join(item_path), safe=safe, shape=shape(name), duplicate=False)
            instances.append(item)
            if not safe:
                warnings.add('存在匿名/动态块、外参、未知内容或扩展信息：对应实例只标疑似，不自动扣除')
            if block is None:
                warnings.add('缺失块定义，可能无法完整统计嵌套内容')
            if nested and block is not None and not xref:
                for child in block.query('INSERT'):
                    walk(child, layout, matrix, layer, chain+(name.casefold(),), item_path, context, safe)

    for layout in ([doc.modelspace()] if scope=='model' else doc.layouts):
        for ref in layout.query('INSERT'):
            walk(ref, layout.name, Matrix44(), '0', (), (), (), True)

    groups, exact = [], defaultdict(list)
    representatives = []
    for i, item in enumerate(instances):
        if item['safe']:
            key = (item['layout'], item['layer'].casefold(), item['name'].casefold(), item['nested'],
                   item['matrix'], item['context'])
            exact[key].append(i)
        else:
            representatives.append(i)
    for members in exact.values():
        representatives.append(members[0])
        if len(members)>1:
            groups.append(('确认重复', members, '同块定义、世界变换、图层、层级口径及属性/显示上下文完全相同'))
            for i in members[1:]:
                instances[i]['duplicate'] = True

    # Grid search checks neighboring cells, including negative coordinates and boundaries.
    buckets = defaultdict(list)
    roots = {i:i for i in representatives}
    suspect_members = set()
    comparisons = 0
    def root(i):
        while roots[i] != i:
            roots[i] = roots[roots[i]]
            i=roots[i]
        return i
    for i in representatives:
        item=instances[i]
        cell=tuple(math.floor(v/tolerance) for v in item['point'])
        prefix=(item['layout'],item['layer'].casefold(),item['nested'])
        for offset in itertools.product((-1,0,1), repeat=3):
            for j in buckets[prefix+tuple(a+b for a,b in zip(cell,offset))]:
                comparisons+=1
                if comparisons>1000000:
                    raise ValueError('重叠候选过多，去重分析未完成；请拆分图纸或缩小统计范围')
                other=instances[j]
                same_name=item['name'].casefold()==other['name'].casefold()
                same_shape=item['shape'] is not None and item['shape']==other['shape']
                if not (same_name or same_shape):
                    continue
                if math.dist(item['point'],other['point'])<=tolerance:
                    roots[root(i)] = root(j)
                    suspect_members.update((i,j))
        buckets[prefix+cell].append(i)
    suspects=defaultdict(list)
    for i in sorted(suspect_members):
        suspects[root(i)].append(i)
    for members in suspects.values():
        groups.append(('疑似重复',members,'同名或基础图形指纹相同、插入位置在容差内；方向/缩放/属性可不同，不扣除'))

    summary=defaultdict(lambda:[0,0,0,0,set()])
    def summary_key(item):
        return (str(source),item['layout'],item['layer'],item['category'],item['name'])
    for item in instances:
        values=summary[summary_key(item)]
        slot=int(item['nested'])
        values[slot]+=1
        values[2+slot]+=int(item['duplicate'])
    details=[]
    for group_index,(kind,members,reason) in enumerate(groups,1):
        group_id=f'G{group_index:05}'
        for i in members:
            item=instances[i]
            if kind=='疑似重复':
                summary[summary_key(item)][4].add(group_id)
            details.append([str(source),group_id,kind,item['layout'],item['layer'],item['category'],item['name'],
                            '嵌套' if item['nested'] else '直接',item['path'],*item['point'],
                            '是' if kind=='确认重复' and item['duplicate'] else '否',reason])
    rows=[]
    for key,(direct,sub,dupd,dups,susp) in sorted(summary.items()):
        rows.append([*key,direct,sub,dupd,dups,direct-dupd,sub-dups,len(susp)])
    if any(item['category']=='未分类' for item in instances):
        warnings.add('有未分类块：请按实际块名/图层配置分类，不应将所有块直接视为灯具或道具')
    return rows,details,sorted(warnings)


def load_rules(path):
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    rules=data.get('rules',[])
    if not isinstance(rules,list):
        raise ValueError('rules 必须为列表')
    for rule in rules:
        if (not isinstance(rule,dict) or not isinstance(rule.get('category'),str) or not rule['category']
                or not isinstance(rule.get('block','*'),str) or not isinstance(rule.get('layer','*'),str)):
            raise ValueError('分类规则必须含 category 字符串，block/layer 为可选匹配字符串')
    return rules
