#!/usr/bin/env python
"""CHECKPOINT-v3-hazırlık (Hakem-direktifi; D89-deseni):
progress.md'deki D60..D101-uzun-girdilerini archive_v2_20260906/'a
dosya-başına-çıkarır; yerlerine-kısa-referans-satırı-bırakır.
D>=102-TAM-kalır (yeni-sayfa-girdileri). Commit-DEĞİL (Reis'te).
"""

import hashlib
import re
import sys
from pathlib import Path

PROG = Path("memory-bank/progress.md")
ARCH = Path("memory-bank/archive_v2_20260906")
MIN_D, MAX_D = 60, 101


def slugify(title: str, num: str) -> str:
    t = re.sub(rf"^##\s*D{num}\s*[-—·:]*\s*", "", title).strip()
    t = re.sub(r"[^0-9A-Za-zçğıöşüÇĞİÖŞÜ]+", "_", t).strip("_")
    return t[:24]


def main() -> int:
    ARCH.mkdir(exist_ok=True)
    with open(PROG, encoding="utf-8", newline="") as f:
        text = f.read()
    lines = text.replace("\r\n", "\n").split("\n")

    head_idx = [i for i, l in enumerate(lines) if l.startswith("## ")]
    blocks = []  # (start, end_inclusive, title)
    for k, i in enumerate(head_idx):
        end = head_idx[k + 1] - 1 if k + 1 < len(head_idx) else len(lines) - 1
        blocks.append((i, end, lines[i]))

    archive, keep = [], []
    prev_kept_end = -1
    counts = {}
    for start, end, title in blocks:
        m = re.match(r"^##\s+D(\d+)", title)
        if m:
            num = int(m.group(1))
        else:
            num = None
        if num is not None and MIN_D <= num <= MAX_D:
            slug = slugify(title, str(num))
            base = f"D{num}" + (f"_{slug}" if slug else "")
            name = base + ".md"
            n = counts.get(name, 0)
            if n:
                name = f"{base}_{n + 1}.md"
            counts[base] = n + 1
            body = "\n".join(lines[start : end + 1]).rstrip() + "\n"
            (ARCH / name).write_text(body, encoding="utf-8")
            archive.append((name, title, start, end))
        else:
            keep.append((start, end))

    # yeni-progress: korunan-bloklar + arşivlenen-yerine-kısa-ref
    new_lines, cursor = [], 0
    for start, end in keep:
        new_lines.extend(lines[cursor:start])
        cursor = end + 1
    new_lines.extend(lines[cursor:])
    # arşivlenen-yerlere-ref-satırı: blok-sırasına-göre-ekle
    final, ref_iter = [], 0
    a_sorted = sorted(archive, key=lambda x: x[2])
    keep_sorted = sorted(keep)
    merged = []
    ki = 0
    for name, title, start, end in a_sorted:
        while ki < len(keep_sorted) and keep_sorted[ki][0] < start:
            merged.append(("KEEP", keep_sorted[ki]))
            ki += 1
        merged.append(("ARCH", (name, title, start, end)))
    while ki < len(keep_sorted):
        merged.append(("KEEP", keep_sorted[ki]))
        ki += 1

    pos = 0
    for kind, item in merged:
        if kind == "KEEP":
            start, end = item
            final.extend(lines[pos : end + 1])
            pos = end + 1
        else:
            name, title, start, end = item
            # referans-başlık + yol
            final.append(title + " *(ARŞİV — checkpoint-v3-öncesi)*")
            final.append("")
            final.append(f"> Ayrıntı: memory-bank/archive_v2_20260906/{name}")
            final.append("")
            pos = end + 1
    final.extend(lines[pos:])

    with open(PROG, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(final))

    h = hashlib.sha256(PROG.read_bytes()).hexdigest()
    print(f"archived-entries: {len(archive)}")
    print(f"new-progress: {len(final)} lines sha256={h[:12]}")
    for name, title, _, _ in archive:
        print("  ->", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
