"""Windows regression tests for the self-contained C# launcher.

Uses synthetic Python entries in a temporary test installation. It never runs
conversion against user assets or changes host security settings. The matching
bundled runtime is required (or set LAUNCHER_TEST_RUNTIME explicitly).
"""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
if not (REPO / 'Launcher.cs').is_file() and not (REPO / 'TextureLauncher.cs').is_file():
    REPO = HERE.parents[3] / 'development' / os.environ.get('LAUNCHER_TEST_APP', 'MeshConverter')
IS_MESH = (REPO / 'Launcher.cs').is_file()
SOURCE = REPO / ('Launcher.cs' if IS_MESH else 'TextureLauncher.cs')
APP = 'MeshConverter' if IS_MESH else 'TextureConverter'
CSC = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
RUNTIME = Path(os.environ.get('LAUNCHER_TEST_RUNTIME', str(REPO.parents[1] / APP / 'runtime')))

FIXTURE = r'''
import json,os,pathlib,subprocess,sys,time
mode,out=sys.argv[1:3]
out=pathlib.Path(out)
if mode=='probe':
    out.write_text(json.dumps({'argv':sys.argv,'isolated':sys.flags.isolated,
        'ignore_environment':sys.flags.ignore_environment,'no_user_site':sys.flags.no_user_site,
        'path':sys.path,'cwd':os.getcwd(),'env':dict(os.environ)},ensure_ascii=False),encoding='utf-8')
elif mode=='echo':
    print('asset-progress',flush=True)
    print('asset-warning',file=sys.stderr,flush=True)
    out.write_text('done',encoding='utf8')
elif mode=='long':
    for stream in (sys.stdout,sys.stderr):
        for _ in range(2048): stream.write('x'*8192)
        stream.write('\n')
    out.write_text('complete',encoding='utf-8')
elif mode=='volume':
    for _ in range(14000): sys.stdout.write('x'*1023+'\n')
    out.write_text('complete',encoding='utf-8')
elif mode in ('spawn-exit','spawn-wait'):
    p=subprocess.Popen([sys.executable,'-I','-B','-X','utf8','-c','import time;time.sleep(120)'],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    out.write_text(json.dumps({'app':os.getpid(),'child':p.pid}),encoding='utf-8')
    if mode=='spawn-wait': time.sleep(120)
else: raise RuntimeError('unknown fixture mode')
'''

HARNESS = r'''
using System;
using System.IO;
static class Harness {
    static int Main(string[] args) {
        using (LauncherLog log = new LauncherLog(args[0], false)) {
            try {
                string[] appArgs = new string[args.Length-2];
                Array.Copy(args,2,appArgs,0,appArgs.Length);
                return LauncherProcess.Run(args[1],Path.Combine(args[1],"runtime","python.exe"),
                    Path.Combine(args[1],"app","fixture.py"),appArgs,0,log,null);
            } catch (Exception e) { log.Write(e.ToString(), true); return 1; }
        }
    }
}
'''

