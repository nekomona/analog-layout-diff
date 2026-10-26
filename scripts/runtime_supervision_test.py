"""Real Linux lifecycle regression with disposable parents, never the live CIW."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from layoutdiff.runtime import process_identity


def until(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError("Timed out waiting for test process")


class Supervision(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ald_runtime_test_")
        self.root = Path(self.temp.name)
        self.parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.children = []
        self.worker_source = self.root / "dummy.py"
        self.worker_source.write_text('''import os, sys, time, signal, json
from pathlib import Path
root=Path(sys.argv[1])
(root/'worker.lock').write_text(str(os.getpid()))
(root/'histories/owned').mkdir(parents=True)
(root/'histories/owned/.lock').write_text(str(os.getpid()))
(root/'histories/owned/HEAD').write_text('durable commit')
(root/'histories/foreign').mkdir(parents=True)
(root/'histories/foreign/.lock').write_text('987654321')
Path(os.environ['TMPDIR'], 'scratch').write_text('temporary')
git=root/'git'; git.mkdir()
(git/'index.lock').write_text('owned-git-token')
(git/'index.ald-test').write_text('temporary index')
foreign=root/'foreign-git'; foreign.mkdir()
(foreign/'index.lock').write_bytes(bytes([0,255,254]))
records=[{'pid':os.getpid(),'path':str(git/'index.lock'),'token':'owned-git-token',
          'index_staging':str(git/'index.ald-test')},
         {'pid':os.getpid(),'path':str(foreign/'index.lock'),'token':'not-the-lock'}]
(Path(os.environ['TMPDIR']).parent/'git-locks.json').write_text(json.dumps(records))
(root/'ready').touch()
if sys.argv[2]=='stubborn':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True: time.sleep(.05)
while not (root/'STOP').exists(): time.sleep(.05)
''')

    def tearDown(self):
        for p in self.children:
            if p.poll() is None:
                p.stdin.write(b"STOP\n")
                p.stdin.flush()
                p.wait(timeout=10)
            for stream in (p.stdin, p.stdout, p.stderr):
                if stream and not stream.closed:
                    stream.close()
        self.parent.terminate()
        self.parent.wait()
        self.temp.cleanup()

    def start(self, mode="normal"):
        code = ("from layoutdiff.runtime import supervise; supervise(" +
                repr(str(self.root)) + "," + str(self.parent.pid) + ",65081,'TEST',worker_command=" +
                repr([sys.executable, str(self.worker_source), str(self.root), mode]) + ",grace=.2)")
        p = subprocess.Popen([sys.executable, "-u", "-c", code], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.children.append(p)
        until(lambda: (self.root / "ready").exists())
        return p

    def verify_cleanup(self, p, reason):
        p.wait(timeout=8)
        self.assertEqual(p.returncode, 0, p.stderr.read().decode())
        state = json.loads((self.root / "runtime.json").read_text())
        self.assertEqual(state["reason"], reason)
        self.assertIsNone(process_identity(state["worker_pid"]))
        self.assertFalse((self.root / "worker.lock").exists())
        self.assertFalse((self.root / "histories/owned/.lock").exists())
        self.assertEqual((self.root / "histories/foreign/.lock").read_text(), "987654321")
        self.assertEqual((self.root / "histories/owned/HEAD").read_text(), "durable commit")
        self.assertFalse((self.root / "git/index.lock").exists())
        self.assertFalse((self.root / "git/index.ald-test").exists())
        self.assertEqual((self.root / "foreign-git/index.lock").read_bytes(), bytes([0, 255, 254]))
        self.assertFalse(Path(state['temporary_directory']).exists())

    def test_gui_stop(self):
        p = self.start()
        p.stdin.write(b"STOP\n"); p.stdin.flush()
        self.verify_cleanup(p, "gui-stop")

    def test_parent_death(self):
        p = self.start()
        self.parent.kill(); self.parent.wait()
        self.verify_cleanup(p, "parent-exit")

    def test_ipc_eof(self):
        p = self.start()
        p.stdin.close()
        self.verify_cleanup(p, "ipc-eof")

    def test_stubborn_worker_is_killed(self):
        p = self.start("stubborn")
        p.stdin.write(b"STOP\n"); p.stdin.flush()
        self.verify_cleanup(p, "gui-stop")
        self.assertEqual(json.loads((self.root / "runtime.json").read_text())["worker_exit"], -9)

    def test_duplicate_supervisor_refused(self):
        p = self.start()
        code = ("from layoutdiff.runtime import supervise; supervise(" + repr(str(self.root)) +
                "," + str(self.parent.pid) + ",65081,'TEST')")
        result = subprocess.run([sys.executable, "-c", code], input=b"STOP\n", capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"already owns", result.stderr)
        self.assertIsNone(p.poll())
        p.stdin.write(b"STOP\n"); p.stdin.flush()
        self.verify_cleanup(p, "gui-stop")

    def test_process_identity_rejects_reuse_and_zombies(self):
        proc = self.root / "proc"
        (proc / "123").mkdir(parents=True)
        (proc / "sys/kernel/random").mkdir(parents=True)
        (proc / "sys/kernel/random/boot_id").write_text("boot")
        stat = proc / "123/stat"
        stat.write_text("123 (name with ) parens) S " + "0 " * 18 + "111 0")
        a = process_identity(123, proc)
        stat.write_text("123 (other) S " + "0 " * 18 + "222 0")
        self.assertNotEqual(a, process_identity(123, proc))
        stat.write_text("123 (other) Z " + "0 " * 18 + "222 0")
        self.assertIsNone(process_identity(123, proc))


if __name__ == "__main__":
    unittest.main(verbosity=2)
