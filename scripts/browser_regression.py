"""Native Git-style browser regression, limited to the dedicated test library."""
import json
from pathlib import Path
import shlex
import sys
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.eda.virtuoso.adapter import checked, VirtuosoAdapter
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.data.history import atomic_json
from layoutdiff.data.core import digest

project = Path(__file__).resolve().parents[1]
out = project / "evidence/git-snapshots"
out.mkdir(parents=True, exist_ok=True)
c = VirtuosoClient.from_env()
def skill(code):
    result = c.execute_skill("progn(" + code + ")", timeout=45)
    assert not result.warnings, result
    return checked(result)
def shell(code):
    result = c.ssh_runner.run_command(code, timeout=45)
    assert result.returncode == 0, result
    return result.stdout
root = loads(skill("ALDRuntimeRoot"))
def audits():
    code = "import pathlib,json; print(json.dumps([json.loads(p.read_text()) for p in pathlib.Path(" + repr(root + "/requests") + ").glob('*.json')]))"
    return json.loads(shell("python3 -c " + shlex.quote(code)))
def request(code, command):
    baseline = max([r["time"] for r in audits()] or [0])
    skill(code)
    for _ in range(100):
        rows = [r for r in audits() if r["time"] > baseline and r["request"][0] == command]
        if rows:
            row = max(rows, key=lambda r: r["time"])
            assert "error" not in row, row
            return row["result"]
        time.sleep(.25)
    raise RuntimeError("No response: " + command)
def screenshot(name):
    remote = root + "/browser-" + name + ".png"
    skill(f'hiWindowSaveImage(?target ALDGUIHistoryForm ?path {sk(remote)} ?format "png" ?toplevel t)')
    checked(c.download_file(remote, str(out / (name + ".png"))))

assert loads(skill("ALDRuntimeState")) == "Running"
assert skill("ALDRuntimeMenu->aldBrowser") != "nil"
lib, cell = "LAYOUT_DIFF_TEST", "git_browser_" + uuid.uuid4().hex[:8]
identity = [lib, cell, "layout"]
with c.layout.create(lib, cell) as edit:
    for x in (0, 3, 6):
        edit.add(f'dbCreateRect(cv list("MET1" "drawing") list(list({x} 0) list({x+2} 1)))')
    edit.add('dbReplaceProp(cv "stage" "string" "placement")')
win = int(skill(f'deOpenCellView({sk(lib)} {sk(cell)} "layout" "maskLayout" nil "a")~>windowNum'))
def commit(message):
    request(f"ALDGUIQuickSave(window({win}))", "quick-preview")
    return request(f'ALDGUIQuickForm->aldMessage->value={sk(message)} hiFormDone(ALDGUIQuickForm)', "quick-commit")
first = commit("Place initial metal geometry")
with c.layout.modify(lib, cell) as edit:
    edit.add('dbReplaceProp(cv "stage" "string" "routing")')
    edit.add('dbDeleteObject(car(setof(s cv~>shapes car(car(s~>bBox))==6)))')
    edit.add('dbCreatePath(cv list("MET2" "drawing") list(0:3 4:3 4:2) 0.4)')
