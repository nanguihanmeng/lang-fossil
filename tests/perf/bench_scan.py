#!/usr/bin/env python3
"""Performance benchmark: fixed corpus, wall-clock per stage.

Run manually or from perf.yml:

    python tests/perf/bench_scan.py [--files N]

Budget (spec 4.2): parso parses one file in < 10ms; a 500-rule full
regression stays in the seconds range.
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from lang_fossil.config import LangFossilSettings
from lang_fossil.core.engine import Engine
from lang_fossil.core.scanner import scan
from lang_fossil.core.stratigraphy import build_report
from lang_fossil.core.zombie_api import ZombieApiDB
from lang_fossil.rules.registry import RuleRegistry

_SYNTHETIC = (
    "import cPickle\n"
    "def f{i}(data):\n"
    "    d = dict(data)\n"
    "    if d.has_key('k'):\n"
    "        for j in xrange(10):\n"
    "            print d[j]\n"
    "    return d.get('k', 0)\n"
)


def build_corpus(root: Path, count: int) -> None:
    """Create a deterministic synthetic corpus.

    Args:
        root: Target directory.
        count: Number of files.
    """
    for i in range(count):
        (root / f"mod_{i:04d}.py").write_text(_SYNTHETIC.format(i=i), encoding="utf-8")


def main() -> int:
    """Run the benchmark and print per-stage timings.

    Returns:
        Process exit code (0).
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=100)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_corpus(root, args.files)

        t0 = time.perf_counter()
        engine = Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())
        t1 = time.perf_counter()
        result = scan(root, LangFossilSettings(), engine, cache=None)
        t2 = time.perf_counter()
        build_report(result)
        t3 = time.perf_counter()

        per_file_ms = (t2 - t1) / args.files * 1000
        print(f"files scanned:      {result.scanned_files}")
        print(f"fossils found:      {len(result.fossils)}")
        print(f"rule load:          {(t1 - t0) * 1000:.1f} ms")
        print(f"scan total:         {(t2 - t1) * 1000:.1f} ms")
        print(f"per file:           {per_file_ms:.2f} ms")
        print(f"stratigraphy:       {(t3 - t2) * 1000:.1f} ms")
        # Loose end-to-end sanity ceiling (whole scan per file); the spec's
        # <10ms budget is parse-only and visible per-stage above.
        assert per_file_ms < 100, "per-file scan budget blown (sanity ceiling)"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
