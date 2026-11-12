"""Native OA capture and fresh-cell readback with a display-free Virtuoso process.

No Bridge daemon, GUI SKILL, window callbacks or persistent native process is
loaded. The caller supplies an already configured environment and cds.lib cwd.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import uuid

from layoutdiff.data.core import canonicalize, diff, validate
from layoutdiff.data.history import atomic_json
from layoutdiff.data.storage import write_records
from layoutdiff.eda.virtuoso.adapter import capture_records, render, replay_source
from layoutdiff.eda.virtuoso.dependencies import (
    native_snapshot, compare_dependencies, emit_warnings, normalized_dependencies, dependency_records)
from layoutdiff.eda.virtuoso.hash_views import fingerprint
from layoutdiff.eda.virtuoso.sexpr import loads, dumps as sk
from layoutdiff.eda.virtuoso.support import checked_records, coverage


class BatchAdapter:
    capture_state = 'saved_oa'
    def __init__(self, executable='virtuoso', cwd=None, artifacts='artifacts', *,
                 writable_library=None, timeout=240, group_definition_source=None):
        self.executable = str(executable)
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.artifacts = Path(artifacts).resolve()
        self.writable_library = writable_library
        self.timeout = timeout
        self.group_definition_source = group_definition_source
        self.last_dependency_warnings = []
        self.last_readback_normalization = None

    def _job(self):
        folder = self.artifacts / ('batch-' + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        return folder

    def _run(self, folder, body):
        skill = Path(__file__).parent / 'skill'
        script = folder / 'run.il'
        done = folder / 'complete'
        script.write_text(
            'aldBatchResult=errset(progn(\n'
            f'load({sk(str(skill / "reader.il"))})\n'
            f'load({sk(str(skill / "hierarchy.il"))})\n' + body + '\nt) t)\n'
            'if(aldBatchResult then\n'
            f'let((p) p=outfile({sk(str(done))}) unless(p error("Cannot write batch result")) '
            'fprintf(p "ok\\n") close(p)) exit(0)\nelse exit(1))\n', encoding='utf-8')
        env = os.environ.copy()
        # CDS_NOGRAPH_DISPLAY makes -nograph emulate a GUI; remove both bindings.
        env.pop('DISPLAY', None)
        env.pop('CDS_NOGRAPH_DISPLAY', None)
        log = folder / 'process.log'
        with log.open('wb') as stream:
            with subprocess.Popen([self.executable, '-nograph', '-nocdsinit',
                    '-log', str(folder / 'CDS.log'), '-restore', str(script)],
                    cwd=self.cwd, env=env, stdin=subprocess.DEVNULL, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=os.name != 'nt',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0) as process:
                try:
                    process.wait(timeout=self.timeout)
                except BaseException as exc:
                    if os.name == 'nt':
                        process.kill()
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait()
                    if isinstance(exc, subprocess.TimeoutExpired):
                        raise RuntimeError('Native batch timed out; inspect retained job ' + str(folder)) from exc
                    raise
        if process.returncode or not done.exists():
            raise RuntimeError('Native batch failed; inspect ' + str(log))

    @staticmethod
    def _rows(path):
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                if line.strip():
                    yield dict(loads(line))

    def _records(self, folder, dependencies):
        yield from capture_records(self._rows(folder / 'capture.sexpr'))
        if dependencies:
            rows = list(self._rows(folder / 'hierarchy.sexpr'))
            hashed = {p: fingerprint(p) for p in {r['path'] for r in rows if r['path']}}
            yield from normalized_dependencies(rows, hashed)

    @staticmethod
    def _capture_code(folder, lib, cell, view, dependencies):
        args = ' '.join(map(sk, (lib, cell, view)))
        code = f'ALDRead({args} {sk(str(folder / "capture.sexpr"))})\n'
        if dependencies:
            code += f'ALDDependencies({args} {sk(str(folder / "hierarchy.sexpr"))})\n'
        return code

    def capture_store(self, lib, cell, view='layout', *, dependencies=True, temporary=False,
                      allow_unsupported=False):
        folder = self._job()
        self._run(folder, self._capture_code(folder, lib, cell, view, dependencies))
        owner = tempfile.TemporaryDirectory(prefix='ald_batch_capture_') if temporary else None
        target = Path(owner.name) / 'layout' if owner else folder / 'layout'
        try:
            records = self._records(folder, dependencies)
            store = write_records(records if allow_unsupported else checked_records(
                records, folder / 'unsupported.jsonl'), target)
            if allow_unsupported:
                from layoutdiff.eda.virtuoso.omissions import project
                full = store
                try:
                    store = project(full, target.with_name('supported.layout'), folder / 'omissions.jsonl')
                finally:
                    full.close()
            store._capture_owner = owner
            return store
        except BaseException:
            if owner:
                owner.cleanup()
            raise

    def capture(self, lib, cell, view='layout', *, dependencies=True):
        store = self.capture_store(lib, cell, view, dependencies=dependencies, temporary=True)
        try:
            return store.materialize()
        finally:
            store.dispose()

    def reconstruct(self, snapshot, lib, cell, view='layout', *, group_definition_source=None,
                    cleanup=False):
        validate(snapshot)
        issues = coverage(snapshot)
        if issues:
            raise ValueError('Snapshot cannot be faithfully reconstructed: ' + '; '.join(issues))
        if lib != self.writable_library or not lib:
            raise ValueError('Destination is outside the configured writable library')
        self.last_readback_normalization = None
        folder = self._job()
        meta = snapshot['objects']['cell:']
        args = ' '.join(map(sk, (lib, cell, view)))
        source, _ = replay_source(render(snapshot), 'ALDBatchBuild')
        context = group_definition_source or self.group_definition_source
        context_code = ''
        if context:
            if len(context) != 3 or not all(isinstance(v, str) and v for v in context):
                raise ValueError('Group-definition source must be a library/cell/view identity')
            context_code = ('let((cv) cv=dbOpenCellViewByType(' + ' '.join(map(sk, context)) +
                            ' "maskLayout" "r") unless(cv error("Cannot read group-definition source")) dbClose(cv))\n')
        defaults = folder / 'via-defaults.sexpr'
        names = sorted({r['viaDef'] for r in snapshot['objects'].values() if r['kind'] == 'stdVia'})
        body = (f'unless(ddGetObj({sk(lib)}) error("Destination library does not exist"))\n'
                f'unless(techGetTechLibName(ddGetObj({sk(lib)}))=={sk(meta["technology"])} '
                'error("Destination technology differs from snapshot"))\n'
                f'when(ddGetObj({args}) error("Destination already exists"))\n' +
                (f'when(ddGetObj({sk(lib)} {sk(cell)}) error("Validation cell already exists"))\n' if cleanup else '') +
                context_code + source + '\n'
                'let((cv owned) unwindProtect(progn(\n'
                f'cv=dbOpenCellViewByType({args} "maskLayout" "w") '
                'unless(cv error("Cannot create destination")) owned=t\n'
                'ALDBatchBuild(cv) unless(dbSave(cv) error("Cannot save reconstruction")) '
                'dbClose(cv) cv=nil\n' + self._capture_code(folder, lib, cell, view, True) +
                f'let((tf vd p) tf=techGetTechFile(ddGetObj({sk(lib)})) '
                f'p=outfile({sk(str(defaults))}) unless(p error("Cannot write via defaults")) '
                f'fprintf(p "%L\\n" foreach(mapcar name {sk(names)} vd=techFindViaDefByName(tf name) '
                'list(name when(vd nth(3 vd~>params)) when(vd nth(4 vd~>params))))) close(p))\n'
                ') progn(when(cv dbClose(cv)) ' +
                (f'when(owned unless(ddDeleteObj(ddGetObj({args})) '
                 'error("Cannot clean validation cell")))' if cleanup else '') + ')))\n')
        self._run(folder, body)
        actual = canonicalize(list(self._records(folder, True)))
        equal = native_snapshot(actual) == native_snapshot(snapshot)
        if not equal and any(r['kind'] == 'stdVia' or r.get('mpp') for r in snapshot['objects'].values()):
            from layoutdiff.eda.virtuoso.native_equivalence import via_default_projection
            values = loads(defaults.read_text())
            params = {name: {'cutRows': rows, 'cutColumns': columns} for name, rows, columns in values or []}
            expected, _ = via_default_projection(snapshot, params, mpp_connectivity=True)
            observed, _ = via_default_projection(actual, params, mpp_connectivity=True)
            equal = expected == observed
            self.last_readback_normalization = {'method': 'technology-defaults-and-mpp-effective-connectivity',
                                                'equal': equal, 'via_defaults': params}
        if not equal:
            mismatch = folder / 'mismatch.json'
            atomic_json(mismatch, diff(native_snapshot(snapshot), native_snapshot(actual)))
            raise ValueError('Reconstruction readback mismatch: ' + str(mismatch))
        self.last_dependency_warnings = compare_dependencies(snapshot, actual) if dependency_records(snapshot) else []
        emit_warnings(self.last_dependency_warnings)
        return actual

    def validate(self, snapshot):
        if not snapshot['objects']:
            return {'empty': True, 'dependency_warnings': []}
        self.reconstruct(snapshot, self.writable_library, 'ald_validation_' + uuid.uuid4().hex,
                         cleanup=True)
        return {'dependency_warnings': self.last_dependency_warnings,
                'readback_normalization': self.last_readback_normalization,
                'backend': 'batch', 'capture_state': 'saved_oa'}