second = commit("Add route, remove spare metal, update stage")
rows = request(f"ALDGUIHistory(window({win}))", "history")
assert len(rows) == 2
assert loads(skill("ALDGUIHistoryForm->aldCommits->choices"))[0][-3:] == [1, 1, 1]
assert len(loads(skill("ALDGUIHistoryForm->aldFiles->choices"))) == 1
assert "Layout:" in loads(skill("ALDGUIHistoryForm->aldSummary->value"))
assert "#e5f4e9" in loads(skill("ALDGUIHistoryForm->aldPatch->value"))
screenshot("main")
old = request("hiReportSelectItem(ALDGUIHistoryForm->aldCommits 1 t)", "browser-select")
assert old["id"] == first["git_commit"] and len(old["files"]) == len(first["files"])
latest = request("hiReportSelectItem(ALDGUIHistoryForm->aldCommits 0 t)", "browser-select")
assert latest["counts"] == {"added": 1, "modified": 1, "deleted": 1}
file_index = next(i for i, f in enumerate(latest["files"]) if f["path"] == second["snapshot_path"])
selected = request(f"hiReportSelectItem(ALDGUIHistoryForm->aldFiles {file_index} t)", "browser-file")
assert selected["path"] == second["snapshot_path"]
assert "diff --git" in loads(skill("ALDGUIHistoryForm->aldPatch->value"))
screenshot("file-diff")
full = int(skill('ALDGUIBrowserFull(ALDGUIHistoryForm)~>windowNum'))
skill(f"hiCloseWindow(window({full}))")
request("ALDGUIBrowserSemantic(ALDGUIHistoryForm)", "browser-file")
before = loads(skill("ALDGUIHistoryForm->aldPatch->value"))
skill('ALDGUIBrowserPatch("expired" "expired" 0 "wrong" "wrong" "wrong")')
assert loads(skill("ALDGUIHistoryForm->aldPatch->value")) == before
review = request("ALDGUIHistoryCB(ALDGUIHistoryForm)", "review")
adapter = VirtuosoAdapter(c, out / "capture")
assert adapter.capture(*identity) == adapter.capture(lib, review["cell"])
skill(f'hiCloseWindow(window({review["window"]}))')
local_sources = loads(skill("ALDGUIHistoryForm->aldSources"))
local_index = next(i for i, x in enumerate(local_sources) if x[1].startswith("runtime_source_"))
local_history = request(f"hiReportSelectItem(ALDGUIHistoryForm->aldLayouts {local_index} t)", "history")
assert local_history and "Local history" in loads(skill("ALDGUIHistoryForm->aldCommits->choices"))[0]
request(f"ALDGUIHistory(window({win}))", "history")
request("ALDGUIBrowserSave(ALDGUIHistoryForm)", "quick-preview")  # saved/no-change path
assert "No changes" in loads(skill("ALDGUIResultForm->aldResult->value"))
skill("hiFormCancel(ALDGUIResultForm)")
request("ALDGUIBrowserRefresh(ALDGUIHistoryForm)", "browser")
assert loads(skill("ALDGUIHistoryForm->aldSelectedCommit")) == second["git_commit"]
screenshot("main")
repo = second["repository"]
git = "git -C " + shlex.quote(repo) + " "
# The older Git payload remains browseable without its custom commit IDs.
legacy = json.loads((project / "evidence/browser/report.json").read_text())
legacy_identity = legacy["source"]
assert legacy_identity[0] == lib
legacy_win = int(skill(f'deOpenCellView({sk(lib)} {sk(legacy_identity[1])} "layout" "maskLayout" nil "a")~>windowNum'))
legacy_tree = ".layoutdiff/histories/" + digest(legacy_identity)
old_tree = shell(git + "rev-parse " + shlex.quote("HEAD:" + legacy_tree)).strip()
old_head = shell(git + "rev-parse HEAD").strip()
legacy_rows = request(f"ALDGUIHistory(window({legacy_win}))", "history")
assert legacy_rows[0]["id"] == legacy["second"]["git_commit"]
request(f"ALDGUIQuickSave(window({legacy_win}))", "quick-preview")
assert "Adopt snapshot storage" in loads(skill("ALDGUIQuickForm->aldSummary->value"))
request("hiFormCancel(ALDGUIQuickForm)", "quick-cancel")
assert shell(git + "rev-parse HEAD").strip() == old_head
request(f"ALDGUIQuickSave(window({legacy_win}))", "quick-preview")
adopted = request('ALDGUIQuickForm->aldMessage->value="Adopt canonical Git snapshot storage" hiFormDone(ALDGUIQuickForm)', "quick-commit")
assert all(path.startswith("layouts/") for path in adopted["files"])
assert shell(git + "rev-parse " + shlex.quote("HEAD:" + legacy_tree)).strip() == old_tree
adopted_rows = request(f"ALDGUIHistory(window({legacy_win}))", "history")
assert len(adopted_rows) == len(legacy_rows) + 1
assert loads(skill("ALDGUIHistoryForm->aldCommits->choices"))[0][-3:] == [0, 0, 0]
legacy_detail = request("hiReportSelectItem(ALDGUIHistoryForm->aldCommits 1 t)", "browser-select")
assert legacy_detail["id"] == legacy["second"]["git_commit"]
old_review = request("ALDGUIHistoryCB(ALDGUIHistoryForm)", "review")
assert adapter.capture(*legacy_identity) == adapter.capture(lib, old_review["cell"])
skill(f'hiCloseWindow(window({old_review["window"]}))')
screenshot("legacy-history")
# Runtime panel has the same save/preview flow; no standalone writer remains.
skill(f'ALDRuntimePanel() ALDRuntimeForm->aldLib->value={sk(lib)} '
      f'ALDRuntimeForm->aldCell->value={sk(cell)} ALDRuntimeForm->aldView->value="layout"')
panel = request('ALDRuntimeRequest("commit")', "quick-preview")
assert panel["no_changes"]
skill("hiFormCancel(ALDGUIResultForm) hiFormCancel(ALDRuntimeForm)")
request(f"ALDGUIHistory(window({win}))", "history")
screenshot("main")
assert not shell("git -C " + shlex.quote(repo) + " status --porcelain").strip()
assert loads(skill("ALDRuntimeState")) == "Running"
atomic_json(out / "report.json", {"source": identity, "window": win, "first": first, "second": second,
    "counts": latest["counts"], "files": latest["files"], "history_selection": True,
    "file_selection": True, "full_diff_viewer": True, "escaped_colored_diff": True,
    "stale_response_ignored": True, "review_native_equal": True, "standalone_history": True,
    "browser_save_no_change": True, "refresh": True, "git_status_clean": True, "runtime_running": True,
    "legacy_adoption": adopted, "legacy_tree_unchanged": True, "legacy_cancel_unchanged": True,
    "legacy_git_revision_review_equal": True, "runtime_save_uses_git": True,
    "git_commit_ids_only": True, "latest_affected_files": 1})
print("PASS native Git snapshots, legacy adoption/cancel/review, Git IDs, single-file commits, browser and runtime save flow")
