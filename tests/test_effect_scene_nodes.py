"""Production-entry regressions for camera-facing geometry, blast nodes and inline FX."""
from pathlib import Path
import tempfile
import unittest

from converter import convert_file
from convert_models import IDENTITY, P, sized
from inspect_nif import Nif
from test_animated import fixture
from test_static import make_fixture


def add_scene_nodes(writer, billboard_suffix=P('H', 1), blast_suffix=bytes((1, 1, 0))):
    billboard = writer.add('NiBillboardNode', writer.av('Beam', IDENTITY)
                           + P('Ii', 1, 7) + billboard_suffix)
    blast = writer.add('BSBlastNode', writer.av('Muzzle', IDENTITY)
                       + P('Ii', 1, billboard) + blast_suffix)
    writer.set(0, writer.av('Animated', IDENTITY, collision=5, extra=[4], ctrl=1)
               + P('Ii', 1, blast))


def inline_effect(writer, active):
    hashes = P('III', 1, 0, 1957349758) if active else P('II', 0, 0)
    net = writer.net('')
    prefix = (P('4f', 0, 0, 1, 1) + sized('textures/beam.dds') + P('4B', 3, 240, 1, 0)
              + P('4f', 0.2, 0.6, 0.4, 0.8))
    suffix = P('6f', 1, 0.5, 0.25, 1, 8, 2) + sized('') * 4 + P('f', 1)
    fo76_only = sized('') * 2 + P('3f', 0, 0, 0) + sized('') + P('4f', 100, 13.5, 2, 3)
    writer.set(8, net + hashes + prefix + P('f', 0.1) + suffix + fo76_only)
    return net + P('II', 0x8000 if active else 0, 0) + prefix + suffix


class EffectSceneNodeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root / 'input' / 'source.nif'
        self.dest = self.root / 'out' / 'target.nif'
        self.src.parent.mkdir()

    def test_animated_nodes_keep_subclass_fields_children_and_keys(self):
        fixture(self.src, add_scene_nodes)
        report = convert_file(self.src, self.dest, collision=False)
        before, after = Nif(self.src), Nif(self.dest)
        self.assertEqual(after.bs, 130)
        self.assertTrue(report['animation_keys_preserved'])
        nodes = {n['id']: n for n in after.inspect()}
        self.assertEqual(nodes[9]['billboard_mode'], 1)
        self.assertEqual(nodes[10]['blast_range'], (1, 1, 0))
        self.assertEqual(nodes[0]['children'], [10])
        self.assertEqual(nodes[10]['children'], [9])
        self.assertEqual(nodes[9]['children'], [7])
        self.assertEqual(before.blocks[9:11], after.blocks[9:11])

    def test_fixed_collision_rejects_camera_facing_geometry(self):
        fixture(self.src, add_scene_nodes)
        for dry in (True, False):
            with self.subTest(dry=dry), self.assertRaisesRegex(ValueError, '朝向相机'):
                convert_file(self.src, self.dest, collision=True, dry_run=dry)
            self.assertFalse(self.dest.exists())

    def test_unknown_mode_and_incomplete_node_payloads_are_rejected(self):
        for billboard, blast in ((P('H', 65535), bytes(3)), (bytes(1), bytes(3)),
                                 (bytes(2), bytes(4))):
            with self.subTest(billboard=billboard, blast=blast):
                fixture(self.src, lambda w: add_scene_nodes(w, billboard, blast))
                with self.assertRaisesRegex(ValueError, 'facing mode|suffix size'):
                    convert_file(self.src, self.dest, collision=False)
                self.assertFalse(self.dest.exists())

    def test_inactive_refraction_does_not_block_mapped_effect_fields(self):
        expected = []
        fixture(self.src, lambda w: expected.append(inline_effect(w, False)))
        report = convert_file(self.src, self.dest, collision=False)
        notes = [item for item in report['notes'] if isinstance(item, dict)]
        self.assertAlmostEqual(notes[0]['inactive_fo76_refraction_power'], 0.1)
        self.assertEqual(Nif(self.dest).blocks[8], expected[0])

    def test_active_refraction_still_requires_parameter_mapping(self):
        fixture(self.src, lambda w: inline_effect(w, True))
        with self.assertRaisesRegex(ValueError, 'FO76 专属参数'):
            convert_file(self.src, self.dest, collision=False)
        self.assertFalse(self.dest.exists())

    def test_static_and_reverse_paths_preserve_node_fields(self):
        writer = make_fixture(self.src)
        writer.blocks[2] = ('NiBillboardNode', writer.av('Billboard', IDENTITY)
                            + P('IiH', 1, 3, 9))
        writer.save(self.src)
        with self.assertRaisesRegex(ValueError, '朝向相机'):
            convert_file(self.src, self.dest, collision=True)
        self.assertFalse(self.dest.exists())
        convert_file(self.src, self.dest, collision=False)
        reverse = self.root / 'reverse' / 'reverted.nif'
        convert_file(self.dest, reverse, direction='4-to-76', collision=False)
        for path in (self.dest, reverse):
            nodes = {n['id']: n for n in Nif(path).inspect()}
            billboard = next(n for n in nodes.values() if n['type'] == 'NiBillboardNode')
            self.assertEqual(billboard['billboard_mode'], 9)
            self.assertEqual(nodes[billboard['children'][0]]['type'], 'BSTriShape')
