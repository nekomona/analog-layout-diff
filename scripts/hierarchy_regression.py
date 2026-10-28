"""Live child-only history, nonblocking drift, Git, and hierarchical GDS regression."""
import json
import sys
import uuid
import warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from explore import ROOT
from inventory import LIB
from virtuoso_bridge import VirtuosoClient
from layoutdiff.data.core import diff, digest
from layoutdiff.data.history import History, atomic_json
from layoutdiff.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.virtuoso.dependencies import native_snapshot, dependency_records, DependencyWarning
from layoutdiff.virtuoso.geometry import export, compare_gds
from layoutdiff.git.tools import git, setup, extract
from layoutdiff.virtuoso.sexpr import dumps as sk


def main():
    c = VirtuosoClient.from_env()
    run = uuid.uuid4().hex[:8]
    out = ROOT / "evidence" / ("hierarchy_" + run)
    out.mkdir(parents=True)
    adapter = VirtuosoAdapter(c, out / "raw")
    leaf, child, top = [x + "_" + run for x in ("dep_leaf", "dep_child", "dep_top")]
    with c.layout.create(LIB, leaf) as edit:
        edit.add('dbCreateRect(cv list("MET1" "drawing") list(list(0 0) list(1 1)))')
    with c.layout.create(LIB, child) as edit:
        edit.add(f'dbCreateParamInstByMasterName(cv {sk(LIB)} {sk(leaf)} "layout" "L" list(0 0) "R0")')
    with c.layout.create(LIB, top) as edit:
        edit.add(f'dbCreateParamInstByMasterName(cv {sk(LIB)} {sk(child)} "layout" "C" list(0 0) "R0")')
        edit.add(f'dbCreateParamInstByMasterName(cv {sk(LIB)} {sk(leaf)} "layout" "SHARED" list(5 0) "R0")')
        edit.add(f'dbCreateParamSimpleMosaicByMasterName(cv {sk(LIB)} {sk(child)} "layout" "A" list(0 5) "R90" 2 3 3.0 3.0 nil)')
    history = History(out / "history")
    history.init()
    repo = out / "git-demo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Layout Diff Regression")
    git(repo, "config", "user.email", "layout-diff@example.invalid")
    setup(repo)
    states = []
    head = None
    report = {"library": LIB, "top": top, "child": child, "leaf": leaf, "revisions": []}
    stream_map = out / "stream.map"
    stream_map.write_bytes(b"MET1 drawing 1 0\nMET2 drawing 2 0\n")
    for step in range(3):
        if step:
            target = leaf if step == 1 else child
            with c.layout.modify(LIB, target) as edit:
                edit.add(f'dbCreateRect(cv list("MET2" "drawing") list(list({step} 2) list({step+1} 3)))')
        snapshot = adapter.capture(LIB, top)
        assert len(dependency_records(snapshot)) == 2
        assert all(r["fingerprint"]["status"] == "ok" for r in dependency_records(snapshot).values())
        if states:
            assert native_snapshot(snapshot) == native_snapshot(states[0])
            changes = diff(states[-1], snapshot)["operations"]
            assert len(changes) == 1 and changes[0]["key"].startswith("dependency:")
        commit = history.commit(snapshot, "initial" if not step else f"child-only change {step}", expected_head=head)
        head = commit["id"]
        assert history.replay() == snapshot
        atomic_json(repo / "top.layout.json", snapshot)
        atomic_json(out / f"revision{step}.layout.json", snapshot)
        git(repo, "add", ".gitattributes", "top.layout.json")
        git(repo, "commit", "-m", f"revision {step}")
        states.append(snapshot)
        report["revisions"].append({"step": step, "commit": head, "digest": digest(snapshot)})
        if step == 0:
            export(c, LIB, top, out / "historical.gds", stream_map)
        print("PASS hierarchy capture", step, flush=True)
    assert adapter.check_dependencies(states[-1]) == []
    old = extract(repo, "HEAD~2", "top.layout.json", out / "from-git.layout.json")
    assert old == states[0]
    patch = git(repo, "log", "-p", "--textconv", "--", "top.layout.json").decode()
    (out / "git-log.txt").write_text(patch, encoding="utf-8")
    assert "fingerprint =" in patch
    destination = "dep_rebuilt_" + run
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DependencyWarning)
        actual = adapter.reconstruct(old, LIB, destination)
    assert native_snapshot(actual) == native_snapshot(old)
    assert len(adapter.last_dependency_warnings) == 2
    assert len(captured) == 2
    assert dependency_records(actual) == dependency_records(states[-1])
    report["drift_warnings"] = adapter.last_dependency_warnings
    report["old_revision_restore_succeeded"] = True
    report["destination"] = destination
    # Old histories have no dependency records and must retain their old equality.
    legacy = native_snapshot(old)
    assert adapter.reconstruct(legacy, LIB, "dep_legacy_" + run) == legacy
    report["legacy_restore_equal"] = True
    export(c, LIB, top, out / "current.gds", stream_map)
    export(c, LIB, destination, out / "restored.gds", stream_map)
    current_xor = compare_gds(out / "current.gds", out / "restored.gds", left_top=top, right_top=destination)
    historical_xor = compare_gds(out / "historical.gds", out / "restored.gds", left_top=top, right_top=destination)
    assert current_xor["equal"] and current_xor["has_geometry"]
    assert not historical_xor["equal"] and historical_xor["has_geometry"]
    report["current_gds_xor"] = current_xor
    report["historical_gds_xor"] = historical_xor
    # Existing demo includes PCells and PCell mosaics. Fingerprint the definition once.
    pcell = adapter.capture(LIB, "DEMO_layout_diff")
    assert len([r for r in dependency_records(pcell).values() if r["pcell"]]) == 1
    assert adapter.check_dependencies(pcell) == []
    report["pcell_definition_deduplicated"] = True
    atomic_json(out / "report.json", report)
    print("PASS hierarchy/Git/GDS regression", out, flush=True)


if __name__ == "__main__":
    main()
