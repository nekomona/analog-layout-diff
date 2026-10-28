# Development

Use `uv` and a virtual environment; never install into global Python.

```sh
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e ".[verify]"
```

Linux uses `.venv/bin/python`. Activate the environment before running examples.
Native operations additionally require Virtuoso Bridge, Virtuoso, and accessible
technology and masters. See the [GUI guide](VIRTUOSO_GUI.md).

## Source and testing

The [program map](architecture/PROGRAM_STRUCTURE.md) describes the packages.
Use canonical imports such as `layoutdiff.data.core` and `layoutdiff.git.commit`.
Package imports must not start processes or connect to a live database.

```sh
python -m pytest tests klayout_plugin/tests -q --basetemp=.test-tmp-run
python scripts/check_docs.py
python scripts/check_publication.py
```

Pure codec, Git and KLayout tests run without a live design environment. Native
tests need a dedicated writable test library and must preserve source views.
Verify SKILL against the documentation installed with the target Virtuoso version.

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

Keep user-facing behavior in operating guides, serialization in the format
specifications, and implementation structure in `architecture/`. Findings should
describe reusable API behavior without source-design names, PDK recipes, private
paths, session IDs, checkpoint IDs, dates, or measured production-layout data.
Use synthetic examples and relative Markdown links. Run link and publication
checks after editing documentation.

## Local agent material

Store local-only instructions, session reports and migration backups beneath
`.local/agent/`. The shared `.gitignore` excludes all of `.local/`; cleanup skips
it. Keep `.env` local. Never force-add private material. A committed deletion does
not remove earlier copies: inspect every branch and tag before publication.

## Releases

Update `pyproject.toml` and the behavior-focused [changelog](CHANGELOG.md), run
relevant checks, and tag the validated revision. Source history and layout
snapshot repositories are separate; source maintenance must not touch a
designer's runtime or design repository.
