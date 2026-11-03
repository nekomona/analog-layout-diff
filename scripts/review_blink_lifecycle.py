"""Check matrix cancellation and timer teardown in owned review windows."""
import json
import sys
import time
import shlex
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.eda.virtuoso.adapter import checked
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.data.history import atomic_json

out = Path(__file__).resolve().parents[1] / 'evidence/review-shadows'
report = json.loads((out / 'native-report.json').read_text())
c = VirtuosoClient.from_env()
def skill(code):
    r = c.execute_skill('progn(' + code + ')', timeout=120)
    assert not r.warnings, r
    return checked(r)

root = loads(skill('ALDRuntimeRoot'))
def audits():
    code = 'import json,pathlib; print(json.dumps([json.loads(p.read_text()) for p in pathlib.Path(' + repr(root + '/requests') + ').glob("*.json")]))'
    r = c.ssh_runner.run_command('python3 -c ' + shlex.quote(code), timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)
baseline = max([r['time'] for r in audits()] or [0])
request = ['review', *report['source'], report['review']['commit']]
skill('ALDGUIEnqueue(' + sk(request) + ')')
deadline = time.monotonic() + 120
while True:
    matches = [r for r in audits() if r['time'] > baseline and r['request'] == request]
    if matches:
        result = max(matches, key=lambda r: r['time'])
        assert 'error' not in result, result
        break
    assert time.monotonic() < deadline
    time.sleep(.4)
win, token = result['result']['window'], result['result']['token']
saved = loads(skill(f'ALDGUIStyleData[{sk(token)}]["deleted"]'))
skill(f'ALDGUIStyles(window({win})) ALDGUIStyleForm->aldStyle_deleted_0->value="Magenta" hiFormCancel(ALDGUIStyleForm)')
assert loads(skill(f'ALDGUIStyleData[{sk(token)}]["deleted"]')) == saved
# Window-only changes, no preference writes. Include a group animation.
skill(f'ALDGUIUpdateStyles({sk(token)} list(list("groupChanged" list("Yellow" "Dash-dot" "3" "Blink") nil)))')
phases = set()
for _ in range(8):
    phases.add(skill(f'ALDGUIWindows[window({win})]["groupChanged"]->enable'))
    time.sleep(.18)
assert phases == {'t', 'nil'}
skill(f'ALDGUIToggleGroups(window({win}))')
for _ in range(3):
    time.sleep(.4)
    assert skill(f'ALDGUIWindows[window({win})]["groupChanged"]->enable') == 'nil'
skill(f'ALDGUIToggleGroups(window({win}))')
generation = int(skill('ALDGUIBlinkGeneration'))
skill('ALDGUIRefreshBlink()')
state = skill('list(ALDGUIBlinkGeneration ALDGUIBlinkPhase ALDGUIBlinkScheduled)')
assert skill(f'ALDGUIBlinkTick({generation}) list(ALDGUIBlinkGeneration ALDGUIBlinkPhase ALDGUIBlinkScheduled)') == state
# Close only fresh review_shadows fixtures from this task, never design windows.
closed = loads(skill('''let((closed state)
 foreach(win hiGetWindowList()
  state=ALDGUIWindows[win]
  when(state && state['review] && car(state['source])=="LAYOUT_DIFF_TEST"
       && substring(cadr(state['source]) 1 15)=="review_shadows_"
    closed=cons(win~>windowNum closed) hiCloseWindow(win)))
 ALDGUIAttachAll() closed)'''))
time.sleep(1.2)
assert skill(f'ALDGUIReviews[{sk(token)}]') == 'nil'
# Other open reviews can legitimately keep the shared timer running. Make
# their window-only styles steady for this check; saved preferences stay intact.
skill('''foreach(win hiGetWindowList()
 when(ALDGUIWindows[win] && ALDGUIWindows[win]['review]
  foreach(g ALDGUIHighlightGroups
   let((token data) token=ALDGUIWindows[win]['review] data=ALDGUIStyleData[token][g]
    ALDGUIStyleData[token][g]=list(car(data) cadr(data) caddr(data) "Steady")))))
 ALDGUIRefreshBlink()''')
assert skill('ALDGUIBlinkScheduled') == 'nil'
generation = int(skill('ALDGUIBlinkGeneration'))
skill('ALDRuntimeStop()')
deadline = time.monotonic() + 30
while skill('ALDRuntimeIPC') != 'nil':
    assert time.monotonic() < deadline
    time.sleep(.4)
assert skill('ALDGUIOwner') == 'nil'
assert skill('ALDGUIBlinkScheduled') == 'nil'
skill(f'ALDGUIBlinkTick({generation})')
assert skill('ALDGUIBlinkScheduled') == 'nil'
skill('ALDRuntimeStart()')
deadline = time.monotonic() + 40
while loads(skill('ALDRuntimeState')) != 'Running':
    assert time.monotonic() < deadline
    time.sleep(.4)
atomic_json(out / 'lifecycle.json', dict(cancel_unchanged=True, group_blink=True,
    group_toggle_stays_hidden=True, stale_callback_ignored=True, closed_windows=closed,
    closed_reviews_removed=True, timer_stopped_with_no_active_blink=True,
    stop_invalidates_callback=True, runtime_restarted=True))
print((out / 'lifecycle.json').read_text(), flush=True)
