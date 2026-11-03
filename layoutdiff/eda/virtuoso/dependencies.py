"""External master change hints, kept separate from native top-level equality."""
import json
import shlex
import uuid
import warnings
from pathlib import Path
from layoutdiff.data.core import canonicalize
from layoutdiff.data.history import atomic_json
from layoutdiff.eda.virtuoso.sexpr import loads, dumps as sk
from layoutdiff.eda.virtuoso.paths import scratch


class DependencyWarning(UserWarning):
    pass


def native_snapshot(snapshot):
    return canonicalize([r for r in snapshot["objects"].values() if r["kind"] != "dependency"])


def dependency_records(snapshot):
    return {k: r for k, r in snapshot["objects"].items() if r["kind"] == "dependency"}


def compare_dependencies(expected, current):
    issues = []
    old, new = dependency_records(expected), dependency_records(current)
    for key in sorted(old.keys() | new.keys()):
        a, b = old.get(key), new.get(key)
        reason = None
        if not a:
            reason = "new referenced master"
        elif not b:
            reason = "referenced master unavailable"
        elif a != b:
            reason = "referenced master fingerprint changed"
        elif b["fingerprint"]["status"] != "ok":
            reason = "referenced master fingerprint could not be verified"
        elif a.get("dirty") or b.get("dirty"):
            reason = "referenced master has unsaved edits; saved OA hash is incomplete"
        if reason:
            issues.append({"key": key, "reason": reason, "recorded": a, "current": b})
    return issues


def emit_warnings(issues):
    for issue in issues:
        warnings.warn(issue["key"] + ": " + issue["reason"] +
                      "; replay uses the currently available master", DependencyWarning, stacklevel=2)


class HierarchyReader:
    def __init__(self, client, artifacts, checked):
        self.client, self.artifacts, self.checked = client, Path(artifacts), checked
        self.loaded = False
        self.helper = None

    def read(self, *, root=None, identities=None):
        if not self.loaded:
            self.checked(self.client.load_il((Path(__file__).parent / "skill" / "hierarchy.il")))
            self.loaded = True
        token = uuid.uuid4().hex
        remote = scratch(self.client, "ald_hierarchy_" + token)
        local = self.artifacts / ("hierarchy_" + token + ".sexpr")
        if root:
            expr = "ALDDependencies(" + " ".join(sk(x) for x in root) + " " + sk(remote) + ")"
        else:
            expr = f"ALDCheckDependencies({sk(identities)} {sk(remote)})"
        self.checked(self.client.execute_skill(expr, timeout=120))
        self.client.download_file(remote, str(local))
        raw = [dict(loads(line)) for line in local.read_text(encoding="utf-8").splitlines() if line.strip()]
        paths = sorted({r["path"] for r in raw if r["path"]})
        hashed = {}
        if paths:
            try:
                if getattr(self.client, "layoutdiff_local_files", False):
                    from layoutdiff.eda.virtuoso.hash_views import fingerprint
                    hashed = {p: fingerprint(p) for p in paths}
                elif not self.helper:
                    helper = scratch(self.client, "ald_hash_" + uuid.uuid4().hex + ".py")
                    self.client.upload_file(str(Path(__file__).with_name("hash_views.py")), helper)
                    self.helper = helper
                if not getattr(self.client, "layoutdiff_local_files", False):
                    request = self.artifacts / ("hash_request_" + token + ".json")
                    atomic_json(request, paths)
                    self.client.upload_file(str(request), remote + ".json")
                    result = self.client.ssh_runner.run_command("python3 " + shlex.quote(self.helper) + " " + shlex.quote(remote + ".json"))
                    if result.returncode:
                        raise RuntimeError("Remote hash helper failed")
                    hashed = json.loads(result.stdout)
            except Exception as exc:
                # Missing Python, SSH, or filesystem access cannot prohibit replay.
                warnings.warn("Saved OA hashing unavailable; using timestamp hints: " + str(exc), DependencyWarning)
        records = {}
        for r in raw:
            identity = [r[x] for x in ("libName", "cellName", "viewName")]
            name = json.dumps(identity, ensure_ascii=True, separators=(",", ":"))
            fingerprint = hashed.get(r["path"], {"status": "unavailable"})
            if not r["resolved"]:
                fingerprint = {"status": "unresolved"}
            if fingerprint["status"] != "ok":
                fingerprint = {**fingerprint, "method": "saved-time-hint", "savedTime": r["savedTime"]}
            record = {"kind": "dependency", "name": name,
                      **{k: r[k] for k in ("libName", "cellName", "viewName")},
                      "pcell": bool(r["pcell"]), "fingerprint": fingerprint,
                      "dirty": bool(r["dirty"]), "dirtyCounter": r["dirtyCounter"]}
            if name in records and records[name] != record:
                record["fingerprint"] = {"status": "unstable"}
            records[name] = record
        return list(records.values())
