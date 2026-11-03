# Contributing to Analog Layout Diff

Contributions can improve the native codec, exact comparison, Git integration,
review workflows, performance, documentation or synthetic regression coverage.
Use the [program map](docs/architecture/PROGRAM_STRUCTURE.md) to locate the owning
component and the [development guide](docs/development/README.md) for detailed setup.

## Set up a checkout

Use Python 3.10 or later, Git, `uv` and a virtual environment. From the repository
root:

```sh
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e ".[verify]"
git switch -c codex/describe-the-change
```

On Linux use `.venv/bin/python`. Activate the environment before running commands.
The `verify` extra installs pytest and KLayout. Native operations additionally
need Virtuoso Bridge in the same environment, a running Virtuoso session and
accessible technology/masters. Follow [Bridge integration](docs/runtime/BRIDGE.md).
Pure codec, file-only Git and KLayout work can run without a native connection.

The branch name above is an example; choose a short topic describing the work.
Start from the intended development branch and keep unrelated edits separate.

## Make a focused change

| Area | Contribution boundary |
| --- | --- |
| `data` | Preserve canonical types, identities, duplicate multiplicity, integrity and reversible patch behavior |
| `comparison` | Keep inferred correspondence and visual classification separate from exact stored operations |
| `eda.virtuoso` | Extend capture, reference resolution, coverage, replay and readback together; verify APIs against installed Cadence docs |
| `eda.klayout` | Keep static capture, reconstruction, review and rendering consistent with the documented KLayout contract |
| `git` | Preserve unrelated staged/unstaged work, repository-local configuration and stale-preview checks |
| `ui` | Keep user confirmation, omission audits, read-only review and checkpoint-restore behavior explicit |
| `runtime` | Preserve process identity, owned resources and lease-based cleanup |
| C++ | Match the Python reference and wire protocol |

Use package-qualified imports. Importing a package must not connect to Virtuoso
or launch processes. Explain API/schema changes and compatibility effects in the
pull request. Update the relevant module guide when behavior changes; document
the current implementation without adding a release timeline.

## Validate the change

Run checks appropriate to the affected behavior. Make test inputs independent
and synthetic, and test the invariant or failure being fixed.

| Change | Validation |
| --- | --- |
| Documentation | `python scripts/check_docs.py` and `python scripts/check_publication.py` |
| Python behavior | Relevant pytest cases; use the offline suite below for changes spanning components |
| Storage or patches | Forward/reverse replay, corruption rejection, types and duplicate multiplicity |
| Native OA/ROD behavior | Dedicated test-library capture/replay and native readback; GDS XOR/labels as a separate geometry check |
| C++ kernel | Python/native byte parity and failure/fallback behavior |
| KLayout frontend | `tests/test_klayout.py`; verify desktop interaction separately from database/view API tests |

```sh
python -m pytest tests -q --basetemp=.test-tmp-run
python scripts/check_docs.py
python scripts/check_publication.py
```

Native regression drivers live under `scripts/`. Use a dedicated writable test
library and preserve existing source cellviews. Record the checks actually run,
their result and any untested dependency/environment boundary. An unavailable
native environment is a reported limitation, not a passing native result.
See [verification methodology](docs/development/VERIFICATION.md) and the
[Windows temporary-directory setup](docs/development/README.md#source-and-testing).

## Keep design and environment data local

Publish independently generated synthetic fixtures and generic examples. Do not
commit production layout captures, netlists, design names, measured design data,
foundry device recipes, credentials, private host paths or session reports.
Renaming objects or translating captured coordinates does not turn a design
capture into independent synthetic data.

Keep agent instructions and runbooks under `.local/agent/`, configuration in
ignored `.env` files, and generated output under ignored evidence/artifact paths.
Do not force-add ignored material. Review staged filenames and content before
committing; the publication checker complements manual review and provenance
checks.

## Name commits and pull requests

Use the [commit convention](docs/development/COMMITS.md):

```text
<type>(<scope>): <summary>
```

For example, `fix(git): preserve unrelated staged files during commits`.
Use the same format for the pull request title. Keep commits focused and explain
why the change is needed. The repository includes a [.gitmessage](.gitmessage)
template; from the repository root it can be enabled for this clone with:

```sh
git config --local commit.template "$(git rev-parse --show-toplevel)/.gitmessage"
```

## Submit a pull request

Describe the concrete problem, resulting behavior, validation and material
limitations. Link a related issue when one exists. Include compatibility or
migration instructions when a public API or format changes. Use the provided
[pull request template](.github/pull_request_template.md).

Keep the source-tool repository separate from design-snapshot repositories.
Do not include native deployments, captured designs or unrelated changes in the
pull request. If a screenshot helps explain UI behavior, use a synthetic layout
and remove environment/session details.
