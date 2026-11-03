"""Exercise both native consent dialogs in a disposable layout/Git repository.

Run only with the updated plugin installed in the selected CIW. No production
cellviews or production Git history are changed. Runtime Git selection is
restored in finally. A bus net is intentionally unsupported by the adapter.
"""
import json
from pathlib import Path
import shlex
import time
import uuid
from virtuoso_bridge import VirtuosoClient
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads

c = VirtuosoClient.from_env()
tag = uuid.uuid4().hex[:8]
out = Path(__file__).resolve().parents[1]/'evidence'/('omission-'+tag)
out.mkdir(parents=True)
def skill(code):
    return checked(c.execute_skill('progn('+code+')', timeout=120))
def shell(code):
    r = c.ssh_runner.run_command(code, timeout=120)
    if r.returncode: raise RuntimeError(r.stderr)
    return r.stdout
def read_json(path):
    return json.loads(shell('cat '+shlex.quote(path)))

root = loads(skill('ALDRuntimeRoot'))
repo = '/tmp/ald-omission-regression-'+tag
identity = ['LAYOUT_DIFF_TEST', 'omission_'+tag, 'layout']
shell('mkdir -p '+shlex.quote(repo))
shell('git -C '+shlex.quote(repo)+' init')
shell('git -C '+shlex.quote(repo)+' config user.name "Omission Regression"')
shell('git -C '+shlex.quote(repo)+' config user.email omission@example.invalid')
original = read_json(root+'/git.json')
setting = out/'git.json'
setting.write_text(json.dumps({**original, 'repository':repo}))
checked(c.upload_file(str(setting), root+'/git.json'))
poller = out/'poll.py'
poller.write_text('''import json, pathlib, sys
paths = list(pathlib.Path(sys.argv[1], "requests").glob("*.json"))
if len(sys.argv) == 2:
    print(json.dumps([p.name for p in paths])); sys.exit()
seen, request = set(json.loads(sys.argv[2])), json.loads(sys.argv[3])
for p in paths:
    if p.name not in seen:
        row = json.loads(p.read_text())
        if row["request"] == request:
            print(json.dumps(row)); break
''')
checked(c.upload_file(str(poller), repo+'/poll.py'))
def checkpoint():
    # Compare request IDs, not clocks on the Windows host and remote NAS.
    return json.loads(shell('python3 '+shlex.quote(repo+'/poll.py')+' '+shlex.quote(root)))
def wait(args, start, error=False):
    until = time.monotonic()+150
    while time.monotonic()<until:
        text = shell('python3 '+shlex.quote(repo+'/poll.py')+' '+shlex.quote(root)+' '+shlex.quote(json.dumps(start))+' '+shlex.quote(json.dumps(args)))
        if text.strip():
            row = json.loads(text)
            if error:
                assert 'error' in row, row
                return row
            assert 'error' not in row, row
            print(args[0], 'PASS', flush=True)
            return row['result']
        time.sleep(.4)
    raise TimeoutError(args)
def request(args, error=False):
    start = checkpoint()
    skill('ALDGUIEnqueue('+sk(args)+')')
    return wait(args, start, error)
def begin():
    p = request(['quick-preview', *identity])
    start = checkpoint()
    skill('ALDGUIQuickForm->aldMessage->value="Omission regression" hiFormDone(ALDGUIQuickForm)')
    result = wait(['quick-commit', p['token'], 'Omission regression'], start)
    assert result['confirmation']==1 and loads(skill('hiIsFormDisplayed(ALDGUIOmissionForm)'))
    return result
def accept(first, error=False):
    start = checkpoint()
    skill('ALDGUIOmissionAccept(ALDGUIOmissionForm)')
    return wait(['quick-omit-continue' if first['confirmation']==1 else 'quick-omit-confirm', first['token']], start, error)
def reject(p):
    start = checkpoint(); skill('hiFormCancel(ALDGUIOmissionForm)')
    wait(['quick-cancel', p['token']], start)
def no_commit():
    r = c.ssh_runner.run_command('git -C '+shlex.quote(repo)+' rev-parse --verify HEAD')
    assert r.returncode != 0
