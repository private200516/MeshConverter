"""Central dispatch and no-overwrite publication regressions."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert_models import Writer, P, IDENTITY
from converter import convert_file
from inspect_nif import Nif


def helper(path, bs=155):
    writer = Writer(bs=bs)
    writer.add('NiNode', writer.av('Root', IDENTITY) + P('I', 0))
    writer.save(path)


class ConverterPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_root = self.root / 'input'
        self.output_root = self.root / 'output'
        self.source_root.mkdir()
        self.output_root.mkdir()
        self.src = self.source_root / 'source.nif'
        self.out = self.output_root / 'output.nif'
        helper(self.src)

    def tearDown(self):
        self.temp.cleanup()

    def assert_no_staging(self):
        self.assertEqual(list(self.root.rglob('.mesh-converter-*.tmp')), [])

    def test_success_is_validated_then_published_with_final_path(self):
        before = self.src.read_bytes()
        result = convert_file(self.src, self.out)
        self.assertEqual(Nif(self.out).bs, 130)
        self.assertEqual(result['output'], str(self.out.resolve()))
        self.assertEqual(result['validation']['shapes'], 0)
        self.assertFalse(result['game_verified'])
        self.assertEqual(before, self.src.read_bytes())
        self.assert_no_staging()

    def test_reverse_direction_is_dispatched_and_validated(self):
        helper(self.src, bs=130)
        result = convert_file(self.src, self.out, direction='4-to-76')
        self.assertEqual(Nif(self.out).bs, 155)
        self.assertEqual(result['target_bs'], 155)
        self.assert_no_staging()

    def test_dry_run_writes_no_output_or_staging_files(self):
        result = convert_file(self.src, self.out, dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertFalse(self.out.exists())
        self.assert_no_staging()

    def test_existing_target_is_kept_before_converter_runs(self):
        self.out.write_bytes(b'important')
        with patch('convert_models.convert') as convert:
            with self.assertRaises(FileExistsError):
                convert_file(self.src, self.out)
            convert.assert_not_called()
        self.assertEqual(self.out.read_bytes(), b'important')

    def test_source_cannot_be_output(self):
        before = self.src.read_bytes()
        with self.assertRaises(ValueError):
            convert_file(self.src, self.src)
        self.assertEqual(self.src.read_bytes(), before)

    def test_direction_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'BS155'):
            convert_file(self.src, self.out, direction='4-to-76')
        self.assertFalse(self.out.exists())

    def test_target_in_source_directory_is_rejected(self):
        before = self.src.read_bytes()
        target = self.source_root / 'unsafe-output.nif'
        with self.assertRaisesRegex(ValueError, 'must be separate'):
            convert_file(self.src, target)
        self.assertFalse(target.exists())
        self.assertEqual(self.src.read_bytes(), before)
        self.assert_no_staging()

    def test_partial_failed_output_is_removed(self):
        def fail(src, dst, **kwargs):
            Path(dst).write_bytes(b'partial')
            raise ValueError('conversion failed')
        with patch('convert_models.convert', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'conversion failed'):
                convert_file(self.src, self.out)
        self.assertFalse(self.out.exists())
        self.assert_no_staging()

    def test_invalid_result_cannot_be_published(self):
        def invalid(src, dst, **kwargs):
            Path(dst).write_bytes(b'invalid')
            return {}
        with patch('convert_models.convert', side_effect=invalid):
            with self.assertRaises(ValueError):
                convert_file(self.src, self.out)
        self.assertFalse(self.out.exists())
        self.assert_no_staging()

    def test_wrong_target_version_cannot_be_published(self):
        def wrong_version(src, dst, **kwargs):
            helper(dst, bs=155)
            return {}
        with patch('convert_models.convert', side_effect=wrong_version):
            with self.assertRaisesRegex(ValueError, '版本'):
                convert_file(self.src, self.out)
        self.assertFalse(self.out.exists())
        self.assert_no_staging()

    def test_destination_created_during_conversion_is_not_overwritten(self):
        def race(src, dst, **kwargs):
            helper(dst, bs=130)
            self.out.write_bytes(b'created concurrently')
            return {}
        with patch('convert_models.convert', side_effect=race):
            with self.assertRaises(FileExistsError):
                convert_file(self.src, self.out)
        self.assertEqual(self.out.read_bytes(), b'created concurrently')
        self.assert_no_staging()


if __name__ == '__main__':
    unittest.main()
