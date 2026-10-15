"""Experimental FO4 -> FO76 meshes; explicit visual-only policy for Havok.

This converts NIF containers, geometry bounds, shader layouts, texture slots,
and shared skin/animation structures. Materials and textures are separate.
It does not convert Havok 2014 physics into Havok 2015 or retarget animations.
Schema reference: niftools/nifxml; bounds checked against FO76 source meshes.
"""
import hashlib
import math
import struct
from pathlib import Path

from inspect_nif import Nif, Reader
from convert_models import Writer, P, sized, COMMON_EXTRA_TYPES, validate_extra
from convert_preserved import shape, skin_instance, validate_weights, ref
from convert_animated import CONTROLLERS, ANIM, validate_animation
from skin_reference import match_skeleton
from shader_animation import SCALAR_CONTROLLERS, convert_controller_block, convert_animation_block, animation_semantics

NODES = {'NiNode', 'BSFadeNode', 'BSValueNode'}
SHAPES = {'BSTriShape', 'BSSubIndexTriShape'}
ANIMATION = ANIM

COMMON = NODES | SHAPES | ANIMATION | COMMON_EXTRA_TYPES | {
    'BSSkin::Instance', 'BSSkin::BoneData', 'BSConnectPoint::Parents',
    'BSConnectPoint::Children', 'BSXFlags', 'NiAlphaProperty',
    'NiStringExtraData', 'NiIntegerExtraData', 'NiFloatExtraData',
    'BSInvMarker', 'BSLightingShaderProperty', 'BSEffectShaderProperty',
    'BSShaderTextureSet', 'bhkNPCollisionObject', 'bhkPhysicsSystem',
}


def bounds(n, d):
    """The F76 six-float field stores center and HALF EXTENTS, not extrema."""
    data = n.blocks[d['id']]
    stride = (d['desc'] & 15) * 4
    fmt = '<3f' if (d['desc'] >> 44) & 0x400 else '<3e'
    low = [math.inf] * 3
    high = [-math.inf] * 3
    for index in range(d['vertices']):
        vertex = struct.unpack_from(fmt, data, d['dataoffset'] + index * stride)
        for axis, value in enumerate(vertex):
            if not math.isfinite(value):
                raise ValueError('网格坐标包含无效数值')
            low[axis] = min(low[axis], value)
            high[axis] = max(high[axis], value)
    return tuple((a+b)/2 for a,b in zip(low, high)) + tuple((b-a)/2 for a,b in zip(low, high))


def external_shader(n, block, lighting):
    reader = Reader(block)
    if lighting:
        reader.u()  # FO4 NiObjectNET's BSLightingShaderType prefix.
    start = reader.p
    net = n.net(reader)
    if not net['name']:
        return None
    expected = '.bgsm' if lighting else '.bgem'
    if not net['name'].lower().endswith(expected):
        raise ValueError('外部材质名称不是预期的 '+expected+' 路径')
    if net['extra']:
        raise ValueError('外部着色器额外数据尚未验证反向转换')
    allowed = {'BSLightingShaderPropertyFloatController', 'BSLightingShaderPropertyColorController'} if lighting else {'BSEffectShaderPropertyFloatController', 'BSEffectShaderPropertyColorController'}
    ref(n, net['ctrl'], allowed, '着色器控制器', True)
    # F76 stops reading after NiObjectNET when Name is non-empty.
    return block[start:reader.p]


def inline_effect(n, block):
    from shader_flags import fo4_to_fo76
    reader = Reader(block)
    net = n.net(reader)
    if net['name'] or net['extra']:
        raise ValueError('内嵌特效属性布局尚未支持')
    ref(n, net['ctrl'], {'BSEffectShaderPropertyFloatController', 'BSEffectShaderPropertyColorController'}, '特效控制器', True)
    base = block[:reader.p]
    flag1, flag2 = reader.get('II')
    hashes1, hashes2 = fo4_to_fo76(flag1, flag2)
    uv = reader.read(16)
    texture = reader.s()
    clamp = reader.read(4)
    falloff = reader.read(16)
    color_depth = reader.read(24)
    textures = [reader.s() for _ in range(4)]
    env_scale = reader.read(4)
    if reader.p != len(block):
        raise ValueError('内嵌特效属性含未解析尾部')
    # FO76-only fields use the documented defaults; the source has no equivalent.
    return (base + P('II', len(hashes1), len(hashes2))
            + b''.join(P('I', value) for value in hashes1 + hashes2)
            + uv + sized(texture) + clamp + falloff + P('f', 0)
            + color_depth + b''.join(sized(value) for value in textures) + env_scale
            + sized('') + sized('') + P('3f', 0, 0, 0) + sized('')
            + P('4f', 100, 13.5, 2, 3))


