"""Unit tests for the deprecation snapshot sync script (mirrors scripts/)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "sync_deprecations.py"


def _load_sync_module() -> ModuleType:
    """Import the standalone script as a module (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("lang_fossil_sync", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load_sync_module()


def _make_repo(tmp_path: Path) -> Path:
    """Lay out a mini repository with a curated manifest and empty data dirs."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "src" / "lang_fossil" / "data").mkdir(parents=True)
    manifest = """\
schema_version: 1
sources:
  - name: Fixture docs
    url: https://example.invalid/whatsnew
    version: "3.99"
packages:
  - module: fake_module
    removed_in: "3.99"
    removal: pep999
    replacement: replacement_pkg
  - module: fake_attr
    attribute: gone
    removed_in: "3.99"
    removal: semantic
    replacement: something_else
"""
    (tmp_path / "scripts" / "deprecation-sources.yaml").write_text(manifest, encoding="utf-8")
    return tmp_path


def _snapshots(root: Path) -> tuple[Path, Path]:
    """Return the two snapshot paths under a fixture repo."""
    return (
        root / "data" / "dead-packages.json",
        root / "src" / "lang_fossil" / "data" / "dead-packages.json",
    )


def test_write_regenerates_both_copies(tmp_path: Path) -> None:
    """write produces identical, versioned copies at both data locations."""
    root = _make_repo(tmp_path)
    sync.write(root, version="2099.01")
    repo_copy, packaged_copy = _snapshots(root)
    assert repo_copy.read_text(encoding="utf-8") == packaged_copy.read_text(encoding="utf-8")
    document = json.loads(repo_copy.read_text(encoding="utf-8"))
    assert document["snapshot_version"] == "2099.01"
    assert document["schema_version"] == 1
    assert document["sources"][0]["url"] == "https://example.invalid/whatsnew"
    assert document["packages"][0]["module"] == "fake_module"
    # Reference-only manifest keys never leak into the snapshot.
    assert all("ref_url" not in entry for entry in document["packages"])


def test_check_passes_after_write_and_fails_on_drift(tmp_path: Path) -> None:
    """check is green after write, red when a snapshot drifts."""
    root = _make_repo(tmp_path)
    sync.write(root, version="2099.01")
    assert sync.check(root) is True
    repo_copy, _packaged = _snapshots(root)
    snapshot = json.loads(repo_copy.read_text(encoding="utf-8"))
    snapshot["packages"][0]["removed_in"] = "3.98"
    repo_copy.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    assert sync.check(root) is False


def test_write_bumps_snapshot_version(tmp_path: Path) -> None:
    """write with a fresh stamp overwrites the previous version."""
    root = _make_repo(tmp_path)
    sync.write(root, version="2099.01")
    sync.write(root, version="2099.02")
    repo_copy, packaged_copy = _snapshots(root)
    for path in (repo_copy, packaged_copy):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["snapshot_version"] == "2099.02"


def test_verify_uses_local_ref_files(tmp_path: Path) -> None:
    """verify corroborates entries against local ref files (offline tests)."""
    root = _make_repo(tmp_path)
    ref = tmp_path / "whatsnew.txt"
    ref.write_text("fake_module and fake_attr.gone were removed.\n", encoding="utf-8")
    manifest_path = tmp_path / "scripts" / "deprecation-sources.yaml"
    manifest = sync.load_manifest(manifest_path)
    for entry in manifest["packages"]:
        entry["ref_url"] = str(ref)
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    assert sync.verify(root) is True
    ref.write_text("nothing relevant here.\n", encoding="utf-8")
    assert sync.verify(root) is False


def test_load_manifest_rejects_bad_shape(tmp_path: Path) -> None:
    """A manifest without a packages list is rejected."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="packages"):
        sync.load_manifest(bad)


def test_main_exit_codes(tmp_path: Path) -> None:
    """CLI entry returns 0/1 for write/check and 2 on manifest errors."""
    root = _make_repo(tmp_path)
    assert sync.main(["write", "--root", str(root)]) == 0
    assert sync.main(["check", "--root", str(root)]) == 0
    (tmp_path / "scripts" / "deprecation-sources.yaml").write_text("packages: {", encoding="utf-8")
    assert sync.main(["check", "--root", str(root)]) == 2
