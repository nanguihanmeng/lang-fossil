"""parso-based Python front end supporting multiple grammar versions.

parso ≥ 0.8.2 removed the historical Python 2 grammar files from its
distribution, so the Python 2.7 grammar is vendored with this package
(``grammars/grammar27.txt``, taken from parso v0.7.1, MIT licensed) and
loaded via ``parso.load_grammar(path=...)``. This keeps the spec promise:
Python 2 corpora parse on Python 3 interpreters (spec appendix C, M0 PoC).

Strategy: parse with the interpreter's grammar first; if syntax errors are
reported and the source smells like Python 2, retry with the vendored 2.7
grammar and keep the result with fewer errors. Sources older than 2.7 are
outside parso's support range and fall through to regex-heuristic rules
(rules flagged ``match_mode: heuristic``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import parso

from lang_fossil.core.models import ParseResult

_PY2_VERSION = "2.7"
_PY2_GRAMMAR_PATH = Path(__file__).parent / "grammars" / "grammar27.txt"
_MIN_GRAMMAR_DIGITS = 2  # grammar file names carry >= 2 digits ("39", "310")

# Constructs that only exist before Python 3; used to decide whether a Py2
# grammar retry is worth attempting.
_PY2_HINTS = re.compile(
    r"^\s*print\s+[^(=]|"  # print statement
    r"raise\s+\w+\s*,\s*|"  # raise E, msg
    r"^\s*exec\s+[^\s(]|"  # exec statement
    r"[\s(]<{2}\s*\d|"  # print >> stream
    r"=\s*[uU][rR][\"']|"  # ur'' string literal
    r"[\w)\]]`|`[\w(]",  # backtick repr
    re.MULTILINE,
)


def _load_py2_grammar() -> Any:
    """Load the vendored Python 2.7 grammar.

    Returns:
        A parso grammar, or ``None`` when the vendored file is missing.
    """
    try:
        return parso.load_grammar(path=str(_PY2_GRAMMAR_PATH))
    except (OSError, ValueError):
        return None


def _load_default_grammar() -> Any:
    """Load the interpreter's grammar, falling back to the newest available.

    Returns:
        A parso grammar, or ``None`` when no grammar can be loaded at all.
    """
    try:
        return parso.load_grammar()
    except (OSError, NotImplementedError, ValueError):
        pass
    # Future interpreters may exceed parso's bundled grammars: pick the
    # highest grammar file the installed parso actually ships.
    grammar_dir = Path(parso.__file__).parent / "python"
    candidates: list[tuple[int, int, Path]] = []
    for grammar_file in grammar_dir.glob("grammar*.txt"):
        digits = grammar_file.stem[len("grammar") :]
        if digits.isdigit() and len(digits) >= _MIN_GRAMMAR_DIGITS:
            candidates.append((int(digits[0]), int(digits[1:]), grammar_file))
    if not candidates:
        return None
    newest = max(candidates)
    try:
        return parso.load_grammar(path=str(newest[2]))
    except (OSError, ValueError, NotImplementedError):
        return None


class ParsoPythonParser:
    """Multi-grammar-version Python parser (main workhorse)."""

    language = "python"

    def parse(self, source: str, *, path: str = "<source>") -> ParseResult:
        """Parse Python source, falling back to the 2.7 grammar when needed.

        Args:
            source: Raw Python source text.
            path: Path used in diagnostics only.

        Returns:
            The parse result with the fewest syntax errors; grammar version
            actually used is recorded on the result.
        """
        modern = self._parse_with_version(source, None)
        modern_errors = list(modern["errors"])
        if not modern_errors or not _PY2_HINTS.search(source):
            return ParseResult(
                tree=modern["tree"],
                errors=tuple(modern_errors),
                language=self.language,
                grammar_version=str(modern["version"]),
            )

        legacy = self._parse_with_version(source, _PY2_VERSION)
        legacy_errors = list(legacy["errors"])
        if legacy["tree"] is not None and len(legacy_errors) < len(modern_errors):
            return ParseResult(
                tree=legacy["tree"],
                errors=tuple(legacy_errors),
                language=self.language,
                grammar_version=str(legacy["version"]),
            )
        return ParseResult(
            tree=modern["tree"],
            errors=tuple(modern_errors),
            language=self.language,
            grammar_version=str(modern["version"]),
        )

    def _parse_with_version(self, source: str, version: str | None) -> dict[str, Any]:
        """Parse with an explicit grammar version, collecting errors.

        Args:
            source: Raw Python source text.
            version: Grammar version (``None`` = current interpreter;
                ``"2.7"`` = vendored Py2 grammar).

        Returns:
            Dict with keys ``tree`` (parso node or ``None``), ``errors``
            (list of formatted error strings) and ``version`` (label).
        """
        if version is None:
            grammar = _load_default_grammar()
            label = "3.x"
        else:
            grammar = _load_py2_grammar()
            label = version
        if grammar is None:
            return {"tree": None, "errors": ["grammar unavailable"], "version": label}

        try:
            tree = grammar.parse(source)
        except (RecursionError, ValueError, NotImplementedError) as exc:
            # parso itself should not raise; degrade defensively regardless.
            return {"tree": None, "errors": [f"parser failure: {exc}"], "version": label}

        errors: list[str] = []
        try:
            for error in grammar.iter_errors(tree):
                errors.append(
                    f"line {getattr(error, 'lineno', '?')},"
                    f" col {getattr(error, 'column', '?')}:"
                    f" {getattr(error, 'message', 'syntax error')}"
                )
        except (RecursionError, ValueError):  # pragma: no cover - defensive
            errors.append("error collection failed")
        return {"tree": tree, "errors": errors, "version": label}
