"""Read known FO4 LOD layouts; never imply unverified FO76 LOD semantics."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert_models import Writer, P, IDENTITY, LIGHT
from inspect_nif import Nif
from convert_preserved import shape
from converter import convert_file


def fixture(path, tail=None, precombined=False):
    writer = Writer(bs=130)
    writer.add('NiNode')
    writer.add('BSMeshLODTriShape')
    shader = bytearray(LIGHT)
    struct.pack_into('<i', shader, 4, writer.sid('Materials/lod.bgsm'))
    struct.pack_into('<i', shader, 40, 3)
    writer.add('BSLightingShaderProperty', bytes(shader))
    writer.add('BSShaderTextureSet', P('I', 9) + P('I', 0) * 9)
    vertices = b''.join(P('4e', *v, 0) for v in ((0, 0, 0), (5, 0, 0), (0, 5, 0)))
    data = vertices + P('9H', 0, 1, 2, 0, 2, 1, 1, 0, 2)
    if tail is None:
        tail = P('3I', 1, 1, 1)
    writer.set(1, writer.av('LOD', IDENTITY)
               + P('4fiiiQIHI', 0, 0, 0, 6, -1, 2, -1, 2 | (1 << 44), 3, 3, len(data))
               + data + tail)
    writer.set(0, writer.av('Root', IDENTITY) + P('Ii', 1, 1))
    if precombined:
        writer.add('BSPackedCombinedSharedGeomDataExtra', b'')
    writer.save(path)


class LodParsingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.dest = self.root / 'input.nif', self.root / 'output.nif'

    def tearDown(self):
        self.temp.cleanup()

    def test_three_lod_counts_parse_in_both_common_readers(self):
        fixture(self.source)
        nif = Nif(self.source)
        desc = next(d for d in nif.inspect() if d['type'] == 'BSMeshLODTriShape')
        self.assertEqual(desc['lod_sizes'], (1, 1, 1))
        self.assertEqual(nif.blocks[1][desc['tailoffset']:], P('3I', 1, 1, 1))
        self.assertEqual(shape(nif, 1)['lod_sizes'], (1, 1, 1))
        self.assertEqual(nif.validate()['triangles'], 3)

    def test_single_lod_levels_can_be_empty(self):
        fixture(self.source, tail=P('3I', 0, 3, 0))
        nif = Nif(self.source)
        self.assertEqual(shape(nif, 1)['lod_sizes'], (0, 3, 0))
        self.assertEqual(nif.validate()['shapes'], 1)

    def test_short_lod_tail_is_rejected(self):
        fixture(self.source, tail=P('2I', 1, 2))
        nif = Nif(self.source)
        with self.assertRaises(ValueError):
            nif.inspect()
        with self.assertRaises(ValueError):
            shape(nif, 1)

    def test_extra_lod_tail_bytes_are_rejected(self):
        fixture(self.source, tail=P('4I', 1, 1, 1, 0))
        nif = Nif(self.source)
        with self.assertRaises(ValueError):
            nif.inspect()
        with self.assertRaises(ValueError):
            shape(nif, 1)

    def test_lod_counts_must_cover_exact_triangle_count(self):
        for sizes in ((1, 1, 0), (2, 1, 1), (0xffffffff, 0, 4)):
            with self.subTest(sizes=sizes):
                fixture(self.source, tail=P('3I', *sizes))
                nif = Nif(self.source)
                with self.assertRaisesRegex(ValueError, 'LOD'):
                    nif.inspect()
                with self.assertRaisesRegex(ValueError, 'LOD'):
                    shape(nif, 1)

    def test_reverse_conversion_remains_blocked_without_fo76_reference(self):
        fixture(self.source)
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'BSMeshLODTriShape'):
            convert_file(self.source, self.dest, direction='4-to-76', collision=False)
        self.assertFalse(self.dest.exists())
        self.assertEqual(before, self.source.read_bytes())
        self.assertEqual(list(self.root.glob('.mesh-converter-*.tmp')), [])

    def test_precombined_lod_is_not_silently_flattened(self):
        fixture(self.source, precombined=True)
        with self.assertRaises(ValueError):
            convert_file(self.source, self.dest, direction='4-to-76', collision=False)
        self.assertFalse(self.dest.exists())


if __name__ == '__main__':
    unittest.main()
