"""Live GUI net-only classification, group outlines/toggles and blink controls."""
import json
from pathlib import Path
import shlex
import sys
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.eda.virtuoso.sexpr import loads, dumps as sk
from layoutdiff.data.core import digest
from layoutdiff.comparison.review import classify
from layoutdiff.data.history import atomic_json

project = Path(__file__).resolve().parents[1]
out = project / 'evidence/review-controls'
out.mkdir(parents=True, exist_ok=True)
c = VirtuosoClient.from_env()
lib = 'LAYOUT_DIFF_TEST'
cell = 'review_controls_' + uuid.uuid4().hex[:8]
identity = [lib, cell, 'layout']
adapter = VirtuosoAdapter(c, out / 'capture')

def skill(code):
    result = c.execute_skill('progn(' + code + ')', timeout=120)
    assert not result.warnings, result
    return checked(result)

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
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        rows = [r for r in audits() if r['time'] > baseline and r['request'][0] == name]
        if rows:
            entry = max(rows, key=lambda r: r['time'])
            atomic_json(out / (name + '-last.json'), entry)
            assert 'error' not in entry, entry
            return entry['result']
        time.sleep(.4)
    raise TimeoutError(name)

def commit(message):
    preview = request('ALDGUIEnqueue(' + sk(['quick-preview', *identity]) + ')', 'quick-preview')
    summary = loads(skill('ALDGUIQuickForm->aldPreview->value'))
    result = request('ALDGUIEnqueue(' + sk(['quick-commit', preview['token'], message]) + ')', 'quick-commit')
    skill('hiFormCancel(ALDGUIQuickForm)')
    return result, summary

assert loads(skill('ALDRuntimeState')) == 'Running'
old_status = shell('git -C ' + shlex.quote(repo) + ' status --porcelain')
with c.layout.create(lib, cell) as edit:
    edit.add('let((n p o g lg) n=dbCreateNet(cv "N") p=dbCreateNet(cv "P")')
    for x in (0, 4, 8, 12, 16, 20):
        edit.add(f'o=dbCreateRect(cv list("MET1" "drawing") list(list({x} 0) list({x+2} 2)))')
        if x < 12:
            edit.add('dbAddFigToNet(o n)')
        if x == 12:
            edit.add('g=dbCreateFigGroup(cv "modify" nil 0:0 "R0") dbAddFigToFigGroup(g o) '
                     'lg=dbCreateGroup(cv "logical" list("set" "unordered" "uniqueName" "deleteNever")) dbAddObjectToGroup(lg o)')
        if x == 16:
            edit.add('g=dbCreateFigGroup(cv "delete" nil 0:0 "R0") dbAddFigToFigGroup(g o)')
    edit.add('dbCreateGroup(cv "empty" list("set" "unordered" "uniqueName" "deleteNever")) t)')
before = adapter.capture(lib, cell)
first, _ = commit('Review controls fixture: initial')
with c.layout.modify(lib, cell) as edit:
    edit.add('let((o g) dbReplaceProp(dbFindNetByName(cv "N") "note" "string" "net metadata") '
             'o=car(setof(s cv~>shapes s~>objType=="rect" && caar(s~>bBox)==4.0)) dbReplaceProp(o "tag" "int" 1) '
             'o=car(setof(s cv~>shapes s~>objType=="rect" && caar(s~>bBox)==8.0)) dbAddFigToNet(o dbFindNetByName(cv "P")) '
             'g=car(setof(g cv~>figGroups g~>name=="modify")) dbReplaceProp(g "edit" "int" 1) '
             'g=car(setof(g cv~>figGroups g~>name=="delete")) dbDeleteObject(g) '
             'g=dbCreateFigGroup(cv "add" nil 0:0 "R0") '
             'o=car(setof(s cv~>shapes s~>objType=="rect" && caar(s~>bBox)==20.0)) dbAddFigToFigGroup(g o) '
             'dbReplaceProp(dbGetGroupByName(cv "logical") "edit" "int" 1) '
             'dbReplaceProp(dbGetGroupByName(cv "empty") "edit" "int" 1) '
             'dbCreateRect(cv list("MET1" "drawing") list(24:0 26:2)) t)')
