"""NIF SHIFT desktop host. GPL-3.0. Local-only model conversion."""
import copy,json,multiprocessing as mp,os,sys,threading,time,uuid
from collections import deque, Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from converter import convert_file, DIRECTIONS, BUILD
from publication_guard import OutputBoundary, absolute_path

def worker(conn,src,dest,collision,dry,direction='76-to-4',reference_root=None):
    try:
        result=convert_file(src,dest,direction=direction,collision=collision,
                            dry_run=dry,reference_root=reference_root)
        conn.send({'ok':True,'data':result})
    except BaseException as e: conn.send({'ok':False,'error':str(e) or type(e).__name__})
    finally: conn.close()

def worker_loop(conn):
    """Reuse imports and target skeleton profiles across files in one batch."""
    try:
        while True:
            request=conn.recv()
            if request is None:break
            try:conn.send({'ok':True,'data':convert_file(**request)})
            except Exception as e:conn.send({'ok':False,'error':str(e) or type(e).__name__})
    except (EOFError,BrokenPipeError):pass
    finally:conn.close()

class IsolatedWorker:
    """One persistent, killable process per dispatch thread; no shared model state."""
    def __init__(self):
        self.process=None;self.connection=None
    def call(self,request,stop,timeout=180):
        if self.process is None or not self.process.is_alive():
            self.close()
            parent,child=mp.Pipe()
            self.process=mp.Process(target=worker_loop,args=(child,),daemon=True)
            self.process.start();child.close();self.connection=parent
        proc,recv=self.process,self.connection
        started=time.monotonic()
        try:
            recv.send(request)
            while not recv.poll(.05):
                if stop.is_set():
                    self.close();return {'ok':False,'cancelled':True,'error':'已取消'}
                if time.monotonic()-started>timeout:
                    self.close();return {'ok':False,'error':'单文件处理超过 180 秒，已停止该文件'}
                if not proc.is_alive():
                    self.close();return {'ok':False,'error':'转换进程意外退出'}
            return recv.recv()
        except (EOFError,BrokenPipeError,OSError):
            self.close();return {'ok':False,'error':'转换进程意外退出'}
    def close(self):
        proc,conn=self.process,self.connection
        self.process=None;self.connection=None
        if conn is not None:
            try:conn.send(None)
            except (EOFError,BrokenPipeError,OSError):pass
            conn.close()
        if proc is not None:
            proc.join(.2)
            if proc.is_alive():proc.terminate()
            proc.join()

