"""Bounded readers for animation structures shared by FO4 and FO76.

Field layouts and known controlled-variable values: niftools/nifxml.
Unknown controlled variables are rejected rather than assumed equivalent.
No engine playback or material conversion is implied by structural validation.
"""
import math
import struct
from inspect_nif import Reader

FLOATS = {'NiFloatInterpolator', 'NiBlendFloatInterpolator'}
POINTS = {'NiPoint3Interpolator', 'NiBlendPoint3Interpolator'}
BOOLS = {'NiBoolInterpolator', 'NiBoolTimelineInterpolator', 'NiBlendBoolInterpolator'}
INTERPOLATORS = FLOATS | POINTS | BOOLS | {'NiBlendTransformInterpolator'}
KEY_DATA = {'NiFloatData', 'NiPosData', 'NiBoolData'}
SCALAR_CONTROLLERS = {
    'BSEffectShaderPropertyFloatController', 'BSEffectShaderPropertyColorController',
    'BSLightingShaderPropertyFloatController', 'BSLightingShaderPropertyColorController',
    'BSNiAlphaPropertyTestRefController', 'NiVisController',
}
EXTRA_ANIM = INTERPOLATORS | KEY_DATA | SCALAR_CONTROLLERS
DEFAULT_AV = {'NiNode', 'BSFadeNode', 'BSValueNode', 'BSTriShape', 'BSSubIndexTriShape'}
VARIABLES = {
    'BSEffectShaderPropertyFloatController': {
        0: 'emissive_multiple', 1: 'falloff_start_angle', 2: 'falloff_stop_angle',
        3: 'falloff_start_opacity', 4: 'falloff_stop_opacity', 5: 'alpha',
        6: 'u_offset', 7: 'u_scale', 8: 'v_offset', 9: 'v_scale'},
    'BSEffectShaderPropertyColorController': {0: 'emissive_color'},
    'BSLightingShaderPropertyFloatController': {
        0: 'refraction_strength', 8: 'environment_map_scale', 9: 'glossiness',
        10: 'specular_strength', 11: 'emissive_multiple', 12: 'alpha',
        20: 'u_offset', 21: 'u_scale', 22: 'v_offset', 23: 'v_scale'},
    'BSLightingShaderPropertyColorController': {0: 'specular_color', 1: 'emissive_color'},
}


def _finite(values, label):
    if not all(math.isfinite(v) for v in values):
        raise ValueError(label + ' 含非有限数值')


def _ref(n, index, types, label, nullable=False):
    if nullable and index == -1:
        return
    if not 0 <= index < n.count or n.types[n.indices[index]] not in types:
        raise ValueError(label + ' 引用无效')


def _keys(reader, width, boolean=False):
    count = reader.u()
    if not count:
        return {'keys': 0}
    kind = reader.u()
    if kind not in ((1, 5) if boolean else (1, 2, 3, 5)):
        raise ValueError('未支持的标量/颜色关键帧插值类型：' + str(kind))
    floats = width + (2 * width if kind == 2 else 0) + (3 if kind == 3 else 0)
    stride = 5 if boolean else 4 * (1 + floats)
    if count > (len(reader.b) - reader.p) // stride:
        raise ValueError('关键帧数量超出数据块')
    previous = -math.inf
    for _ in range(count):
        time = reader.get('f')[0]
        _finite((time,), '关键帧时间')
        if time < previous:
            raise ValueError('关键帧时间未排序')
        previous = time
        if boolean:
            if reader.get('B')[0] not in (0, 1):
                raise ValueError('可见性关键帧值无效')
        else:
            _finite(reader.get('f' * floats), '关键帧值')
    return {'keys': count, 'interpolation': kind}


