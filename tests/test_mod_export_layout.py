import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import batch_nif
from app import Api
from converter import convert_file
from inspect_nif import Nif
from publication_guard import plan_mesh_paths
from selftest import wait
from test_converter import helper


class ModExportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / 'game' / 'MeShEs' / 'Props' / '道具' / '模型.nif'
        self.source.parent.mkdir(parents=True)
        helper(self.source)
        self.output = self.root / 'my mod'
        self.relative = Path('meshes/Props/道具/模型.nif')

    def cli(self, source, output, *options):
        lines = io.StringIO()
        args = ['mesh', str(source), str(output), *options]
        with patch.object(sys, 'argv', args), redirect_stdout(lines):
            code = batch_nif.main()
        return code, [json.loads(line) for line in lines.getvalue().splitlines()]

    def test_single_nested_and_library_selections_share_one_target(self):
        for index, path in enumerate((self.source, self.source.parent, self.root/'game'/'MeShEs', self.root/'game')):
            with self.subTest(path=path):
                out = self.root / str(index)
                code, lines = self.cli(path, out, '--no-report')
                self.assertEqual(code, 0)
                self.assertEqual(lines[-1], dict(report=None, counts=dict(passed=1, rejected=0, skipped=0)))
                self.assertEqual(Nif(out/self.relative).bs, 130)
                self.assertEqual(list(out.glob('*')), [out/'meshes'])

    def test_selected_category_and_optional_reports(self):
        chosen = self.output/'MeShEs'
        code, lines = self.cli(self.source, chosen)
        self.assertEqual(code, 0)
        self.assertEqual(Nif(chosen/Path(*self.relative.parts[1:])).bs, 130)
        report = Path(lines[-1]['report'])
        self.assertEqual(report.parent, chosen/'reports')
        self.assertEqual(json.loads(report.read_bytes())['counts']['passed'], 1)
        self.assertFalse((chosen/'meshes').exists())
        self.assertFalse((chosen.parent/'reports').exists())
        code, lines = self.cli(self.source, chosen, '--no-report')
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1]['counts']['skipped'], 1)
        self.assertEqual(list(report.parent.iterdir()), [report])

    def test_preflight_and_failure_without_reports_make_no_output(self):
        code, lines = self.cli(self.source, self.output, '--preflight', '--no-report')
        self.assertEqual(code, 0)
        self.assertIsNone(lines[-1]['report'])
        self.assertFalse(self.output.exists())
        self.source.write_bytes(b'invalid')
        code, lines = self.cli(self.source, self.output, '--no-report')
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['counts']['rejected'], 1)
        self.assertFalse(self.output.exists())

    def test_multiple_input_trees_cannot_publish_ambiguous_targets(self):
        second = self.root/'second'/'Meshes'/'props'/'道具'/self.source.name
        second.parent.mkdir(parents=True)
        helper(second)
        code, lines = self.cli(self.root, self.root.parent/(self.root.name+'-unused'), '--no-report')
        self.assertEqual((code, lines[-1]['counts']['rejected']), (1, 2))
        self.assertIn('same game path', lines[0]['error'])
        self.assertFalse((self.root.parent/(self.root.name+'-unused')).exists())

    def test_loose_paths_and_repeated_meshes_names(self):
        loose = self.root/'loose'
        loose_file = loose/'sub'/'test.nif'
        self.assertEqual(plan_mesh_paths([loose_file], loose, self.output)[loose_file],
                         (Path('meshes/sub/test.nif'), False))
        repeat = self.root/'game'/'MeShEs'/'Props'/'meshes'/'child.nif'
        for selection in (self.root/'game', repeat.parent):
            self.assertEqual(plan_mesh_paths([repeat], selection, self.output)[repeat][0],
                             Path('meshes/Props/meshes/child.nif'))

    def test_deep_input_protects_other_source_asset_folders(self):
        api = Api()
        for dest in ('MeShEs/sibling', 'materials/new', 'textures/new'):
            self.assertIn('error', api.configure(self.source, self.root/'game'/dest))
        self.assertIn('error', api.start('scan', True, 'false'))

    def test_existing_shared_root_output_stays_skipped_across_gui_phases(self):
        target=self.output/self.relative
        target.parent.mkdir(parents=True)
        target.write_bytes(b'keep my edited model')
        api=Api()
        self.assertTrue(api.configure(self.source,self.output)['ok'])
        with patch.object(api,'_call') as worker:
            for stage in ('scan','convert'):
                self.assertTrue(api.start(stage,False,False)['ok'])
                self.assertEqual(wait(api)['status_counts'],{'跳过':1})
            worker.assert_not_called()
        self.assertEqual(target.read_bytes(), b'keep my edited model')

    def test_gui_session_no_report_keeps_results_and_output_target(self):
        api = Api()
        self.assertIn('ok', api.configure(self.source, self.output))
        def process(path, target, collision, dry):
            data = convert_file(path, target, collision=collision, dry_run=dry,
                                source_root=self.source.parent, output_root=self.output, _staged=True)
            return dict(ok=True, data=data)
        with patch.object(api, '_call', side_effect=process):
            for stage in ('scan', 'convert'):
                self.assertTrue(api.start(stage, False, False)['ok'])
                wait(api)
        snap = api.snapshot()
        self.assertEqual(snap['phase'], 'done')
        self.assertEqual(snap['status_counts'], {'完成': 1})
        self.assertEqual(Nif(self.output/self.relative).bs, 130)
        self.assertEqual(Path(snap['rows'][0]['output_relative']), self.relative)
        self.assertFalse((self.output/'reports').exists())
        self.assertFalse(snap['report'])
        self.assertTrue(snap['logs'])
