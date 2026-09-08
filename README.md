<div align="center">

**EN** | [中文](README_CN.md)

# lang-fossil

**90% of large codebases live in the wrong historical version.**

Every legacy system carries its own geology: code written for eras that have
ended — APIs the platform has since removed, idioms the language has outlawed,
habits inherited from teams that no longer exist. Nobody planned it. Nobody
sees it whole. Every refactor decision is made half-blind.

**lang-fossil is carbon dating for your codebase.** Point it at a repository
and it reads the strata back to you: which era your code belongs to, which
APIs are already dead, which modules are still maintained in the style of a
decade ago. No configuration. No network. No rewrite — the findings arrive as
a stratigraphy report your team can act on this sprint.

*Do not ask how old your code is. Ask which era it was written for.*

</div>

---

> Archaeology for codebases — dig out fossilized legacy APIs across language eras.

`lang-fossil` is an **offline-first static analysis CLI** that scans a source
repository and reports *fossils*: syntax, idioms, and standard-library APIs
that belong to an earlier era of a language — a Python 2 `print` statement, an
`ur''` literal, a `distutils` import, a removed stdlib function — and then
aggregates them into a **stratigraphy report** grouped by language era and by
module.

It deliberately complements the lint ecosystem. A linter tells you what is
*upgradeable*; `lang-fossil` tells you what is already *dead* (APIs removed
from the standard library) and where *the same fossil recurs across strata*
(copy-pasted code). Everything runs offline against a packaged snapshot — no
network access is ever performed — which makes it CI-friendly and safe for
air-gapped codebases.

---

## Table of Contents

