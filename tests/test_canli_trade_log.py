#!/usr/bin/env python
"""D129 B.2 — canli_trade.log daily rotation tests.

Controlled-unit evidence (AGENTS.md §3): temp dir, no network. Verifies:
- daily file naming (canli_trade_YYYY-MM-DD.log) with TODAY's data
- UTC-midnight rollover (date change -> new dated file)
- 14-day retention pruning
- current_daily_path returns today's path (tail -f acceptance)
"""

import logging
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, r"C:\Users\Administrator\Desktop\sniper_forex")

from src.live.canli_trade_log import (
    DEFAULT_PREFIX,
    RETENTION_DAYS,
    DailyUtcFileHandler,
    current_daily_path,
    setup_canli_trade_log,
)


def _reset_logger(prefix: str = DEFAULT_PREFIX):
    logger = logging.getLogger(f"sniper_forex.{prefix}")
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.INFO)


def test_setup_creates_daily_file_with_today_data():
    """setup_canli_trade_log bugünün tarihli dosyasına yazar (kabul kriteri)."""
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = setup_canli_trade_log(log_dir=tmpdir)
        logger.info("canli test mesaji")
        for handler in logger.handlers:
            handler.flush()
            handler.close()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_file = os.path.join(tmpdir, f"canli_trade_{today}.log")
        assert os.path.exists(daily_file), f"günlük dosya yok: {daily_file}"
        with open(daily_file, "r", encoding="utf-8") as f:
            content = f.read()
            assert "canli test mesaji" in content
    _reset_logger()


def test_current_daily_path_today():
    """current_daily_path bugünün dosyasını döndürür (tail -f kabul kriteri)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = current_daily_path()
    assert path.endswith(f"canli_trade_{today}.log"), path
    assert path.startswith("logs"), path


def test_current_daily_path_custom_dir():
    """current_daily_path özel dizinle çalışır."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = current_daily_path(log_dir=r"C:\tmp\mylogs")
    assert path == rf"C:\tmp\mylogs\canli_trade_{today}.log", path


def test_retention_days_default():
    """Varsayılan retention 14 gün (D129)."""
    assert RETENTION_DAYS == 14


def test_handler_rolls_on_date_change():
    """Gün değişince yeni tarihli dosyaya yazar (UTC-midnight rollover)."""
    dates_iter = iter(["2026-09-05", "2026-09-06"])  # dün → bugün
    orig_today = DailyUtcFileHandler._today

    def fake_today(self):
        return next(dates_iter)

    DailyUtcFileHandler._today = fake_today
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = DailyUtcFileHandler(log_dir=tmpdir)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger = logging.getLogger("test.roll")
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

            logger.info("day1")  # 2026-09-05 dosyası
            day1_file = os.path.join(tmpdir, "canli_trade_2026-09-05.log")
            assert os.path.exists(day1_file), "ilk gün dosyası yok"

            logger.info("day2")  # gün değişti → 2026-09-06 dosyası
            day2_file = os.path.join(tmpdir, "canli_trade_2026-09-06.log")
            assert os.path.exists(day2_file), "gün değişiminde yeni dosya açılmadı"

            handler.close()
            logger.removeHandler(handler)
    finally:
        DailyUtcFileHandler._today = orig_today


def test_handler_prunes_old_files():
    """14 günden eski dosyalar silinir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        handler = DailyUtcFileHandler(log_dir=tmpdir, retention_days=14)
        handler.setFormatter(logging.Formatter("%(message)s"))

        # 20 günlük eski dosya + bugünkü dosya oluştur
        old = os.path.join(tmpdir, "canli_trade_2026-08-15.log")
        with open(old, "w", encoding="utf-8") as f:
            f.write("old\n")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur = os.path.join(tmpdir, f"canli_trade_{today}.log")
        with open(cur, "w", encoding="utf-8") as f:
            f.write("cur\n")

        handler._prune_old()
        assert not os.path.exists(old), "eski dosya silinmedi"
        assert os.path.exists(cur), "bugünkü dosya silinmemeli"


def test_handler_ignores_nonmatching_files():
    """Adlandırma şemasına uymayan dosyalara dokunulmaz."""
    with tempfile.TemporaryDirectory() as tmpdir:
        handler = DailyUtcFileHandler(log_dir=tmpdir, retention_days=14)
        other = os.path.join(tmpdir, "unrelated.log")
        with open(other, "w", encoding="utf-8") as f:
            f.write("x\n")
        handler._prune_old()
        assert os.path.exists(other), "ilgisiz dosya silinmemeli"


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
