"""Verify complete coverage reporting in the deployed GUI and unchanged Git HEAD."""
import json
from pathlib import Path
import shlex
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.eda.virtuoso.adapter import checked
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.data.history import atomic_json

report_path = Path(sys.argv[1])
fixture = json.loads(report_path.read_text())['unsupported']
identity = fixture['source']
assert identity[0] == 'LAYOUT_DIFF_TEST'
c = VirtuosoClient.from_env()
def skill(code):
    r = c.execute_skill('progn(' + code + ')', timeout=90)
    assert not r.warnings, r
    return checked(r)
def shell(code):
    r = c.ssh_runner.run_command(code, timeout=90)
    assert r.returncode == 0, r.stderr
    return r.stdout
root = loads(skill('ALDRuntimeRoot'))
repo = root.rsplit('/', 2)[0] + '/analog_layout_diff_git'
def audits():
    code = 'import json,pathlib; print(json.dumps([json.loads(p.read_text()) for p in pathlib.Path(' + repr(root + '/requests') + ').glob("*.json")]))'
    return json.loads(shell('python3 -c ' + shlex.quote(code)))
old_window = int(skill('hiGetCurrentWindow()~>windowNum'))
win = int(skill('deOpenCellView(' + ' '.join(sk(x) for x in identity) + ' "maskLayout" nil "a")~>windowNum'))
head = shell('git -C ' + shlex.quote(repo) + ' rev-parse HEAD')
status = shell('git -C ' + shlex.quote(repo) + ' status --porcelain')
baseline = max([r['time'] for r in audits()] or [0])
skill(f'ALDGUIQuickSave(window({win}))')
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    rows = [r for r in audits() if r['time'] > baseline and r['request'] == ['quick-preview', *identity]]
    if rows:
        result = max(rows, key=lambda r: r['time'])
        break
    time.sleep(.25)
else:
    raise TimeoutError('preview error report')
assert result['unsupported_counts'] == fixture['counts'], result
assert 'notification_error' not in result, result
shown = loads(skill('ALDGUIResultForm->aldResult->value'))
assert all(reason in shown for reason in fixture['counts']), shown
assert skill('ALDGUIResultForm->aldFullReport->enabled') == 't'
skill('ALDGUIOpenUnsupported()')
report_win = int(skill('ALDGUIResultForm->aldReportWindow~>windowNum'))
remote_path = loads(skill('ALDGUIResultForm->aldReportPath'))
lines = shell('cat ' + shlex.quote(remote_path)).splitlines()
assert len(lines) == fixture['details'], lines
image = root + '/unsupported-report.png'
skill(f'hiWindowSaveImage(?target ALDGUIResultForm ?path {sk(image)} ?format "png" ?toplevel t)')
checked(c.download_file(image, str(report_path.parent / 'unsupported-report.png')))
assert shell('git -C ' + shlex.quote(repo) + ' rev-parse HEAD') == head
assert shell('git -C ' + shlex.quote(repo) + ' status --porcelain') == status
skill(f'hiCloseWindow(window({report_win})) hiFormCancel(ALDGUIResultForm) hiCloseWindow(window({win}))')
skill(f'when(member(window({old_window}) hiGetWindowList()) hiRaiseWindow(window({old_window})))')
atomic_json(report_path.parent / 'unsupported-gui-report.json', {'counts': result['unsupported_counts'],
    'displayed': shown, 'details': len(lines), 'all_elements_button_passed': True,
    'git_head_preserved': True, 'git_status_preserved': True, 'audit': result})
print('PASS complete GUI report, all-elements viewer, unchanged Git HEAD/status')