class Api:
    def __init__(self):
        self._window=None;self._guard=threading.RLock();self._stop=threading.Event();self.busy=False;self.exit_allowed=False
        self._logs=deque(maxlen=2000);self._log_id=0
        self._process=None;self._connection=None;self._workers={};self._batch_started=None;self._batch_elapsed=0.0
        self._rows_identity=None;self._rows_count=0;self._status_counts=Counter();self._rows_revision=0
        self.state={'phase':'idle','input':'','output':'','reference':'','direction':'76-to-4','rows':[],'completed':0,'message':'选择源模型目录与独立输出目录','report':'','build':BUILD}
    def _index_rows(self):
        """Rebuild only when replacing the queue; per-file changes use _change_row."""
        rows=self.state['rows']
        if rows is not self._rows_identity or len(rows)!=self._rows_count:
            self._rows_identity=rows;self._rows_count=len(rows)
            self._status_counts=Counter(row['status'] for row in rows)
            self._rows_revision+=1
    def _change_row(self,row,**changes):
        with self._guard:
            self._index_rows()
            before=row['status'];after=changes.get('status',before)
            if before!=after:
                self._status_counts[before]-=1
                if not self._status_counts[before]:del self._status_counts[before]
                self._status_counts[after]+=1
            row.update(changes);self._rows_revision+=1
    def snapshot(self,after_log=0,row_offset=-1,row_limit=250,after_rows_revision=-1,after_row_offset=-1,after_row_limit=250):
        with self._guard:
            self._index_rows()
            rows=self.state['rows'];limit=max(1,min(500,int(row_limit)))
            offset=int(row_offset)
            if offset<0:offset=max(0,min(len(rows)-limit,self.state['completed']-10))
            offset=max(0,min(offset,max(0,len(rows)-1)))
            result={k:copy.deepcopy(v) for k,v in self.state.items() if k!='rows'}
            unchanged=int(after_rows_revision)==self._rows_revision and int(after_row_offset)==offset and int(after_row_limit)==limit
            result.update(row_total=len(rows),row_offset=offset,row_limit=limit,status_counts=dict(self._status_counts),
                          rows_revision=self._rows_revision,rows_unchanged=unchanged)
            # Older callers receive a complete bounded page. Updated clients can reuse it.
            if not unchanged:
                result['rows']=[{k:copy.deepcopy(v) for k,v in row.items() if k!='result'} for row in rows[offset:offset+limit]]
            result['logs']=[dict(entry) for entry in self._logs if entry['id']>int(after_log)]
            result['log_total']=self._log_id
            elapsed=max(0.0,time.monotonic()-self._batch_started) if self.busy and self._batch_started is not None else self._batch_elapsed
            result['elapsed_seconds']=round(elapsed,2)
            result['files_per_second']=round(self.state['completed']/elapsed,2) if elapsed>.05 else 0.0
            return result
    def _log(self,message,level='info'):
        with self._guard:
            self._log_id+=1
            self._logs.append(dict(id=self._log_id,time=time.strftime('%H:%M:%S'),level=level,message=str(message)))
    def _update(self,**kw):
        with self._guard:
            self.state.update(kw)
            if 'rows' in kw:self._index_rows()
    def configure(self,source,dest):
        with self._guard:
            if self.busy:return {'error':'任务进行中，请先取消'}
            try:
                a=absolute_path(source);b=absolute_path(dest)
                if not a.is_dir():return {'error':'源目录不存在'}
                OutputBoundary(b,a)
            except (OSError,ValueError) as error:return {'error':str(error)}
            self.state.update(input=str(a),output=str(b),rows=[],phase='idle',report='',completed=0)
            return {'ok':True}
    def configure_options(self,direction,reference=None):
        with self._guard:
            if self.busy:return {'error':'任务进行中，请先取消'}
            if direction not in DIRECTIONS:return {'error':'无效转换方向'}
            if reference is not None and reference and not Path(reference).exists():return {'error':'参照路径不存在'}
            if reference is not None:self.state['reference']=str(reference)
            self.state.update(direction=direction,rows=[],phase='idle',report='',completed=0)
            return {'ok':True}
    def choose(self,kind):
        import webview
        if kind not in ('input','output','reference','skeleton'):return {'error':'无效目录类型'}
        if self.busy:return {'error':'任务进行中，请先取消'}
        result=self._window.create_file_dialog(webview.FileDialog.OPEN,file_types=('NIF files (*.nif)',),allow_multiple=False) if kind=='skeleton' else self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if result:
            with self._guard:self.state['reference' if kind=='skeleton' else kind]=result[0];self.state['rows']=[];self.state['phase']='idle';self.state['report']=''
        return self.snapshot()
    def start(self,kind,collision=True):
        with self._guard:
            if self.busy:return {'error':'任务已经在运行'}
            if kind not in ('scan','convert'):return {'error':'未知任务'}
            a=self.state['input'];b=self.state['output']
            if not a or not b:return {'error':'请先选择源目录和输出目录'}
            try:
                pa=absolute_path(a);pb=absolute_path(b)
                if not pa.is_dir():return {'error':'请选择互相独立的有效目录'}
                OutputBoundary(pb,pa)
            except (OSError,ValueError) as error:return {'error':str(error)}
            self.state.update(input=str(pa),output=str(pb))
            if kind=='convert' and self.state['phase']!='ready':return {'error':'请先扫描模型'}
            if kind=='convert' and bool(collision)!=self.state.get('scanned_collision',bool(collision)):
                return {'error':'碰撞选项已改变，请重新扫描'}
            if kind=='scan':self.state['scanned_collision']=bool(collision)
            self.busy=True;self._stop.clear();self._batch_started=time.monotonic();self._batch_elapsed=0.0;self.state.update(phase='scanning' if kind=='scan' else 'running',completed=0,report='')
            self._log('开始预扫描' if kind=='scan' else '开始批量转换')
            self._log('源目录：'+a);self._log('输出目录：'+b)
            threading.Thread(target=self._run,args=(kind,bool(collision)),daemon=True).start()
            return {'ok':True}
    def cancel(self):
        if not self._stop.is_set():self._log('收到取消请求，正在结束当前文件','warn')
        self._stop.set();self._update(message='正在取消当前任务…');return {'ok':True}
    def _call(self,src,dest,collision,dry):
        # Each executor thread owns an independent child process and skeleton cache.
        ident=threading.get_ident()
        with self._guard:
            instance=self._workers.setdefault(ident,IsolatedWorker())
        request=dict(src=str(src),dest=str(dest),direction=self.state['direction'],
                     collision=collision,dry_run=dry,reference_root=self.state['reference'] or None,
                     _staged=True,output_root=self.state['output'],source_root=self.state['input'])
        return instance.call(request,self._stop)
    def _shutdown_worker(self):
        for instance in self._workers.values():instance.close()
        self._workers.clear();self._process=None;self._connection=None
    def _parallelism(self,rows):
        # Small batches avoid spawn overhead. Large NIFs retain the serial memory ceiling.
        if len(rows)<8 or (os.cpu_count() or 1)<4:return 1
        sizes=[max(0,row.get('size',0)) for row in rows]
        return 2 if max(sizes,default=0)<=32*1024*1024 and sum(sizes)>=4*1024*1024 else 1
    def _process_row(self,row,kind,collision,dest):
        temp=None;boundary=None
        if self._stop.is_set():return None
        src=Path(row['path']);target=dest/row['name']
        self._change_row(row,status='扫描中' if kind=='scan' else '转换中')
        self._update(message=row['name'])
        self._log(('检查模型：' if kind=='scan' else '处理模型：')+row['name'])
        if kind=='convert' and not row.get('supported'):
            self._change_row(row,status='不支持')
            self._log(row['name']+' · 不支持，已跳过','warn')
            return dict(row)
        try:
            boundary=OutputBoundary(dest,self.state['input'])
            boundary.validate_source(src)
            boundary.validate(target,must_be_absent=True)
            if kind=='convert':boundary.prepare_parent(target)
            temp=target.with_name('.nifshift-'+uuid.uuid4().hex+'.tmp')
            boundary.validate(temp,must_be_absent=True)
            result=self._call(src,temp,collision,kind=='scan')
            if result.get('ok') and kind=='convert':
                if self._stop.is_set():result={'ok':False,'cancelled':True,'error':'已取消'}
                else:
                    boundary.publish(temp,target);result['data']['output']=str(target)
        except FileExistsError as e:result={'ok':False,'skip':True,'error':str(e) or '输出已存在，保留原件'}
        except Exception as e:result={'ok':False,'error':str(e) or type(e).__name__}
        finally:
            if boundary is not None:boundary.cleanup(temp)
        changes={'status':('可转换' if kind=='scan' else '完成') if result['ok'] else ('跳过' if result.get('skip') else '已取消' if result.get('cancelled') else '不支持' if kind=='scan' else '失败'),
                 'detail':(result['data']['conversion_kind']+' · '+('结构检查通过' if kind=='scan' else '已写入并回读校验')) if result['ok'] else result['error']}
        if kind=='scan':changes['supported']=result['ok']
        if result.get('data'):changes['result']=result['data']
        self._change_row(row,**changes)
        self._log(row['name']+' · '+row['status']+' · '+row['detail'],'success' if result['ok'] else 'warn' if result.get('skip') or result.get('cancelled') else 'error')
        if result.get('ok'):
            data=result['data'];notes=data.get('warnings',[])+data.get('notes',[])
            for note in dict.fromkeys(str(note) if isinstance(note,str) else json.dumps(note,ensure_ascii=False) for note in notes):
                self._log(row['name']+' · '+note,'warn')
        return dict(row)
    def _run(self,kind,collision):
        records={}
        try:
            source=absolute_path(self.state['input']);dest=absolute_path(self.state['output'])
            boundary=OutputBoundary(dest,source)
            if kind=='scan':
                files=[]
                for folder,dirs,names in os.walk(source,followlinks=False):
                    if self._stop.is_set():break
                    dirs[:]=[d for d in dirs if not Path(folder,d).is_symlink() and not Path(folder,d).is_junction()]
                    for name in names:
                        f=Path(folder,name)
                        if f.suffix.lower()=='.nif' and not f.is_symlink():files.append(f)
                files.sort()
                self._update(rows=[{'path':str(f),'name':str(f.relative_to(source)),'status':'等待扫描','size':f.stat().st_size,'detail':''} for f in files])
            rows=self.state['rows']
            if not rows:self._update(message='目录中没有 NIF 模型',phase='idle');self._log('目录中没有 NIF 模型','warn');return
            width=self._parallelism(rows)
            self._update(workers=width)
            cursor=iter(enumerate(rows));pending={};completed=0
            with ThreadPoolExecutor(max_workers=width,thread_name_prefix='mesh-dispatch') as pool:
                def submit_next():
                    if self._stop.is_set():return False
                    item=next(cursor,None)
                    if item is None:return False
                    index,row=item
                    pending[pool.submit(self._process_row,row,kind,collision,dest)]=index
                    return True
                for _ in range(width):submit_next()
                while pending:
                    finished,_=wait(pending,timeout=.1,return_when=FIRST_COMPLETED)
                    for future in finished:
                        index=pending.pop(future)
                        record=future.result()
                        if record is not None:
                            records[index]=record;completed+=1
                            self._update(completed=completed)
                        submit_next()
            if kind=='convert':
                report=dest/('nifshift-report-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.json')
                boundary.prepare_parent(report)
                boundary.validate(report,must_be_absent=True)
                with report.open('x',encoding='utf8') as stream:
                    json.dump({'build':BUILD,'direction':self.state['direction'],'reference':self.state['reference'],'cancelled':self._stop.is_set(),'collision':collision,'game_verified':False,'workers':width,'files':[records[i] for i in sorted(records)]},stream,ensure_ascii=True,indent=2)
                boundary.validate(report)
                self._update(report=str(report))
            self._update(phase='idle' if self._stop.is_set() else 'ready' if kind=='scan' else 'done',message='任务已取消，已完成文件已保留' if self._stop.is_set() else '扫描完成' if kind=='scan' else '转换结束，请查看逐项结果')
            self._log(self.state['message'],'warn' if self._stop.is_set() else 'info')
            if self.state['report']:self._log('报告已保存：'+self.state['report'],'success')
        except Exception as e:
            self._update(phase='idle',message='任务错误：'+(str(e) or type(e).__name__))
            self._log(self.state['message'],'error')
        finally:
            self._shutdown_worker()
            with self._guard:
                self._batch_elapsed=max(0.0,time.monotonic()-self._batch_started) if self._batch_started is not None else 0.0
                self.busy=False
    def open_output(self):
        path=Path(self.state['output'])
        if self.state['output'] and path.is_dir():os.startfile(str(path));return {'ok':True}
        return {'error':'输出目录尚未创建'}
    def close(self):
        if self.busy:self.cancel();return {'error':'正在结束任务，请稍后关闭'}
        self.exit_allowed=True;self._window.destroy();return {'ok':True}

