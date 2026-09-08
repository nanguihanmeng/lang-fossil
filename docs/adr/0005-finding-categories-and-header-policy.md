# ADR-0005: Finding categories and configuration-driven `.h` policy

- Status: Accepted
- Date: 2026-09-08
- Supersedes: part of ADR-0004 (the `.h` content probe)
- Related: ADR-0004

## Context

Review feedback challenged two v0.2 behaviours:

1. **Presence signals masqueraded as age signals.** Reporting `sprintf`,
   `strcpy`, `var`, `register`, `Vector`, … as "old fossils" confuses "a
   construct appeared in an old standard" with "this code is old". Some of
   those constructs are still legal and idiomatic today; only constructs that
   a standard *removed or deprecated* are trustworthy age signals.
2. **`.h` content scoring was high-complexity, low-value.** The weighted
   content probe misclassified real-world bare-class headers and shipped ~200
   lines of machinery (scorer, thresholds, boundary tests) for an outcome
   whose practical impact is near zero (C/C++ rule packs barely overlap). The
   ambiguity is better owned by the user.

## Decision

1. **Explicit finding category on every rule.** `RuleSpec.category` is
   `fossil` (age-datable) or `unsafe` (review finding, never dated). A fossil
   rule *must* carry `deprecated_in` and/or `removed_in`; an unsafe rule *must*
   use the reserved `era = "unsafe"` and carry no version labels. The engine
   maps category → `Fossil.era`, so stratigraphy keeps fossil strata free of
   unsafe findings by construction.
2. **Version metadata is the trust anchor.** Only rules with a declared
   deprecated/removed version enter a fossil stratum. Legacy-but-legal
   patterns (JS `var`/`eval`, Java `Vector`, C# `ArrayList`, C
   `sprintf`/`strcpy`) are classified unsafe; their "fix_hint" still drives
   `--fix` bridging.
3. **No content scoring for headers.** The `probe_c_family` machinery is
   deleted. `ScanSettings.ambiguous_headers` controls `.h` resolution:
   `mode` (`auto` / `c` / `cpp`) plus glob `overrides` matched against the
   repository-relative path. `auto` decides from sibling-directory `.c` /
   `.cpp` tallies already gathered during discovery (zero extra I/O),
   defaulting to `c` with no C-family siblings.
4. **Cache invalidation follows semantics.** The scan-cache digest includes
   rule `category`/`era`, so reclassifying a rule invalidates stale cached
   fossils (the historical stale-cache defect).

## Consequences

- The "fossil index" and `check` gates remain inclusive of unsafe findings for
  backward compatibility; `unsafe_count` is surfaced separately and unsafe
  findings form their own near-final stratum.
- Users decide C-vs-C++ for headers instead of the tool guessing; the cost is
  one config section, the benefit is zero misattribution and no reading of
  header contents.
- Adding rules now requires a conscious category/version decision at authoring
  time, which is exactly the guardrail the review asked for.
