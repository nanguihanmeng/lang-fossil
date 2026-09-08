# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-09-08

### Added

- Git "era drift" dimension (batch 3): the optional enricher is now wired
  into scans and reports. `Fossil` carries `last_commit_year`; JSON/HTML
  summaries expose `git_dated_fossils` and `active_fossils` (fossils in files
  committed within the last two years = actively maintained legacy). Opt-in
  via `[tool.lang-fossil.git] enabled = true` (default stays off).
- External linter report import + archaeology labeling (batch 2): new
  `annotate` CLI command and `lang_fossil.importers` package consuming eslint
  JSON, clang-tidy textual diagnostics and PMD XML reports. Findings are
  labeled with era/category/provenance via a provenance-alias channel or a
  same-line position channel; undateable findings stay `unannotated`.
- Rule `source` field (batch 4): optional official reference URL backing a
  removal/deprecation claim.
- Versioned, generated dead-package snapshots (batch 4): the offline
  snapshot is now rendered from a curated manifest
  (`scripts/deprecation-sources.yaml`) by `scripts/sync_deprecations.py`
  (`check`/`verify`/`write`), keeping the two JSON copies in sync with
  `schema_version`, `sources`, and a `snapshot_version` stamp. Runtime stays
  offline-first.
- `codecov.yml` + hardened Codecov upload step (never fails CI).
- Lockfile `pdm.lock` for `pdm install --frozen-lockfile` CI installs.
- Weekly snapshot-sync CI gate (`sync.yml`): offline `check` keeps both
  dead-package copies in sync with the curated manifest.
- `fix` now states languages with fix hints but no bridged fixer, so users
  are never left guessing why a hinted fossil produced no command.
- Community contribution workflow documented in `docs/rules-guide.md`
  (custom rule packs via `load_from_dir`, snapshot entries via the manifest).

### Changed

- `docs/rules-guide.md` documents the importer formats, `annotate`, the
  `source` field, and the snapshot sync workflow.
- ADR-0006 (git era-drift), ADR-0007 (external linter annotation),
  ADR-0008 (data-driven snapshot sync); ADR-0003 gains an upstream-maintenance
  risk addendum (parso pinned `>=0.8,<0.10`; degradation chain documented).
- Dead-package snapshot extended with the remaining Python 3.13 removals
  (`aifc`, `chunk`, `crypt`, `lib2to3`, `tkinter.tix`) and regenerated from
  the manifest.
- Clone detection documented as an experimental archaeological signal
  (not a general-purpose duplicate detector); `fix` bridging scope
  (Python & JavaScript) stated in output and README.

### Fixed

- `annotate` position channel no longer reads files outside the scan root
  (report paths are not trusted: `..`/absolute paths are rejected; see the
  v0.4.0 code-review report, finding #1).
- PMD provenance aliases now match case-insensitively; previously the
  human-cased `PMD (Rule)` declarations never fired against lower-case
  importer tags (finding #4 surfaced this by a consistency test).
- Heuristic language set is derived from the single `SUPPORTED_LANGUAGES`
  registry instead of a second hard-coded tuple in the scanner (finding #2).
- Reserved `meta`/`unsafe`/`LF-IO` identifiers centralized in `core/models`
  and referenced everywhere they carry aggregation semantics (finding #3).
- `fix --apply` inserts the `--` end-of-options separator for dash-prefixed
  file paths (finding #6/argument injection surface).
- perf job step renamed to `Collect scan benchmark` (no baseline diff was
  implemented); bench sanity-ceiling comment states its real semantics
  (finding #5).
- Removed dead `_SNAPSHOT_COPIES` constant in the sync script.

## [0.3.0] - 2026-09-08

### Added

- Rule `category` semantics (`fossil` vs `unsafe`): only constructs that were
  removed/deprecated by a language standard are age-dated fossils; unsafe /
  bad-practice patterns (still legal today) are review findings that never
  masquerade as age signals.
- Rule version metadata (`deprecated_in` / `removed_in`) with schema
  validation: a fossil rule must carry a version label; unsafe rules must use
  the reserved `unsafe` era and carry no version labels.
- `unsafe_count` on the stratigraphy report/JSON summary with its own
  (near-last) stratum; `dig`/HTML surfaces it; `rules` shows Category and
  Dep./Removed columns.
- Configurable ambiguous-header policy (`[tool.lang-fossil.scan]
  ambiguous_headers`): `mode` (`auto`/`c`/`cpp`) + glob `overrides`, with
  `auto` deciding from sibling `.c`/`.cpp` tallies (no content reading).
- Tests: schema consistency, header policy matrix, unsafe stratum isolation.

### Changed

- Removed `.h` content scoring (`probe_c_family`); headers are resolved by
  configuration (see ADR-0005).
- JS rules reclassified as `unsafe` (no longer dated); C `sprintf`/`strcpy`
  /`strcat`/`register` reclassified as unsafe; C/C++/C#/Java fossils carry
  version labels.
- Scan-cache digest now includes rule category/era so reclassified rules
  invalidate stale cached results.

## [0.2.0] - 2026-09-08

### Added

- C / C++ / C# / Java language support (heuristic front ends).
- Built-in legacy-idiom rule packs: `CF*` (C: `gets`, `sprintf`,
  `strcpy/strcat`, `register`), `CXX*` (C++: `iostream.h`, `std::auto_ptr`,
  `throw()`, `register`, bind-family), `CS*` (C#: `ArrayList`, `Hashtable`,
  non-generic `Stack/Queue`, `BinaryFormatter`), `JV*` (Java: `Vector`,
  `Hashtable`, `StringBuffer`, `Thread.stop`, `finalize`, boxing constructors).
- C/C++ `.h` disambiguation: weighted content probe (`probe_c_family`) with a
  conservative C default on ties.
- Generic `HeuristicParser`; `JsHeuristicParser` now a thin subclass.
- Per-language generation eras (`c90`/`c99`/`c11`, `cpp98`/`cpp17`,
  `cs1`/`cs8`, `java-legacy`) with `meta` ordered last in strata reports.
- Language packs and corpus tests for the new languages (158 tests total).

### Changed

- `RuleSpec.language` literal now covers six languages.
- `fix` bridge maps languages to fixer tools explicitly and skips languages
  without a bridged tool (no more `eslint` fallback for non-Python).
- Language registry consolidated in `core/language.py`.

## [0.1.0] - 2026-09-07

### Added

- Initial scaffold per the engineering spec (v1.1): src-layout, PDM + PEP 621,
  Ruff/Black/mypy toolchain, pydantic-settings configuration.
- Core pipeline: scanner, rule engine, stratigraphy aggregation, `--fix` bridge.
- Differentiating features: zombie standard-library API detection (offline
  snapshot DB) and winnowing-based code clone fingerprints.
- Parsers: parso multi-grammar-version Python front end (Python 2 corpus
  supported on Python 3 interpreters), stdlib `ast` fast path, heuristic JS.
- Reporting: self-contained HTML (data/view separation, embedded JSON),
  JSON, and SARIF 2.1.0 output.
- CLI commands: `dig`, `check`, `diff`, `rules`, `fix`.
- Tests: unit (mirroring src), integration, golden corpus (Py2 release gate),
  perf benchmark scaffold.
- CI: lint + 3 OS x Py3.9-3.13 test matrix with layered coverage gates,
  golden job, release workflow (OIDC trusted publisher), weekly perf job.
