"""Generated attacks only: bounded parsing, publication, traversal and bridge."""
import copy
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corpus_inventory as inventory
import inspect_nif
from app import Api
from convert_models import Writer, P, IDENTITY
from converter import convert_file
from inspect_nif import Nif, Reader
from publication_guard import OutputBoundary
from shader_animation import _keys as scalar_keys
from skin_reference import skeleton_profiles
from test_corpus_inventory import nif_bytes


def helper(path, bs=155):
    writer = Writer(bs=bs)
    writer.add('NiNode', writer.av('Root', IDENTITY) + P('I', 0))
    writer.save(path)


class UntrustedNifTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.nif'

    def tearDown(self):
        self.temp.cleanup()

    def test_open_handle_size_is_enforced_even_if_path_stat_lies(self):
        self.source.write_bytes(b'x' * 65)
        with patch.object(inspect_nif, 'MAX_NIF_BYTES', 64), patch.object(Path, 'stat') as path_stat:
            path_stat.return_value.st_size = 1
            with self.assertRaisesRegex(ValueError, 'per-file conversion limit'):
                Nif(self.source)

    def test_growth_during_read_cannot_request_unbounded_bytes(self):
        self.source.write_bytes(b'x' * 16)
        original_open = Path.open
        requested = []
        source = self.source

        class GrowingStream:
            def __enter__(self):
                self.stream = original_open(source, 'rb')
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def read(self, count):
                requested.append(count)
                with open(source, 'ab') as writer:
                    writer.write(b'y' * 256)
                return self.stream.read(count)

        with patch.object(Path, 'open', return_value=GrowingStream()), patch.object(inspect_nif, 'MAX_NIF_BYTES', 64):
            with self.assertRaisesRegex(ValueError, 'changed while'):
                inspect_nif.read_nif_bytes(self.source)
        self.assertEqual(requested, [17])

    def test_bounded_reader_retains_one_snapshot_hash_and_legacy_strings(self):
        writer = Writer(bs=155)
        writer.add('NiNode', writer.av('中文\udcff', IDENTITY) + P('I', 0))
        writer.save(self.source)
        expected = hashlib.sha256(self.source.read_bytes()).hexdigest()
        parsed = Nif(self.source)
        self.assertEqual(parsed.source_sha256, expected)
        self.assertEqual(parsed.strings, ['中文\udcff'])
        self.assertEqual(parsed.validate()['shapes'], 0)

    def test_array_budget_rejects_backed_count_before_allocating_tuple(self):
        count = inspect_nif.MAX_TABLE_ITEMS + 1
        reader = Reader(b'\0' * (count * 4))
        with self.assertRaisesRegex(ValueError, 'item safety limit'):
            reader.array('I', count)
        self.assertEqual(reader.p, 0)

    def test_large_declared_tables_and_strings_are_rejected(self):
        # A small test budget exercises fully backed malicious containers.
        fixtures = [
            (nif_bytes(indices=(0, 0, 0), blocks=(b'', b'', b'')), 'block count'),
            (nif_bytes(types=('NiNode', 'Other', 'Third')), 'block type count'),
        ]
        for data, message in fixtures:
            self.source.write_bytes(data)
            with patch.object(inspect_nif, 'MAX_TABLE_ITEMS', 2), patch.object(inspect_nif, 'MAX_BLOCK_TYPES', 2):
                with self.assertRaisesRegex(ValueError, message):
                    Nif(self.source)
        reader = Reader(P('I', inspect_nif.MAX_STRING_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'string exceeds'):
            reader.s()

    def test_header_budget_stops_before_payload_parsing(self):
        helper(self.source)
        with patch.object(inspect_nif, 'MAX_HEADER_BYTES', 64):
            with self.assertRaisesRegex(ValueError, 'header exceeds'):
                Nif(self.source)

    def test_animation_count_budget_applies_before_key_iteration(self):
        reader = Reader(P('II', inspect_nif.MAX_TABLE_ITEMS + 1, 1))
        with self.assertRaisesRegex(ValueError, 'key count exceeds'):
            scalar_keys(reader, 1)


class PublicationAttackTests(unittest.TestCase):
    def test_hardlink_inserted_after_boundary_check_cannot_truncate_victim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input/source.nif'
            source.parent.mkdir()
            helper(source)
            victim = root / 'outside-victim.txt'
            victim.write_bytes(b'preserve the existing file exactly')
            before = victim.read_bytes()
            original_save = Writer.save

            def raced_save(writer, target, **kwargs):
                os.link(victim, target)
                return original_save(writer, target, **kwargs)

            for staged in (False, True):
                target = root / ('staged' if staged else 'published') / 'result.nif'
                with self.subTest(staged=staged), patch.object(Writer, 'save', raced_save):
                    with self.assertRaises(FileExistsError):
                        convert_file(source, target, _staged=staged)
                self.assertEqual(victim.read_bytes(), before)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), Nif(source).source_sha256)

    def test_replaced_ancestor_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'input', root / 'output'
            source.mkdir()
            output.mkdir()
            boundary = OutputBoundary(output, source)
            output.rename(root / 'old-output')
            output.mkdir()
            with self.assertRaisesRegex(ValueError, 'was replaced'):
                boundary.prepare_parent(output / 'result.nif')
            self.assertEqual(list(output.iterdir()), [])

    def test_reverse_conversion_uses_exclusive_writer_too(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input/source.nif'
            source.parent.mkdir()
            helper(source, bs=130)
            victim = root / 'victim'
            victim.write_bytes(b'keep')
            original_save = Writer.save

            def raced_save(writer, target, **kwargs):
                os.link(victim, target)
                return original_save(writer, target, **kwargs)

            with patch.object(Writer, 'save', raced_save), self.assertRaises(FileExistsError):
                convert_file(source, root / 'output/out.nif', direction='4-to-76')
            self.assertEqual(victim.read_bytes(), b'keep')


class ScanResourceTests(unittest.TestCase):
    def test_file_directory_entry_and_byte_limits_fail_explainably(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('a.nif', 'b.nif', 'c.txt'):
                (root / name).write_bytes(b'x')
            (root / 'subdir').mkdir()
            budgets = [('MAX_SCAN_FILES', 1, 'NIF file'), ('MAX_SCAN_DIRECTORIES', 1, 'directory'),
                       ('MAX_SCAN_ENTRIES', 1, 'entry'), ('MAX_SCAN_BYTES', 1, '1 TiB')]
            for constant, maximum, message in budgets:
                with self.subTest(limit=constant), patch.object(inventory, constant, maximum):
                    with self.assertRaisesRegex(inventory.ScanLimitError, message):
                        list(inventory.nif_files(root))

    def test_cancellation_stops_scanning_before_any_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            stop = threading.Event()
            stop.set()
            with patch.object(inventory.os, 'scandir') as scan:
                self.assertEqual(list(inventory.nif_files(directory, stop=stop)), [])
                scan.assert_not_called()

    def test_reparse_entries_are_not_traversed_even_if_reported_as_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            info = types.SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
            entry = Mock()
            entry.stat.return_value = info
            scan = Mock()
            scan.__enter__ = Mock(return_value=iter([entry]))
            scan.__exit__ = Mock(return_value=False)
            with patch.object(inventory.os, 'scandir', return_value=scan) as scandir:
                self.assertEqual(list(inventory.nif_files(directory)), [])
                self.assertEqual(scandir.call_count, 1)

    def test_skeleton_reference_has_its_own_candidate_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper(root / 'skeleton-a.nif', bs=130)
            helper(root / 'skeleton-b.nif', bs=130)
            with patch('skin_reference.MAX_REFERENCE_FILES', 1):
                with self.assertRaisesRegex(ValueError, 'Skeleton reference tree exceeds'):
                    skeleton_profiles(root)


class BridgeSchemaTests(unittest.TestCase):
    def test_invalid_json_pagination_and_options_return_errors_without_mutation(self):
        api = Api()
        before = copy.deepcopy(api.state)
        for value in (None, True, '1', [], {}, 1.5, float('inf'), 2**54):
            with self.subTest(value=repr(value)):
                self.assertIn('error', api.snapshot(after_log=value))
        for direction in ([], {}, None, True, 'untrusted'):
            self.assertIn('error', api.configure_options(direction))
        for reference in ([], {}, True, 1, 'bad\0path', 'x' * 32768):
            self.assertIn('error', api.configure_options('76-to-4', reference))
        self.assertEqual(api.state, before)

    def test_non_boolean_collision_cannot_start_worker(self):
        api = Api()
        with patch('app.threading.Thread') as worker:
            for value in ('false', 0, 1, [], {}, None):
                self.assertIn('error', api.start('scan', value))
            worker.assert_not_called()
        self.assertFalse(api.busy)

    def test_dialog_returning_during_batch_cannot_replace_active_directories(self):
        api = Api()
        before = copy.deepcopy(api.state)
        api._window = Mock()

        def dialog(*args, **kwargs):
            api.busy = True
            return ['C:/attacker/changed-output']

        api._window.create_file_dialog.side_effect = dialog
        fake_webview = types.SimpleNamespace(FileDialog=types.SimpleNamespace(OPEN=1, FOLDER=2))
        with patch.dict(sys.modules, {'webview': fake_webview}):
            self.assertIn('error', api.choose('output'))
        self.assertEqual(api.state, before)

    def test_conversion_api_does_not_coerce_string_switches(self):
        for argument in ('collision', 'dry_run', '_staged'):
            with self.subTest(argument=argument), self.assertRaisesRegex(ValueError, 'booleans'):
                convert_file('unused', 'unused', **{argument: 'false'})


if __name__ == '__main__':
    unittest.main()
