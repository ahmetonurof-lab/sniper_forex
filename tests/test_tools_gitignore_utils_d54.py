"""D54 — gitignore_utils must fail LOUD when pathspec is missing.

Provenance guard (referee D54): index.json is line-anchored and
gitignore-scope-critical. The pre-D54 module swallowed the ImportError and
set ``pathspec = None``, so ``is_ignored`` silently skipped .gitignore and
a regen leaked gitignored ``logs/fix/`` into the index. Two silent-skip
incidents (§19) => the guard is now code, and this test pins it.
"""

from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path

import pytest

_UTILS_PATH = (
    Path(__file__).resolve().parent.parent / "tools" / "code-index-system" / "gitignore_utils.py"
)


def _load_fresh(monkeypatch: pytest.MonkeyPatch, *, hide_pathspec: bool):
    """Import gitignore_utils as a NEW module (fresh exec, cache-free)."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if hide_pathspec and name == "pathspec":
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    spec = importlib.util.spec_from_file_location("_gitignore_utils_d54", _UTILS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop("_gitignore_utils_d54", None)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop("_gitignore_utils_d54", None)


def test_missing_pathspec_raises_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock-missing import must abort module load with an actionable message."""
    with pytest.raises(ImportError, match="install pathspec"):
        _load_fresh(monkeypatch, hide_pathspec=True)


def test_present_pathspec_ignores_gitignored_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Positive control: with pathspec present, .gitignore scope is honored
    (the exact leak class D54 closes: gitignored logs/ must be ignored)."""
    module = _load_fresh(monkeypatch, hide_pathspec=False)
    (tmp_path / ".gitignore").write_text("logs/\n", encoding="utf-8")
    leaked = tmp_path / "logs" / "fix" / "bot_binance.py"
    leaked.parent.mkdir(parents=True)
    leaked.write_text("", encoding="utf-8")
    src = tmp_path / "src" / "keep.py"
    src.parent.mkdir(parents=True)
    src.write_text("", encoding="utf-8")

    assert module.is_ignored(str(tmp_path), str(leaked), set()) is True
    assert module.is_ignored(str(tmp_path), str(src), set()) is False