def validate_shared_block(n, index, controllers=None, av_types=None):
    """Parse one shared block. The returned links allow caller graph validation."""
    typ = n.types[n.indices[index]]
    if typ not in EXTRA_ANIM:
        raise ValueError('未支持的共享动画块：' + typ)
    r = Reader(n.blocks[index])
    report = {'block': index, 'type': typ}
    controllers = set(controllers or ()) | SCALAR_CONTROLLERS
    av_types = set(av_types or DEFAULT_AV)
    if typ in SCALAR_CONTROLLERS:
        nxt, flags, frequency, phase, start, stop, target = r.get('iH4fi')
        _finite((frequency, phase, start, stop), '控制器时间')
        _ref(n, nxt, controllers, '下一个控制器', True)
        if typ.startswith('BSLighting'):
            target_types = {'BSLightingShaderProperty'}
        elif typ.startswith('BSEffect'):
            target_types = {'BSEffectShaderProperty'}
        elif typ == 'BSNiAlphaPropertyTestRefController':
            target_types = {'NiAlphaProperty'}
        else:
            target_types = av_types
        _ref(n, target, target_types, '动画控制器目标')
        interpolator = r.i()
        allowed = BOOLS if typ == 'NiVisController' else POINTS if 'ColorController' in typ else FLOATS
        _ref(n, interpolator, allowed, '动画插值器', True)
        report.update(next=nxt, target=target, flags=flags, frequency=frequency,
                      phase=phase, start=start, stop=stop, interpolator=interpolator)
        if typ in VARIABLES:
            variable = r.u()
            canonical = canonical_variable(typ, variable, n.bs)
            if canonical not in VARIABLES[typ]:
                raise ValueError('未支持的着色器动画参数：%s/%d' % (typ, variable))
            report.update(variable=variable, semantic=VARIABLES[typ][canonical])
    elif typ in KEY_DATA:
        report.update(_keys(r, 3 if typ == 'NiPosData' else 1, typ == 'NiBoolData'))
    elif typ.startswith('NiBlend'):
        flags, capacity, threshold = r.get('BBf')
        if flags & ~3:
            raise ValueError('未支持的混合插值器标记')
        _finite((threshold,), '混合阈值')
        children = []
        if not flags & 1:
            count, single, high, next_high = r.get('BBbb')
            if count > capacity or (single != 255 and single >= capacity):
                raise ValueError('混合插值器计数/索引无效')
            _finite(r.get('4f'), '混合插值器参数')
            family = BOOLS if typ == 'NiBlendBoolInterpolator' else POINTS if typ == 'NiBlendPoint3Interpolator' else FLOATS if typ == 'NiBlendFloatInterpolator' else {'NiTransformInterpolator', 'NiBlendTransformInterpolator'}
            for _ in range(capacity):
                child, weight, normalized, priority, ease = r.get('iffBf')
                _ref(n, child, family, '混合子插值器', True)
                _finite((weight, normalized, ease), '混合权重')
                if child != -1:
                    children.append(child)
        if typ == 'NiBlendBoolInterpolator':
            if r.get('B')[0] not in (0, 1, 2):
                raise ValueError('布尔插值器姿势值无效')
        elif typ != 'NiBlendTransformInterpolator':
            _finite(r.get('3f' if typ == 'NiBlendPoint3Interpolator' else 'f'), '混合姿势')
        report.update(manager_controlled=bool(flags & 1), capacity=capacity, children=children)
    else:
        if typ in BOOLS:
            if r.get('B')[0] not in (0, 1, 2):
                raise ValueError('布尔插值器姿势值无效')
            data_type = 'NiBoolData'
        else:
            _finite(r.get('3f' if typ == 'NiPoint3Interpolator' else 'f'), '插值器姿势')
            data_type = 'NiPosData' if typ == 'NiPoint3Interpolator' else 'NiFloatData'
        data = r.i()
        _ref(n, data, {data_type}, '关键帧数据', True)
        report['data'] = data
    if r.p != len(r.b):
        raise ValueError(typ + ' 含未解析的尾部字段')
    return report


