"""One validated, atomic conversion API shared by the CLI and desktop host."""
import uuid

from inspect_nif import Nif, Reader
from publication_guard import OutputBoundary, absolute_path

DIRECTIONS = {'76-to-4': (155,130), '4-to-76': (130,155)}
BUILD = 'ALPHA 1.0 · common metadata 2026-10-14'


def classify(n):
    types = {n.types[t] for t in n.indices}
    if 'BSSkin::Instance' in types:
        return '蒙皮模型（骨骼参照）'
    if any('Controller' in t or 'Interpolator' in t or 'Sequence' in t for t in types):
        return '节点动画（试验）'
    if not types.intersection({'BSTriShape','BSSubIndexTriShape','BSMeshLODTriShape'}):
        return '辅助节点'
    if 'BSEffectShaderProperty' in types:
        return '特效/静态模型'
    return '静态模型'


def convert_file(src, dest, direction='76-to-4', collision=True, dry_run=False,
                 reference_root=None, _staged=False, output_root=None, source_root=None):
    """Convert within caller-approved roots; direct callers default to parent roots.

    Source/output roots must be disjoint.  Staged worker writes are subject to
    the same checks as final writes; GUI publication must also use this guard.
    """
    if direction not in DIRECTIONS:
        raise ValueError('请选择 76-to-4 或 4-to-76 转换方向')
    src, dest = absolute_path(src), absolute_path(dest)
    boundary = OutputBoundary(output_root if output_root is not None else dest.parent,
                              source_root if source_root is not None else src.parent)
    src = boundary.validate_source(src)
    dest = boundary.validate(dest, must_be_absent=True)
    n = Nif(src)
    expected, target = DIRECTIONS[direction]
    if n.bs != expected:
        raise ValueError(f'方向不匹配：当前 BS{n.bs}，所选方向需要 BS{expected}')
    if n.groups or n.roots != [0]:
        raise ValueError('目前仅支持无块组、根节点为 block 0 的 NIF')
    kind = classify(n)
    types = {n.types[t] for t in n.indices}
    if direction == '4-to-76':
        from convert_reverse import convert
        kwargs = dict(collision=bool(collision), dry_run=bool(dry_run), reference_root=reference_root)
    elif 'BSSkin::Instance' in types:
        from convert_preserved import convert
        kwargs = dict(collision=False, dry_run=bool(dry_run), reference_root=reference_root)
    elif kind == '节点动画（试验）':
        from convert_animated import convert
        kwargs = dict(collision=bool(collision), dry_run=bool(dry_run))
    else:
        from convert_models import convert
        kwargs = dict(collision=bool(collision), dry_run=bool(dry_run))
        # Inline effects without physical objects can use the preserving route.
        if 'BSEffectShaderProperty' in types and 'bhkPhysicsSystem' not in types:
            for i,t in enumerate(n.indices):
                if n.types[t] == 'BSEffectShaderProperty':
                    if not n.net(Reader(n.blocks[i]))['name']:
                        from convert_preserved import convert
                        kwargs = dict(collision=False, dry_run=bool(dry_run), reference_root=reference_root)
                        break
    temp = None
    try:
        output = dest
        if not dry_run:
            boundary.prepare_parent(dest)
            if not _staged:
                temp = dest.with_name('.mesh-converter-'+uuid.uuid4().hex+'.tmp')
                output = temp
        boundary.validate_source(src)
        boundary.validate(output, must_be_absent=True)
        result = convert(src,output,_nif=n,**kwargs)
        result.update(conversion_kind=kind, direction=direction,
                      source_bs=n.bs, target_bs=target, build=BUILD,
                      game_verified=False, dry_run=bool(dry_run))
        if not dry_run:
            boundary.validate(output)
            converted = Nif(output)
            if converted.bs != target:
                raise ValueError('转换结果的目标 NIF 版本不正确')
            result['validation'] = converted.validate()
            boundary.validate(output)
            if not _staged:
                boundary.publish(temp, dest)
            result['output'] = str(dest)
        return result
    finally:
        boundary.cleanup(temp)