- [Background & Goals](#background--goals)
- [Core Features](#core-features)
- [Commands](#commands)
- [Architecture](#architecture)
- [Key Design Decisions](#key-design-decisions)
- [Repository Layout](#repository-layout)
- [Requirements & Installation](#requirements--installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Testing](#testing)
- [Extension & Maintenance](#extension--maintenance)

---

## Background & Goals

Legacy code does not die uniformly. A repository assembled over years mixes
several "geological" layers: Python 2 idioms inside a Python 3 tree, dead
standard-library imports that still parse, whole files copied between modules.
The project name is the thesis: treat a codebase like an archaeological dig and
classify what you find by era.

Goals:

1. **Detect the dead, not just the unupgradeable.** Beyond syntax-era rules,
   flag standard-library modules/APIs that have already been *removed*
   (`distutils`, `imp`, `asyncore`, `inspect.getargspec`, …) using an offline
   data snapshot instead of a hand-maintained rule list.
2. **Make technical debt legible.** Compute a *Fossil Index* (fossils per
   thousand lines), stratify findings by language era and module, and expose
   results in formats that humans (HTML), tools (JSON), and CI platforms
   (SARIF 2.1.0) can consume.
3. **Integrate with CI.** A `check` command doubles as a budget gate with a
   stable exit-code contract.
4. **Degrade, never abort.** Unparseable files, broken caches, and missing
   optional tools degrade to partial results with diagnostics — a scan never
   crashes on a hostile repository.
5. **Stay offline-first and provenance-driven.** Every finding carries where it
   came from (which lint rule, which data snapshot), so results can be traced
   back to a source of truth.

## Core Features

### Fossil detection pipeline

| Layer | Responsibility |
| --- | --- |
| **Discovery** | Recursive walk with exclusion pruning; extension-based language sniffing; null-byte (binary) and sampling filters. |
| **Parsing** | Multi-version Python front end (parso), stdlib `ast` fast path, heuristic JavaScript front end. |
| **Matching** | Built-in rule packs + data-driven zombie-API detection against parsed trees and raw lines. |
| **Stratigraphy** | Era/module/rule/severity aggregation and the Fossil Index. |
| **Reporting** | JSON (canonical), self-contained HTML, SARIF 2.1.0. |

### Differentiators

- **Zombie API detection (data-driven, offline).** Standard-library removals
  are modelled as *data* — `dead-packages.json` — supporting both module-level
  entries (`distutils`, removed in 3.12) and attribute-level entries
  (`asyncio.get_event_loop`'s semantic removal in 3.14,
  `configparser.SafeConfigParser`, `inspect.getargspec`). New removals are a
  one-line data change, no code change.
- **Code-clone fingerprints (winnowing, experimental).** Cross-file copy-paste
  detection using the classic winnowing algorithm (Schleimer *et al.*, 2003):
  k-gram hashes with a minimum-selection guarantee. Flags "the same fossil
  appearing in multiple strata" — an archaeological signal, not a general
  duplicate detector.
- **Multi-era parsing.** The Python front end parses with the interpreter's
  grammar first; when a source smells like Python 2, it retries with a vendored
  Python 2.7 grammar so Py2 corpora parse on Py3 interpreters.
- **`--fix` bridge.** Fossil → external fixer mapping (`pyupgrade`,
  `eslint --fix`) rather than reimplementing codemods. Dry-run by default;
  bridging currently covers Python & JavaScript only (other languages are
  reported explicitly).
- **Provenance on every rule.** Each built-in rule records its origin and maps
  to the existing ecosystem (`pyupgrade`, `eslint (no-var)`, …) for audit and
  training purposes.
- **External-linter annotation (`annotate`).** lang-fossil consumes
  eslint/clang-tidy/PMD reports and labels each finding with archaeology
  metadata (era/category) via rule-provenance aliases or same-line positions —
  without inventing dates for undatable findings (`unannotated`).
- **Git era-drift dimension (opt-in).** When `[tool.lang-fossil.git] enabled`
  is on, fossils carry their file's last-commit year and reports surface
  `active_fossils` — old-era code that is still being maintained.

### Supported languages

| Language | Extensions | Front end | Built-in pack |
| --- | --- | --- | --- |
| Python | `.py`, `.pyw` | parso multi-grammar + stdlib `ast` | `PF*` |
| JavaScript | `.js`, `.mjs`, `.cjs`, `.jsx` | heuristic | `JS*` |
| C | `.c`, `.h` * | heuristic | `CF*` |
| C++ | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx`, `.h` * | heuristic | `CXX*` |
| C# | `.cs` | heuristic | `CS*` |
| Java | `.java` | heuristic | `JV*` |

> \* `.h` is ambiguous between C and C++. The scan settings resolve it without
> reading the file: `ambiguous_headers.mode` (`auto` decides from the sibling
> directory's `.c`/`.cpp` tallies, defaulting to C) plus glob `overrides`
> matched against the repository-relative path (see Configuration).

Findings are classified into two categories. **Fossils** — constructs removed
or deprecated by a language standard — are stratified by **era**: the
Python-era labels (`paleozoic`, `mesozoic`, `cenozoic`) plus per-language
generation strata (`c90`, `cpp98`, `cs1`, `java-legacy`, …). **Unsafe**
findings (bad practices still legal today, e.g. `sprintf`, `var`, `eval`)
appear under their own `unsafe` stratum and are never dated as fossils.

## Commands

| Command | Purpose |
| --- | --- |
| `dig` | Scan a repository and emit table/JSON/HTML/SARIF reports. |
| `check` | CI budget gate: fail when the Fossil Index or fossil count exceeds thresholds. |
| `diff` | Compare two JSON reports (`introduced` / `resolved` fossils). |
| `rules` | List built-in rules with language, era, mode, and provenance. |
| `annotate` | Import an eslint/clang-tidy/PMD report and label findings with era/category metadata. |
| `fix` | Print (or, with `--apply`, run) external fixer commands for fixable fossils (bridged: Python & JavaScript). |

Exit codes are a stable API for CI: `0` pass, `1` budget exceeded,
`2` configuration/input error, `64` usage error.

## Architecture

```
        ┌──────────────┐
        │     CLI       │  typer entry points (dig/check/diff/rules/fix)
        └──────┬───────┘
               │
   config.py ──┤  precedence: CLI > env (LANG_FOSSIL_*) > TOML > defaults
               ▼
   ┌────────────────────────────────────────────────┐
   │ discover → parse → engine → stratigraphy → report │
   └────────────────────────────────────────────────┘
        parse      parso_py (multi-grammar) / ast_py / heuristic
                   (js, c, cpp, csharp, java)
        engine     rule packs (YAML, validated) + zombie DB (data-driven)
        importers  eslint / clang-tidy / PMD report parsers
        annotate   provenance-alias + same-line labeling of external findings
        infra      content-hash sqlite cache · read-only git wrapper ·
                   offline snapshot loader
        reporting  json_report (canonical) · html_report (embeds JSON) ·
                   sarif_report
```

Layers follow a strict dependency direction — `cli` and `core` never reach
into parser internals, and business modules receive validated configuration
by injection rather than reading the environment themselves.

## Key Design Decisions

Architecture decisions are recorded as ADRs under `docs/adr/`; the essentials:

1. **Degrade, never abort.** Parsing failures, cache corruption, and missing
   optional binaries are converted into structured diagnostics
   (`ParseResult.errors`, cache misses) instead of exceptions. Only *hard*
   configuration errors abort, fail-fast, at startup.
2. **Config is validated once, at the boundary.** All settings (TOML, env, CLI)
   merge into a single pydantic model (`extra="forbid"`) before any business
   code runs. Env values use the `LANG_FOSSIL_` prefix and `__` nesting
   delimiter (`LANG_FOSSIL_SCAN__WORKERS=4`).
3. **Rules as data, zombies as data.** YAML rule packs are validated against a
   pydantic whitelist schema (unknown keys are load errors). Removed stdlib
   APIs live in a versioned offline snapshot; the snapshot version is folded
   into the scan-cache key so a data update invalidates stale results.
4. **Canonical JSON, multiple views.** The JSON document is the single source
   of truth; HTML embeds it verbatim for archival and `diff` reads it back.
5. **Content-addressed cache.** Per-file results are cached keyed on
   `sha256(source ‖ rules digest)`; paths are re-attached on retrieval so
   renamed content still hits. The cache is best-effort and thread-safe for
   the parallel scan workers.
6. **Security posture.** `yaml.safe_load` only; git is invoked read-only with a
   verb whitelist and list-form arguments (`shell=False`); HTML output is
   autoescaped and embedded JSON neutralises `</script>`.
7. **Heuristics are explicit.** JavaScript and pre-Py2 corpora are regex-only
   and tagged `heuristic`; consumers can annotate confidence accordingly.

## Repository Layout

```
lang-fossil/
├── pyproject.toml             PEP 621 metadata; PDM backend; ruff/black/mypy/pytest
├── pdm.lock                   locked dependency set (CI --frozen-lockfile)
├── README.md / README_CN.md   this document (中文版见 README_CN.md)
├── LICENSE / CHANGELOG.md     changelog with versioned milestone entries
├── codecov.yml                coverage thresholds for the Codecov app
├── data/
│   └── dead-packages.json     generated removal snapshot (repo-level copy)
├── scripts/
│   ├── deprecation-sources.yaml  curated removal manifest (single source of truth)
│   └── sync_deprecations.py   check/verify/write pipeline for the snapshots
├── src/lang_fossil/
│   ├── cli/                   typer commands + exit-code contract
│   ├── config.py              unified settings (pydantic-settings)
│   ├── core/
│   │   ├── scanner.py         discovery + orchestration (thread pool)
│   │   ├── engine.py          rule matching + zombie detection driver
│   │   ├── models.py          frozen domain dataclasses
│   │   ├── stratigraphy.py    era aggregation & Fossil Index
│   │   ├── zombie_api.py      removed-stdlib-API detection
│   │   ├── clone.py           winnowing clone fingerprints
│   │   ├── annotate.py        external-finding era labeling (annotate cmd)
│   │   ├── fixer.py           fossil → external fixer mapping
│   │   └── enricher.py        optional git "carbon dating" (opt-in)
│   ├── importers/             eslint · clang-tidy · PMD report parsers
│   ├── parsers/
│   │   ├── base.py            Parser protocol
│   │   ├── parso_py.py        multi-grammar Python (Py2 fallback)
│   │   ├── ast_py.py          stdlib ast fast path
│   │   ├── js_heuristic.py    regex-level JavaScript front end
│   │   └── grammars/          vendored Python 2.7 parso grammar (see ADR-0003)
│   ├── rules/                 registry + pydantic-validated rule packs
│   │   └── builtin/           <language>/packs: python, javascript, c,
│   │                          cpp, csharp, java (see Supported languages)
│   ├── reporting/             json (canonical) · html · sarif writers
│   ├── infra/                 sqlite cache · read-only git · snapshot loader
│   └── data/dead-packages.json  versioned snapshot shipped in wheels
├── tests/
│   ├── unit/                  mirrors src/ one-to-one
│   ├── integration/           CLI end-to-end (exit codes, report files)
│   ├── golden/                Py2/mixed-era corpora (release gate)
│   └── perf/                  wall-clock benchmark
└── docs/                      rules-guide.md · adr/ · archive/ (git-ignored)
```

## Requirements & Installation

**Runtime requirements**

- Python ≥ 3.9 (CI matrix runs 3.9–3.13 across Linux/macOS/Windows).
- No network access is required at scan time.

**Install from source (PDM — recommended for development)**

```bash
git clone <repo-url> && cd lang-fossil
pdm install -G:all          # installs runtime + test + lint tooling
```

**Install from source (plain pip)**

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | POSIX: source .venv/bin/activate
pip install -e .            # runtime dependencies are declared in pyproject.toml
pip install pytest pytest-cov ruff black mypy   # developer tooling
```

**Install as a tool**

```bash
pipx install lang-fossil            # core CLI, fully offline
pipx install 'lang-fossil[git]'     # optional git-enrichment extra
```

> Note: the optional `[git]` extra reserves `GitPython` for future enrichment.
> The current carbon-dating implementation shells out to the system `git`
> binary over read-only, verb-whitelisted subprocess calls and does not require
> the extra at runtime.

## Configuration

Settings are read in strict precedence order and validated once:

```
CLI flags > environment variables > [tool.lang-fossil] in pyproject.toml > defaults
```

### TOML (`pyproject.toml`)

```toml
[tool.lang-fossil]
max_fossil_index = 0.5          # optional default for `check`

[tool.lang-fossil.cache]
enabled = true
path = ".lang-fossil/cache.db"  # sqlite scan cache
timeout_seconds = 5.0

[tool.lang-fossil.scan]
workers = 0                     # 0 = min(CPU, 8); 1..16 explicit
exclude = ["node_modules", ".venv", "venv", "dist", "build"]
parse_timeout = 5.0
sample_ratio = 1.0              # < 1.0 = deterministic sampling

[tool.lang-fossil.scan.ambiguous_headers]   # .h resolution (no content scoring)
mode = "auto"                   # auto | c | cpp
[tool.lang-fossil.scan.ambiguous_headers.overrides]
"legacy_lib/*.h" = "c"          # repo-relative globs beat `mode`

[tool.lang-fossil.git]          # optional carbon dating (default off)
enabled = false
blame_batch = 200
```

### Environment variables

Environment keys mirror the model with a `LANG_FOSSIL_` prefix and `__` as the
nested delimiter:

```bash
export LANG_FOSSIL_SCAN__WORKERS=8
export LANG_FOSSIL_CACHE__ENABLED=0        # disable the scan cache
export LANG_FOSSIL_MAX_FOSSIL_INDEX=0.8    # Optional[T] fields are supported
export LANG_FOSSIL_DATA_DIR=/path/to/data  # override snapshot location
```

Unknown keys and out-of-range values raise `ConfigError` (exit code `2`)
instead of being silently ignored.

## Usage

Scan a directory and print the stratigraphy table:

```bash
lang-fossil dig ./sample-repo
```

Write a self-contained HTML report (embeds the canonical JSON):

```bash
lang-fossil dig ./sample-repo --format html -o report.html
```

Write JSON / SARIF reports:

```bash
lang-fossil dig ./sample-repo --format json  -o report.json
lang-fossil dig ./sample-repo --format sarif -o report.sarif
```

CI budget gate — exits `1` when exceeded:

```bash
lang-fossil check ./sample-repo --max-fi 0.5 --max-fossils 20
```

Compare two JSON reports (track `introduced` / `resolved` fossils over time):

```bash
lang-fossil diff baseline.json current.json
```

List built-in rules with provenance:

```bash
lang-fossil rules
```

Bridge fixable fossils to external fixers (dry run, then apply):

```bash
lang-fossil fix ./sample-repo
lang-fossil fix ./sample-repo --apply    # requires pyupgrade / eslint installed
```

### Example output

```
$ lang-fossil dig ./legacy-sample
┌───────────────┬─────────┬──────────────────────────┐
│ Era           │ Fossils │ Top modules              │
├───────────────┼─────────┼──────────────────────────┤
│ paleozoic     │       6 │ legacy (6)               │
│ mesozoic      │       1 │ modern (1)               │
│ cenozoic      │       2 │ legacy (2)               │
└───────────────┴─────────┴──────────────────────────┘
fossil index: 1.90/kLOC, files: 14, clones: 1, parse errors: 0
```

Notes:

- The terminal table always prints; file output goes to `--output` or to
  `lang-fossil-report.<fmt>`.
- `--no-embed` writes an HTML shell plus a sibling `.json` data file; that
  variant requires an HTTP server (`python -m http.server`) because browsers
  block `file://` JSON fetches. The default embedded HTML works from disk.
- `--no-cache` disables the content-hash cache; `--workers 1` forces a single
  thread.

## Testing

The test suite mirrors the source tree and is organised into four layers:

```bash
pytest tests/unit            # fast unit tests (one module per src module)
pytest tests/integration     # CLI end-to-end: exit codes, report files
pytest tests/golden -m golden # release gate: Py2 corpora must parse & hit rules
python tests/perf/bench_scan.py --files 100   # wall-clock benchmark vs budget
```

Static analysis and type checking (all enforced in CI):

```bash
ruff check src tests
ruff format --check src tests
mypy src
```

Coverage gates are layered in CI (core module coverage and overall coverage);
run locally with:

```bash
pytest tests --cov=lang_fossil --cov-report=term-missing
```

The golden corpus is the compatibility contract: any change that shifts the
snapshotted expected hits is a deliberate release decision and must be
reviewed as such.

## Extension & Maintenance

**Add a rule.** Author a YAML rule in `src/lang_fossil/rules/builtin/<lang>/`
(or a custom directory loaded via `RuleRegistry.load_from_dir`), follow the
schema in `docs/rules-guide.md`, add positive/negative samples in the pack's
`samples/samples.yaml`, and run the registry + golden tests. Rule ids must
match `^[A-Z]{2,4}\d{3}$` and carry `provenance`.

**Record a standard-library removal.** Add the entry to the curated manifest
`scripts/deprecation-sources.yaml` (module-level, or attribute-level with a
*single-segment* attribute name; optionally with an official `ref_url`), then
run `python scripts/sync_deprecations.py write` — it regenerates both snapshot
copies and bumps `snapshot_version`. The scan cache key incorporates the
version, so stale results invalidate automatically; `sync_deprecations.py
check` verifies the two copies never drift (CI-friendly).

**Support a new language.** Add its extensions to the single registry in
`src/lang_fossil/core/language.py` (resolve any ambiguous extensions through
the `ambiguous_headers`-style config policy, never by content scoring),
register a parser in the `scanner` `parsers` table, extend the
`RuleSpec.language` literal, and author a rule pack under
`rules/builtin/<language>/`. Every rule declares its `category` (fossil rules
also carry `deprecated_in`/`removed_in`). A regex/heuristic front end (generic
`HeuristicParser`) is the pragmatic first step; an AST front end can follow for
languages that need tree matching.

**Add a report format.** Write a module under `reporting/`, keep the canonical
JSON document as the source of truth, and wire it into the `dig` dispatcher.

**Performance.** Track regressions against `tests/perf/bench_scan.py`; the
per-file scan budget is in the milliseconds range. Clone detection and zombie
attribute walks are documented with their scaling characteristics in code
comments.

**Engineering practices.** Maintain ruff/black/mypy-strict cleanliness, keep
the test tree mirrored to `src/`, cover release gates with the golden corpus,
and record architectural changes as new ADRs in `docs/adr/`.

---

## License

MIT — see [LICENSE](LICENSE).
