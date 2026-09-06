#!/usr/bin/env python
"""D129 B.3 — AUDITCHAIN DAILY ROTATION (dated JSONL journal).

Amaç: Makine-okunur forensic kayıt. Mevcut ``AuditChain``
(``state/audit.jsonl``) → günlük dosyalara taşınır:
``logs/audit_YYYY-MM-DD.jsonl``.

Rotasyon:
- Günlük dosya: ``logs/audit_YYYY-MM-DD.jsonl``
- 14 gün saklama (eskiler silinir)
- Hash-chain bütünlüğü: HER günlük dosyanın kendi zinciri (global zincir
  YOK — rotasyonla bozulmasın)

TASARIM NOTU (AGENTS.md §2.2 — prefer existing mechanisms):
Kanıtlanmış ``AuditChain`` (delta-watermark, atomik-yazma, torn-tail
tolerası, re-entrancy guard) DOKUNULMUYOR — freezing riski (AGENTS.md
§2.1). Bunun yerine katman yaklaşımı: ``AuditChain``'in
``auto_flush_path``'ini her flushi günün dosyasına yönlendiren hafif bir
katman. Zincirin su-markası/zincir-semantiği değişmez; sadece hedef
patika gün bazlı seçilir.

Migration (tek seferlik): mevcut ``state/audit.jsonl`` →
``logs/audit_today.jsonl`` (D129 B.3). ``migrate_legacy_audit()`` bunu
atomik taşıma ile yapar; dosya yoksa no-op.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_LOG_DIR = "logs"
DEFAULT_PREFIX = "audit"
RETENTION_DAYS = 14  # D129: 14 gün saklama


def daily_audit_filename(when: Optional[datetime] = None) -> str:
    """Bir an için günlük audit dosya adı: ``audit_YYYY-MM-DD.jsonl``."""
    dt = when if when is not None else datetime.now(timezone.utc)
    return f"{DEFAULT_PREFIX}_{dt.strftime('%Y-%m-%d')}.jsonl"


def daily_audit_path(log_dir: Optional[str] = None, when: Optional[datetime] = None) -> str:
    """Bugünün (veya verilen anın) audit dosya yolunu döndür."""
    return str(Path(log_dir or DEFAULT_LOG_DIR) / daily_audit_filename(when))


def resolve_target_path(
    base_path: str,
    log_dir: Optional[str] = None,
    when: Optional[datetime] = None,
) -> str:
    """Verilen ``base_path``'i günlük-hedefli patikaya çöz.

    Katman yaklaşımı: ``AuditChain``'in ``auto_flush_path``'i normalde
    sabittir. Bu yardımcı, her flush/seçimde çağrılarak günün dosyasını
    döndürür. ``base_path`` bilgi amaçlı korunur (geriye dönük uyum);
    fiili hedef günlük dosyadır.
    """
    del base_path  # bilgi amaçlı; fiili hedef günlük dosya
    return daily_audit_path(log_dir, when)


def iterate_daily_files(log_dir: Optional[str] = None) -> Iterable[Path]:
    """``logs/audit_YYYY-MM-DD.jsonl`` desenindeki tüm dosyaları sırala."""
    d = Path(log_dir or DEFAULT_LOG_DIR)
    if not d.exists():
        return ()
    return sorted(d.glob(f"{DEFAULT_PREFIX}_????-??-??.jsonl"))


def prune_old_audit(retention_days: int = RETENTION_DAYS, log_dir: Optional[str] = None) -> int:
    """14 günden eski audit_*.jsonl dosyalarını sil. Silinen sayıyı döndür."""
    removed = 0
    cutoff = datetime.now(timezone.utc).date()
    prefix_pre = f"{DEFAULT_PREFIX}_"
    for p in iterate_daily_files(log_dir):
        try:
            stem = p.stem
            if not stem.startswith(prefix_pre):
                continue
            date_part = stem[len(prefix_pre) :]
            file_date = datetime.strptime(date_part, "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        if (cutoff - file_date).days > retention_days:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def migrate_legacy_audit(
    legacy_path: str,
    log_dir: Optional[str] = None,
) -> Optional[str]:
    """Tek seferlik migration: ``state/audit.jsonl`` → ``logs/audit_today.jsonl``.

    Atomik taşıma (move). Kaynak yoksa/no-op ise ``None`` döner; başarılı
    taşımada hedef yolu döndürür. Hedef zaten varsa üzerine yazmaz
    (koruma) — kaynak korunarak ``None`` döner.
    """
    src = Path(legacy_path)
    if not src.exists():
        return None
    dst = Path(log_dir or DEFAULT_LOG_DIR) / f"{DEFAULT_PREFIX}_today.jsonl"
    if dst.exists():
        return None  # hedef zaten var — üzerine yazma
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return str(dst)
