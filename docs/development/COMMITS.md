# Commit and pull request naming

Use Conventional Commits-style subjects for new commits and pull request titles:

```text
<type>(<scope>): <summary>
```

Type and scope are lowercase. Scope is optional for a change that intentionally
spans components. Write an imperative English summary, start it with a lowercase
verb, omit a final period, and aim for at most 72 characters including the prefix.

## Types

| Type | Use |
| --- | --- |
| `feat` | Add a user-visible capability |
| `fix` | Correct behavior or a regression |
| `docs` | Change documentation without changing runtime behavior |
| `refactor` | Restructure implementation while preserving behavior |
| `perf` | Improve performance without changing the contract |
| `test` | Add or improve tests and synthetic fixtures |
| `build` | Change packaging, compilation or build configuration |
| `ci` | Change automated checks or CI configuration |
| `chore` | Maintain repository tooling or metadata |
| `revert` | Revert an earlier change; identify it in the body |

Choose the type for the main outcome. A bug fix accompanied by regression tests
is still `fix`; `test` describes a change whose main outcome is test coverage.

## Scopes

Choose the narrowest owning component from the
[program structure](../architecture/PROGRAM_STRUCTURE.md).

| Scope | Area |
| --- | --- |
| `data` | Canonical model, storage, exact operations and standalone chains |
| `comparison` | Matching, classification, categories and paging |
| `virtuoso` | Native capture/replay, coverage and readback |
| `git` | Snapshot history, commit transactions and textconv |
| `ui` | CLI, toolbar, browser, review and restore |
| `runtime` | Supervisor/worker, deployment and cleanup |
| `native` | Optional C++ backend |
| `klayout` | Separate static-layout frontend |
| `docs` | Cross-component reference documentation |
| `tests` | Shared test infrastructure or fixtures |
| `tooling` | Development and maintenance scripts |
| `deps` | Dependency requirements or environment setup |
| `project` | Project introduction, contribution policy and root metadata |

For documentation about one component, use its scope, such as `docs(runtime)`.
Avoid design-library names, source-cell names or local session identifiers in
commit subjects or bodies.

## Examples

```text
fix(git): preserve unrelated staged files during commits
perf(comparison): bound candidate searches for large via sets
docs(runtime): explain Bridge profile and port selection
test(data): cover duplicate records in reverse replay
docs(project): clarify contribution and commit conventions
```

## Body and footers

Separate the subject from the body with a blank line. Explain the problem, the
resulting behavior and relevant validation. Include an issue reference only when
there is a real associated issue.

Mark a compatibility-breaking change with `!` before the colon and a
`BREAKING CHANGE:` footer explaining the impact and migration. The same rule
applies to PR titles when the submitted change breaks a public API or format.
Do not label ordinary internal refactoring as a breaking change.

## Local template

Enable the repository's [commit template](../../.gitmessage) from the root:

```sh
git config --local commit.template "$(git rev-parse --show-toplevel)/.gitmessage"
```

`git commit` then opens the template in the configured editor. Comments are
guidance; replace them with the actual message. A `git commit -m` message bypasses
the template and must follow the same convention. This is an editor aid, not an
installed validation hook. No global Git configuration is changed.
