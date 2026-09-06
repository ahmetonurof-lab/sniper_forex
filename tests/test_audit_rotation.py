#!/usr/bin/env python
"""D129 B.3 — AuditChain daily rotation tests.

Controlled-unit evidence (AGENTS.md §3): temp dir, no network. Verifies:
- daily filename (audit_YYYY-MM-DD.jsonl)
- resolve_target_path layers onto AuditChain's auto_flush_path
- iteration over daily files
- 14-day retention pruning
- legacy migration (state/audit.jsonl -> logs/audit_today.jsonl)
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"C:\Users\Administrator\Desktop\sniper_forex")

from src.live.audit_rotation import (
    RETENTION_DAYS,
    daily_audit_filename,
    daily_audit_path,
    iterate_daily_files,
    migrate_legacy_audit,
    prune_old_audit,
    resolve_target_path,
)


def test_daily_filename_format():
    """Günlük dosya adı: audit_YYYY-MM-DD.jsonl."""
    fn = daily_audit_filename(datetime(2026, 9, 6, tzinfo=timezone.utc))
    assert fn == "audit_2026-09-06.jsonl", fn


def test_daily_audit_path():
    """Günlük yol logs altında."""
    p = daily_audit_path(log_dir="logs", when=datetime(2026, 9, 3, tzinfo=timezone.utc))
    assert Path(p) == Path("logs/audit_2026-09-03.jsonl"), p


def test_resolve_target_is_daily():
    """Katman: base_path bilgi amaçlı, fiili hedef günlük dosya."""
    target = resolve_target_path("state/audit.jsonl", log_dir="logs")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert Path(target) == Path(f"logs/audit_{today}.jsonl"), target


def test_iterate_daily_files_only_match():
    """iterate_daily_files sadece audit_YYYY-MM-DD.jsonl desenini döndürür."""
    with tempfile.TemporaryDirectory() as tmpdir:
        open(os.path.join(tmpdir, "audit_2026-09-05.jsonl"), "w").write("{}\n")
        open(os.path.join(tmpdir, "audit_2026-09-06.jsonl"), "w").write("{}\n")
        open(os.path.join(tmpdir, "unrelated.jsonl"), "w").write("{}\n")
        files = list(iterate_daily_files(tmpdir))
        names = [f.name for f in files]
        assert "audit_2026-09-05.jsonl" in names
        assert "audit_2026-09-06.jsonl" in names
        assert "unrelated.jsonl" not in names


def test_prune_old_audit():
    """14 günden eski audit dosyaları silinir, yeniler kalır."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old = os.path.join(tmpdir, "audit_2026-08-15.jsonl")
        open(old, "w").write("{}\n")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur = os.path.join(tmpdir, f"audit_{today}.jsonl")
        open(cur, "w").write("{}\n")

        removed = prune_old_audit(RETENTION_DAYS, log_dir=tmpdir)
        assert removed == 1
        assert not os.path.exists(old), "eski dosya silinmedi"
        assert os.path.exists(cur), "bugünkü dosya silinmemeli"


def test_migrate_legacy_move():
    """Migrasyon: state/audit.jsonl -> logs/audit_today.jsonl (atomik)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        legacy = os.path.join(tmpdir, "state", "audit.jsonl")
        os.makedirs(os.path.dirname(legacy), exist_ok=True)
        open(legacy, "w").write('{"a":1}\n')
        dst = migrate_legacy_audit(legacy, log_dir=tmpdir)
        assert dst == os.path.join(tmpdir, "audit_today.jsonl"), dst
        assert os.path.exists(dst)
        assert not os.path.exists(legacy), "kaynak taşınmadı"


def test_migrate_legacy_missing_source():
    """Kaynak yoksa migrasyon no-op (None)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = migrate_legacy_audit("/nonexistent/audit.jsonl", log_dir=tmpdir)
        assert result is None


def test_migrate_legacy_target_exists_no_overwrite():
    """Hedef zaten varsa üzerine yazmaz (koruma)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        legacy = os.path.join(tmpdir, "audit.jsonl")
        open(legacy, "w").write("SOURCE\n")
        dst = os.path.join(tmpdir, "audit_today.jsonl")
        open(dst, "w").write("DST_EXISTS\n")
        result = migrate_legacy_audit(legacy, log_dir=tmpdir)
        assert result is None
        with open(dst, "r") as f:
            assert f.read() == "DST_EXISTS\n", "hedef ezildi!"


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"PASS: {t.__name__}")
        except Exception:
            print(f"FAIL: {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
