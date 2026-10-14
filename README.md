# git-quality-gates

Git hooks and CI checks that keep a repository's commit history, comments and prose
consistent. The gates are plain Python with no dependencies, read only the lines a change
adds, run on your machine, and send nothing anywhere. They work on any language because
they read git diffs and commit messages, not syntax trees.

| Gate | Enforces | Why |
|------|----------|-----|
| `commit-message` | Subject is `type(scope): description` with a known type and no trailing period | Changelogs and release notes are built from subjects, and history cannot be relinted after a push |
| `attribution` | No AI-attribution trailers or "Generated with" lines in commit messages | Keeps authorship statements true; a `prepare-commit-msg` hook strips them before they are stored |
| `regression-test` | A `fix` commit that touches guarded source also touches a test, or carries `No-test: <reason>` | A fix without a test is lost at the next refactor |
| `comment` | Added comments describe what the code does, not what it used to do | A history comment is true on the day it is written and wrong on every day after; history belongs in the commit message |
| `writing` | No em or en dashes, curly quotes, emoji, filler vocabulary or "This document provides" openers in added lines | One plain-text standard for docs, comments and messages |
| `prose` | British spellings, wordy phrases, doubled words and `a`/`an` slips in Markdown and source comments | American English drifts unseen in review |
| `license` | Every vendored library is under an allowed license; GPL and AGPL are banned, LGPL needs a written exception | A copyleft file copied into a tree is easy to miss and expensive to remove |
| changelog sync (optional) | Appends `feat`, `fix`, `perf`, `refactor`, `revert` and `security` commits to `[Unreleased]` | The changelog cannot fall behind the code |

## Install

```sh
uv tool install git+https://github.com/ragonxdragon/git-quality-gates
git-quality-gates init       # writes a commented .quality-gates.toml (optional)
git-quality-gates install    # installs the git hooks into this clone
```

`install` needs a POSIX `sh` (Git for Windows provides one). It copies the hooks into
`.git/hooks`, or into `core.hooksPath` when that is set. It will not replace a hook it did
not write unless you pass `--force`, which keeps the old one as `<hook>.orig`.
`git-quality-gates install --uninstall` removes only its own hooks and restores any
`.orig` files. If the tool is missing from `PATH` when a hook runs, the hook prints a
warning and lets the commit through, so CI is the backstop.

Python 3.11 or newer is required. `pip install` works in place of `uv tool install`.

### pre-commit framework

The repository ships a `.pre-commit-hooks.yaml`. Add it to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/ragonxdragon/git-quality-gates
    rev: v0.1.0
    hooks:
      - id: commit-message
      - id: writing
      - id: comments
```

Then run `pre-commit install --hook-type pre-commit --hook-type commit-msg`.

## Example failures

A commit message that does not parse:

```text
[commit-msg] BLOCKED: does not parse as type(scope): description: 'fixed a bug'
[commit-msg] expected: type(scope): description
```

A fix with no test:

```text
BLOCKED: a fix ships with its test
  this commit is a fix that changes src/a.py and touches no test. Add the test that fails
  against the unfixed code, or add a trailer: No-test: <why no test could fail>

Bypass once with GQG_SKIP=regression-test (logged).
```

A comment that narrates history:

```text
BLOCKED: comments that narrate history, added lines only
  src/a.py:2  [narrates a change]  'we now'

Describe what the code does now and put the history in the commit message.
End a line with comment-allow to allow it, or bypass once with GQG_SKIP=comment (logged).
```

A dash and a filler opener:

```text
BLOCKED: writing standard, added lines only
  notes.md:1  [filler opener]  start with the content
  notes.md:2  [em or en dash]  use a comma, period, colon or parentheses
```

A banned license:

```text
BLOCKED: license allowlist
  gplthing: GPL-3.0 is banned
