"""Live save/preview/Cancel/Enter/OK/Git regression, confined to owned fixtures."""
import json
import argparse
import shlex
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso import x11
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.data.history import atomic_json

PROJECT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", default="evidence/quick-commit")
OUT = PROJECT / parser.parse_args().output
OUT.mkdir(parents=True, exist_ok=True)
c = VirtuosoClient.from_env()
def skill(expr):
    return checked(c.execute_skill("progn(" + expr + ")", timeout=45))
def shell(command):
    r = c.ssh_runner.run_command(command, timeout=45)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout
root = loads(skill("ALDRuntimeRoot"))
repo = root.rsplit("/", 2)[0] + "/analog_layout_diff_git"
def audits():
    code = "import pathlib,json; print(json.dumps([json.loads(p.read_text()) for p in pathlib.Path(" + repr(root + "/requests") + ").glob('*.json')]))"
    return json.loads(shell("python3 -c " + shlex.quote(code)))
def request(expr, command, *, expect_error=None):
    baseline = max([a["time"] for a in audits()] or [0])
    skill(expr)
    return await_result(command, baseline, expect_error=expect_error)
def await_result(command, baseline, *, expect_error=None):
    for _ in range(80):
        rows = [a for a in audits() if a["time"] > baseline and a["request"][0] == command]
        if rows:
            row = max(rows, key=lambda a: a["time"])
            if expect_error:
                assert expect_error in row.get("error", ""), row
                return row
            assert "error" not in row, row
            return row["result"]
        time.sleep(.25)
    raise RuntimeError("No completed request: " + command + " / " + skill("ALDRuntimeState"))
def screenshot(name, target):
    remote = root + "/" + name + ".png"
    skill(f'hiWindowSaveImage(?target {target} ?path {sk(remote)} ?format "png" ?toplevel t)')
    checked(c.download_file(remote, str(OUT / (name + ".png"))))
def head():
    r = c.ssh_runner.run_command("git -C " + shlex.quote(repo) + " rev-parse --verify HEAD")
    return r.stdout.strip() if not r.returncode else None

for _ in range(60):
    if loads(skill("ALDRuntimeState")) == "Running":
        break
    time.sleep(.25)
else:
    raise RuntimeError("Runtime failed to start")

run = uuid.uuid4().hex[:8]
lib, cell = "LAYOUT_DIFF_TEST", "quick_source_" + run
identity = [lib, cell, "layout"]
with c.layout.create(lib, cell) as edit:
    edit.add('dbCreateRect(cv list("MET1" "drawing") list(0:0 2:1))')
win = int(skill(f'let((w) w=deOpenCellView({sk(lib)} {sk(cell)} "layout" "maskLayout" nil "a") w~>windowNum)'))
skill("ALDGUIAttachAll()")
skill(f"hiRaiseWindow(window({win})) ALDGUIFit(window({win}))")
key = loads(skill("ALDGUIQuickKey"))
assert key
assert loads(skill(f'hiGetBindKey("Layout" {sk(key)})')) == "ALDGUIQuickSave(hiGetCurrentWindow())"
toolbar = f"ALDGUIWindows[window({win})]['commitToolbar]->aldQuickCommit"
toolbar_callback = loads(skill(toolbar + "->hiCallback"))
assert toolbar_callback == f"ALDGUIQuickSave(window({win}))"
assert key in loads(skill(toolbar + "->hiToolTip"))
screenshot("toolbar", f"window({win})")
# Simulate an unsaved user edit only in the explicitly created fixture.
skill(f'dbReplaceProp(geGetEditCellView(window({win})) "quickNote" "string" "unsaved change")')
assert skill(f'dbIsCellViewModified(geGetEditCellView(window({win})))') == "t"
first_preview = request(toolbar_callback, "quick-preview")
assert skill(f'dbIsCellViewModified(geGetEditCellView(window({win})))') == "nil"
setup_prompt = first_preview.get("needs_repository", False)
if setup_prompt:
    suggested = loads(skill("ALDGUIGitForm->aldRepo->value"))
    assert suggested == loads(skill("getWorkingDir()")).rsplit("/", 1)[0]
    screenshot("initialize-repository", "ALDGUIGitForm")
    # The only repository initialized by this test is the authorized sibling.
    skill(f'ALDGUIGitForm->aldRepo->value={sk(repo)}')
    first_preview = request("hiFormDone(ALDGUIGitForm)", "git-setup")
else:
    assert first_preview["repo"] == repo
