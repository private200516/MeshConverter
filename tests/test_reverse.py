"""FO4 -> FO76 schema safety and bounds tests using generated fixtures."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert_models import Writer, P, IDENTITY, LIGHT, sized
from inspect_nif import Nif, Reader
from convert_preserved import shape
from convert_reverse import convert, bounds


def fixture(path, slots=9, physics=False, full_precision=False):
    writer = Writer(bs=130)
    writer.add('NiNode')
    writer.add('BSTriShape')
    writer.add('BSLightingShaderProperty')
    writer.add('BSShaderTextureSet', P('I', slots) + b''.join(sized(f'textures/slot{i}.dds') for i in range(slots)))
    material = writer.sid('Materials/example.bgsm')
    shader = bytearray(LIGHT)
    struct.pack_into('<i', shader, 4, material)
    struct.pack_into('<i', shader, 40, 3)
    writer.set(2, bytes(shader))
    coords = ((-2, -2, -3), (4, 8, 13), (4, -2, 5))
    data = b''.join(P('4f' if full_precision else '4e', *vertex, 0) for vertex in coords) + P('3H', 0, 1, 2)
    desc = 4 | (0x401 << 44) if full_precision else 2 | (1 << 44)
    writer.set(1, writer.av('Geometry', IDENTITY) + P('4fiiiQIHI', 1, 3, 5, 10, -1, 2, -1, desc, 1, 3, len(data)) + data)
    collision = -1
    extras = []
    if physics:
        collision = writer.add('bhkNPCollisionObject')
        payload = b'FO4_HAVOK_BYTES!!'
        system = writer.add('bhkPhysicsSystem', P('I', len(payload)) + payload)
        writer.set(collision, P('iHiI', 0, 128, system, 0))
        extras.append(writer.add('BSXFlags', P('iI', writer.sid('BSX'), 0x12)))
    writer.set(0, writer.av('Root', IDENTITY, collision=collision, extra=extras) + P('Ii', 1, 1))
    writer.save(path)
    return writer


class ReverseCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.src, self.out = self.root / 'source.nif', self.root / 'output.nif'

    def tearDown(self):
        self.temp.cleanup()

    def test_bounds_store_center_and_half_extents_for_half_and_full_precision(self):
        for full in (False, True):
            with self.subTest(full_precision=full):
                fixture(self.src, full_precision=full)
                if self.out.exists():
                    self.out.unlink()
                source = Nif(self.src)
                desc = next(d for d in source.inspect() if d['type'] == 'BSTriShape')
                self.assertEqual(bounds(source, desc), (1., 3., 5., 3., 5., 8.))
                convert(self.src, self.out)
                target = Nif(self.out)
                shape_info = shape(target, 1)
                self.assertEqual(target.bs, 155)
                self.assertEqual(struct.unpack_from('<6f', target.blocks[1], shape_info['boundend']), (1., 3., 5., 3., 5., 8.))
                self.assertEqual(target.blocks[1][shape_info['dataoffset']:], source.blocks[1][desc['dataoffset']:])

    def test_nine_and_ten_texture_slots_are_preserved_then_padded(self):
        for slots in (9, 10):
            with self.subTest(slots=slots):
                fixture(self.src, slots=slots)
                if self.out.exists():
                    self.out.unlink()
                convert(self.src, self.out)
                result = Nif(self.out)
                r = Reader(result.blocks[3])
                textures = [r.s() for _ in range(r.u())]
                self.assertEqual(len(textures), 15)
                self.assertEqual(textures[:slots], [f'textures/slot{i}.dds' for i in range(slots)])
                self.assertEqual(textures[slots:], [''] * (15 - slots))
                self.assertEqual(r.p, len(r.b))

    def test_unverified_texture_count_is_rejected(self):
        fixture(self.src, slots=11)
        with self.assertRaisesRegex(ValueError, '9/10'):
            convert(self.src, self.out)
        self.assertFalse(self.out.exists())

    def test_physics_requires_explicit_visual_only_selection(self):
        fixture(self.src, physics=True)
        with self.assertRaisesRegex(ValueError, 'Havok'):
            convert(self.src, self.out, collision=True)
        self.assertFalse(self.out.exists())
        result = convert(self.src, self.out, collision=False)
        target = Nif(self.out)
        self.assertTrue(result['physics_removed'])
        self.assertFalse(any(t.startswith('bhk') for t in target.types))
        self.assertEqual(target.inspect()[0]['collision'], -1)
        self.assertNotIn(b'FO4_HAVOK_BYTES!!', self.out.read_bytes())
        flags = next(d for d in target.inspect() if d['type'] == 'BSXFlags')
        self.assertEqual(flags['value'], 0x10)

    def test_unknown_blocks_are_rejected(self):
        writer = fixture(self.src)
        writer.add('NiCamera', b'')
        writer.save(self.src)
        with self.assertRaisesRegex(ValueError, 'NiCamera'):
            convert(self.src, self.out)

    def test_invalid_root_reference_is_rejected(self):
        fixture(self.src)
        self.src.write_bytes(self.src.read_bytes()[:-4] + P('i', 999))
        with self.assertRaises(ValueError):
            convert(self.src, self.out)
        self.assertFalse(self.out.exists())

    def test_existing_destination_is_never_overwritten(self):
        fixture(self.src)
        self.out.write_bytes(b'keep my file')
        with self.assertRaises(ValueError):
            convert(self.src, self.out)
        self.assertEqual(self.out.read_bytes(), b'keep my file')

    def test_malformed_value_node_tail_is_rejected(self):
        writer = fixture(self.src)
        writer.blocks[0] = ('BSValueNode', writer.blocks[0][1] + P('I', 42))
        writer.save(self.src)
        with self.assertRaises(ValueError):
            convert(self.src, self.out)
        self.assertFalse(self.out.exists())

    def test_node_unknown_suffix_is_rejected(self):
        writer = fixture(self.src)
        writer.set(0, writer.blocks[0][1] + b'unknown fields')
        writer.save(self.src)
        with self.assertRaises(ValueError):
            convert(self.src, self.out)
        self.assertFalse(self.out.exists())

    def test_malformed_animation_controller_is_rejected(self):
        writer = fixture(self.src)
        controller = writer.add('NiTransformController', b'')
        writer.set(0, writer.av('Root', IDENTITY, ctrl=controller) + P('Ii', 1, 1))
        writer.save(self.src)
        with self.assertRaises(ValueError):
            convert(self.src, self.out)
        self.assertFalse(self.out.exists())

    def test_extra_with_invalid_string_reference_is_rejected(self):
        writer = fixture(self.src)
        extra = writer.add('NiStringExtraData', P('ii', writer.sid('marker'), 10000))
        writer.set(0, writer.av('Root', IDENTITY, extra=[extra]) + P('Ii', 1, 1))
        writer.save(self.src)
        with self.assertRaises(ValueError):
            convert(self.src, self.out)
        self.assertFalse(self.out.exists())

    def test_truncated_alpha_property_is_rejected(self):
        writer = fixture(self.src)
        alpha = writer.add('NiAlphaProperty', writer.net(''))
        data = bytearray(writer.blocks[1][1])
        struct.pack_into('<i', data, 96, alpha)
        writer.set(1, bytes(data))
        writer.save(self.src)
        with self.assertRaises(ValueError):
            convert(self.src, self.out)
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
