"""Deploy the host runtime once; startup and every subsequent launch are SKILL-owned."""
import argparse
import json
import shlex
import sys
import tarfile
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient, SSHClient
from layoutdiff.data.history import atomic_json
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.eda.virtuoso.adapter import checked

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, help="Absolute dedicated runtime path on the Virtuoso host")
    parser.add_argument('--profile', help='Explicit Bridge profile for the intended CIW')
    parser.add_argument('--preserve-runtime-settings', action='store_true',
                        help='Retain this CIW runtime root, launch command and pinned bridge port')
    parser.add_argument("--migrate", action="store_true", help="Stop the old Windows worker and copy its histories/settings once")
    parser.add_argument("--native", choices=("auto", "off", "required"), default="auto", help="Build the optional accelerator when a host C++ compiler is available")
    args = parser.parse_args()
    remote = args.destination.rstrip("/")
    if not remote.startswith("/") or any(x in remote for x in ("\n", "\r", "..")):
        raise ValueError("Expected an absolute dedicated deployment path")
    if args.profile:
        tunnel = SSHClient.from_env(profile=args.profile); tunnel.warm()
        c = VirtuosoClient.from_tunnel(tunnel)
    else:
        c = VirtuosoClient.from_env()
    settings = None
    if args.preserve_runtime_settings:
        settings = loads(checked(c.execute_skill('list(ALDRuntimeRoot ALDRuntimeCommand ALDRuntimeBridgePort)')))
        if remote + '/.venv/bin/python' not in settings[1]:
            raise ValueError('Existing runtime command belongs to another deployment destination')
    def run(cmd):
        r = c.ssh_runner.run_command(cmd, timeout=240)
        print(r.stdout, flush=True)
        if r.returncode:
            raise RuntimeError(r.stderr)
        return r.stdout
    q = shlex.quote
    evidence = PROJECT / "evidence/runtime"
    evidence.mkdir(parents=True, exist_ok=True)
    if args.migrate:
        old = PROJECT / "gui-workspace"
        if (old / "worker.lock").exists():
            (old / "STOP").touch()
            deadline = time.monotonic() + 30
            while (old / "worker.lock").exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("Old worker has not stopped; migration refused")
                time.sleep(.5)
    # Avoid changing package files underneath an active integrated worker.
    state = checked(c.execute_skill("if(boundp('ALDRuntimeIPC) then ALDRuntimeIPC else nil)"))
    if state != "nil":
        checked(c.execute_skill("ALDRuntimeStop()"))
        for _ in range(50):
            if checked(c.execute_skill("ALDRuntimeIPC")) == "nil":
                break
            time.sleep(.4)
        else:
            raise RuntimeError("Integrated runtime did not stop")
    bundle = evidence / "runtime-source.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        for directory, prefix in [(PROJECT / "layoutdiff", "app/layoutdiff"),
                                  (PROJECT / "klayout_plugin", "app/klayout_plugin"),
                                  (PROJECT.parent / "src/virtuoso_bridge", "bridge/src/virtuoso_bridge")]:
            for path in sorted(directory.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    tar.add(path, arcname=prefix + "/" + path.relative_to(directory).as_posix())
        tar.add(PROJECT / "pyproject.toml", arcname="app/pyproject.toml")
        tar.add(PROJECT.parent / "pyproject.toml", arcname="bridge/pyproject.toml")
        for name in ("build.py", "CMakeLists.txt", "src/main.cpp"):
            tar.add(PROJECT / "native-performance" / name, arcname="native-performance/" + name)
    run("mkdir -p " + q(remote))
    checked(c.upload_file(str(bundle), remote + "/runtime-source.tar.gz"))
    previous = remote + '/app-previous-' + uuid.uuid4().hex[:8]
    run('if test -d '+q(remote+'/app')+'; then mv '+q(remote+'/app')+' '+q(previous)+'; fi')
    run("tar -xzf " + q(remote + "/runtime-source.tar.gz") + " -C " + q(remote))
    run("uv venv --python 3.10 --allow-existing " + q(remote + "/.venv"))
    run("uv pip install --python " + q(remote + "/.venv/bin/python") +
        " -e " + q(remote + "/bridge") + " -e " + q(remote + "/app"))
    compiler = c.ssh_runner.run_command("command -v g++")
    if args.native != "off" and compiler.returncode == 0:
        run(" ".join(map(q, [remote + "/.venv/bin/python", remote + "/native-performance/build.py",
            "--compiler", compiler.stdout.strip(), "--output", remote + "/.venv/bin/layoutdiff-native"])))
    elif args.native == "required":
        raise RuntimeError("A C++17 compiler is required for --native required")
    elif args.native != "off":
        print("No host C++ compiler found; the Python backend remains available.", flush=True)
    if args.migrate:
        archive = evidence / "history-migration.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name in ("histories", "styles.json"):
                source = PROJECT / "gui-workspace" / name
                if source.exists():
                    tar.add(source, arcname=name)
        checked(c.upload_file(str(archive), remote + "/history-migration.tar.gz"))
        # A migration never overwrites an existing host history.
        run("test ! -d " + q(remote + "/state/histories") + " && mkdir -p " + q(remote + "/state") +
            " && tar -xzf " + q(remote + "/history-migration.tar.gz") + " -C " + q(remote + "/state"))
    command = ("/usr/bin/env -u LD_LIBRARY_PATH -u LD_PRELOAD " + q(remote + "/.venv/bin/python") +
        " -u -m layoutdiff.runtime supervise --root " + q(remote + "/state"))
    runtime_root, bridge_port = remote + '/state', None
    if settings:
        runtime_root, command, bridge_port = settings
    startup = evidence / "startup.il"
    startup.write_text(
        '; Generated Layout Diff entry point. Load after the existing bridge setup.\n'
        + 'ALDRuntimeRoot=' + sk(runtime_root) + '\n'
        + 'ALDRuntimeCommand=' + sk(command) + '\n'
        + ('ALDRuntimeBridgePort=' + sk(bridge_port) + '\n' if settings else '')
        + 'load(' + sk(remote + "/app/layoutdiff/ui/skill/workflow.il") + ')\n'
        + 'load(' + sk(remote + "/app/layoutdiff/ui/skill/gui.il") + ')\n'
        + 'load(' + sk(remote + "/app/layoutdiff/ui/skill/runtime.il") + ')\n'
        + 'ALDRuntimeInstall()\nALDRuntimeStart()\n', encoding="utf-8")
    checked(c.upload_file(str(startup), remote + "/startup.il"))
    checked(c.execute_skill("load(" + sk(remote + "/startup.il") + ")"))
    atomic_json(evidence / "deployment.json", {"remote": remote, "startup": remote + "/startup.il",
                "migrated": args.migrate, "launcher": "Virtuoso ipcBeginProcess"})
    print("SKILL-launched runtime deployed. CIW menu: Layout Diff")


if __name__ == "__main__":
    main()
