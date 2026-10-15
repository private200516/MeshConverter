"""Synthetic static-format regressions; no game files are bundled."""
from pathlib import Path
import math
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert_models import Writer, P, IDENTITY, convert, geometry
from inspect_nif import Nif, Reader
from convert_preserved import shape
from havok.bhk_autounpack import parse_bytes


def make_fixture(path, partition=False, helper=False, transformed=False):
    w = Writer(bs=155)
    w.add('NiNode')
    extra = w.add('BSConnectPoint::Parents', P('iI', w.sid('CPA'), 1)
                  + P('I', 4) + b'Root' + P('I', 4) + b'Lamp'
                  + P('8f', 0, 0, 0, 1, 3, 4, 5, 1))
    value = w.add('BSValueNode')
    node_transform = (12., 0., 0., *IDENTITY[3:])
    if helper:
        w.set(value, w.av('Value', node_transform, flags=6) + P('IIB', 0, 7, 3))
    else:
        mesh = w.add('BSSubIndexTriShape' if partition else 'BSTriShape')
        shader = w.add('BSLightingShaderProperty', w.net('Materials/test.bgsm'))
        data = b''.join(P('4e', *v, 0) for v in ((0, 0, 0), (70, 0, 0), (0, 70, 0))) + P('3H', 0, 1, 2)
        tail = P('7I', 1, 1, 1, 0, 1, 0xffffffff, 0) if partition else b''
        payload = (w.av('Mesh', IDENTITY, flags=14) + P('10f', 0, 0, 0, 100, 35, 35, 0, 35, 35, 0)
                   + P('iiiQIHI', -1, shader, -1, 2 | (1 << 44), 1, 3, len(data)) + data + tail)
        w.set(mesh, payload)
        w.set(value, w.av('Value', node_transform, flags=6) + P('IiIB', 1, mesh, 7, 3))
    root_transform = (100., 200., 300., *IDENTITY[3:]) if transformed else IDENTITY
    w.set(0, w.av('Root', root_transform, extra=[extra], flags=12) + P('Ii', 1, value))
    w.save(path)
    return w


class StaticCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.src, self.out = self.root / 'source.nif', self.root / 'output.nif'

    def tearDown(self):
        self.temp.cleanup()

    def test_writer_130_and_155_headers_with_legacy_strings(self):
        for version in (130, 155):
            writer = Writer(bs=version)
            name = '\u4e2d\u6587\udcff'
            writer.add('NiNode', writer.av(name, IDENTITY) + P('I', 0))
            writer.save(self.out)
            result = Nif(self.out)
            self.assertEqual(result.bs, version)
            self.assertEqual(result.strings, [name])
            self.assertEqual(result.maxlen, 7)
            self.assertEqual(result.roots, [0])
            if version == 155:
                self.assertEqual(result.unk, 0)
                self.assertFalse(hasattr(result, 'process'))

    def test_partition_tail_not_read_as_triangles(self):
        make_fixture(self.src, partition=True)
        source = Nif(self.src)
        desc = next(d for d in source.inspect() if d['type'] == 'BSSubIndexTriShape')
        self.assertEqual(geometry(source, desc)[1], [(0, 1, 2)])
        report = convert(self.src, self.out, collision=False)
        target = Nif(self.out)
        target_id = next(i for i, t in enumerate(target.indices) if target.types[t] == 'BSSubIndexTriShape')
        parsed = shape(target, target_id)
        self.assertEqual(parsed['segments']['segments'], 1)
        self.assertEqual(report['partitioned_shapes'], 1)
        self.assertEqual(target.blocks[target_id][parsed['dataoffset']:], source.blocks[desc['id']][desc['dataoffset']:])

    def test_value_node_children_flags_and_extras_preserved(self):
        make_fixture(self.src)
        convert(self.src, self.out, collision=False)
        source, target = Nif(self.src), Nif(self.out)
        value = next(d for d in target.inspect() if d['type'] == 'BSValueNode')
        self.assertEqual(value['name'], 'Value')
        self.assertEqual(value['flags'], 6)
        self.assertEqual(len(value['children']), 1)
        self.assertEqual(target.blocks[value['id']][-5:], P('IB', 7, 3))
        old = next(i for i, t in enumerate(source.indices) if source.types[t] == 'BSConnectPoint::Parents')
        new = next(i for i, t in enumerate(target.indices) if target.types[t] == 'BSConnectPoint::Parents')
        self.assertEqual(source.blocks[old], target.blocks[new])

    def test_helper_only_model_is_preserved_without_invented_collision(self):
        make_fixture(self.src, helper=True, transformed=True)
        report = convert(self.src, self.out)
        target = Nif(self.out)
        self.assertEqual(report['shapes'], 0)
        self.assertTrue(report['helper_only'])
        self.assertIsNone(report['collision_rebuilt'])
        self.assertNotIn('bhkPhysicsSystem', target.types)
        self.assertEqual(target.inspect()[0]['transform'][:3], (100., 200., 300.))

    def test_root_transform_collision_keeps_local_coordinates(self):
        make_fixture(self.src, transformed=True, partition=True)
        report = convert(self.src, self.out)
        target = Nif(self.out)
        root = target.inspect()[0]
        self.assertEqual(root['transform'][:3], (100., 200., 300.))
        self.assertEqual(root['flags'], 12)
        self.assertNotEqual(root['collision'], -1)
        physics = next(b for t, b in zip(target.indices, target.blocks) if target.types[t] == 'bhkPhysicsSystem')
        parsed = parse_bytes(physics[4:])[0]
        self.assertEqual(len(parsed.faces), 1)
        # Vertex coordinates include child translation (12), never root translation (100).
        self.assertAlmostEqual(min(v[0] for v in parsed.verts), 12 / 69.99125, places=3)
        self.assertEqual(report['collision_triangles'], 1)

    def test_controller_is_rejected_instead_of_silently_dropped(self):
        writer = make_fixture(self.src)
        writer.add('NiTransformController', b'')
        writer.save(self.src)
        with self.assertRaisesRegex(ValueError, 'NiTransformController'):
            convert(self.src, self.out)
        self.assertFalse(self.out.exists())

    def test_node_cycle_is_rejected(self):
        writer = make_fixture(self.src, helper=True)
        writer.set(2, writer.av('Value', IDENTITY) + P('IiIB', 1, 0, 7, 3))
        writer.save(self.src)
        with self.assertRaisesRegex(ValueError, 'cycle'):
            convert(self.src, self.out)

    def test_malformed_value_payload_rejected(self):
        writer = make_fixture(self.src, helper=True)
        writer.set(2, writer.blocks[2][1][:-1])
        writer.save(self.src)
        with self.assertRaisesRegex(ValueError, 'BSValueNode'):
            convert(self.src, self.out)

    def test_dry_run_preserves_input_and_writes_nothing(self):
        make_fixture(self.src, partition=True)
        before = self.src.read_bytes()
        report = convert(self.src, self.out, dry_run=True)
        self.assertEqual(report['shapes'], 1)
        self.assertEqual(before, self.src.read_bytes())
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
