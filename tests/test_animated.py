"""Animation corruption and collision-mode tests using generated NIF fixtures."""
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inspect_nif import Nif, Reader
from convert_models import Writer, P, IDENTITY
from convert_animated import convert, validate_animation, ANIM
from havok.bhk_autounpack import parse_bytes


def fixture(path, mutate=None):
    w = Writer(bs=155)
    for typ in ('NiNode', 'NiTransformController', 'NiTransformInterpolator', 'NiTransformData',
                'BSXFlags', 'bhkNPCollisionObject', 'bhkPhysicsSystem', 'BSTriShape', 'BSEffectShaderProperty'):
        w.add(typ)
    w.set(0, w.av('Animated', IDENTITY, collision=5, extra=[4], ctrl=1) + P('Ii', 1, 7))
    w.set(1, P('iH4fii', -1, 76, 1, 0, 0, 1, 0, 2))
    w.set(2, P('8fi', 0, 0, 0, 1, 0, 0, 0, 1, 3))
    w.set(3, P('III8fI', 0, 2, 1, 0, 0, 0, 0, 1, 1, 2, 3, 0))
    w.set(4, P('iI', w.sid('BSX'), 3))
    w.set(5, P('iHiI', 0, 128, 6, 0))
    payload = b'FO76_PHYSICS_PAYLOAD_SHOULD_NEVER_BE_COPIED'
    w.set(6, P('I', len(payload)) + payload)
    data = b''.join(P('4e', *v, 0) for v in ((0, 0, 0), (70, 0, 0), (0, 70, 0))) + P('3H', 0, 1, 2)
    w.set(7, w.av('Triangle', IDENTITY) + P('10f', 0, 0, 0, 100, 35, 35, 0, 35, 35, 0)
          + P('iiiQIHI', -1, 8, -1, 2 | (1 << 44), 1, 3, len(data)) + data)
    w.set(8, w.net('Materials/demo.bgem'))
    if mutate:
        mutate(w)
    w.save(path)


class AnimationTests(unittest.TestCase):
    def test_standalone_animation_and_collision_off_preserve_frames(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
            fixture(src); result = convert(src, dst, collision=False)
            original, target = Nif(src), Nif(dst)
            self.assertEqual(target.bs, 130)
            self.assertTrue(result['collision_removed'])
            self.assertNotIn('bhkPhysicsSystem', target.types)
            self.assertNotIn('bhkNPCollisionObject', target.types)
            self.assertNotIn(b'FO76_PHYSICS_PAYLOAD', dst.read_bytes())
            self.assertEqual(target.av(Reader(target.blocks[0]))['collision'], -1)
            self.assertEqual(struct.unpack('<iI', target.blocks[4])[1], 1)
            for i, t in enumerate(original.indices):
                if original.types[t] in ANIM:
                    self.assertEqual(original.blocks[i], target.blocks[i])
            self.assertEqual(validate_animation(target)[1], {0})

    def test_collision_rebuild_and_preflight_encode_same_payload(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
            fixture(src)
            preflight = convert(src, dst, collision=True, dry_run=True)
            self.assertFalse(dst.exists())
            result = convert(src, dst, collision=True)
            self.assertEqual(preflight['collision_bodies'], result['collision_bodies'])
            target = Nif(dst); bodies = parse_bytes(target.blocks[6][4:])
            self.assertEqual(len(bodies), 1)
            self.assertEqual(bodies[0].physics.mass, 0)
            self.assertTrue(bodies[0].physics.is_dynamic)
            self.assertNotIn(b'FO76_PHYSICS_PAYLOAD', dst.read_bytes())

    def test_controller_cycle_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
            fixture(src, lambda w: w.set(1, P('i', 1) + w.blocks[1][1][4:]))
            with self.assertRaisesRegex(ValueError, '循环'):
                convert(src, dst, collision=False)
            self.assertFalse(dst.exists())

    def test_wrong_interpolator_reference_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
            fixture(src, lambda w: w.set(1, w.blocks[1][1][:-4] + P('i', 6)))
            with self.assertRaisesRegex(ValueError, '插值器'):
                convert(src, dst, collision=False, dry_run=True)
            self.assertFalse(dst.exists())

    def test_unordered_or_nonfinite_key_data_rejected(self):
        for bad in (math.nan, -1):
            with self.subTest(value=bad), tempfile.TemporaryDirectory() as td:
                src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
                def mutate(w):
                    raw = bytearray(w.blocks[3][1]); struct.pack_into('<f', raw, 28, bad)
                    w.set(3, bytes(raw))
                fixture(src, mutate)
                with self.assertRaises(ValueError):
                    convert(src, dst, collision=False)
                self.assertFalse(dst.exists())

    def test_unknown_shader_controller_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / 'source.nif', Path(td) / 'target.nif'
            fixture(src, lambda w: w.add('BSLightingShaderPropertyUShortController', b''))
            with self.assertRaisesRegex(ValueError, '未支持'):
                convert(src, dst, collision=False)
            self.assertFalse(dst.exists())


if __name__ == '__main__':
    unittest.main()