```

## Commands

Hooks call these for you. CI calls the gate commands directly.

| Command | What it does |
|---------|--------------|
| `comment [--range A..B]` | Comment gate on the staged diff, or on a revision range |
| `writing [--range A..B]` | Writing gate on the staged diff, or on a revision range |
| `prose [--fix] [paths]` | Spelling and wording over tracked Markdown and source comments; `--fix` rewrites spelling and terms |
| `license [--root DIR]` | License gate over the vendored libraries |
| `regression --staged FILE` or `--range A..B` | Fix-needs-a-test gate for one message file or a range |
| `commit-messages [RANGE or --all]` | Conventional Commit check over a range; the default is since the last `v*` tag |
| `pick-range EVENT --pr-base SHA --pr-head SHA --before SHA --sha SHA` | The commit range a CI run should check (see below) |
| `init`, `install`, `config KEY`, `changelog` | Setup and helpers |
| `pre-commit`, `commit-msg FILE`, `prepare-commit-msg FILE`, `pre-push` | What the installed hooks run |

`pick-range` prints `merge-base..head` for a pull request and `before..sha` for a push. It
prints nothing for a new branch, a force push or a manual run, because those ranges reach
back through history the rules did not cover. The reason goes to stderr as a GitHub notice.

## Configuration

Everything lives in one optional file at the repository root, `.quality-gates.toml`. Every
key has a default; a file overrides only the keys it names. An unknown table, an unknown key
or a value of the wrong type is an error, so a typo cannot silently leave a gate on its
defaults. `git-quality-gates init` writes the full file with the defaults.

| Table | Key | Default | Meaning |
|-------|-----|---------|---------|
| `gates` | `disabled` | `[]` | Gates to switch off: `commit-message`, `attribution`, `regression-test`, `comment`, `writing`, `prose`, `license` |
| `paths` | `exclude` | `vendor/`, `third_party/`, `node_modules/`, `.git/`, `.venv/`, `dist/`, `build/` | Path prefixes the content gates never read |
| `commit_message` | `types` | `feat fix perf refactor revert security docs chore style test ci build` | Allowed Conventional Commit types |
| `commit_message` | `extra_attribution_patterns` | `[]` | Extra case-insensitive regular expressions matched against message lines |
| `regression_test` | `fix_types` | `["fix"]` | Commit types that owe a test |
| `regression_test` | `guarded_prefixes` | `["src/"]` | A commit touching these paths owes a test |
| `regression_test` | `test_globs` | `test/**`, `tests/**`, `**/test_*.py`, `**/*_test.py`, `**/*_test.go`, `**/*.test.*`, `**/*.spec.*`, `**/test-*.sh` | What counts as a test (`**` crosses directories) |
| `regression_test` | `min_reason_chars` | `20` | Minimum length of a `No-test:` reason |
| `writing` | `extra_vocabulary` | `[]` | Words to reject on top of the built-in list |
| `prose` | `source_roots` | `[]` | Directories whose source comments are spell-checked; empty means every tracked source file |
| `prose` | `terms` | `{}` | Term fixes such as `{ WiFi = "Wi-Fi" }` |
| `license` | `vendor_dirs` | `["vendor", "third_party"]` | Each directory directly under these is one library |
| `license` | `allowed` | `MIT Apache-2.0 BSD-2-Clause BSD-3-Clause ISC Zlib` | Accepted SPDX identifiers |
| `license` | `banned_prefixes` | `["GPL", "AGPL"]` | Identifier prefixes that always fail |
| `license` | `lgpl_prefix` | `"LGPL"` | Identifiers with this prefix fail unless listed under `exceptions` |
| `license` | `declared` | `{}` | Licenses for libraries with no license file, each backed by a pattern found in a named file |
| `license` | `exceptions` | `[]` | Accepted exceptions: `library`, `license` and a `reason` of 20 or more characters |
| `changelog` | `sync` | `false` | Turn on the post-commit changelog hook |
| `changelog` | `file` | `"CHANGELOG.md"` | File the hook edits |
| `changelog` | `product_paths` | `["src/"]` | A `docs`, `chore`, `style`, `test`, `ci` or `build` commit touching these gets a note |
| `hooks` | `pre_commit_commands` | `[]` | Commands the pre-commit hook runs after the gates (split into arguments, no shell) |
| `hooks` | `pre_push_commands` | `[]` | Commands the pre-push hook runs; a non-zero exit blocks the push |

Example: a Go service that allows its own `lib/` directory, bans a custom word, and checks
vendored licenses.

```toml
[commit_message]
types = ["feat", "fix", "docs", "chore", "test", "ci"]

