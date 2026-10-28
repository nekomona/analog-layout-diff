"""Commit and review a verified custom/chamfer fixture through the deployed GUI."""
import argparse
import json
from pathlib import Path
import shlex
import sys
import time
project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.virtuoso.sexpr import loads, dumps as sk
from layoutdiff.data.history import atomic_json
from layoutdiff.data.core import digest
p = argparse.ArgumentParser(); p.add_argument('report')
p.add_argument('--message', default='Verify custom and chamfer path segment support')
args = p.parse_args()
report_path = Path(args.report)
fixture = json.loads(report_path.read_text())
identity = fixture['source']; assert identity[0] == 'LAYOUT_DIFF_TEST'
out = report_path.parent
c = VirtuosoClient.from_env()

def skill(code):
    r = c.execute_skill('progn(' + code + ')', timeout=90)
    assert not r.warnings, r
    return checked(r)

def shell(code):
    r = c.ssh_runner.run_command(code, timeout=120)
    if r.returncode: raise RuntimeError(r.stderr)
    return r.stdout

root = loads(skill('ALDRuntimeRoot'))
repo = root.rsplit('/', 2)[0] + '/analog_layout_diff_git'
def audits():
    code = 'import json,pathlib; print(json.dumps([json.loads(p.read_text()) for p in pathlib.Path(' + repr(root + '/requests') + ').glob("*.json")]))'
    return json.loads(shell('python3 -c ' + shlex.quote(code)))

def request(code, name):
    baseline = max([r['time'] for r in audits()] or [0])
    skill(code)
    end = time.monotonic() + 120
    while time.monotonic() < end:
        rows = [r for r in audits() if r['time'] > baseline and r['request'][0] == name]
        if rows:
            r = max(rows, key=lambda r: r['time'])
            assert 'error' not in r, r
            return r['result']
        time.sleep(.25)
    raise TimeoutError(name)

def screenshot(name, target):
    remote = root + '/pathseg-' + name + '.png'
    skill(f'hiWindowSaveImage(?target {target} ?path {sk(remote)} ?format "png" ?toplevel t)')
    checked(c.download_file(remote, str(out / (name + '.png'))))

for _ in range(60):
    if loads(skill('ALDRuntimeState')) == 'Running': break
    time.sleep(.25)
assert loads(skill('ALDRuntimeState')) == 'Running'
old_window = int(skill('hiGetCurrentWindow()~>windowNum'))
lib, cell, view = identity
win = int(skill(f'deOpenCellView({sk(lib)} {sk(cell)} {sk(view)} "maskLayout" nil "a")~>windowNum'))
old_status = shell('git -C ' + shlex.quote(repo) + ' status --porcelain')
preview = request(f'ALDGUIQuickSave(window({win}))', 'quick-preview')
assert preview.get('repo') == repo, preview
assert 'MET1 shapes' in loads(skill('ALDGUIQuickForm->aldPreview->value'))
assert skill('hiGetCurrentField(ALDGUIQuickForm)') == 'aldMessage'
screenshot('commit-preview', 'ALDGUIQuickForm')
committed = request(f'ALDGUIQuickForm->aldMessage->value={sk(args.message)} hiFormDone(ALDGUIQuickForm)', 'quick-commit')
history = request(f'ALDGUIHistory(window({win}))', 'history')
review = request('ALDGUIHistoryCB(ALDGUIHistoryForm)', 'review')
adapter = VirtuosoAdapter(c, out / 'gui-readback')
assert digest(adapter.capture(lib, review['cell'])) == fixture['cases'][-1]['digest']
skill(f'ALDGUIFit(window({review["window"]}))')
screenshot('review', f'window({review["window"]})')
assert shell('git -C ' + shlex.quote(repo) + ' status --porcelain') == old_status
skill(f'hiCloseWindow(window({review["window"]})) hiFormCancel(ALDGUIHistoryForm) hiCloseWindow(window({win}))')
skill(f'when(member(window({old_window}) hiGetWindowList()) hiRaiseWindow(window({old_window})))')
atomic_json(out / 'gui-report.json', {'identity': identity, 'preview': preview,
    'commit': committed, 'native_review_equal': True, 'review': review,
    'git_status_preserved': True, 'runtime': loads(skill('ALDRuntimeState'))})
print('PASS deployed Save & Commit and native GUI review: ' + args.message)
