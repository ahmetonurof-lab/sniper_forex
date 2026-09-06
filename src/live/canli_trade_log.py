#!/usr/bin/env python
"""D129 B.2 — CANLI TRADE LOG (daily-rotating plain-text journal).

Amaç: Terminal kapansa/SSH düşse bile ``tail -f`` ile canlı takip.
``ConsoleReporter`` çıktısının aynısı, zaman damgalı, düz metin (JSON
DEĞİL).

Rotasyon:
- Günlük dosya: ``logs/canli_trade_YYYY-MM-DD.log``
- UTC gece yarısında yeni gün dosyasına geçer (crypto Pattern 2 ile aynı)
- 14 günden eski dosyalar otomatik silinir

TASARIM NOTU (AGENTS.md §12.1 — şeffaf sapma):
D129 spesifikasyonu ``logging.handlers.TimedRotatingFileHandler``
(midnight UTC) önerir. Ancak TimedRotatingFileHandler bugünün verisini
BASE dosyaya (``canli_trade.log``) yazar ve tarihli dosyayı YALNIZCA
gece yarısı rotasyonunda üretir. Bu, D129'un KABUL KRİTERİYLE çelişir:

    tail -f logs/canli_trade_$(date +%Y-%m-%d).log   ← bugünün verisi

Kabul kriteri, bugünün dosyasının ``canli_trade_YYYY-MM-DD.log`` olmasını
ve bugünün verisini içermesini şart koşar. TimedRotatingFileHandler bunu
sağlayamaz (bugünün verisi base'de kalır). Bu yüzden küçük bir özel
``DailyUtcFileHandler`` yazıldı: aynı midnight-UTC + 14-gün-retention
semantiğini korur, ancak doğrudan tarihli dosyaya yazar. Bu, mevcut
mekanizmayı yeniden icat değil — kabul kriterini karşılamak için
adlandırma/rotasyon davranışını düzeltir.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_LOG_DIR = "logs"
DEFAULT_PREFIX = "canli_trade"
RETENTION_DAYS = 14  # D129: 14 gün saklama (crypto Pattern 2 ile aynı)


class DailyUtcFileHandler(logging.Handler):
    """UTC gece yarısında dönen, doğrudan tarihli dosyaya yazan handler.

    Her emit'te günü kontrol eder; gün değiştiyse eski dosyayı kapatır,
    yeni ``canli_trade_YYYY-MM-DD.log`` açar ve 14 günden eski dosyaları
    siler. ``tail -f logs/canli_trade_$(date +%Y-%m-%d).log`` bugünün
    verisini gösterir (D129 kabul kriteri).
    """

    def __init__(
        self,
        log_dir: str = DEFAULT_LOG_DIR,
        prefix: str = DEFAULT_PREFIX,
        retention_days: int = RETENTION_DAYS,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self.retention_days = retention_days
        self.encoding = encoding
        self._current_date: Optional[str] = None
        self._stream = None

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _path_for(self, date_str: str) -> Path:
        return self.log_dir / f"{self.prefix}_{date_str}.log"

    def _roll_if_needed(self) -> None:
        today = self._today()
        if self._current_date == today:
            return
        # Gün değişti (veya ilk açılış): eski stream'i kapat, yenisini aç.
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
        self._current_date = today
        path = self._path_for(today)
        self._stream = open(path, "a", encoding=self.encoding)
        self._prune_old()

    def _prune_old(self) -> None:
        """14 günden eski canli_trade_*.log dosyalarını sil."""
        if self.retention_days <= 0:
            return
        cutoff = datetime.now(timezone.utc).date()
        prefix_prefix = f"{self.prefix}_"
        for p in self.log_dir.glob(f"{self.prefix}_*.log"):
            try:
                # Dosya adı: canli_trade_YYYY-MM-DD.log →
                # stem = "canli_trade_2026-08-15" → prefix'i at →
                # date_part = "2026-08-15"
                stem = p.stem
                if not stem.startswith(prefix_prefix):
                    continue
                date_part = stem[len(prefix_prefix) :]
                file_date = datetime.strptime(date_part, "%Y-%m-%d").date()
            except (ValueError, IndexError):
                continue  # adlandırma şemasına uymayan dosyaya dokunma
            if (cutoff - file_date).days > self.retention_days:
                try:
                    p.unlink()
                except OSError:
                    pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._roll_if_needed()
            if self._stream is None:
                return
            msg = self.format(record)
            self._stream.write(msg + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        super().close()


def setup_canli_trade_log(
    log_dir: Optional[str] = None,
    prefix: str = DEFAULT_PREFIX,
    retention_days: int = RETENTION_DAYS,
    level: int = logging.INFO,
) -> logging.Logger:
    """Initialize daily-rotating canli_trade logger.

    Creates:
    - ``logs/canli_trade_YYYY-MM-DD.log`` (daily UTC rotation, 14-day
      retention) — ``tail -f`` ile canlı takip edilebilir.
    - stdout stream (interactive session'da görünür).

    Returns the configured logger.
    """
    logger = logging.getLogger(f"sniper_forex.{prefix}")
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_dir_path = Path(log_dir or DEFAULT_LOG_DIR)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    file_handler = DailyUtcFileHandler(
        log_dir=str(log_dir_path),
        prefix=prefix,
        retention_days=retention_days,
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Stream handler (stdout) — interactive session'da görünür
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info(
        "canli_trade log initialized -> %s",
        (log_dir_path / f"{prefix}_{today}.log").absolute(),
    )
    return logger


def canli_trade_logger() -> logging.Logger:
    """Get the configured canli_trade logger (or a no-op fallback)."""
    return logging.getLogger(f"sniper_forex.{DEFAULT_PREFIX}")


def current_daily_path(log_dir: Optional[str] = None, prefix: str = DEFAULT_PREFIX) -> str:
    """Bugünün canli_trade dosya yolunu döndür (tail -f için).

    ``logs/canli_trade_YYYY-MM-DD.log`` — D129 kabul kriteri:
    ``tail -f logs/canli_trade_$(date +%Y-%m-%d).log``.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return str(Path(log_dir or DEFAULT_LOG_DIR) / f"{prefix}_{today}.log")
