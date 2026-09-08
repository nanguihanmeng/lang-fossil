"""Stdlib ``ast`` fast path for modern Python syntax.

The rule engine matches against parso trees (the multi-version workhorse),
so this module is used where only semantic inspection of modern code is
needed (name extraction for clone fingerprinting, zombie API attribute
walks) and when a cheap "is this modern-parseable" probe is enough.
"""

from __future__ import annotations

import ast

from lang_fossil.core.models import ParseResult


class AstPythonParser:
    """Fast modern-syntax parser built on :mod:`ast`."""

    language = "python"

    def parse(self, source: str, *, path: str = "<source>") -> ParseResult:
        """Parse modern Python source.

        Args:
            source: Raw Python source text.
            path: Path used in diagnostics only.

        Returns:
            Parse result; on :class:`SyntaxError` the tree is ``None`` and
            the error is reported through ``errors`` (degrade, never raise).
        """
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, ValueError) as exc:
            detail = getattr(exc, "msg", str(exc))
            message = f"line {getattr(exc, 'lineno', '?')}: {detail}"
            return ParseResult(
                tree=None,
                errors=(message,),
                language=self.language,
                grammar_version="stdlib",
            )
        except RecursionError:  # pragma: no cover - defensive
            return ParseResult(
                tree=None,
                errors=("parser failure: recursion limit",),
                language=self.language,
                grammar_version="stdlib",
            )
        return ParseResult(
            tree=tree,
            errors=(),
            language=self.language,
            grammar_version="stdlib",
        )


def walk_names(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Collect all identifier leaves from an AST.

    Args:
        tree: Parsed module node.

    Returns:
        Tuples of ``(name, lineno, col_offset)`` for every ``Name`` and
        ``Attribute`` identifier in the tree.
    """
    names: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append((node.id, node.lineno, node.col_offset))
        elif isinstance(node, ast.Attribute):
            names.append((node.attr, node.lineno, node.col_offset))
    return names
