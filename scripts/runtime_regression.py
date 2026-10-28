"""Exercise the installed SKILL-owned runtime through its real GUI callbacks."""
import json
import shlex
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.virtuoso.sexpr import loads, dumps as sk
from layoutdiff.data.history import atomic_json

PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "evidence/runtime"
OUT.mkdir(parents=True, exist_ok=True)
c = VirtuosoClient.from_env()
def skill(text):
    return checked(c.execute_skill("progn(" + text + ")", timeout=120))
remote_root = loads(skill("ALDRuntimeRoot"))
def remote_json(relative):
    response = c.ssh_runner.run_command("cat " + shlex.quote(remote_root + "/" + relative))
    if response.returncode:
        raise RuntimeError(response.stderr)
    return json.loads(response.stdout)

def audits():
    command = "import pathlib,json; print(json.dumps([json.loads(p.read_text()) for p in pathlib.Path(" + repr(remote_root + "/requests") + ").glob('*.json')]))"
    response = c.ssh_runner.run_command("python3 -c " + shlex.quote(command))
    return json.loads(response.stdout)

def callback(expression, command):
    baseline = max([a["time"] for a in audits()] or [0])
    skill(expression)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        matches = [a for a in audits() if a["time"] > baseline and a["request"][0] == command]
        if matches:
            result = max(matches, key=lambda a: a["time"])
            assert "error" not in result, result
            return result["result"]
        time.sleep(.4)
    raise RuntimeError("No completed callback: " + command + " / " + skill("list(ALDRuntimeState ALDRuntimeLog)"))

def wait_state(state):
    for _ in range(50):
        if loads(skill("ALDRuntimeState")).startswith(state):
            return
        time.sleep(.3)
    raise RuntimeError("Runtime did not reach " + state)

wait_state("Running")
initial_runtime = remote_json("runtime.json")
run = uuid.uuid4().hex[:8]
lib, cell = "LAYOUT_DIFF_TEST", "runtime_source_" + run
identity = [lib, cell, "layout"]
adapter = VirtuosoAdapter(c, OUT / "capture")
with c.layout.create(lib, cell) as edit:
    for x in (0, 3, 6):
        edit.add(f'dbCreateRect(cv list("MET1" "drawing") list(list({x} 0) list({x+2} 1)))')
source_win = int(skill(f'deOpenCellView({sk(lib)} {sk(cell)} "layout" "maskLayout" nil "a")~>windowNum'))
skill('ALDRuntimePanel()')
skill(f'ALDRuntimeForm->aldLib->value={sk(lib)} ALDRuntimeForm->aldCell->value={sk(cell)} ALDRuntimeForm->aldView->value="layout"')
callback('ALDRuntimeRequest("commit")', "quick-preview")
first = callback('ALDGUIQuickForm->aldMessage->value="Runtime initial" hiFormDone(ALDGUIQuickForm)', "quick-commit")
with c.layout.modify(lib, cell) as edit:
    edit.add('let((o) o=car(setof(s cv~>shapes car(car(s~>bBox))==3)) dbReplaceProp(o "reviewNote" "string" "runtime change") o=car(setof(s cv~>shapes car(car(s~>bBox))==6)) dbDeleteObject(o))')
    edit.add('dbCreatePath(cv list("MET2" "drawing") list(list(0 3) list(4 3) list(4 2)) 0.4)')
callback('ALDRuntimeRequest("commit")', "quick-preview")
second = callback('ALDGUIQuickForm->aldMessage->value="Runtime property/add/remove" hiFormDone(ALDGUIQuickForm)', "quick-commit")
source = adapter.capture(*identity)
commits = callback('ALDRuntimeRequest("history")', "history")
assert len(commits) == 2
assert commits[0]["id"] == second["git_commit"] and commits[0]["parent"] == first["git_commit"]
review = callback('ALDGUIHistoryCB(ALDGUIHistoryForm)', "review")
assert review["counts"] == {"untouched": 1, "changed": 1, "new": 1}, review
win = review["window"]
assert loads(skill(f'geGetWindowCellView(window({win}))~>mode')) == "r"
assert adapter.capture(lib, review["cell"]) == source == adapter.capture(*identity)
for group in ("untouched", "changed", "new"):
    skill(f'ALDGUIToggle(window({win}) {sk(group)})')
    assert skill(f'ALDGUIWindows[window({win})][{sk(group)}]->enable') == "nil"
    skill(f'ALDGUIToggle(window({win}) {sk(group)})')
skill(f'ALDGUIStyles(window({win}))')
callback('ALDGUIStyleForm->aldGroup->value="changed" ALDGUIStyleForm->aldColor->value="Cyan" ALDGUIStyleForm->aldLine->value="Dotted" ALDGUIStyleForm->aldWidth->value="3" ALDGUIStyleCB(ALDGUIStyleForm)', "style")
skill('hiFormCancel(ALDGUIStyleForm) hiFormCancel(ALDGUIHistoryForm)')
for filename, target in (("panel", "ALDRuntimeForm"), ("review", f"window({win})")):
    remote = remote_root + "/" + filename + ".png"
    skill(f'hiWindowSaveImage(?target {target} ?path {sk(remote)} ?format "png" ?toplevel t)')
    checked(c.download_file(remote, str(OUT / (filename + ".png"))))
skill(f'hiCloseWindow(window({win}))')  # Only this test's own review window.
cleanup = callback('ALDGUIEnqueue(list("cleanup"))', "cleanup")
assert next(row for row in cleanup if row["cell"] == review["cell"])["status"] == "deleted"
skill('ALDRuntimeStop()')
wait_state("Stopped")
stopped = remote_json("runtime.json")
assert stopped["reason"] == "gui-stop", stopped
assert skill("ALDGUIOwner") == "nil"
assert skill("ALDRuntimeMenu") != "nil"  # Persistent entry point survives stop.
skill('ALDRuntimeStart()')
wait_state("Running")
started = remote_json("runtime.json")
assert started["worker_pid"] != initial_runtime["worker_pid"]
skill('ALDRuntimeRestart()')
time.sleep(.5)
wait_state("Running")
restarted = remote_json("runtime.json")
assert restarted["worker_pid"] != started["worker_pid"]
assert len(callback('ALDRuntimeRequest("history")', "history")) == 2
final_review = callback('ALDGUIHistoryCB(ALDGUIHistoryForm)', "review")
assert adapter.capture(*identity) == source
callback('ALDGUIEnqueue(list("sources"))', "sources")
skill('hiFormCancel(ALDGUIHistoryForm) ALDRuntimePanel()')
atomic_json(OUT / "live-report.json", {"source": identity, "first": first["id"], "second": second["id"],
    "review": final_review, "initial_runtime": initial_runtime, "stopped": stopped,
    "started": started, "restarted": restarted, "source_unchanged": True,
    "gui_commit_history_review": True, "read_only_review": True, "highlight_toggles": 3,
    "style_callback": True, "cleanup": cleanup, "history_survives_restart": True})
print("PASS SKILL-owned startup, commits, history, review, styles, cleanup, stop, start, restart")
