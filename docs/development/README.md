# Development

Start with [CONTRIBUTING.md](../../CONTRIBUTING.md) for the contribution workflow
and [commit naming](COMMITS.md) for subject types, component scopes and templates.

Use `uv` and a virtual environment; never install into global Python.

```sh
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e ".[verify]"
```

Linux uses `.venv/bin/python`. Activate the environment before running examples.
Native operations additionally require Virtuoso Bridge, Virtuoso, and accessible
technology and masters. Bridge is not installed by this project's dependency
metadata. Follow [Bridge integration](../runtime/BRIDGE.md) to install it in the
same environment and verify the CIW connection before native work.

## Source and testing

The [program map](../architecture/PROGRAM_STRUCTURE.md) describes the packages.
Use canonical imports such as `layoutdiff.data.core` and `layoutdiff.git.commit`.
Package imports must not start processes or connect to a live database.

```sh
python -m pytest tests -q --basetemp=.test-tmp-run
python scripts/check_docs.py
python scripts/check_publication.py
```

Pure codec, Git and KLayout tests run without a live design environment. Native
tests need a dedicated writable test library and must preserve source views.
Verify SKILL against the documentation installed with the target Virtuoso version.

Reusable native regression drivers remain under `scripts/`. Create a writable
`LAYOUT_DIFF_TEST` library attached to a suitable technology before running them.
For example, `python scripts/regression.py --seeds 2 --steps 3` exercises seeded
geometry edits, replay and native readback; the hierarchy, group, omission,
workflow and review drivers exercise their respective features. Technology
layers and via definitions used by a driver must exist in the test environment.
Keep design-specific surveys and session replay scripts local.

In restricted Windows environments, point temporary storage into the checkout
before running the suite:

```powershell
$env:TMP = Join-Path (Get-Location).Path '.cache/test-temp'
$env:TEMP = $env:TMP
$env:TMPDIR = $env:TMP
$env:PYTHONPATH = (Get-Location).Path
New-Item -ItemType Directory -Path $env:TMP -Force | Out-Null
```

Preview cleanup with `./scripts/clean_local_artifacts.ps1 -WhatIf`; omit `-WhatIf`
to remove generated evidence, caches and temporary repositories. Cleanup preserves
`.git`, virtual environments, `.local/`, source and permanent synthetic fixtures.

## Documentation maintenance

Organize reference material under the owning package: `data/`, `comparison/`,
`eda/`, `git/`, `ui/`, and `runtime/`. Keep tool-specific guides under
`eda/virtuoso/` and `eda/klayout/`. Use `architecture/` for flows spanning
packages and `native-performance/` for the optional C++ component. Findings should
describe reusable API behavior without source-design names, PDK recipes, private
paths, session IDs, checkpoint IDs, dates, or measured production-layout data.
Use synthetic examples and relative Markdown links. Run link and publication
checks after editing documentation.

## Local agent material

Store local-only instructions, session reports and migration backups beneath
`.local/agent/`. The shared `.gitignore` excludes all of `.local/`; cleanup skips
it. Keep `.env` local. Never force-add private material. A committed deletion does
not remove earlier copies: inspect every branch and tag before publication.

## Current-release documentation

`pyproject.toml` identifies the current release. Keep the documentation index
aligned with it and describe the current implementation in the present tense.
Remove release timelines, superseded instructions and unimplemented proposals.
Document supported formats and compatibility behavior as current capabilities;
schema versions identify data contracts, independently of application releases.
Run the relevant checks before tagging a validated source revision.

Use `<type>(<scope>): <summary>` for commit subjects and pull request titles.
The [commit convention](COMMITS.md) defines the available types and scopes.

Source history and layout snapshot repositories are separate. Source maintenance
must not modify a designer's runtime or design repository.