def wait_file(path, seconds=12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(.05)
    raise AssertionError(f'Test fixture did not produce {path.name}')

def running(pid):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k.OpenProcess.restype = ctypes.c_void_p
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    k.GetExitCodeProcess.restype = ctypes.c_int
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    try:
        code = ctypes.c_uint32()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
    finally:
        k.CloseHandle(h)

@unittest.skipUnless(os.name == 'nt' and CSC.is_file() and (RUNTIME/'python.exe').is_file(),
                     'Requires Windows .NET compiler and matching bundled Python runtime')
class LauncherSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='converter-launcher-security-')
        cls.base = Path(cls.temporary.name)
        cls.install = cls.base / 'install with spaces 中文'
        cls.install.mkdir()
        rt = cls.install / 'runtime'
        rt.mkdir()
        for file in RUNTIME.iterdir():
            if file.is_file() and file.suffix.lower() in ('.exe', '.dll'):
                shutil.copy2(file, rt / file.name)
        pth_files = list(RUNTIME.glob('python*._pth'))
        if len(pth_files) != 1:
            raise AssertionError('Expected one isolated bundled runtime path file')
        (rt / pth_files[0].name).write_text(
            '\n'.join([str(RUNTIME), str(RUNTIME/'Lib'), str(RUNTIME/'DLLs'),
                       str(cls.install/'app'), 'import site', '']), encoding='utf-8')
        app = cls.install / 'app'
        app.mkdir()
        for name in ('fixture.py', 'app.py', 'batch_nif.py', 'corpus_inventory.py',
                     'validate_samples.py', 'main.py', 'texture_cli.py'):
            (app/name).write_text(FIXTURE, encoding='utf-8')
        cls.harness = cls.install / 'Harness.exe'
        harness_cs = cls.base / 'Harness.cs'
        harness_cs.write_text(HARNESS, encoding='utf-8')
        compile_command = [str(CSC), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
                           '/reference:System.Windows.Forms.dll']
        p = subprocess.run(compile_command + ['/main:Harness', '/out:'+str(cls.harness),
                           str(SOURCE), str(harness_cs)], capture_output=True, timeout=30)
        if p.returncode:
            raise AssertionError(p.stdout.decode(errors='replace') + p.stderr.decode(errors='replace'))
        cls.launcher = cls.install / (APP+'.exe')
        p = subprocess.run(compile_command + ['/out:'+str(cls.launcher), str(SOURCE)],
                           capture_output=True, timeout=30)
        if p.returncode:
            raise AssertionError(p.stdout.decode(errors='replace') + p.stderr.decode(errors='replace'))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.test_dir = self.base / self.id().rsplit('.', 1)[-1]
        self.test_dir.mkdir()

    def run_fixture(self, mode, args=(), env=None, timeout=30):
        output = self.test_dir / 'result.json'
        p = subprocess.run([str(self.harness), str(self.test_dir), str(self.install),
                            mode, str(output), *args], capture_output=True,
                           timeout=timeout, env=env)
        self.assertEqual(p.returncode, 0, p.stdout.decode(errors='replace') + p.stderr.decode(errors='replace'))
        logs = list(self.test_dir.glob('launcher-*.log'))
        self.assertEqual(len(logs), 1)
        return output, logs[0]

    def assert_stopped(self, *pids):
        end = time.monotonic() + 5
        while time.monotonic() < end and any(running(pid) for pid in pids):
            time.sleep(.05)
        self.assertFalse(any(running(pid) for pid in pids), 'Owned test process outlived its launcher')

    def test_windows_argument_roundtrip(self):
        args = ['', 'plain', 'with space', '中文路径', 'quoted"part', 'C:\\tail\\',
                'slashes\\\\"quote', '; & $() are plain arguments']
        output, _ = self.run_fixture('probe', args)
        data = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(data['argv'][3:], args)
        self.assertEqual(Path(data['cwd']), self.install)
        self.assertEqual(Path(data['argv'][0]), self.install/'app'/'fixture.py')

    def test_python_and_plugin_environment_boundary(self):
        env = dict(os.environ)
        blocked = ['PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE', 'PYTHONINSPECT',
                   'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH',
                   'QML_IMPORT_PATH', 'QTWEBENGINEPROCESS_PATH', 'QTWEBENGINE_CHROMIUM_FLAGS']
        env.update({key: str(self.test_dir/'unrelated') for key in blocked})
        env['QT_OPENGL'] = 'software'
        env['QT_QPA_PLATFORM'] = 'windows'
        env['PATH'] = str(self.test_dir/'unrelated')
        output, _ = self.run_fixture('probe', env=env)
        data = json.loads(output.read_text(encoding='utf-8'))
        child_env = {k.upper(): v for k, v in data['env'].items()}
        for key in blocked:
            self.assertNotIn(key, child_env)
        self.assertEqual(data['isolated'], 1)
        self.assertEqual(data['ignore_environment'], 1)
        self.assertEqual(data['no_user_site'], 1)
        self.assertNotIn(str(self.test_dir/'unrelated'), data['path'])
        self.assertNotIn(str(self.test_dir/'unrelated'), child_env['PATH'])
        self.assertEqual(child_env['QT_OPENGL'], 'software')
        self.assertEqual(child_env['QT_QPA_PLATFORM'], 'windows')

    def test_unbroken_stdout_and_stderr_have_bounded_records(self):
        output, log = self.run_fixture('long')
        self.assertEqual(output.read_text(encoding='utf-8'), 'complete')
        records = log.read_text(encoding='utf-8').splitlines()
        self.assertLess(log.stat().st_size, 20000)
        self.assertTrue(any('[record truncated]' in row for row in records))
        self.assertLessEqual(max(map(len, records)), 4096 + len(' [record truncated]'))

    def test_total_log_budget_drains_child_to_completion(self):
        output, log = self.run_fixture('volume')
        self.assertEqual(output.read_text(encoding='utf-8'), 'complete')
        self.assertLessEqual(log.stat().st_size, 8 * 1024 * 1024)
        self.assertEqual(log.read_text(encoding='utf-8').count('[launcher log limit reached;'), 1)

    def test_normal_exit_reaps_owned_descendant(self):
        output, _ = self.run_fixture('spawn-exit')
        data = json.loads(output.read_text(encoding='utf-8'))
        self.assert_stopped(data['app'], data['child'])

    def test_terminating_launcher_reaps_application_and_descendant(self):
        output = self.test_dir / 'result.json'
        p = subprocess.Popen([str(self.harness), str(self.test_dir), str(self.install),
                              'spawn-wait', str(output)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        try:
            data = wait_file(output)
            self.assertTrue(running(data['app']))
            self.assertTrue(running(data['child']))
            p.kill()
            p.wait(timeout=5)
            self.assert_stopped(data['app'], data['child'])
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=5)

    def test_product_entry_routes_forward_arguments(self):
        routes = [('--cli', 'batch_nif.py'), ('--inventory', 'corpus_inventory.py'),
                  ('--validate', 'validate_samples.py')] if IS_MESH else [('--cli', 'texture_cli.py')]
        for route, expected in routes:
            output = self.test_dir / (expected+'.json')
            p = subprocess.run([str(self.launcher), route, 'probe', str(output), '中文 "\\'],
                               capture_output=True, timeout=30)
            self.assertEqual(p.returncode, 0)
            data = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(Path(data['argv'][0]).name, expected)
            self.assertEqual(data['argv'][3:], ['中文 "\\'])

    def test_no_report_keeps_cli_progress_without_a_launcher_transcript(self):
        local = Path(os.environ['LOCALAPPDATA']) / 'private0516' / APP
        if IS_MESH:
            local = local / 'logs'
        result = self.test_dir / 'result.txt'
        process = subprocess.Popen([str(self.launcher), '--cli', 'echo', str(result), '--no-report'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(result.read_text(encoding='utf8'), 'done')
        self.assertIn(b'asset-progress', stdout)
        self.assertIn(b'asset-warning', stderr)
        self.assertFalse(list(local.glob(f'launcher-*-{process.pid}-*.log')))

    def test_launcher_manifest_requests_current_user_privileges(self):
        candidates = [REPO/'app.manifest', REPO/'launcher.manifest', REPO/'launcher-source'/'app.manifest']
        existing = [p for p in candidates if p.is_file()]
        if not existing:
            # Distribution owns the manifest while source-only developer builds
            # compile without requesting elevation by default.
            existing = [REPO.parents[1]/APP/'launcher-source'/'app.manifest']
        text = existing[0].read_text(encoding='utf-8-sig')
        self.assertIn('level="asInvoker"', text)
        self.assertNotIn('requireAdministrator', text)

if __name__ == '__main__':
    unittest.main(verbosity=2)
