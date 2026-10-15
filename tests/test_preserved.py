"""Corrupt-bind/partition regression tests using generated, non-game fixtures."""
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inspect_nif import Nif, Reader
from convert_models import Writer, P, IDENTITY
from convert_preserved import segments, shape, skin_instance, validate_weights, validate_graph, effect
from skin_reference import match_skeleton
from shader_flags import fo4_to_fo76, fo76_to_fo4


class InMemoryNif:
    av = Nif.av
    net = Nif.net
    name = Nif.name
    ref = Nif.ref

    def __init__(self, pairs, strings=(), bs=155):
        self.types = [p[0] for p in pairs]
        self.indices = tuple(range(len(pairs)))
        self.blocks = [p[1] for p in pairs]
        self.strings = list(strings)
        self.count = len(pairs)
        self.bs = bs


def fixture_skin():
    writer = Writer()
    root = writer.av('Root', IDENTITY) + P('Ii', 1, 1)
    bone = writer.av('Bone', IDENTITY) + P('I', 0)
    instance = P('iiIiI', 0, 3, 1, 1, 0)
    bone_data = P('I17f', 1, 0, 0, 0, 1, *IDENTITY[3:12], 0, 0, 0, 1)
    return InMemoryNif([('NiNode', root), ('NiNode', bone),
                        ('BSSkin::Instance', instance), ('BSSkin::BoneData', bone_data)], writer.strings)


class PreservedValidationTests(unittest.TestCase):
    def test_external_effect_fallback_uses_owner_vertex_flags(self):
        n = InMemoryNif([('BSEffectShaderProperty', P('iIi', 0, 0, -1))], ['Materials/fx.bgem'])
        fallback, detail = effect(n, n.blocks[0], [dict(skin=-1, desc=1 << 44)])
        self.assertEqual(len(fallback), 104)
        self.assertEqual(struct.unpack_from('<II', fallback, 12), (0x80000000, 0))
        colored, _ = effect(n, n.blocks[0], [dict(skin=1, desc=(1 | 32 | 64) << 44)])
        self.assertEqual(struct.unpack_from('<II', colored, 12), (0x80000002, 32))
        self.assertEqual(detail['external_material'], 'Materials/fx.bgem')

    def test_shader_flags_roundtrip_and_unmapped_rejection(self):
        flags = (0xe0000148, 0x40000031)
        self.assertEqual(fo76_to_fo4(*fo4_to_fo76(*flags)), flags)
        with self.assertRaisesRegex(ValueError, 'no verified'):
            fo4_to_fo76(1, 0)  # Specular is not equivalent to FO76 PBR.
        with self.assertRaisesRegex(ValueError, 'no verified'):
            fo76_to_fo4([731263983], [])

    def test_partition_triangle_ranges_and_coverage(self):
        valid = P('7I', 2, 1, 1, 0, 2, 0xffffffff, 0)
        self.assertEqual(segments(Reader(valid), 2)['segments'], 1)
        with self.assertRaisesRegex(ValueError, '范围'):
            segments(Reader(P('7I', 2, 1, 1, 3, 2, 0xffffffff, 0)), 2)
        partial = segments(Reader(P('7I', 2, 1, 1, 0, 1, 0xffffffff, 0)), 2)
        self.assertEqual(partial['unassigned_triangles'], 1)

    def test_shared_subpartition_layout(self):
        tail = (P('3I', 2, 1, 2) + P('4I', 0, 2, 0xffffffff, 1)
                + P('4I', 0, 2, 0, 0) + P('3I', 1, 2, 0)
                + P('3I', 0, 0xffffffff, 0) + P('3I', 32, 123, 0)
                + P('H', 4) + b'a.ssf'[:4])
        self.assertEqual(segments(Reader(tail), 2)['total_segments'], 2)
        with self.assertRaises(ValueError):
            segments(Reader(tail[:-1]), 2)

    def test_bone_count_must_match(self):
        n = fixture_skin()
        self.assertEqual(skin_instance(n, 2)['names'], ['Bone'])
        n.blocks[3] = P('I', 2) + n.blocks[3][4:]
        with self.assertRaisesRegex(ValueError, '数量'):
            skin_instance(n, 2)

    def test_nonfinite_bind_transform_rejected(self):
        n = fixture_skin()
        b = bytearray(n.blocks[3]);struct.pack_into('<f', b, 20, math.nan)
        n.blocks[3] = bytes(b)
        with self.assertRaisesRegex(ValueError, '有限'):
            skin_instance(n, 2)

    def test_skin_weight_and_index_integrity(self):
        d = dict(desc=5 | (2 << 28), dataoffset=0, vertices=1)
        n = InMemoryNif([('BSTriShape', b'\0' * 8 + P('4e4B', 1, 0, 0, 0, 0, 0, 0, 0))])
        validate_weights(n, 0, d, {'count': 1})
        n.blocks[0] = b'\0' * 8 + P('4e4B', 1, 0, 0, 0, 1, 0, 0, 0)
        with self.assertRaisesRegex(ValueError, '索引'):
            validate_weights(n, 0, d, {'count': 1})
        n.blocks[0] = b'\0' * 8 + P('4e4B', 0, 0, 0, 0, 0, 0, 0, 0)
        with self.assertRaisesRegex(ValueError, '权重'):
            validate_weights(n, 0, d, {'count': 1})

    def test_unskinned_partition_is_valid_without_skin(self):
        writer = Writer()
        vertices = P('4e', 0, 0, 0, 0) * 3
        data = vertices + P('3H', 0, 1, 2)
        desc = 2 | (1 << 44)
        block = (writer.av('Partition', IDENTITY) + P('10f', 0, 0, 0, 1, 0, 0, 0, 1, 1, 1)
                 + P('iiiQIHI', -1, 0, -1, desc, 1, 3, len(data)) + data
                 + P('7I', 1, 1, 1, 0, 1, 0xffffffff, 0))
        n = InMemoryNif([('BSSubIndexTriShape', block)], writer.strings)
        self.assertEqual(shape(n, 0)['skin'], -1)
        # A skin descriptor cannot silently exist with a NULL instance.
        corrupted = bytearray(block);struct.pack_into('<Q', corrupted, 128, desc | (64 << 44))
        n.blocks[0] = bytes(corrupted)
        with self.assertRaises(ValueError):
            shape(n, 0)

    def test_graph_cycle_rejected(self):
        n = fixture_skin()
        n.blocks[1] = n.blocks[1][:-4] + P('Ii', 1, 0)
        with self.assertRaisesRegex(ValueError, '循环'):
            validate_graph(n, [], {2: skin_instance(n, 2)})

    def test_reference_does_not_substitute_actor_families(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for family in ('Character', 'Supermutant'):
                writer = Writer()
                writer.add('NiNode', writer.av('Bone', IDENTITY) + P('I', 0))
                writer.save(root / 'Actors' / family / 'CharacterAssets/skeleton.nif')
            profile = match_skeleton(root, ['Bone'], '/meshes/armor/gloves.nif')
            self.assertIn('Character', profile['path'])
            with self.assertRaisesRegex(ValueError, '多个角色'):
                match_skeleton(root, ['Bone'], '/unknown/gloves.nif')
            with self.assertRaisesRegex(ValueError, '缺少'):
                match_skeleton(root, ['UnknownBone'], '/meshes/armor/gloves.nif')


if __name__ == '__main__':
    unittest.main()
