from layoutdiff import gitcommit as gc
from layoutdiff.browser import HistoryBrowser, field_text, diff_html
from layoutdiff.core import canonicalize
from layoutdiff.history import History


def test_git_browser_metadata_files_counts_and_readonly(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    gc.git(repo, "init")
    gc.git(repo, "config", "user.name", "Browser Test")
    gc.git(repo, "config", "user.email", "browser@example.invalid")
    identity = ["TEST", "browser", "layout"]
    first = canonicalize([{"kind": "cell", "name": "", "props": [["version", "int", 1]]}])
    second = canonicalize([{"kind": "cell", "name": "", "props": [["version", "int", 2]]},
                           {"kind": "rect", "bBox": [[0, 0], [10, 10]]}])
    a = gc.commit(gc.prepare(repo, identity, first), "Initial geometry")
    b = gc.commit(gc.prepare(repo, identity, second), "Add metal\n\nExplain the change")
    index = (repo / ".git/index").read_bytes()
    model = HistoryBrowser(None, identity, repo)
    rows = model.rows()
    assert rows[0][0] == b["git_commit"][:10]
    assert rows[0][2] == "Browser Test"
    assert rows[0][3] != "Not recorded"
    assert rows[0][-4:] == [1, 1, 0, 0]
    detail = model.detail(b["git_commit"])
    assert len(detail["files"]) == 1
    assert {f["status"] for f in detail["files"]} == {"M"}
    assert all(f["added"].isdigit() and f["deleted"].isdigit() for f in detail["files"])
    i = next(i for i, f in enumerate(detail["files"]) if f["path"].endswith("layout.layout.json"))
    assert "+" in model.file_patch(detail, i) and "rect" in model.file_patch(detail, i)
    assert "Cellview properties" in detail["patch"]
    assert "version" in "".join(model.categories(b["git_commit"]).full())
    assert len(model.detail(a["git_commit"])["files"]) == 2
    assert (repo / ".git/index").read_bytes() == index
    assert not gc.git(repo, "status", "--porcelain").stdout


def test_standalone_and_empty_history_do_not_invent_git_metadata(tmp_path):
    identity = ["TEST", "local", "layout"]
    history = History(tmp_path / "history")
    empty = HistoryBrowser(history, identity)
    assert empty.rows() == [] and not history.path.exists()
    history.init()
    commit = history.commit(canonicalize([{"kind": "cell", "name": ""}]), "Local checkpoint")
    model = HistoryBrowser(history, identity)
    assert model.rows()[0][2:4] == ["Local history", "Not recorded"]
    detail = model.detail(commit["id"])
    assert not detail["git"]
    assert "(empty)" in model.file_patch(detail, 0)
    assert "Local checkpoint" in model.file_patch(detail, 1)


def test_large_unicode_browser_text_respects_native_byte_limit():
    text = field_text("\u6d4b\u8bd5" * 20000)
    assert len(text.encode("utf-8")) < 8191
    assert "Open full diff" in text


def test_diff_markup_is_display_only_even_for_skill_links_in_layout_text():
    result = diff_html('+<a href="SKILL:danger()">literal</a>\n-old\n@@header')
    assert '<a href=' not in result
    assert '&lt;a href=' in result
    assert '#e5f4e9' in result and '#fdeaea' in result and '#edf3f8' in result