assert skill("hiGetCurrentField(ALDGUIQuickForm)") == "aldMessage"
assert "Changes:" in loads(skill("ALDGUIQuickForm->aldSummary->value"))
assert "MET1 shapes" in loads(skill("ALDGUIQuickForm->aldPreview->value"))
screenshot("preview", "ALDGUIQuickForm")
# The complete diff remains accessible through Virtuoso's file viewer.
assert skill("ALDGUIQuickForm->aldPath") == "nil"
request('ALDGUIEnqueue(list("quick-full" ALDGUIQuickForm->aldToken))', "quick-full")
viewer = int(skill('ALDGUIQuickForm->aldFullWindow~>windowNum'))
screenshot("full-diff", f"window({viewer})")
skill(f"hiCloseWindow(window({viewer}))")
before_cancel = head()
request("hiFormCancel(ALDGUIQuickForm)", "quick-cancel")
assert head() == before_cancel
assert skill(f'dbIsCellViewModified(geGetEditCellView(window({win})))') == "nil"

# Unrelated staged content must remain outside the layout commit.
unrelated = "unrelated-staged-" + run + ".txt"
shell("printf 'unrelated staged work' > " + shlex.quote(repo + "/" + unrelated))
shell("git -C " + shlex.quote(repo) + " add -- " + shlex.quote(unrelated))
staged_before = shell("git -C " + shlex.quote(repo) + " ls-files --stage -- " + shlex.quote(unrelated))
shortcut_callback = loads(skill(f'hiGetBindKey("Layout" {sk(key)})'))
skill(f"hiSetCurrentWindow(window({win}))")
request(shortcut_callback, "quick-preview")
skill('ALDGUIQuickForm->aldMessage->value="Quick commit via Enter"')
assert skill("hiGetCurrentField(ALDGUIQuickForm)") == "aldMessage"
baseline = max(a["time"] for a in audits())
runner = c.docs_runner
matches = [w for w in x11.list_windows(runner, runner.user, top_level=True)
           if w.get("title") == "Layout Diff - Save & Commit to Git"]
assert len(matches) == 1, matches
window = matches[0]
sent = x11.dismiss_window(runner, runner.user, window["dismiss_id"], display=window["display"], action="enter")
first = await_result("quick-commit", baseline)
assert head() == first["git_commit"]
assert shell("git -C " + shlex.quote(repo) + " ls-files --stage -- " + shlex.quote(unrelated)) == staged_before
assert unrelated not in shell("git -C " + shlex.quote(repo) + " show --pretty= --name-only HEAD").splitlines()
no_changes = request(f"ALDGUIQuickSave(window({win}))", "quick-preview")
assert no_changes["no_changes"]
skill("hiFormCancel(ALDGUIResultForm)")

# Reject edits made after preview; the stale version must never enter Git.
skill(f'dbReplaceProp(geGetEditCellView(window({win})) "quickNote" "string" "second version")')
request(f"ALDGUIQuickSave(window({win}))", "quick-preview")
saved_head = head()
skill(f'dbReplaceProp(geGetEditCellView(window({win})) "quickNote" "string" "edited after preview")')
request('ALDGUIQuickForm->aldMessage->value="stale" hiFormDone(ALDGUIQuickForm)', "quick-commit", expect_error="changed after preview")
assert head() == saved_head
skill("hiFormCancel(ALDGUIResultForm)")
request(f"ALDGUIQuickSave(window({win}))", "quick-preview")
second = request('ALDGUIQuickForm->aldMessage->value="Quick commit via OK" hiFormDone(ALDGUIQuickForm)', "quick-commit")
assert second["git_commit"] != first["git_commit"]

# Git-backed history must be available through the existing History/Review UI.
history = request(f"ALDGUIHistory(window({win}))", "history")
assert len(history) == 2
review = request("ALDGUIHistoryCB(ALDGUIHistoryForm)", "review")
adapter = VirtuosoAdapter(c, OUT / "capture")
assert adapter.capture(*identity) == adapter.capture(lib, review["cell"])
skill("hiFormCancel(ALDGUIHistoryForm)")
# Restore the unrelated regression file to its absent baseline, without touching others.
shell("git -C " + shlex.quote(repo) + " reset --quiet HEAD -- " + shlex.quote(unrelated))
shell("rm -- " + shlex.quote(repo + "/" + unrelated))
atomic_json(OUT / "report.json", {"source": identity, "window": win, "repository": repo,
    "shortcut": key, "toolbar_callback": toolbar_callback, "shortcut_callback": shortcut_callback,
    "full_diff_viewer": True, "save_before_preview": True, "init_prompt": setup_prompt,
    "message_field_focus": True, "cancel_did_not_commit": True, "physical_enter": sent,
    "first": first, "second": second, "ok_callback": True, "stale_preview_rejected": True,
    "unrelated_staged_work_preserved": True, "no_change_detected": True,
    "git_history_review_equal": True, "review": review})
print("PASS save-first, repository prompt, focus, Cancel, physical Enter, OK, stale rejection, Git isolation and review")