after = adapter.capture(lib, cell)
expected = classify(before, after)
assert expected['counts'] == dict(untouched=3, changed=1, netChanged=2, new=1), expected
second, preview = commit('Review controls fixture: nets, groups and ordinary edits')
assert 'Modified net / MET1 shapes' in preview and 'Group membership / MET1 shapes' in preview
history = request('ALDGUIEnqueue(' + sk(['history', *identity]) + ')', 'history')
review = request('ALDGUIEnqueue(' + sk(['review', *identity, second['git_commit']]) + ')', 'review')
assert review['counts'] == expected['counts']
assert not review['boundary_warnings'], review
bounds = {r['name']: r for r in review['group_boundaries']}
assert bounds['add']['bBox'] == [[20, 0], [22, 2]] and bounds['add']['status'] == 'new'
assert bounds['modify']['bBox'] == [[12, 0], [14, 2]] and bounds['modify']['status'] == 'changed'
assert bounds['logical']['bBox'] == [[12, 0], [14, 2]] and bounds['logical']['status'] == 'changed'
assert bounds['delete']['bBox'] == [[16, 0], [18, 2]] and bounds['delete']['side'] == 'before'
assert bounds['empty']['bBox'] is None
win, token = review['window'], review['token']
saved_styles = loads(skill(f'foreach(mapcar group ALDGUIHighlightGroups cons(group ALDGUIStyleData[{sk(token)}][group]))'))
request('ALDGUIEnqueue(' + sk(['styles', token, [r[:4] + ['Steady'] for r in saved_styles]]) + ')', 'styles')
for group in ('untouched', 'changed', 'netChanged', 'new', 'groupNew', 'groupChanged', 'groupDeleted'):
    assert skill(f'ALDGUIWindows[window({win})][{sk(group)}]->enable') == 't'
skill(f'ALDGUIToggleGroups(window({win}))')
for group in ('groupNew', 'groupChanged', 'groupDeleted'):
    assert skill(f'ALDGUIWindows[window({win})][{sk(group)}]->enable') == 'nil'
assert skill(f'ALDGUIWindows[window({win})]["netChanged"]->enable') == 't'
skill(f'ALDGUIToggleGroups(window({win})) ALDGUIToggle(window({win}) "netChanged")')
assert skill(f'ALDGUIWindows[window({win})]["netChanged"]->enable') == 'nil'
skill(f'ALDGUIToggle(window({win}) "netChanged") ALDGUIStyles(window({win}))')
saved_style = loads(skill(f'ALDGUIStyleData[{sk(token)}]["netChanged"]'))
request('ALDGUIStyleForm->aldStyle_netChanged_3->value="Blink" ALDGUIStyleCB(ALDGUIStyleForm)', 'styles')
color = loads(skill('drGetColor("display" ' + sk('ALD' + token + 'netChangedColor') + ')'))
assert color[-1] is None, color  # Animation is owned by the window timer.
phases = set()
for _ in range(8):
    phases.add(skill(f'ALDGUIWindows[window({win})]["netChanged"]->enable'))
    time.sleep(.2)
assert phases == {'t', 'nil'}, phases
skill(f'ALDGUIToggle(window({win}) "netChanged")')
assert skill(f'ALDGUIWindows[window({win})]["netChanged"]->enable') == 'nil'
skill(f'ALDGUIToggle(window({win}) "netChanged")')
for target, name in [('ALDGUIStyleForm', 'style'), (f'window({win})', 'review'), ('ALDGUIHistoryForm', 'history')]:
    remote = root + '/review-controls-' + name + '.png'
    skill(f'hiWindowSaveImage(?target {target} ?path {sk(remote)} ?format "png" ?toplevel t)')
    checked(c.download_file(remote, str(out / (name + '.png'))))
assert digest(adapter.capture(lib, review['cell'])) == digest(after)
assert digest(adapter.capture(lib, cell)) == digest(after)
assert shell('git -C ' + shlex.quote(repo) + ' status --porcelain') == old_status
report = dict(source=identity, commits=[first, second], review=review, blink_color_readback=color,
              groups_toggle_verified=True, net_toggle_verified=True, native_after_unchanged=True,
              source_unchanged_by_review=True, git_status_preserved=True, old_net_style=saved_style)
atomic_json(out / 'native-report.json', report)
# Restore the user's previous animation preference after verifying Blink.
request('ALDGUIEnqueue(' + sk(['styles', token, saved_styles]) + ')', 'styles')
skill('hiFormCancel(ALDGUIStyleForm)')
print(json.dumps(report, indent=2), flush=True)
