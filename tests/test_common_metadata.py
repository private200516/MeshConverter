"""Guest-only regressions for parsed metadata and unused type-table entries.

Fixtures are synthesized here; no game assets or executable dependencies are
copied by these tests. Run in the approved offline guest, never on the host.
"""
import hashlib
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert_models import Writer, P, IDENTITY, sized, COMMON_EXTRA_TYPES, convert as static_convert
from convert_preserved import convert as preserved_convert, shape, validate_weights, skin_instance
from convert_reverse import convert as reverse_convert
from convert_animated import convert as animated_convert
from inspect_nif import Nif, Reader


def metadata(writer, kind):
    name = writer.sid('Metadata')
    if kind == 'BSXFlags':
        return P('iI', name, 1)
    if kind == 'BSBound':
        return P('i6f', name, 1, 2, 3, 4, 5, 6)
    if kind == 'BSInvMarker':
        return P('i3Hf', name, 1, 2, 3, 1.25)
    if kind == 'NiStringExtraData':
        return P('ii', name, writer.sid('preserved value'))
    if kind == 'NiStringsExtraData':
        return P('iI', name, 2) + sized('first value') + sized('second value')
    if kind == 'NiIntegerExtraData':
        return P('iI', name, 17)
    if kind == 'NiBooleanExtraData':
        return P('iB', name, 1)
    if kind == 'NiFloatExtraData':
        return P('if', name, 2.5)
    if kind == 'BSConnectPoint::Parents':
        return P('iI', name, 1) + sized('Root') + sized('Connector') + P('8f', 0, 0, 0, 1, 1, 2, 3, 1)
    if kind == 'BSConnectPoint::Children':
        return P('iBI', name, 1, 1) + sized('Connector')
    if kind in ('BSFurnitureMarker', 'BSFurnitureMarkerNode'):
        return P('iI4f2H', name, 1, 1, 2, 3, 0.5, 1, 1)
    raise AssertionError(kind)


def fixture(path, bs=155, kinds=(), animated=False, mutation=None, skinned=False):
    writer = Writer(bs=bs)
    writer.add('NiNode')
    writer.add('BSTriShape')
    writer.add('BSEffectShaderProperty')
    extras = [writer.add(kind, metadata(writer, kind)) for kind in kinds]
    shader = writer.net('Materials/example.bgem')
    if bs == 130:
        shader += P('II4f', 0x80000000, 0, 0, 0, 1, 1) + sized('')
        shader += P('4B4f4fff', 3, 255, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 100)
        shader += sized('') * 4 + P('f', 1)
    writer.set(2, shader)
    skin = -1
    children = [1]
    desc = 2 | (1 << 44)
    weight = b''
    if skinned:
        bone = writer.add('NiNode', writer.av('Bone', IDENTITY) + P('I', 0))
        bone_data = writer.add('BSSkin::BoneData', P('I17f', 1, 0, 0, 0, 1, *IDENTITY[3:12], 0, 0, 0, 1))
        skin = writer.add('BSSkin::Instance', P('iiIiI', 0, bone_data, 1, bone, 0))
        children.append(bone)
        desc = 5 | (2 << 28) | (0x41 << 44)
        weight = P('4e4B', 1, 0, 0, 0, 0, 0, 0, 0)
    data = b''.join(P('4e', *v, 0) + weight for v in ((0, 0, 0), (1, 0, 0), (0, 1, 0))) + P('3H', 0, 1, 2)
    bound = P('4f', 0, 0, 0, 1)
    if bs == 155:
        bound += P('6f', 0.5, 0.5, 0, 0.5, 0.5, 0)
    writer.set(1, writer.av('Triangle', IDENTITY) + bound
               + P('iiiQIHI', skin, 2, -1, desc, 1, 3, len(data)) + data)
    ctrl = -1
    if animated:
        ctrl = writer.add('NiTransformController')
        interp = writer.add('NiTransformInterpolator', P('8fi', 0, 0, 0, 1, 0, 0, 0, 1, -1))
        writer.set(ctrl, P('iH4fii', -1, 76, 1, 0, 0, 1, 0, interp))
    writer.set(0, writer.av('Root', IDENTITY, extra=extras, ctrl=ctrl)
               + P('I', len(children)) + b''.join(P('i', child) for child in children))
    if mutation:
        mutation(writer, extras)
    writer.save(path)
    return writer, extras


def add_unused_declared_type(path, kind='NiParticleSystem'):
    """Add a real unused directory entry, keeping every payload/index unchanged."""
    data = path.read_bytes()
    reader = Reader(data)
    reader.read(data.index(b'\n') + 1)
    version, endian, user, count, bs = reader.get('IBIII')
    reader.exp()
    reader.u() if bs > 130 else reader.exp()
    reader.exp()
    reader.exp()
    offset = reader.p
    types = reader.get('H')[0]
    for _ in range(types):
        reader.s()
    path.write_bytes(data[:offset] + P('H', types + 1)
                     + data[offset + 2:reader.p] + sized(kind) + data[reader.p:])


