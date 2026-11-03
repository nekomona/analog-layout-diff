"""Versioned graphical merge actions; native views are disposable projections."""
import json
from pathlib import Path
import re
import uuid

from layoutdiff.data.core import digest, apply_diff
from layoutdiff.data.merge_session import MergeSession
from layoutdiff.data.history import atomic_json
from layoutdiff.eda.virtuoso.sexpr import dumps as sk
from layoutdiff.eda.virtuoso.merge_view import MergeView
from layoutdiff.comparison.matching import bounds
from layoutdiff.comparison.merge_index import MergeIndex


def field_text(value):
    raw = value.encode('utf-8')
    return value if len(raw) < 7200 else raw[:7000].decode('utf-8', errors='ignore') + '\n[Details shortened]'


class MergeController:
    def __init__(self, worker):
        self.worker = worker
        self.root = worker.root / 'merges'
        self.root.mkdir(exist_ok=True)
        self.opened = {}
        self.repositories = worker.root / 'merge-repositories'
        self.repositories.mkdir(exist_ok=True)
        self.pending_commit = None
        self.repository_pages = {}

    def start(self, base, target, incoming, *, metadata=None):
        token = uuid.uuid4().hex
        session = MergeSession.create(self.root / token, base, target, incoming, metadata=metadata)
        return self.open(token, session)

    def open(self, token, session=None):
        if not re.fullmatch('[0-9a-f]{32}', token):
            raise ValueError('Invalid merge session ID')
        if token in self.opened:
            raise ValueError('Merge session is already open')
        session = session or MergeSession(self.root / token)
        view = MergeView(self.worker, token, session)
        index = MergeIndex(session.plan)
        view.index = index
        state = {'session': session, 'view': view, 'selected': next(iter(session.plan.units), None),
                 'preview': None, 'page': 0, 'warnings': [], 'index': index, 'category': None}
        self.opened[token] = state
        try:
            view.show(session.snapshot)
            self.refresh(token)
        except BaseException:
            view.close()
            index.close()
            self.opened.pop(token)
            raise
        return {'token': token, 'generation': session.generation, 'unresolved': len(session.unresolved())}

    def refresh(self, token, *, graphics=True):
        state = self.opened[token]
        session, selected = state['session'], state['selected']
        rows = []
        units = session.plan.units
        # Only a bounded page crosses the SKILL bridge.
        page = state['index'].page(state['category'], state['page']*50)
        for ident in page:
            unit = units[ident]
            status = ('resolved' if ident in session.state['resolved'] else
                      'unresolved' if unit['reasons'] else 'automatic')
            rows.append([ident, unit['category'], status])
        label = session.metadata.get('label', 'Target versus Incoming')
        summary = (f'{label}\n{len(session.unresolved())} unresolved / {len(units)} decisions; '
                   f'page {state["page"]+1}\nBase gray; Target cyan; Incoming magenta. Result uses native layers.')
        explanation = 'No conflicting changes. Validate the result before finishing.'
        if selected:
            unit = session.plan.units[selected]
            explanation = (f'{selected}\n{unit["category"]}\n' +
                '\n'.join(unit['reasons'] or ['Automatically combined compatible changes']) +
                '\nPreview an alternative on the canvas, then Accept preview. '
                'Edit result uses native tools; Accept edits resolves this decision.')
            if state['preview']:
                explanation += '\nPREVIEW: ' + state['preview']['choice'] + ' (not accepted)'
            if graphics and not state['view'].editing:
                state['warnings'] = state['view'].highlight(selected)
        if state['warnings']:
            explanation += '\n' + '\n'.join(str(w) for w in state['warnings'][:8])
        if selected:
            overlaps = state['index'].interactions(selected)
            if overlaps:
                explanation += '\nOverlapping branch changes: ' + ', '.join(overlaps) + '. Inspect geometry; this is not DRC/LVS.'
        explanation += '\n' + '\n'.join(session.plan.warnings)
        self.worker.execute(f'ALDMergeUpdate({sk(token)} {session.generation} {sk(rows)} '
                            f'{sk(field_text(summary))} {sk(field_text(explanation))})')
        self.worker.execute(f'ALDMergeCategories({sk(token)} {sk(state["index"].categories)} {sk(state["category"] or "All")})')

    def action(self, token, generation, action, value=''):
        state = self.opened.get(token)
        if state is None:
            raise ValueError('Merge session is closed; resume it first')
        session, view = state['session'], state['view']
        session.check(generation)
        self.worker.execute(f'ALDMergeBusy({sk(token)} {sk(action)})')
        try:
            if view.editing and action not in {'accept-edits', 'cancel-edits', 'details',
                                               'omit-continue', 'omit-confirm', 'omit-cancel'}:
                raise ValueError('Accept or cancel native edits before another merge action')
            if action in {'category', 'page-next', 'page-previous'}:
                if state['preview']:
                    view.show(session.snapshot)
                if action == 'category':
                    if value != 'All' and value not in state['index'].categories:
                        raise ValueError('Unknown category')
                    state['category'], state['page'] = (None if value == 'All' else value), 0
                else:
                    candidate_page = max(0, state['page'] + (1 if action == 'page-next' else -1))
                    if state['index'].page(state['category'], candidate_page*50):
                        state['page'] = candidate_page
                ids = state['index'].page(state['category'], state['page']*50)
                state['selected'], state['preview'] = next(iter(ids), None), None
            elif action in {'select', 'next', 'previous', 'pick'}:
                ids = state['index'].page(state['category'], state['page']*50)
                if not ids:
                    return {'unresolved': 0}
                if action == 'select':
                    if value not in session.plan.units:
                        raise ValueError('Unknown conflict')
                    selected = value
                elif action == 'pick':
                    if not isinstance(value, list) or len(value) != 2:
                        raise ValueError('Expected a canvas point')
                    choices = state['index'].pick(value)
                    if len(choices) != 1:
                        raise ValueError('Choose a decision row: no unique conflict at this point; candidates ' + ', '.join(choices))
                    selected = choices[0]
                else:
                    index = ids.index(state['selected']) if state['selected'] in ids else 0
                    selected = ids[(index + (1 if action == 'next' else -1)) % len(ids)]
                if state['preview']:
                    view.show(session.snapshot)
                state['selected'], state['preview'] = selected, None
            elif action == 'preview':
                candidate = session.preview(state['selected'], value, generation)
                view.show(candidate)  # Full native readback before showing a selectable result.
                state['preview'] = {'choice': value, 'digest': digest(candidate)}
            elif action == 'accept':
                preview = state['preview']
                if not preview:
                    raise ValueError('Preview an alternative before accepting it')
                session.decide(state['selected'], preview['choice'], generation,
                               validated_digest=preview['digest'])
                state['preview'] = None
            elif action == 'edit':
                view.edit()
            elif action == 'accept-edits':
                if not view.editing:
                    raise ValueError('Start Edit result first')
                candidate, audit, source_hash = view.capture_supported()
                if audit:
                    state['omission_pending'] = {'snapshot': candidate, 'audit': audit,
                                                 'source': source_hash, 'phase': 1}
                    self.omission_prompt(token, 1)
                    return {'omission_confirmation': 1}
                # Reconstruct separately before accepting edits into the journal.
                view.show(candidate)
                session.accept_edits(candidate, state['selected'], generation)
                state['preview'] = None
            elif action == 'omit-cancel':
                state.pop('omission_pending', None)
            elif action in {'omit-continue', 'omit-confirm'}:
                pending = state.get('omission_pending')
                phase = 1 if action == 'omit-continue' else 2
                if not pending or pending['phase'] != phase:
                    raise ValueError('Omission consent is missing or stale')
                if phase == 1:
                    pending['phase'] = 2
                    self.omission_prompt(token, 2)
                    return {'omission_confirmation': 2}
                candidate, audit, source_hash = view.capture_supported()
                state.pop('omission_pending')
                if source_hash != pending['source'] or audit != pending['audit'] or candidate != pending['snapshot']:
                    raise ValueError('Native content changed after omission preview; review it again')
                view.show(candidate)
                session.accept_edits(candidate, state['selected'], generation, omissions=audit)
                state['preview'] = None
            elif action == 'cancel-edits':
                state.pop('omission_pending', None)
                view.show(session.snapshot)
                state['preview'] = None
            elif action in {'undo', 'redo'}:
                stack = session.state[action]
                if not stack:
                    raise ValueError('No decision to ' + action)
                event = session.event(stack[-1])
                candidate = apply_diff(session.snapshot, event['patch'], reverse=action == 'undo')
                view.show(candidate)
                session.undo(generation, redo=action == 'redo')
                state['preview'] = None
            elif action == 'details':
                unit = session.plan.units.get(state['selected'], {})
                text = json.dumps(unit, indent=2, ensure_ascii=True)
                if len(text.encode('utf-8')) > 7000:
                    destination = session.path / 'selected-details.json'
                    atomic_json(destination, unit)
                    text = text.encode('utf-8')[:6800].decode('utf-8', errors='ignore') + '\nFull details: ' + str(destination)
                self.worker.execute(f'ALDMergeDetails({sk(token)} {sk(text)})')
            elif action in {'validate', 'finish'}:
                if state['preview']:
                    raise ValueError('Accept or dismiss the current preview first')
                if action == 'finish' and session.unresolved():
                    raise ValueError('Resolve every conflict before finishing')
                view.show(session.snapshot)
                state['validated'] = digest(session.snapshot)
                if action == 'finish':
                    return self.finish(token)
            elif action == 'suspend':
                view.close()
                state['index'].close()
                self.opened.pop(token)
                return {'suspended': token, 'generation': session.generation}
            else:
                raise ValueError('Unknown merge action: ' + action)
            self.refresh(token, graphics=action != 'details')
            return {'token': token, 'generation': session.generation, 'unresolved': len(session.unresolved())}
        finally:
            self.worker.execute(f'ALDMergeBusy({sk(token)} "")')

    def pick(self, session, point):
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError('Expected a canvas point')
        candidates = []
        for ident, unit in session.plan.units.items():
            for side, records in unit['alternatives'].items():
                dbu = session.plan.inputs[side]['objects'].get('cell:', {}).get('dbu', 1000)
                x, y = point[0]*dbu, point[1]*dbu
                for r in records.values():
                    box = bounds(r)
                    if box and box[0]-1 <= x <= box[2]+1 and box[1]-1 <= y <= box[3]+1:
                        candidates.append(ident)
        choices = sorted(set(candidates))
        if not choices:
            raise ValueError('No conflict at that point; choose a row or another point')
        if len(choices) > 1:
            raise ValueError('Several conflicts overlap; select their category/row: ' + ', '.join(choices[:8]))
        return choices[0]

    def omission_prompt(self, token, phase):
        pending = self.opened[token]['omission_pending']
        audit = pending['audit']
        text = (f'{audit["omitted"]} unsupported elements will be omitted; '
                f'{audit["detached"]} group memberships will be detached.\n' +
                json.dumps(audit['counts'], indent=2))
        if phase == 2:
            text = 'Restoring or rolling back to this result WILL LOSE the omitted elements.\n' + text
        self.worker.execute(f'ALDMergeOmissionPrompt({sk(token)} {phase} {sk(text)})')

    def finish(self, token):
        # Repository integration installs a coordinator; file-only sessions retain
        # the validated snapshot and require an explicit destination transaction.
        state = self.opened[token]
        session = state['session']
        if session.metadata.get('repository'):
            from layoutdiff.git.merge import RepositoryMerge
            tx = RepositoryMerge(session.metadata['repository'])
            tx.validate_cell(session.metadata['cell_key'], digest(session.snapshot))
            self.repository_panel(tx.path.name)
            self.worker.notice('Cell validated for this merge. Complete the other cells, then Commit step in the Merge repository panel.')
            return {'validated': digest(session.snapshot), 'repository': str(tx.path)}
        atomic_json(session.path / 'validated-result.json', session.snapshot)
        self.worker.notice('Merge result validated and saved. This session has no Git transaction attached.')
        return {'validated': digest(session.snapshot), 'path': str(session.path / 'validated-result.json')}

    def setup(self):
        from layoutdiff.git.commit import git, revision
        repo = self.worker.git_repository()
        if repo is None:
            raise ValueError('Select a Git repository with Save & Commit before starting a merge')
        branch = revision(repo)['branch'].removeprefix('refs/heads/')
        refs = git(repo, 'for-each-ref', '--format=%(refname:short)', 'refs/heads', 'refs/remotes').stdout.decode().splitlines()
        rows = []
        for p in sorted(self.repositories.glob('*/repository.json')):
            from layoutdiff.data.history import read_json
            s = read_json(p)
            if s['phase'] not in {'published', 'cancelled'}:
                rows.append([p.parent.name, s['phase'], s['original']['branch']])
        self.worker.execute(f'ALDMergeSetup({sk(str(repo))} {sk(branch)} {sk(refs[:100])} {sk(rows[-100:])})')
        return {'repository': str(repo), 'sessions': len(rows)}

    def repository(self, token):
        from layoutdiff.git.merge import RepositoryMerge
        if not re.fullmatch('[0-9a-f]{32}', token):
            raise ValueError('Invalid repository merge ID')
        return RepositoryMerge(self.repositories / token)

    def repository_panel(self, token):
        tx = self.repository(token)
        s = tx.state
        cells = [[k, ' / '.join(c['identity']), 'validated' if c['validated'] else 'needs review']
                 for k, c in s['cells'].items()]
        files = [[p, choice or 'unresolved'] for p, choice in s['files'].items()]
        pages = self.repository_pages.setdefault(token, {'cells': 0, 'files': 0})
        text = (f'Target: {s["original"]["branch"]}\nPhase: {s["phase"]}; step {min(s["step"]+1,len(s["incoming"]))}/{len(s["incoming"])}\n'
                + 'Incoming order: ' + ' -> '.join(v['label'] for v in s['incoming']) +
                f'\n{len(s.get("paths", []))} affected repository paths; {len(cells)} layout cells; {len(files)} ordinary-file conflicts.\n'
                'Commit step creates an isolated two-parent commit. Publish fast-forwards the original clean checkout. OA layouts are unchanged.')
        # Complete affected paths remain available on disk; only bounded rows
        # enter the native forms. Paging is handled by repository navigation.
        text += f'\nCell page {pages["cells"]+1}; file page {pages["files"]+1}. 100 rows per page.'
        self.worker.execute(f'ALDMergeRepository({sk(token)} {sk(field_text(text))} '
                            f'{sk(cells[pages["cells"]*100:(pages["cells"]+1)*100])} '
                            f'{sk(files[pages["files"]*100:(pages["files"]+1)*100])} {sk(digest(s))})')
        return {'token': token, 'phase': s['phase'], 'cells': len(cells), 'files': len(files)}

    def repository_action(self, action, token='', value='', stamp=None):
        from layoutdiff.git.merge import RepositoryMerge
        if stamp is not None and action not in {'start', 'resume', 'refresh'} and digest(self.repository(token).state) != stamp:
            raise ValueError('Stale repository request; refresh the merge panel')
        if action == 'start':
            incoming = value.replace(',', ' ').split()
            token = uuid.uuid4().hex
            RepositoryMerge.create(self.repositories / token, self.worker.git_repository(), incoming)
        elif action == 'resume':
            tx = self.repository(token)
            if tx.state['phase'] == 'committing':
                tx.recover_commit()
            elif tx.state['phase'] == 'publishing':
                tx.recover_publish()
            elif tx.state['phase'] in {'created', 'between', 'preparing'}:
                tx.begin()
        elif action == 'open-cell':
            tx = self.repository(token)
            session = tx.cell(value)
            for existing, state in list(self.opened.items()):
                if state['session'].path == session.path:
                    if self.worker.execute(f'ALDMergeAlive({sk(existing)})') == 't':
                        self.worker.execute(f'hiSetCurrentWindow(ALDMergeSessions[{sk(existing)}][\'window])')
                        return {'token': existing}
                    state['view'].close(); state['index'].close(); self.opened.pop(existing)
            return self.open(uuid.uuid4().hex, session)
        elif action == 'file':
            path, side = value
            self.repository(token).choose_file(path, side)
        elif action == 'commit':
            tx = self.repository(token)
            if any(c['audits'] or tx.cell(k).state.get('omissions') for k,c in tx.state['cells'].items()):
                self.pending_commit = {'token': token, 'message': value, 'phase': 1,
                    'stamp': self.repository_stamp(tx)}
                self.repository_omission_prompt(token, 1)
                return {'omission_confirmation': 1}
            self.commit_repository_step(tx, value)
        elif action in {'omit-continue', 'omit-confirm'}:
            pending = self.pending_commit
            phase = 1 if action == 'omit-continue' else 2
            if not pending or pending['token'] != token or pending['phase'] != phase:
                raise ValueError('Repository omission confirmation is stale')
            if phase == 1:
                pending['phase'] = 2
                self.repository_omission_prompt(token, 2)
                return {'omission_confirmation': 2}
            tx = self.repository(token)
            self.pending_commit = None
            if self.repository_stamp(tx) != pending['stamp']:
                raise ValueError('Merge decisions changed after omission consent; review again')
            self.commit_repository_step(tx, pending['message'], omission_consent=True)
        elif action == 'omit-cancel':
            self.pending_commit = None
        elif action == 'publish':
            tx = self.repository(token)
            result = tx.publish()
            self.worker.notice('Published Git merge ' + result + '. Use History > Restore checkpoint separately to update an OA source layout.')
        elif action == 'cancel':
            tx = self.repository(token)
            self.close_repository_views(tx)
            tx.cancel()
        elif action == 'refresh':
            pass
        elif action in {'cells-next', 'cells-previous', 'files-next', 'files-previous'}:
            table, direction = action.split('-')
            pages = self.repository_pages.setdefault(token, {'cells': 0, 'files': 0})
            proposed = max(0, pages[table] + (1 if direction == 'next' else -1))
            if proposed*100 < len(self.repository(token).state[table]):
                pages[table] = proposed
        elif action in {'paths', 'show-file'}:
            tx = self.repository(token)
            from layoutdiff.git.commit import git
            if action == 'paths':
                text = '\n'.join(tx.state.get('paths', []))
            else:
                if value not in tx.state['files']:
                    raise ValueError('Select an ordinary-file conflict')
                text = ''
                for label, rev in [('Target', tx.state['head']), ('Incoming', tx.state['incoming'][tx.state['step']]['sha'])]:
                    raw = git(tx.work, 'diff', '--no-ext-diff', '--no-textconv', tx.state['base'], rev, '--', value).stdout
                    text += label + '\n' + raw.decode('utf-8', errors='replace') + '\n'
            with self.worker.work_area() as area:
                path = area['path'] / 'merge-paths.txt'; path.write_text(text, encoding='utf-8')
                remote = area['remote'] + '/merge-paths.txt'
                from layoutdiff.eda.virtuoso.adapter import checked
                checked(self.worker.client.upload_file(str(path), remote))
                self.worker.execute(f'ALDGUIViewFile({sk(remote)} "Merge repository paths")')
        else:
            raise ValueError('Unknown repository merge action')
        return self.repository_panel(token)

    def repository_stamp(self, tx):
        return digest([tx.state, {k: tx.cell(k).head for k in tx.state['cells']}])

    def repository_omission_prompt(self, token, phase):
        text = ('This merge includes incomplete snapshots. Their omission diagnostics will be preserved.\n'
                'Restoring the merged checkpoint WILL LOSE the omitted elements.\n'
                + ('Continue to the second confirmation?' if phase == 1 else 'Confirm this loss to create the merge commit.'))
        self.worker.execute(f'ALDMergeRepositoryOmissions({sk(token)} {phase} {sk(text)})')

    def close_repository_views(self, tx):
        for token, state in list(self.opened.items()):
            if state['session'].metadata.get('repository') == str(tx.path):
                state['view'].close()
                state['index'].close()
                self.opened.pop(token)

    def commit_repository_step(self, tx, message, **kwargs):
        # Never discard active native work or an unaccepted graphical preview.
        for state in self.opened.values():
            if state['session'].metadata.get('repository') == str(tx.path) and (state['view'].editing or state['preview']):
                raise ValueError('Accept or cancel every native edit and preview before committing')
        tx.commit_step(message, **kwargs)
        self.repository_pages[tx.path.name] = {'cells': 0, 'files': 0}
        self.close_repository_views(tx)