def screenshot(name):
    path = repo+'/'+name+'.png'
    assert skill('hiWindowSaveImage(?target ALDGUIOmissionForm ?path '+sk(path)+' ?format "png" ?toplevel t)') == 't'
    checked(c.download_file(path, str(out/(name+'.png'))))
def exists(path):
    return c.ssh_runner.run_command('test -e '+shlex.quote(path)).returncode == 0

adapter = VirtuosoAdapter(c, out/'captures')
report = dict(identity=identity, repository=repo)
try:
    with c.layout.create(*identity[:2]) as edit:
        edit.add('dbCreateRect(cv list("MET1" "drawing") list(0:0 2:2))')
        edit.add('dbMakeNet(cv "UNKNOWN<1:0>")')
    before = adapter.capture(*identity, dependencies=False)
    assert any(r['kind']=='net' and r.get('numBits',1)!=1 for r in before['objects'].values()), before
    first = begin(); no_commit(); screenshot('first-warning')
    windows = set(loads(skill('foreach(mapcar w hiGetWindowList() w~>windowNum)')))
    full = request(['quick-omission-report', first['token']])
    viewers = set(loads(skill('foreach(mapcar w hiGetWindowList() w~>windowNum)'))) - windows
    assert len(viewers)==1
    reject(first); no_commit(); assert exists(full['report'])
    for window in viewers:
        skill('hiCloseWindow(window('+str(window)+'))')
    deadline = time.monotonic()+30
    while exists(full['report']) and time.monotonic()<deadline:
        time.sleep(.5)
    assert not exists(full['report'])
    first = begin(); last = accept(first); no_commit(); screenshot('second-warning'); reject(last); no_commit()
    # An ignored-only change must invalidate the exact consented capture.
    first = begin(); last = accept(first)
    with c.layout.modify(*identity[:2]) as edit:
        edit.add('dbReplaceProp(car(setof(n cv~>nets n~>name=="UNKNOWN<1:0>")) "omissionTest" "string" "changed")')
    failed = accept(last, error=True)
    assert 'ignored elements' in failed['error']; no_commit()
    skill('hiFormCancel(ALDGUIResultForm)')
    before = adapter.capture(*identity, dependencies=False)
    first = begin()
    bad = request(['quick-omit-confirm', first['token']], error=True)
    assert 'expired' in bad['error']; no_commit()
    skill('hiFormCancel(ALDGUIResultForm)')
    last = accept(first)
    assert last['confirmation']==2
    text = loads(skill('ALDGUIOmissionForm->aldOmissionText->value'))
    assert 'WILL BE LOST' in text
    committed = accept(last)
    report['commit'] = committed
    assert adapter.capture(*identity, dependencies=False) == before
    request(['history', *identity])
    review = request(['review', *identity, committed['git_commit']])
    reconstructed = adapter.capture(review['library'], review['cell'], dependencies=False)
    assert any(r['kind']=='rect' for r in reconstructed['objects'].values())
    assert not any(r['kind']=='net' and r.get('numBits',1)!=1 for r in reconstructed['objects'].values())
    assert 'INCOMPLETE CHECKPOINT' in review['summary']
    skill('hiCloseWindow(window('+str(review['window'])+'))')
    plan = request(['restore-prepare', *identity, committed['git_commit']])
    assert 'INCOMPLETE CHECKPOINT' in loads(skill('ALDGUIRestoreForm->aldRestoreText->value'))
    request(['restore-cancel', plan['token']])
    skill('ALDGUIRestoreForm->aldToken=nil hiFormCancel(ALDGUIRestoreForm)')
    assert adapter.capture(*identity, dependencies=False) == before
    report.update(passed=True, first_rejection=True, second_rejection=True, ordered_tokens=True,
                  exact_supported_reconstruction=True, restore_warning=True, source_unchanged=True,
                  unknown_only_stale_preview_rejected=True, full_report_window_cleanup=True)
finally:
    setting.write_text(json.dumps(original))
    checked(c.upload_file(str(setting), root+'/git.json'))
    skill('hiFormCancel(ALDGUIHistoryForm)')
    (out/'report.json').write_text(json.dumps(report, indent=2))
    print('Evidence:', out, flush=True)
