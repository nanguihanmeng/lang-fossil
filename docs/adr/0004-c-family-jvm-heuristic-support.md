# ADR-0004: C/C++/C#/Java heuristic language support

- Status: Accepted
- Date: 2026-09-08
- Related: ADR-0001, ADR-0002

## Context

lang-fossil supported Python (AST-grade via parso/`ast`) and JavaScript
(heuristic). To serve the "codebase archaeology" goal across the broader
industry, C, C++, C#, and Java are the next languages. Each poses distinct
challenges: C and C++ share the `.h` extension and much of the syntax; C# and
Java have unambiguous extensions but rich package/namespace structure; none of
the four has a parser backend in this project, and shipping real AST parsers
for all of them is disproportionate.

The language identifier was duplicated in four places (extension map, rule
schema literal, scanner parser registry, fixer tool map) with no single source
of truth, and the fixer fell back to `eslint` for every non-Python language —
a latent misfire as soon as any new language shipped a `fix_hint`.

## Decision

1. **Extension-first classification with a single content probe.** All
   extensions live in `core/language.py` (`SUPPORTED_LANGUAGES`,
   `_LANG_BY_EXT`). Only the ambiguous C/C++ header extension (`.h`) triggers
   `probe_c_family`, a weighted-marker scorer (C++: STL headers, `namespace`,
   `class X :`, `std::`; C: stdio-family headers, `struct/union/enum`,
   `printf`/`scanf`, `->`, `malloc/free`) that picks the higher score and
   defaults to C on a tie.
2. **Heuristic-only front ends for the new languages.** A single generic
   `HeuristicParser` (regex-line, `tree=None`, `heuristic=True`) replaces the
   JS-only heuristic; `JsHeuristicParser` becomes a thin subclass. No AST
   parser is introduced (YAGNI); tree-based rules for these languages are a
   future, separately-budgeted option.
3. **One language registry, enforced everywhere.** `RuleSpec.language` is a
   literal covering the six languages; the scanner `parsers` table registers
   one parser per language; the fixer maps languages to external tools
   explicitly (`_TOOL_BY_LANGUAGE`) and skips languages without a bridged
   tool instead of falling back to `eslint`.
4. **Fossil rules target legacy idioms, not generic lint.** Each language pack
   ships a small, provenance-carrying heuristic pack (`CF*`, `CXX*`, `CS*`,
   `JV*`) centred on removed/unsafe/legacy constructs (e.g. `gets`,
   `sprintf`, `std::auto_ptr`, `throw()`, `ArrayList`, `Vector`, `finalize`).
5. **Per-language generation eras.** Stratification uses generation labels
   (`c90`, `cpp98`, `cs1`, `java-legacy`, …) ordered in `stratigraphy` after
   the Python era labels; the tool-level `meta` stratum sorts last.

## Consequences

- `.h` classification is heuristic: a header with balanced or no markers
  defaults to C (conservative), documented and tested (unit + discovery-level
  golden coverage).
- Heuristic rules may fire inside comments/strings (consistent with the
  existing JavaScript heuristic); no false-confidence guarantees.
- Adding a language is now a single-source change (extensions + parser
  registration + literal + rule pack + corpus) instead of edits across
  duplicated maps.
- Clone fingerprinting remains Python-only; extending it to the new languages
  is tracked separately and needs comment-style awareness in the tokenizer.

## Superseded in part (2026-09-08, v0.3.0)

Decision item 1 (content probe for `.h`) is superseded by ADR-0005: headers are
now resolved by user configuration instead of content scoring. Decision items
2–5 remain in force; ADR-0005 additionally refines the finding taxonomy into
`fossil` (age-datable, version-labelled) vs `unsafe` (review findings that are
never dated), per review feedback that presence-based signals were being
mistaken for age signals.
