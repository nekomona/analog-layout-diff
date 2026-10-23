"""Linux host runtime launched by SKILL; no SSH and no external desktop worker.

The small supervisor never calls SKILL. It remains responsive while a worker is
waiting for Virtuoso, and owns exactly one worker process group and scratch tree.
The existing bridge is shared infrastructure and is never stopped by this tool.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time
import traceback
import uuid

from .history import atomic_json, read_json


def process_identity(pid, proc=Path("/proc")):
    """Linux start ticks + boot ID prevent PID-reuse mistakes; zombies are dead."""
    try:
        stat = (proc / str(int(pid)) / "stat").read_text()
        fields = stat[stat.rfind(")") + 2:].split()
        if fields[0] in {"Z", "X"}:
            return None
        return (proc / "sys/kernel/random/boot_id").read_text().strip() + ":" + fields[19]
    except (OSError, ValueError, IndexError):
        return None


def remove_owned_locks(root, pid):
    """Call only after waiting for the owned worker, while holding runtime flock."""
    for path in [root / "worker.lock", *root.glob("histories/*/.lock")]:
        try:
            if path.read_text().strip() == str(pid):
                path.unlink()
        except FileNotFoundError:
            pass


def stop_group(child, grace=8):
    """The worker has a new session: signal only that known process group."""
    try:
        child.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=3)
    # A crashed worker could leave its own subprocesses behind.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def supervise(root, parent_pid, port, review_library, *, worker_command=None, grace=8):
    import fcntl
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_id = process_identity(parent_pid)
    if not parent_id:
        raise RuntimeError("Virtuoso parent is not alive")
    # Kernel flock is released even after SIGKILL. Keep the inode (never unlink).
    with (root / "runtime.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A supervisor already owns this workspace") from None
        if (root / "worker.lock").exists():
            # Do not adopt/kill a possibly unrelated old process.
            raise RuntimeError("Existing worker.lock: stop the previous worker first")
        token = uuid.uuid4().hex
        session = root / "sessions" / token
        session.mkdir(parents=True, mode=0o700)
        (session / "tmp").mkdir()
        stop = root / "STOP"
        stop.unlink(missing_ok=True)
        reason = "worker-exit"
        stopping = False
        def request_stop(signum, frame):
            nonlocal stopping
            stopping = True
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(signum, request_stop)
        env = os.environ.copy()
        env["TMPDIR"] = str(session / "tmp")
        command = worker_command or [sys.executable, "-u", "-m", "layoutdiff.runtime", "worker",
            "--root", str(root), "--session", str(session), "--port", str(port),
            "--parent", str(parent_pid), "--review-library", review_library]
        # Bound retained diagnostic logs. Histories and preferences are durable.
        logfile = root / "runtime.log"
        if logfile.exists() and logfile.stat().st_size > 2_000_000:
            os.replace(logfile, root / "runtime.previous.log")
        child = None
        state = {"supervisor_pid": os.getpid(), "parent_pid": parent_pid,
                 "parent_identity": parent_id, "session": token, "root": str(root),
                 "started": time.time(), "status": "starting"}
        try:
            with logfile.open("a", buffering=1) as log:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                         stderr=log, env=env, start_new_session=True)
                state["worker_pid"] = child.pid
                atomic_json(root / "runtime.json", state)
                print(f"Supervisor {os.getpid()}, worker {child.pid}, Virtuoso {parent_pid}", flush=True)
                while child.poll() is None:
                    if stopping:
                        reason = "signal"
                        break
                    if process_identity(parent_pid) != parent_id:
                        reason = "parent-exit"
                        break
                    ready, _, _ = select.select([sys.stdin], [], [], .5)
                    if ready:
                        data = os.read(sys.stdin.fileno(), 4096)
                        if not data:
                            reason = "ipc-eof"
                            break
                        if b"STOP" in data:
                            reason = "gui-stop"
                            break
                    if stop.exists():
                        reason = "stop-file"
                        break
                stop.touch()
                stop_group(child, grace=grace if process_identity(parent_pid) == parent_id else .5)
        finally:
            if child:
                if child.poll() is None:
                    stop.touch()
                    stop_group(child, grace=.5)
                remove_owned_locks(root, child.pid)
                from .gitcommit import cleanup_locks
                cleanup_locks(session / "git-locks.json", child.pid)
            # Only our randomly named child of sessions is disposable.
            assert session.parent == root / "sessions" and session.name == token
            shutil.rmtree(session)
            stop.unlink(missing_ok=True)
            state.update(status="stopped", reason=reason, stopped=time.time(),
                         worker_exit=None if not child else child.returncode)
            atomic_json(root / "runtime.json", state)
            if child and child.returncode and logfile.exists():
                print(logfile.read_text(errors="replace")[-8000:], flush=True)
            print("Stopped: " + reason + "; worker, scratch and owned locks released", flush=True)


def run_worker(root, session, port, parent_pid, review_library):
    from virtuoso_bridge import VirtuosoClient
    from .gui import GuiWorker
    from .virtuoso import checked
    from .sexpr import dumps as sk
    root, session = Path(root), Path(session)
    # An explicit local client never reads the Windows/SSH configuration.
    client = VirtuosoClient.local(port=port)
    client.layoutdiff_local_files = True
    client.layoutdiff_scratch = lambda name: session / "tmp" / name
    # Verify the bridge targets this exact CIW before installing/mutating any UI.
    actual_pid = int(checked(client.execute_skill("ipcGetPid()")))
    if actual_pid != parent_pid:
        raise RuntimeError("Bridge endpoint belongs to a different Virtuoso process")
    worker = GuiWorker(client, root, review_library=review_library)
    worker.adapter.artifacts = session / "artifacts"
    worker.adapter.artifacts.mkdir()
    worker.adapter.hierarchy.artifacts = worker.adapter.artifacts
    worker.lock_registry = session / "git-locks.json"
    worker.git_scratch = session / "tmp"
    lock = root / "worker.lock"
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    stop = root / "STOP"
    def request_stop(signum, frame):
        stop.touch()
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, request_stop)
    try:
        worker.install()
        worker.execute(f"ALDRuntimeReady({sk(worker.token)} {os.getpid()} {sk(str(root))})")
        state = read_json(root / "runtime.json")
        state.update(status="running", ready=time.time())
        atomic_json(root / "runtime.json", state)
        worker.clean_reviews()  # Deferred DB cleanup after an earlier session exit.
        worker.dispatch(["sources"])
        while not stop.exists():
            count = worker.poll()
            worker.execute(f"ALDRuntimeHeartbeat({os.getpid()} {count})")
            time.sleep(.8)
    except Exception:
        traceback.print_exc()
        raise
    finally:
        if process_identity(parent_pid):
            try:
                worker.execute(f"ALDGUIStop({sk(worker.token)})")
                worker.clean_reviews()
            except Exception:
                traceback.print_exc()
        worker.close()
        client.close()
        remove_owned_locks(root, os.getpid())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["supervise", "worker"])
    p.add_argument("--root", required=True)
    p.add_argument("--parent", type=int, required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--review-library", default="LAYOUT_DIFF_TEST")
    p.add_argument("--session")
    args = p.parse_args()
    if args.mode == "supervise":
        supervise(args.root, args.parent, args.port, args.review_library)
    else:
        run_worker(args.root, args.session, args.port, args.parent, args.review_library)


if __name__ == "__main__":
    main()