[regression_test]
guarded_prefixes = ["cmd/", "internal/"]

[license]
vendor_dirs = ["vendor", "third_party"]

[[license.exceptions]]
library = "somelib"
license = "LGPL-3.0"
reason = "Dynamically linked and unmodified; replacement tracked upstream."
```

### How each gate reads your repository

- **Line-level gates** (`comment`, `writing`) read only added lines of a `-U0` diff, so old
  text in a file never blocks an edit. End a line with `comment-allow` or `humanizer-allow`
  to allow it.
- **Comment gate** knows `//` and block comments (C-family, Java, Go, Rust, JavaScript,
  TypeScript, C#, Swift, Kotlin, Scala, PHP) and `#` comments (Python, shell, Ruby, YAML,
  PowerShell, TOML, INI, Terraform). It cannot see a comment that restates the code.
- **License gate** reads, per library, every `LICENSE` or `COPYING` file at any depth
  (identified by its text), then the `license` field of `library.json` or `package.json`.
  Sources that disagree fail, and so does an exception that no longer matches a library.
  It checks vendored copies, not package-manager lock files.
- **Regression gate** cannot tell whether the test fails against the unfixed code. Review
  confirms that: write the test, watch it fail, then fix.

## Bypass, and how it is logged

A gate can be skipped for one command by naming it:

```sh
GQG_SKIP=comment,writing GQG_SKIP_REASON="quoted vendor text" git commit -m "docs: quote upstream notice"
GQG_SKIP=all git commit ...        # every gate
GQG_SKIP=pre-push git push         # the pre-push commands
```

Names are the gate names in the table above, plus `pre-commit-commands` and `pre-push`.
Each skipped gate prints a notice on stderr and appends one tab-separated line to
`quality-gates-bypass.log` inside the git directory (`.git/quality-gates-bypass.log`):
UTC time, user, gate, short HEAD, and the text of `GQG_SKIP_REASON`. The log stays in the
clone and is never committed. Other deliberate exits:

- `comment-allow` or `humanizer-allow` at the end of a line allows that one line.
- A `No-test: <reason>` trailer excuses a fix commit and stays in the commit message,
  where review reads it.
- `[gates].disabled` in `.quality-gates.toml` turns a gate off for everyone, in a
  reviewed, committed change.
- `git commit --no-verify` skips the hooks entirely and cannot be logged by a hook. That is
  why the CI job runs the same gates over the pushed commits.

## CI

The workflow in `.github/workflows/ci.yml` runs this repository's own gates over its own
history on every push and pull request, after lint and tests. Copy it as a starting point:

```yaml
- uses: actions/checkout@<sha>
  with:
    fetch-depth: 0   # the range gates refuse a shallow clone
- uses: astral-sh/setup-uv@<sha>
- run: uv tool install git+https://github.com/ragonxdragon/git-quality-gates
- run: |
    range=$(git-quality-gates pick-range "$EVENT" --pr-base "$PR_BASE" --pr-head "$PR_HEAD" --before "$BEFORE" --sha "$SHA")
    if [ -n "$range" ]; then
      git-quality-gates commit-messages "$range"
      git-quality-gates regression --range "$range"
      git-quality-gates comment --range "$range"
      git-quality-gates writing --range "$range"
    fi
    git-quality-gates license
```

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Shell-hook tests need a POSIX `sh` and are skipped without one. To run the hooks against a checkout of this tool, install them with
`sh src/git_quality_gates/data/install-hooks.sh` and set
`GQG_CMD="uv run git-quality-gates"` in your shell. Each hook runs `$GQG_CMD` when it is
set and the installed `git-quality-gates` otherwise.

## License

MIT. See `LICENSE`.