def validate_tree(n, descriptors):
    visited, active = set(), set()
    def visit(index):
        if index == -1:
            return
        if index in active:
            raise ValueError('模型节点图包含循环')
        if index in visited:
            raise ValueError('模型节点图存在多个父节点')
        if index not in descriptors:
            raise ValueError('模型节点图引用了不支持的类型')
        visited.add(index)
        active.add(index)
        for child in descriptors[index].get('children', []):
            visit(child)
        active.remove(index)
    for root in n.roots:
        visit(root)
    for index, d in descriptors.items():
        if d['type'] in SHAPES and index not in visited:
            raise ValueError('存在未连接到根节点的网格')


def validate_metadata(n):
    """Copy only fully parsed common node/extra layouts, with typed links."""
    descriptors = {}
    collision_targets = {}
    for i, type_id in enumerate(n.indices):
        typ, block = n.types[type_id], n.blocks[i]
        r = Reader(block)
        if typ in NODES | SHAPES:
            d = n.av(r)
            d.update(id=i, type=typ)
            ref(n, d['ctrl'], CONTROLLERS, '节点控制器', True)
            ref(n, d['collision'], {'bhkNPCollisionObject'}, '节点碰撞', True)
            for extra in d['extra']:
                ref(n, extra, COMMON_EXTRA_TYPES | {'NiTextKeyExtraData'}, '节点扩展数据')
            if typ in NODES:
                d['children'] = list(r.array('i', r.u()))
                for child in d['children']:
                    ref(n, child, NODES | SHAPES, '子节点', True)
                if typ == 'BSValueNode':
                    r.get('IB')
                if r.p != len(block):
                    raise ValueError(typ + ' 含未解析的尾部字段')
            descriptors[i] = d
        elif typ in COMMON_EXTRA_TYPES:
            validate_extra(n, typ, block)
        elif typ == 'NiAlphaProperty':
            metadata = n.net(r)
            if metadata['extra']:
                raise ValueError('透明属性包含未支持的扩展数据')
            ref(n, metadata['ctrl'], {'BSNiAlphaPropertyTestRefController'}, '透明属性控制器', True)
            r.get('HB')
            if r.p != len(block):
                raise ValueError('透明属性含未解析的尾部字段')
        elif typ == 'bhkNPCollisionObject':
            target, flags, data, body = r.get('iHiI')
            ref(n, target, NODES | SHAPES, '碰撞目标')
            ref(n, data, {'bhkPhysicsSystem'}, '物理数据')
            collision_targets[i] = target
            if r.p != len(block):
                raise ValueError('碰撞对象含未解析的尾部字段')
        elif typ == 'bhkPhysicsSystem':
            r.read(r.u())
            if r.p != len(block):
                raise ValueError('物理数据含未解析的尾部字段')
    for i, d in descriptors.items():
        if d['collision'] != -1 and collision_targets[d['collision']] != i:
            raise ValueError('碰撞绑定与目标节点不一致')
    validate_tree(n, descriptors)
    return descriptors


