"""Read user-selected target skeletons; never ship or synthesize game skeletons.

Matching names establishes a structural reference, not animation compatibility.
The conversion report deliberately records that in-game behavior is unverified.
"""
import hashlib
import math
import re
import struct
import time
from pathlib import Path

from inspect_nif import Nif, Reader

_cache = {}


def skeleton_profiles(reference_root, expected_bs=130):
    """Return bone-name profiles from a target resources root or one skeleton.

    Profiles are refreshed after 60 seconds and whenever a known skeleton changes.
    This keeps large batches from walking the resources tree for every mesh.
    """
    if not reference_root:
        raise ValueError('蒙皮转换需要选择目标游戏的 Meshes 目录或 skeleton.nif 作为参照')
    root = Path(reference_root).resolve()
    if not root.exists():
        raise ValueError('目标骨骼参照路径不存在：' + str(root))
    key = (str(root), expected_bs)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < 60:
        try:
            if all((Path(p).stat().st_size, Path(p).stat().st_mtime_ns) == sig
                   for p, sig in cached[1]):
                return cached[2]
        except OSError:
            pass
    if root.is_file():
        candidates = [root]
    else:
        # Prefer Meshes under a supplied resources root; never search other disks.
        for sub in ('Meshes', 'meshes', 'Loose Files/meshes'):
            if (root / sub).is_dir():
                root = root / sub
                break
        candidates = sorted((p for p in root.rglob('*.nif')
                             if p.name.lower().startswith('skeleton')), key=str)
    profiles, stamps = [], []
    for path in candidates:
        stat = path.stat()
        stamps.append((str(path), (stat.st_size, stat.st_mtime_ns)))
        try:
            n = Nif(path)
            if (n.ver, n.user, n.bs) != (0x14020007, 12, expected_bs):
                continue
            names = set()
            for i, typ in enumerate(n.indices):
                if n.types[typ] not in ('NiNode', 'BSFadeNode'):
                    continue
                node = n.av(Reader(n.blocks[i]))
                if not all(math.isfinite(v) for v in node['transform']):
                    raise ValueError('nonfinite reference bone transform')
                if node['name']:
                    names.add(node['name'])
            if names:
                profiles.append(dict(path=str(path), bs=expected_bs,
                                     names=frozenset(names),
                                     sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        except (ValueError, IndexError, OSError, struct.error):
            continue
    if not profiles:
        raise ValueError('参照目录内未找到可读取的目标版本 skeleton*.nif')
    result = tuple(profiles)
    _cache[key] = (time.monotonic(), stamps, result)
    return result


def match_skeleton(reference_root, bone_names, source_path='', expected_bs=130):
    required = set(bone_names)
    profiles = skeleton_profiles(reference_root, expected_bs)
    source = str(source_path).lower().replace('\\', '/')
    actor = re.search(r'/actors/([^/]+)/', source)
    family = actor.group(1) if actor else None
    if family is None and re.search(r'/(armor|clothes|clothing)/', source):
        family = ('dogmeat' if '/armor/doggear/' in source and required and all(name.startswith('Dogmeat_') for name in required) else
                  'powerarmor' if '/armor/powerarmor/' in source else 'character')
    first_person = '_1st' in source or '1stperson' in source
    def profile_family(profile):
        match = re.search(r'/actors/([^/]+)/', profile['path'].lower().replace('\\', '/'))
        return match.group(1) if match else None
    # An explicitly selected single file is authoritative. A whole directory is
    # never allowed to substitute e.g. a Supermutant skeleton for human gloves.
    if not Path(reference_root).is_file():
        if family:
            profiles = tuple(p for p in profiles if profile_family(p) == family)
        profiles = tuple(p for p in profiles if first_person == ('_1st' in p['path'].lower() or '1stperson' in p['path'].lower()))
        if not profiles:
            raise ValueError('未找到同角色类型及视角的目标骨骼；请显式选择正确的 skeleton.nif')
    matches = [p for p in profiles if required <= p['names']]
    if not matches:
        closest = min(profiles, key=lambda p: len(required - p['names']))
        missing = ', '.join(sorted(required - closest['names']))
        raise ValueError('目标骨骼缺少绑定骨骼（不能自动重定向）：' + missing)
    if not family and len({profile_family(p) for p in matches}) > 1:
        raise ValueError('骨骼名称匹配多个角色类型；请显式选择正确的 skeleton.nif')
    def score(profile):
        path = profile['path'].lower().replace('\\', '/')
        return (len(profile['names']), path)
    selected = min(matches, key=score)
    return dict(path=selected['path'], sha256=selected['sha256'],
                bs=expected_bs, matched_bones=sorted(required),
                matching_profiles=len(matches),
                source_actor_family=family, first_person=first_person,
                validation='bone_names_and_binary_layout',
                transforms_and_weights_preserved=True,
                animation_retargeted=False, semantic_runtime_verified=False)
