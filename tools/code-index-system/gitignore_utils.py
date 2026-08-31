"""
gitignore_utils.py
Her repo kok dizinindeki .gitignore dosyasini okuyup, o repo icin
dogru "bu dosya ignore edilsin mi" kontrolunu saglar.

Kurulum:
    pip install pathspec
"""

import os

try:
    import pathspec
except ImportError as exc:  # D54: provenance-critical — NEVER silent-partial.
    # A missing pathspec used to be swallowed (pathspec = None) so
    # is_ignored() quietly skipped .gitignore and produced a partial index
    # (logs/ leaked in once). §19 silent-fallback pattern — seen twice, so
    # the guard is now code: fail LOUD with an actionable message.
    raise ImportError(
        "index regen incomplete — install pathspec "
        "(gitignore-awareness is mandatory; see requirements.txt)"
    ) from exc

_spec_cache = {}


def _load_gitignore_spec(repo_root):
    if repo_root in _spec_cache:
        return _spec_cache[repo_root]

    patterns = []
    gitignore_path = os.path.join(repo_root, ".gitignore")
    if os.path.isfile(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
            patterns = f.readlines()

    # D54: pathspec import is guaranteed above (loud-fail), so the spec is
    # never None here — the old silent "spec = None" branch is gone.
    spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    _spec_cache[repo_root] = spec
    return spec


def is_ignored(repo_root, abs_path, always_ignored_dirs):
    """abs_path, repo_root altinda bir dosya/klasor olmali."""
    rel_path = os.path.relpath(abs_path, repo_root).replace("\\", "/")
    parts = rel_path.split("/")

    if any(part in always_ignored_dirs for part in parts):
        return True

    spec = _load_gitignore_spec(repo_root)
    return spec.match_file(rel_path)


def clear_cache(repo_root=None):
    if repo_root is None:
        _spec_cache.clear()
    else:
        _spec_cache.pop(repo_root, None)
