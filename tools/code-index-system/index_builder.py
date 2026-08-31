"""
index_builder.py
Monorepo icindeki her alt repo icin fonksiyon/metod taramasi yapar.
.py dosyalari icin Python'un kendi 'ast' modulunu kullanir (stdlib,
derleme gerektirmez, Windows/Linux/Mac fark etmez).
Diger diller icin (JS/TS/Java/Go/...) hafif bir regex fallback vardir
(daha az kesin ama harici bagimlilik gerektirmez).

Kurulum:
    pip install pathspec
(tree-sitter YOK - Windows'ta C-extension derleme sorunlarindan kacinmak icin
 kaldirildi; repo %100 Python oldugu icin ast modulu yeterli ve daha guvenilir.)

Kullanim (tum repolari tam tara):
    python index_builder.py --config config.json --full
"""

import argparse
import ast
import hashlib
import json
import os
import re
import time

from gitignore_utils import is_ignored

# ---------------------------------------------------------------------------
# PYTHON: ast tabanli, tam dogru satir numaralari
# ---------------------------------------------------------------------------


def _signature_from_node(node):
    try:
        src = ast.unparse(node)
        first_line = src.split("\n")[0]
        return first_line[:200]
    except Exception:
        args = getattr(node, "args", None)
        arg_names = [a.arg for a in args.args] if args else []
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({', '.join(arg_names)}):"[:200]


def extract_functions_python(rel_path, source_text):
    module = module_name_from_path(rel_path)
    results = []

    try:
        tree = ast.parse(source_text, filename=rel_path)
    except SyntaxError as e:
        print(f"UYARI: {rel_path} syntax hatasi nedeniyle atlandi: {e}")
        return results

    def walk(node, context):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, context + [child.name])
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join(context + [child.name])
                key = f"{module}.{qualified}"
                results.append(
                    {
                        "key": key,
                        "file": rel_path,
                        "line_start": child.lineno,
                        "line_end": getattr(child, "end_lineno", child.lineno),
                        "signature": _signature_from_node(child),
                    }
                )
                walk(child, context + [child.name])
            else:
                walk(child, context)

    walk(tree, [])
    return results


# ---------------------------------------------------------------------------
# DIGER DILLER: hafif regex fallback (harici bagimlilik yok)
# ---------------------------------------------------------------------------

_GENERIC_FUNC_PATTERNS = [
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\("),  # JS/TS function decl
    re.compile(
        r"^\s*(?:public|private|protected|static|\s)*[\w<>\[\]]+\s+(\w+)\s*\([^;{]*\)\s*\{"
    ),  # Java/C#/C++
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\("),  # Go
    re.compile(r"^\s*def\s+(\w+)"),  # Ruby
]


def extract_functions_generic(rel_path, source_text):
    module = module_name_from_path(rel_path)
    results = []
    lines = source_text.split("\n")
    for i, line in enumerate(lines):
        for pattern in _GENERIC_FUNC_PATTERNS:
            m = pattern.match(line)
            if m:
                name = m.group(1)
                key = f"{module}.{name}"
                results.append(
                    {
                        "key": key,
                        "file": rel_path,
                        "line_start": i + 1,
                        "line_end": i + 1,  # regex fallback: kesin end line veremiyoruz
                        "signature": line.strip()[:200],
                    }
                )
                break
    return results


SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "generic",
    ".jsx": "generic",
    ".ts": "generic",
    ".tsx": "generic",
    ".java": "generic",
    ".go": "generic",
    ".rb": "generic",
    ".c": "generic",
    ".h": "generic",
    ".cpp": "generic",
    ".hpp": "generic",
    ".cc": "generic",
    ".cs": "generic",
    ".php": "generic",
}


def module_name_from_path(rel_path):
    no_ext = os.path.splitext(rel_path)[0]
    parts = no_ext.replace("\\", "/").split("/")
    return ".".join(parts)


def file_hash(content_bytes):
    return "sha256:" + hashlib.sha256(content_bytes).hexdigest()[:16]


def index_single_file(full_path, rel_path, ext, functions, files_meta):
    """Tek bir dosyayi parse edip functions/files_meta sozluklerine ekler (in-place)."""
    kind = SUPPORTED_EXTENSIONS.get(ext)
    if not kind:
        return
    try:
        with open(full_path, "rb") as f:
            raw = f.read()
    except (IOError, OSError):
        return

    text = raw.decode("utf-8", errors="replace")

    if kind == "python":
        entries = extract_functions_python(rel_path, text)
    else:
        entries = extract_functions_generic(rel_path, text)

    for entry in entries:
        key = entry.pop("key")
        functions[key] = entry

    files_meta[rel_path] = {
        "last_modified": time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(full_path))
        ),
        "hash": file_hash(raw),
    }


def remove_file_entries(repo_section, rel_path):
    repo_section["functions"] = {
        k: v for k, v in repo_section["functions"].items() if v["file"] != rel_path
    }
    repo_section["files"].pop(rel_path, None)


def scan_single_repo(repo_cfg, common_cfg):
    repo_root = os.path.abspath(repo_cfg["root"])
    extensions = set(common_cfg["extensions"])
    always_ignored = set(common_cfg["always_ignored_dirs"])

    functions = {}
    files_meta = {}

    if not os.path.isdir(repo_root):
        print(f"UYARI: repo bulunamadi: {repo_root}")
        return {"functions": functions, "files": files_meta, "last_full_scan": None}

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [
            d
            for d in dirnames
            if not is_ignored(repo_root, os.path.join(dirpath, d), always_ignored)
        ]
        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            if ext not in extensions:
                continue
            full_path = os.path.join(dirpath, fname)
            if is_ignored(repo_root, full_path, always_ignored):
                continue
            rel_path = os.path.relpath(full_path, repo_root)
            index_single_file(full_path, rel_path, ext, functions, files_meta)

    return {
        "functions": functions,
        "files": files_meta,
        "last_full_scan": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def build_full_index(cfg):
    repos_section = {}
    for repo_cfg in cfg["repos"]:
        if not repo_cfg.get("enabled", True):
            continue
        name = repo_cfg["name"]
        print(f"Taraniyor: {name} ({repo_cfg['root']})")
        repos_section[name] = scan_single_repo(repo_cfg, cfg)
        print(f"  -> {len(repos_section[name]['functions'])} fonksiyon")

    return {
        "version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "repos": repos_section,
    }


def write_index(index_data, output_path):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, output_path)


def load_config(path):
    """Config icindeki relatif yollari, config.json'in KENDI konumuna gore cozer
    (calistirildigi dizine gore degil) - boylece watcher hangi dizinden
    baslatilirsa baslatilsin ayni sekilde davranir."""
    config_dir = os.path.dirname(os.path.abspath(path))
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    for repo_cfg in cfg["repos"]:
        repo_cfg["root"] = os.path.normpath(os.path.join(config_dir, repo_cfg["root"]))
        if repo_cfg.get("memory_bank"):
            repo_cfg["memory_bank"] = os.path.normpath(
                os.path.join(config_dir, repo_cfg["memory_bank"])
            )

    cfg["index_output_path"] = os.path.normpath(os.path.join(config_dir, cfg["index_output_path"]))
    return cfg


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--full", action="store_true", help="Tum repolari tam tara")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.full:
        idx = build_full_index(cfg)
        write_index(idx, cfg["index_output_path"])
        total = sum(len(r["functions"]) for r in idx["repos"].values())
        print(f"Index olusturuldu: {cfg['index_output_path']} (toplam {total} fonksiyon)")
