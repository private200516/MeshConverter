import sys, time, tempfile, threading, json, hashlib
from pathlib import Path
from unittest.mock import patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Api, IsolatedWorker
from converter import convert_file
from convert_models import Writer, P, IDENTITY

class SchedulingTests(unittest.TestCase):
    def test_small_and_large_files_remain_serial(self):
        api=Api()
        with patch('app.os.cpu_count',return_value=8):
            self.assertEqual(api._parallelism([{'size':1024*1024}]*7),1)
            self.assertEqual(api._parallelism([{'size':1024*1024}]*8),2)
            self.assertEqual(api._parallelism([{'size':33*1024*1024}]*8),1)
            self.assertEqual(api._parallelism([{'size':128}]*100),1)
        with patch('app.os.cpu_count',return_value=2):
            self.assertEqual(api._parallelism([{'size':1024*1024}]*8),1)

    def test_out_of_order_completions_keep_row_bindings_and_report_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'in';source.mkdir();dest=root/'out'
            api=Api();api.configure(source,dest)
            rows=[dict(path=str(source/f'{i}.nif'),name=f'{i}.nif',size=1024*1024,status='可转换',supported=True,detail='') for i in range(12)]
            api._update(rows=rows);api._parallelism=lambda rows:2
            lock=threading.Lock();active=0;peak=0;order=[]
            def fake(src,target,collision,dry):
                nonlocal active,peak
                with lock:active+=1;peak=max(active,peak)
                index=int(Path(src).stem);time.sleep(.02 if index%2==0 else .002)
                Path(target).write_bytes(str(index).encode())
                with lock:active-=1;order.append(index)
                return {'ok':True,'data':{'conversion_kind':'test','input':str(src)}}
            api._call=fake;api._run('convert',False)
            self.assertEqual(peak,2);self.assertNotEqual(order,list(range(12)))
            report=json.loads(Path(api.state['report']).read_text(encoding='utf8'))
            self.assertEqual([r['name'] for r in report['files']],[f'{i}.nif' for i in range(12)])
            for i,row in enumerate(api.state['rows']):
                self.assertEqual(row['result']['input'],str(source/f'{i}.nif'))
                self.assertEqual((dest/f'{i}.nif').read_text(),str(i))
            self.assertEqual(api.state['completed'],12)
            self.assertFalse(list(root.rglob('.nifshift-*')))

    def test_cancel_stops_new_dispatch_and_removes_partial_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'in';source.mkdir();dest=root/'out'
            sources=[]
            for i in range(12):
                src=source/f'{i}.nif';self.assertFalse(src.exists())
                writer=Writer(bs=155);writer.add('NiNode',writer.av('Root',IDENTITY)+P('I',0));writer.save(src)
                sources.append(src)
            source_hashes={str(src):hashlib.sha256(src.read_bytes()).hexdigest() for src in sources}
            api=Api();self.assertTrue(api.configure(source,dest).get('ok'))
            rows=[dict(path=str(src),name=src.name,size=src.stat().st_size,status='可转换',supported=True,detail='') for src in sources]
            api._update(rows=rows);api._parallelism=lambda rows:2;calls=[];api.busy=True
            def fake(src,target,collision,dry):
                calls.append(str(src));Path(target).write_bytes(b'partial');api.cancel()
                return {'ok':True,'data':{'conversion_kind':'test'}}
            api._call=fake;api._run('convert',False)
            self.assertGreater(len(calls),0);self.assertLessEqual(len(calls),2);self.assertEqual(api.state['phase'],'idle')
            self.assertTrue(api._stop.is_set());self.assertFalse(api.busy)
            self.assertTrue(any(row['status']=='已取消' for row in api.state['rows']))
            self.assertFalse(any(row['status'] in ('完成','失败') for row in api.state['rows']))
            self.assertGreaterEqual(api.state['completed'],1);self.assertLessEqual(api.state['completed'],2)
            self.assertTrue(api.state['report'])
            report_path=Path(api.state['report']);self.assertTrue(report_path.is_file());self.assertEqual(report_path.parent,dest)
            report=json.loads(report_path.read_text(encoding='utf8'))
            self.assertTrue(report['cancelled']);self.assertEqual(api.state['completed'],len(report['files']))
            self.assertTrue(all(record['name'] in {src.name for src in sources} and record['path']==str(source/record['name']) for record in report['files']))
            self.assertFalse(list(dest.glob('*.nif')));self.assertFalse(list(root.rglob('.nifshift-*')))
            self.assertFalse(api._workers)
            self.assertEqual({str(src):hashlib.sha256(src.read_bytes()).hexdigest() for src in sources},source_hashes)

    def test_existing_output_stays_unchanged_during_parallel_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'in';source.mkdir();dest=root/'out';dest.mkdir()
            api=Api();api.configure(source,dest)
            row=dict(path=str(source/'a.nif'),name='a.nif',size=1,status='可转换',supported=True,detail='')
            (dest/'a.nif').write_bytes(b'original')
            with patch.object(api,'_call') as call:api._process_row(row,'convert',False,dest)
            call.assert_not_called();self.assertEqual((dest/'a.nif').read_bytes(),b'original')
            self.assertEqual(row['status'],'跳过')

    def test_parse_and_hash_use_one_source_read_per_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'in.nif';out=root/'out.nif'
            writer=Writer(bs=155);writer.add('NiNode',writer.av('Root',IDENTITY)+P('I',0));writer.save(source)
            reads=[];original=Path.read_bytes
            def tracked(path):
                reads.append(path.resolve());return original(path)
            with patch.object(Path,'read_bytes',tracked):result=convert_file(source,out)
            self.assertEqual(reads.count(source.resolve()),1)
            self.assertEqual(result['source_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertIn(out.parent,reads[-1].parents)

    def test_display_rate_freezes_after_completion(self):
        api=Api();api._batch_elapsed=5;api._update(completed=20)
        self.assertEqual(api.snapshot()['files_per_second'],4)
        self.assertEqual(api.snapshot()['elapsed_seconds'],5)

class WorkerIsolationTests(unittest.TestCase):
    def test_invalid_file_does_not_poison_next_job_in_same_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bad=root/'bad.nif';bad.write_bytes(b'bad header')
            good=root/'good.nif';writer=Writer(bs=155);writer.add('NiNode',writer.av('Root',IDENTITY)+P('I',0));writer.save(good)
            instance=IsolatedWorker();stop=threading.Event()
            try:
                request=dict(src=str(bad),dest=str(root/'out.nif'),dry_run=True,collision=False)
                bad_result=instance.call(request,stop);pid=instance.process.pid
                self.assertFalse(bad_result['ok'])
                request['src']=str(good)
                result=instance.call(request,stop)
                self.assertTrue(result['ok']);self.assertEqual(instance.process.pid,pid)
                self.assertFalse((root/'out.nif').exists())
            finally:instance.close()
            self.assertIsNone(instance.process);self.assertIsNone(instance.connection)

    def test_timeout_and_cancel_close_process_and_connection(self):
        from unittest.mock import Mock
        for cancelled in (False,True):
            worker=IsolatedWorker();process=Mock();conn=Mock();conn.poll.return_value=False
            process.is_alive.return_value=True;worker.process=process;worker.connection=conn
            stop=threading.Event()
            if cancelled:stop.set()
            result=worker.call({},stop,timeout=0)
            self.assertFalse(result['ok']);self.assertEqual(bool(result.get('cancelled')),cancelled)
            process.terminate.assert_called_once();conn.close.assert_called_once()
            self.assertIsNone(worker.process);self.assertIsNone(worker.connection)

    def test_windows_runtime_prune_preserves_metadata_and_licenses(self):
        from build_portable import prune_windows_runtime
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            files=['vendor/webview/platforms/cocoa.py','vendor/webview/platforms/edgechromium.py',
                   'vendor/webview/lib/runtimes/win-arm64/native/WebView2Loader.dll',
                   'vendor/webview/lib/runtimes/win-x64/native/WebView2Loader.dll',
                   'vendor/pywebview-6.2.1.dist-info/METADATA','vendor/pywebview-6.2.1.dist-info/LICENSE']
            for name in files:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
            report=prune_windows_runtime(root)
            self.assertEqual(len(report['removed']),1)
            for name in files[1:]:
                self.assertTrue((root/name).is_file())
            self.assertTrue(report['dependency_metadata_and_licenses_preserved'])
            self.assertEqual(prune_windows_runtime(root)['removed'],[])

if __name__=='__main__':unittest.main()