def convert(src, dest, collision=True, dry_run=False, reference_root=None, _nif=None):
    src, dest = Path(src), Path(dest)
    if src.resolve() == dest.resolve() or dest.exists():
        raise ValueError('输出已存在或与源模型相同')
    n = _nif if _nif is not None else Nif(src)
    if n.bs != 130:
        raise ValueError('反向转换仅接受 Fallout 4 BS130 模型')
    types = {n.types[index] for index in n.indices}
    if 'BSMeshLODTriShape' in types:
        raise ValueError('反向转换暂不支持 BSMeshLODTriShape：已扫描的 FO76 资源中未发现该块，目标游戏的 LOD 语义尚未验证')
    unknown = types - COMMON
    if unknown:
        raise ValueError('反向转换尚未支持：'+', '.join(sorted(unknown)))
    if n.groups or n.roots != [0]:
        raise ValueError('反向转换暂不处理多根节点或块组')
    physical = [i for i,t in enumerate(n.indices) if n.types[t].startswith('bhk')]
    if physical and collision:
        raise ValueError('FO4 → 76 尚不支持 Havok 物理转换；仅可明确选择“仅模型，不保留碰撞”')
    validate_metadata(n)
    animation, animated_targets = validate_animation(n) if types & ANIMATION else ([], set())
    shapes = []
    for i,t in enumerate(n.indices):
        if n.types[t] in SHAPES:
            d = shape(n, i)
            d['id'] = i
            n.ref(d['shader'], nullable=False)
            if n.types[n.indices[d['shader']]] not in ('BSLightingShaderProperty', 'BSEffectShaderProperty'):
                raise ValueError('网格着色器引用类型不匹配')
            ref(n, d['alpha'], {'NiAlphaProperty'}, '透明属性', True)
            shapes.append((i,d))
    skins = {i:skin_instance(n,i) for i,t in enumerate(n.indices) if n.types[t] == 'BSSkin::Instance'}
    bones = list(dict.fromkeys(name for skin in skins.values() for name in skin['names']))
    reference = match_skeleton(reference_root, bones, src, expected_bs=155) if skins else None
    for i,d in shapes:
        if d['skin'] != -1:
            if d['skin'] not in skins:
                raise ValueError('网格蒙皮实例引用无效')
            validate_weights(n, i, d, skins[d['skin']])
    if not shapes and not any(t in NODES for t in types):
        raise ValueError('没有可转换的模型或辅助节点')
    w = Writer(bs=155)
    w.strings = list(n.strings)
    w.blocks = [(n.types[t],b) for t,b in zip(n.indices,n.blocks)]
    warnings = ['材质与贴图文件未转换；外部引用需要另行转换为目标游戏格式。',
                '结构与字节回读校验不代表游戏内可用，未进行动画重定向。']
    if physical:
        warnings.append('用户选择了无碰撞输出：原 Havok 物理数据已移除。')
    shape_map = dict(shapes)
    for i,(typ,b) in enumerate(w.blocks.copy()):
        if typ in ANIMATION:
            w.set(i, convert_animation_block(n, i, 155, w))
        if typ in NODES | SHAPES:
            d = n.av(Reader(b))
            if d['collision'] != -1 and n.types[n.indices[d['collision']]] != 'bhkNPCollisionObject':
                raise ValueError('未支持的碰撞引用类型')
            if d['ctrl'] != -1 and n.types[n.indices[d['ctrl']]] not in ANIMATION:
                raise ValueError('该节点控制器尚未验证反向转换')
            if physical:
                data = bytearray(b)
                struct.pack_into('<i', data, d['avend']-4, -1)
                b = bytes(data)
                w.set(i,b)
        if typ in SHAPES:
            d = shape_map[i]
            w.set(i, b[:d['boundend']] + P('6f', *bounds(n,d)) + b[d['boundend']:])
        elif typ in ('BSLightingShaderProperty', 'BSEffectShaderProperty'):
            converted = external_shader(n,b,typ == 'BSLightingShaderProperty')
            if converted is None:
                if typ == 'BSLightingShaderProperty':
                    raise ValueError('无外部 BGSM 的 FO4 内嵌光照着色器尚未支持反向转换')
                converted = inline_effect(n,b)
            w.set(i,converted)
        elif typ == 'BSShaderTextureSet':
            r = Reader(b)
            count = r.u()
            if count not in (9,10):
                raise ValueError('FO4 贴图槽布局不是已验证的 9/10 槽')
            textures = [r.s() for _ in range(count)]
            if r.p != len(b):
                raise ValueError('贴图槽含未解析尾部')
            w.set(i, P('I',15) + b''.join(sized(t) for t in textures + ['']*(15-count)))
        elif typ.startswith('bhk'):
            # Keep IDs stable for shared skin/controller structures. Physics slots
            # become unreferenced, inert notes; no Havok2014 bytes enter BS155.
            w.blocks[i] = ('NiStringExtraData', P('ii', w.sid('MeshConverter'),
                            w.sid('Physics omitted by explicit visual-only option')))
        elif typ == 'BSXFlags' and physical:
            name, flags = struct.unpack('<iI',b)
            w.set(i,P('iI',name,flags & ~2))
    info = dict(route='fo4-to-76', shapes=len(shapes),
                vertices=sum(d['vertices'] for _,d in shapes),
                triangles=sum(d['triangles'] for _,d in shapes),
                bones=bones, skeleton_reference=reference,
                physics_removed=bool(physical), collision_rebuilt=None,
                animations_preserved=bool(types & ANIMATION),
                animation_blocks=animation, animated_targets=sorted(animated_targets),
                geometry_bytes_preserved=True, warnings=warnings)
    if dry_run:
        return info
    w.save(dest)
    out = Nif(dest)
    if out.bs != 155 or out.roots != n.roots:
        raise ValueError('FO76 目标版本或根节点回读校验失败')
    validate_metadata(out)
    if animation:
        out_animation, out_targets = validate_animation(out)
        if animation_semantics(out_animation) != animation_semantics(animation) or out_targets != animated_targets:
            raise ValueError('动画结构回读校验失败')
    for i,d in shapes:
        od = shape(out,i)
        if out.blocks[i][od['dataoffset']:] != n.blocks[i][d['dataoffset']:]:
            raise ValueError('几何、蒙皮或分区数据发生变化')
        actual = struct.unpack_from('<6f',out.blocks[i],od['boundend'])
        expected = struct.unpack('<6f',P('6f',*bounds(n,d)))
        if actual != expected:
            raise ValueError('FO76 包围盒回读失败')
    for i,t in enumerate(n.indices):
        if n.types[t] in COMMON_EXTRA_TYPES and not (physical and n.types[t] == 'BSXFlags'):
            if out.blocks[i] != n.blocks[i]:
                raise ValueError('公共节点元数据发生变化')
        if n.types[t] in ANIMATION | {'BSSkin::Instance','BSSkin::BoneData'} and out.blocks[i] != (convert_animation_block(n, i, 155, w) if n.types[t] in ANIMATION else n.blocks[i]):
            raise ValueError('动画或骨骼数据发生变化')
    info.update(input=str(src), output=str(dest),
                source_sha256=n.source_sha256)
    return info