class CommonMetadataTests(unittest.TestCase):
    def test_skin_bindings_and_weights_are_kept_with_new_metadata(self):
        for version, convert in ((155, preserved_convert), (130, reverse_convert)):
            with self.subTest(bs=version), tempfile.TemporaryDirectory() as td:
                src, dst, reference = (Path(td) / name for name in ('source.nif', 'target.nif', 'skeleton.nif'))
                _, extras = fixture(src, version, sorted(COMMON_EXTRA_TYPES), skinned=True)
                target_bs = 130 if version == 155 else 155
                skeleton = Writer(bs=target_bs)
                skeleton.add('NiNode', skeleton.av('Bone', IDENTITY) + P('I', 0))
                skeleton.save(reference)
                original = Nif(src)
                result = convert(src, dst, collision=False, reference_root=reference)
                target = Nif(dst)
                self.assertEqual(result['bones'], ['Bone'])
                self.assertEqual(target.bs, target_bs)
                for index in extras:
                    self.assertEqual(target.blocks[index], original.blocks[index])
                before, after = shape(original, 1), shape(target, 1)
                self.assertEqual(original.blocks[1][before['dataoffset']:], target.blocks[1][after['dataoffset']:])
                skin = skin_instance(target, after['skin'])
                self.assertEqual(skin['names'], ['Bone'])
                validate_weights(target, 1, after, skin)

    def test_shared_metadata_bytes_and_references_survive_both_directions(self):
        for version, convert in ((155, preserved_convert), (130, reverse_convert)):
            with self.subTest(bs=version), tempfile.TemporaryDirectory() as td:
                src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
                kinds = sorted(COMMON_EXTRA_TYPES)
                _, extras = fixture(src, version, kinds)
                original = Nif(src)
                source_hash = hashlib.sha256(src.read_bytes()).hexdigest()
                convert(src, dst, collision=False)
                target = Nif(dst)
                self.assertEqual(target.bs, 130 if version == 155 else 155)
                self.assertEqual(target.av(Reader(target.blocks[0]))['extra'], extras)
                for index, kind in zip(extras, kinds):
                    self.assertEqual(target.types[target.indices[index]], kind)
                    self.assertEqual(target.blocks[index], original.blocks[index])
                self.assertEqual(target.strings[:len(original.strings)], original.strings)
                self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), source_hash)

    def test_malformed_shared_metadata_is_rejected_without_output(self):
        mutations = {
            'NiBooleanExtraData': lambda b: b[:-1] + b'\x02',
            'NiFloatExtraData': lambda b: b[:4] + P('f', math.nan),
            'NiStringExtraData': lambda b: b[:4] + P('i', 10000),
            'NiStringsExtraData': lambda b: b[:-1],
            'BSInvMarker': lambda b: b + b'unknown',
        }
        for version, convert in ((155, preserved_convert), (130, reverse_convert)):
            for kind, corrupt in mutations.items():
                with self.subTest(bs=version, kind=kind), tempfile.TemporaryDirectory() as td:
                    src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
                    def mutate(writer, extras):
                        writer.set(extras[0], corrupt(writer.blocks[extras[0]][1]))
                    fixture(src, version, [kind], mutation=mutate)
                    with self.assertRaises(ValueError):
                        convert(src, dst, collision=False)
                    self.assertFalse(dst.exists())

    def test_opaque_binary_payload_remains_unsupported(self):
        for version, convert in ((155, preserved_convert), (130, reverse_convert)):
            with self.subTest(bs=version), tempfile.TemporaryDirectory() as td:
                src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
                def mutate(writer, extras):
                    opaque = writer.add('NiBinaryExtraData', P('iI', writer.sid('UnknownSemantic'), 4) + b'data')
                    writer.set(0, writer.av('Root', IDENTITY, extra=[opaque]) + P('Ii', 1, 1))
                fixture(src, version, mutation=mutate)
                with self.assertRaisesRegex(ValueError, 'NiBinaryExtraData'):
                    convert(src, dst, collision=False)
                self.assertFalse(dst.exists())

    def test_metadata_array_counts_must_fit_their_payload(self):
        kinds = {'NiStringsExtraData': 4, 'BSConnectPoint::Parents': 4,
                 'BSConnectPoint::Children': 5, 'BSFurnitureMarkerNode': 4}
        for version, convert in ((155, preserved_convert), (130, reverse_convert)):
            for kind, offset in kinds.items():
                with self.subTest(bs=version, kind=kind), tempfile.TemporaryDirectory() as td:
                    src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
                    def mutate(writer, extras):
                        block = bytearray(writer.blocks[extras[0]][1])
                        struct.pack_into('<I', block, offset, 0xffffffff)
                        writer.set(extras[0], bytes(block))
                    fixture(src, version, [kind], mutation=mutate)
                    with self.assertRaisesRegex(ValueError, 'array count'):
                        convert(src, dst, collision=False)
                    self.assertFalse(dst.exists())

    def test_unused_type_table_entry_does_not_reject_valid_payloads(self):
        routes = ((155, static_convert, False), (155, preserved_convert, False),
                  (155, animated_convert, True), (130, reverse_convert, False))
        for version, convert, animated in routes:
            with self.subTest(route=convert.__module__), tempfile.TemporaryDirectory() as td:
                src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
                fixture(src, version, animated=animated)
                add_unused_declared_type(src)
                original = Nif(src)
                self.assertIn('NiParticleSystem', original.types)
                self.assertNotIn('NiParticleSystem', {original.types[index] for index in original.indices})
                convert(src, dst, collision=False)
                self.assertNotIn('NiParticleSystem', Nif(dst).types)

    def test_actual_unknown_block_still_rejected(self):
        routes = ((155, static_convert, False), (155, preserved_convert, False),
                  (155, animated_convert, True), (130, reverse_convert, False))
        for version, convert, animated in routes:
            with self.subTest(route=convert.__module__), tempfile.TemporaryDirectory() as td:
                src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
                fixture(src, version, animated=animated,
                        mutation=lambda writer, extras: writer.add('NiParticleSystem', b'unknown'))
                with self.assertRaisesRegex(ValueError, 'NiParticleSystem'):
                    convert(src, dst, collision=False)
                self.assertFalse(dst.exists())


if __name__ == '__main__':
    unittest.main()
