"""Live workflow regression using disposable source cells and a separate Git repo."""
import json
from pathlib import Path
import shlex
import time
import uuid
from virtuoso_bridge import VirtuosoClient
from layoutdiff.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.data.history import atomic_json

c = VirtuosoClient.from_env()
token = uuid.uuid4().hex[:8]
out = Path(__file__).resolve().parents[1]/'evidence'/('workflow-'+token)
out.mkdir(parents=True)
def skill(code):
    result = c.execute_skill('progn('+code+')', timeout=120)
    value = checked(result)
    if result.warnings: print('SKILL warnings', result.warnings, flush=True)
    return value
def shell(code):
    r = c.ssh_runner.run_command(code, timeout=120)
    if r.returncode: raise RuntimeError(r.stderr)
    return r.stdout
root = loads(skill('ALDRuntimeRoot'))
repo = '/tmp/ald-workflow-regression-'+token
def remote_python(code):
    return shell('python3 -c '+shlex.quote(code))
def read_json(path):
    return json.loads(shell('cat '+shlex.quote(path)))
def exists(path):
    return c.ssh_runner.run_command('test -e '+shlex.quote(path)).returncode == 0
def until(predicate, timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate(): return
        time.sleep(.4)
    raise TimeoutError('Condition timed out')
def request(args, *, error=False, busy=False):
    start=time.time()
    visible=loads(skill('ALDGUIEnqueue('+sk(args)+') list(when(boundp(\'ALDGUIBusyForm) hiIsFormDisplayed(ALDGUIBusyForm)) '
                       'ALDGUIBusyActive when(boundp(\'ALDGUIHistoryForm) && ALDGUIHistoryForm ALDGUIHistoryForm->aldBrowserStatus->value))'))
    if busy:
        assert bool(visible[0]) == (args[0] in {'quick-preview', 'quick-commit', 'git-setup'})
        assert visible[1] is True
        if visible[2]:
            assert visible[2].startswith('Loading: '), visible
    end=time.monotonic()+180
    while time.monotonic()<end:
        code = ('import json,pathlib; rows=[json.loads(p.read_text()) for p in pathlib.Path('+repr(root+'/requests')+').glob("*.json")]; '
                'print(json.dumps([r for r in rows if r["time"]>'+repr(start-1)+' and r["request"]=='+repr(args)+']))')
        rows=json.loads(remote_python(code))
        if rows:
            row=max(rows,key=lambda r:r['time'])
            atomic_json(out/(args[0]+'-'+uuid.uuid4().hex[:4]+'.json'),row)
            if error:
                assert 'error' in row,row
                return row
            assert 'error' not in row,row
            print(args[0], 'PASS', flush=True)
            return row['result']
        time.sleep(.4)
    raise TimeoutError(args)

original=read_json(root+'/git.json')
shell('mkdir -p '+shlex.quote(repo))
shell('git -C '+shlex.quote(repo)+' init')
shell('git -C '+shlex.quote(repo)+' config user.name "Workflow Regression"')
shell('git -C '+shlex.quote(repo)+' config user.email workflow@example.invalid')
setting=out/'git.json'; setting.write_text(json.dumps({**original,'repository':repo}))
c.upload_file(str(setting),root+'/git.json')
lib='LAYOUT_DIFF_TEST'; cell='workflow_'+token
identity=[lib,cell,'layout']
adapter=VirtuosoAdapter(c,out/'captures')
report={'identity':identity,'repository':repo}
try:
    with c.layout.create(lib,cell) as edit:
        edit.add('dbCreateRect(cv list("MET1" "drawing") list(0:0 2:2))')
        edit.add('dbCreateRect(cv list("MET2" "drawing") list(4:0 6:2))')
    before=adapter.capture(*identity)
    preview=request(['quick-preview',*identity],busy=True)
    first=request(['quick-commit',preview['token'],'Workflow initial'],busy=True)['git_commit']
    skill('hiFormCancel(ALDGUIQuickForm)')
    with c.layout.modify(lib,cell) as edit:
        edit.add('foreach(o cv~>shapes when(o~>layerName=="MET2" dbDeleteObject(o)))')
        edit.add('dbCreateRect(cv list("MET3" "drawing") list(7:0 9:2))')
    after=adapter.capture(*identity)
    preview=request(['quick-preview',*identity])
    second=request(['quick-commit',preview['token'],'Workflow delete and add'],busy=True)['git_commit']
    skill('hiFormCancel(ALDGUIQuickForm)')
    report.update(first=first,second=second)
    request(['history',*identity])
    review=request(['review',*identity,second],busy=True)
    report['review']=review
    active=read_json(root+'/runtime.json')['temporary_directory']
    assert active.startswith('/tmp/'),active
    path=loads(skill('ddGetObj('+sk(review['library'])+')~>readPath'))
    assert path.startswith(active+'/work/'),path
    assert review['deleted_shadows']['count']==1,review
    second_win=int(skill('deOpenCellView('+sk(review['library'])+' '+sk(review['cell'])+' "layout" "maskLayout" nil "r")~>windowNum'))
    skill('hiCloseWindow(window('+str(review['window'])+'))')
    time.sleep(2)
    assert exists(path), 'Review deleted while second window was open'
    skill('hiCloseWindow(window('+str(second_win)+'))')
    until(lambda:not exists(path),40)
    assert skill('ddGetObj('+sk(review['library'])+')')=='nil'
    report['multiple_window_cleanup']=True
    # Full diff viewers independently retain their own bundles.
    browser_token=loads(skill('ALDGUIHistoryForm->aldBrowserToken'))
    full=request(['browser-full',browser_token,second,-1,-1])
    full_path=full['full_diff']
    viewer=int(skill('ALDGUIHistoryForm->aldFullWindow~>windowNum'))
    skill('hiFormCancel(ALDGUIHistoryForm)')
    time.sleep(2); assert exists(full_path)
    skill('hiCloseWindow(window('+str(viewer)+'))')
    until(lambda:not exists(full_path))
    report['viewer_cleanup']=True
    request(['repository',0,500])
    assert loads(skill('ALDGUIHistoryForm->aldViews->value'))==2
    assert len(loads(skill('ALDGUIHistoryForm->aldViews->page2->aldGraph->choices')))==2
    assert loads(skill('ALDGUIHistoryForm->aldGitCells'))==[identity]
    skill('hiWindowSaveImage(?target ALDGUIHistoryForm ?path '+sk(repo+'/git-centric.png')+' ?format "png" ?toplevel t)')
    c.download_file(repo+'/git-centric.png',str(out/'git-centric.png'))
    browser_token=loads(skill('ALDGUIHistoryForm->aldBrowserToken'))
    skill('ALDGUIHistoryForm->aldSelectedCommit='+sk(first))
    request(['repository-select',browser_token,first])
    # Cancel is non-mutating; edits after preview also prevent restore.
    plan=request(['restore-prepare',*identity,first],busy=True)
    request(['restore-cancel',plan['token']])
    skill('ALDGUIRestoreForm->aldToken=nil hiFormCancel(ALDGUIRestoreForm)')
    assert adapter.capture(*identity)==after
    plan=request(['restore-prepare',*identity,first])
    with c.layout.modify(lib,cell) as edit:
        edit.add('dbReplaceProp(cv "workflowTest" "string" "changed after preview")')
    failed=request(['restore-apply',plan['token']],error=True)
    assert 'changed after restore preview' in failed['error'],failed
    skill('hiFormCancel(ALDGUIRestoreForm) hiFormCancel(ALDGUIResultForm)')
    with c.layout.modify(lib,cell) as edit:
        edit.add('dbDeletePropByName(cv "workflowTest")')
    # Successful restore with two open target windows; Git stays bit-identical.
    old_head=shell('git -C '+shlex.quote(repo)+' rev-parse HEAD')
    old_index=shell('sha256sum '+shlex.quote(repo+'/.git/index'))
    for _ in range(2):
        skill('deOpenCellView('+sk(lib)+' '+sk(cell)+' "layout" "maskLayout" nil "a")')
    plan=request(['restore-prepare',*identity,first],busy=True)
    skill('ALDGUIRestoreForm->aldToken=nil hiFormCancel(ALDGUIRestoreForm)')
    restored=request(['restore-apply',plan['token']],busy=True)
    assert adapter.capture(*identity)==before
    assert shell('git -C '+shlex.quote(repo)+' rev-parse HEAD')==old_head
    assert shell('sha256sum '+shlex.quote(repo+'/.git/index'))==old_index
    assert len(loads(skill('setof(w hiGetWindowList() ALDGUIRestoreMatches(w->displayCellView '+sk(identity)+'))')))==2
    report['restore']=restored
    backup_path=loads(skill('ddGetObj('+sk(restored['backup'][0])+')~>readPath'))
    skill('foreach(w hiGetWindowList() when(ALDGUIRestoreMatches(w->displayCellView '+sk(identity)+') hiCloseWindow(w)))')
    skill('hiFormCancel(ALDGUIResultForm)')
    until(lambda:not exists(backup_path),40)
    report['restore_cleanup']=True
    # Window leases outlive both the worker and its bridge connection.
    request(['history',*identity])
    review=request(['review',*identity,second])
    lease_session=read_json(root+'/runtime.json')['temporary_directory']
    review_path=loads(skill('ddGetObj('+sk(review['library'])+')~>readPath'))
    skill('ALDRuntimeStop()')
    until(lambda:skill('ALDRuntimeIPC')=='nil',30)
    assert exists(review_path), 'Stopping runtime deleted an open review'
    skill('hiCloseWindow(window('+str(review['window'])+'))')
    until(lambda:not exists(lease_session),40)
    skill('ALDRuntimeStart()')
    until(lambda:loads(skill('ALDRuntimeState'))=='Running',40)
    report['worker_stop_reaper']=True
    report['passed']=True
finally:
    setting.write_text(json.dumps(original))
    c.upload_file(str(setting),root+'/git.json')
    atomic_json(out/'report.json',report)
    print('Evidence:',out,flush=True)