def main():
    import webview
    from trusted_ui import TrustedUiServer, attach_bridge
    api=Api();base=Path(getattr(sys,'_MEIPASS',Path(__file__).parent)).resolve()
    smoke='--smoke-test' in sys.argv
    with TrustedUiServer(base/'ui.html') as ui_server:
        # Use only the already-bound in-memory single-page server. A conflict raises
        # here, before WebView can load a page belonging to another local process.
        webview.settings['ALLOW_FILE_URLS']=False
        webview.settings['ALLOW_DOWNLOADS']=False
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
        window=webview.create_window('Mesh Converter · ALPHA 1.0',ui_server.url,js_api=None,width=1060,height=940,resizable=False,background_color='#f8f7f2',hidden=smoke)
        attach_bridge(window,api,ui_server.url,webview)
        api._window=window
        renderer_errors=[]
        def on_initialized(renderer):
            if renderer!='edgechromium':
                renderer_errors.append(
                    'Mesh Converter requires Microsoft Edge WebView2 Runtime. '
                    'The selected engine was '+str(renderer)+', so startup was stopped. '
                    '此版本需要 Microsoft Edge WebView2 Runtime；当前引擎不受支持，已停止启动。')
                # initialized is synchronous. False stops webview.start before
                # guilib.create_window; raising here would be swallowed by Event.
                return False
        window.events.initialized+=on_initialized
        def on_closing():
            if api.busy:api.cancel();return False
            if (not getattr(window,'_private0516_bridge_ready',False)
                    or not window.events.loaded.is_set()
                    or not window.events._pywebviewready.is_set()):
                # Navigation/injection failure must not leave a window whose
                # native close button waits forever for an unavailable JS API.
                api.exit_allowed=True
                return True
            if not api.exit_allowed:
                threading.Thread(target=lambda:window.evaluate_js('window.nifShiftExit && window.nifShiftExit()'),daemon=True).start()
                return False
        window.events.closing+=on_closing
        def test_ui():
            import traceback
            root=Path(sys.argv[sys.argv.index('--smoke-test')+1]).resolve();root.mkdir(parents=True,exist_ok=True)
            result={}
            try:
                for _ in range(100):
                    time.sleep(.1)
                    if window.evaluate_js("Boolean(window.pywebview && window.pywebview.api && document.getElementById('ns-action') && !document.getElementById('ns-action').disabled)"):break
                else:raise TimeoutError('Desktop bridge not ready')
                assert api.configure(str(root/'input'),str(root/'output')).get('ok')
                time.sleep(3)
                window.evaluate_js("document.getElementById('ns-dialog-close').click()")
                for expected in ('ready','done'):
                    window.evaluate_js("window.dispatchEvent(new Event('focus'))")
                    desired='预扫描模型' if expected=='ready' else '开始转换'
                    for _ in range(100):
                        if desired in window.evaluate_js("document.getElementById('ns-action').innerText"):break
                        time.sleep(.1)
                    else:raise TimeoutError('UI state did not refresh')
                    window.evaluate_js("document.getElementById('ns-action').click()")
                    for _ in range(600):
                        time.sleep(.1)
                        if api.snapshot()['phase']==expected and not api.busy:break
                    else:raise TimeoutError('UI action did not reach '+expected+': '+str(api.snapshot()))
                    time.sleep(.7)
                assert any(r['status']=='完成' for r in api.snapshot()['rows'])
                window.evaluate_js("document.querySelector('[data-panel=logs]').click();window.dispatchEvent(new Event('focus'))")
                # The hidden smoke window intentionally defers log DOM work. It must
                # still receive the log count through the real native bridge.
                deferred=window.evaluate_js('document.hidden')
                for _ in range(100):
                    if window.evaluate_js("parseInt(document.getElementById('ns-log-total').textContent,10)>0" if deferred else "document.querySelectorAll('.ns-log-line').length>0"):break
                    time.sleep(.1)
                else:raise TimeoutError('Native log state did not update')
                result={'passed':True,'engine':window.evaluate_js('navigator.userAgent'),'button':window.evaluate_js("document.getElementById('ns-action').innerText"),'log_dom_deferred_while_hidden':deferred,'state':api.snapshot()}
            except Exception:result={'passed':False,'error':traceback.format_exc()}
            finally:
                (root/'ui-test.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');api.cancel()
                while api.busy:time.sleep(.1)
                api.exit_allowed=True;window.destroy()
        storage=(Path(sys.argv[sys.argv.index('--smoke-test')+1]).resolve()/'webview-secure1'
                 if smoke else Path(os.environ.get('LOCALAPPDATA',Path.home()))/'private0516'/'MeshConverter'/'webview-secure1')
        webview.start(test_ui if smoke else None,gui='edgechromium',debug=False,
                      private_mode=False,storage_path=str(storage))
        if renderer_errors:
            # Outside the event dispatcher, this error reaches the launcher.
            raise RuntimeError(renderer_errors[0])

if __name__=='__main__':
    mp.freeze_support()
    if '--self-test' in sys.argv:
        from selftest import run
        def option(name):
            return Path(sys.argv[sys.argv.index(name)+1]) if name in sys.argv else None
        run(Path(sys.argv[sys.argv.index('--self-test')+1]),option('--fo4-root'),option('--fo76-root'))
    else:main()
