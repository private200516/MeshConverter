"""Integration tests with user-supplied game files; fixtures are never bundled."""
import hashlib
import json
import shutil
import time
from pathlib import Path
from app import Api
from inspect_nif import Nif


def wait(api):
    end = time.monotonic() + 180
    while api.busy:
        if time.monotonic() > end:
            api.cancel()
            raise TimeoutError('Batch integration test timed out')
        time.sleep(.03)
    return api.snapshot()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root, fo4_root=None, fo76_root=None):
    if fo4_root is None or fo76_root is None:
        raise ValueError('Supply --fo4-root <FO4 Meshes> and --fo76-root <FO76 meshes>; game assets are not included.')
    fo4_root, fo76_root = Path(fo4_root), Path(fo76_root)
    sources = {
        '墙壁.nif':fo76_root/'architecture/hightech_mansions/htmansion_wallbsolidb_01int.nif',
        'body.nif':fo76_root/'atx/actors/powerarmor/atx_pa_communist_body.nif',
        'lamp.nif':fo76_root/'atx/actors/powerarmor/atx_pa_communist_headlamp_fx.nif',
        'door.nif':fo76_root/'architecture/hightech_mansions/htmansion_doora_01.nif',
        'door_load.nif':fo76_root/'architecture/hightech_mansions/htmansion_doora_01load.nif',
    }
    reverse_source = fo4_root/'Actors/PowerArmor/CharacterAssets/Mods/PA_T45_Body.nif'
    originals = list(sources.values()) + [reverse_source]
    before = {str(p):sha(p) for p in originals}
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = root/'输入模型'
    source.mkdir()
    for name,p in sources.items():shutil.copyfile(p,source/name)
    (source/'broken.nif').write_bytes(b'not a nif')
    api = Api()
    assert api.configure_options('76-to-4',str(fo4_root/'Actors/PowerArmor/CharacterAssets/skeleton.nif')).get('ok')
    assert api.configure(str(source),str(source)).get('error')
    assert api.configure(str(source),str(source/'nested')).get('error')
    out=root/'输出模型'
    assert api.configure(str(source),str(out)).get('ok')
    assert api.start('convert').get('error')
    assert api.start('scan')['ok']
    state=wait(api)
    assert state['phase']=='ready' and state['status_counts'].get('可转换')==5,state
    assert api.start('convert')['ok']
    state=wait(api)
    assert state['phase']=='done' and state['status_counts'].get('完成')==5,state
    for name in sources:assert Nif(out/name).validate()['bs']==130
    assert 'bhkPhysicsSystem' in Nif(out/'墙壁.nif').types
    assert 'BSSkin::Instance' in Nif(out/'body.nif').types
    assert 'NiControllerManager' in Nif(out/'door.nif').types
    assert Path(state['report']).is_file()
    assert state['logs'] and not api.snapshot(state['logs'][-1]['id'])['logs']
    digest=sha(out/'墙壁.nif')
    api.start('scan');wait(api);api.start('convert');wait(api)
    assert sha(out/'墙壁.nif')==digest
    api.configure(str(source),str(root/'无碰撞'))
    api.start('scan');wait(api)
    assert api.start('convert',False).get('error')
    api.start('scan',False);wait(api);api.start('convert',False)
    state=wait(api)
    assert state['status_counts'].get('完成')==5,state
    assert 'bhkPhysicsSystem' not in Nif(root/'无碰撞'/'墙壁.nif').types
    reverse_input=root/'反向输入'
    reverse_input.mkdir()
    shutil.copyfile(reverse_source,reverse_input/'胸甲.nif')
    api.configure(str(reverse_input),str(root/'反向输出'))
    api.configure_options('4-to-76',str(fo76_root/'actors/powerarmor/characterassets/skeleton.nif'))
    assert not api.snapshot()['rows'] and api.start('convert',False).get('error')
    api.start('scan',False);state=wait(api)
    assert state['status_counts'].get('可转换')==1,state
    api.start('convert',False);state=wait(api)
    assert state['status_counts'].get('完成')==1,state
    assert Nif(root/'反向输出'/'胸甲.nif').validate()['bs']==155
    api.configure(str(source),str(root/'取消'))
    api.start('scan');api.cancel();state=wait(api)
    assert state['phase']=='idle' and api._process is None,state
    assert not list(root.rglob('.nifshift-*.tmp'))
    assert not list(root.rglob('.mesh-converter-*.tmp'))
    api.state['rows']=[dict(name=str(i),status='等待扫描',result={'private':'full report'}) for i in range(100000)]
    started=time.monotonic();snapshot=api.snapshot(row_offset=99750)
    assert len(snapshot['rows'])==250 and snapshot['row_total']==100000
    assert 'result' not in snapshot['rows'][0]
    elapsed=time.monotonic()-started
    after={str(p):sha(p) for p in originals}
    assert before==after
    report=dict(passed=True,checks=['both directions','target skeleton references','Unicode paths',
      'invalid file isolation','collision modes','scan invalidation','existing output preserved',
      'cancellation cleanup','100000-row paged snapshot','unchanged source hashes'],
      snapshot_100000_seconds=elapsed,source_sha256=before)
    (root/'test-result.json').write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=True))