def validate_interpolator_links(reports):
    graph = {row['block']: row.get('children', []) for row in reports}
    active, seen = set(), set()
    def visit(index):
        if index in active:
            raise ValueError('混合插值器包含循环引用')
        if index in seen:
            return
        active.add(index)
        for child in graph.get(index, []):
            visit(child)
        active.remove(index)
        seen.add(index)
    for index in graph:
        visit(index)


def effect_with_controller(n, block, owners=None):
    """Preserve validated controller reference while adapting shader layout."""
    from convert_preserved import effect
    from convert_models import P
    r = Reader(block)
    net = n.net(r)
    if net['extra']:
        raise ValueError('特效额外属性未支持')
    _ref(n, net['ctrl'], SCALAR_CONTROLLERS, '特效控制器', True)
    result, note = effect(n, block[:8] + P('i', -1) + block[12:], owners)
    return result[:8] + P('i', net['ctrl']) + result[12:], note


# FO76 aliases are verified in fo76utils/nifskope src/gl/controllers.h/.cpp.
# https://github.com/fo76utils/nifskope/blob/develop/src/gl/controllers.h
# This is format mapping, not a claim of in-game playback validation.
F76_VARIABLE_ALIASES = {
    'BSLightingShaderPropertyFloatController': {3: 11},
    'BSEffectShaderPropertyFloatController': {11: 6, 12: 7, 13: 8, 14: 9},
}

def canonical_variable(typ, value, bs):
    return F76_VARIABLE_ALIASES.get(typ, {}).get(value, value) if bs == 155 else value

def convert_controller_block(n, index, target_bs):
    typ, block = n.types[n.indices[index]], n.blocks[index]
    if typ not in VARIABLES:
        return block
    value = struct.unpack_from('<I', block, len(block) - 4)[0]
    canonical = canonical_variable(typ, value, n.bs)
    if canonical not in VARIABLES[typ]:
        raise ValueError('未支持的着色器动画参数：%s/%d' % (typ, value))
    if target_bs == 155:
        reverse = {v: k for k, v in F76_VARIABLE_ALIASES.get(typ, {}).items()}
        canonical = reverse.get(canonical, canonical)
    return block[:-4] + struct.pack('<I', canonical)

def animation_semantics(reports):
    return [{k:v for k,v in row.items() if k != 'variable'} for row in reports]


def validate_sequence_binding(n, interpolator, controller, names):
    if controller == -1:
        if names[2] in VARIABLES:
            raise ValueError('着色器序列缺少可验证的控制器引用')
        return None
    typ = n.types[n.indices[controller]]
    if typ not in VARIABLES:
        return None
    report = validate_shared_block(n, controller, {n.types[t] for t in n.indices if 'Controller' in n.types[t]})
    allowed = POINTS if 'ColorController' in typ else FLOATS
    _ref(n, interpolator, allowed, '着色器序列插值器', True)
    if names[2] and names[2] != typ:
        raise ValueError('序列控制器类型名称不一致')
    identifier = names[3]
    expected = canonical_variable(typ, report['variable'], n.bs)
    if identifier and (not identifier.isdecimal() or canonical_variable(typ, int(identifier), n.bs) != expected):
        raise ValueError('着色器序列 Controller ID 语义不一致')
    return report

def convert_animation_block(n, index, target_bs, writer):
    typ = n.types[n.indices[index]]
    if typ != 'NiControllerSequence':
        return convert_controller_block(n, index, target_bs) if typ in SCALAR_CONTROLLERS else n.blocks[index]
    result = bytearray(n.blocks[index]); r = Reader(result)
    r.i(); count=r.u(); r.u()
    for _ in range(count):
        interpolator, controller, priority = r.get('iiB')
        start = r.p; names = [n.name(r.i()) for _ in range(5)]
        report = validate_sequence_binding(n, interpolator, controller, names)
        if report and names[3]:
            converted = convert_controller_block(n, controller, target_bs)
            value = struct.unpack_from('<I', converted, 30)[0]
            struct.pack_into('<i', result, start + 12, writer.sid(str(value)))
    return bytes(result)
