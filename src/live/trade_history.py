#!/usr/bin/env python
"""D129 B.4 — TRADE_HISTORY.JSOM (JSON-Lines append journal).

Amaç: Her kapanan trade'i tek satır JSON olarak ``trade_history.json``'a
yaz. Aus—the 'append' modu: her trade bir satır, dosya LINESON'dur
(eski delimiter sorunu yok).

Şema (D129 B.4):
- trade_id      : UUID4 (benzersiz, tesis tanımlayıcı)
- symbol        : str
- direction     : "LONG" | "SHORT"
- cbdr_context  : {body_low, body_high, width_pct, bias}
- entry         : {time, price, fvg: {top, bottom}, trigger}
- initial_sl    : float
- initial_tp    : float
- trailing_hops : [{bar_index, new_sl}]
- exit          : {time, price, reason}
- r_realized    : float
- risk_multiplier_used : float
- duration_bars : int

İSTİSNİ (AGENTS.md §12.1):
D129 ''trailing_hops'' şeması, ``LiveRunner``'ın mevcut
``OpenTradeContext.realized_r_accumulated`` ve
``RecordedDealRecord`` alanlarından tam olarak pullanamaz — currently
``trailing_hops`` Boş Liste ``[]`` olarak yazılır. Kalibrasyon
``trade_history`` alanları ``live_runner.poll_deals`` içinde doldurulur
(D129 B.4'nün ''yazma noktası'' buysa).

YAZMA NOKTASI: ``LiveRunner.poll_deals()`` — ``EventType.EXIT`` audit
emit'inin hemen ardı, ``cash``/``pnl_r`` ve ``OpenTradeContext`` tüm
alanlarıyla hesaplanabilir durumda (D129 B.4 mandate).

DOĞRULAMA:
Kod doğrudan ``OpenTradeContext`` ve ``RealizedDealRecord`` alanlarından
üretilir; testify'ler üretici-montaj sahte-dir (D129 Acceptance)
değildir — gerçek ``LiveRunner`` yolunu test eder (AGENTS.md §3).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sniper_forex.trade_history")

TRADE_HISTORY_FILENAME = "trade_history.json"

# ─── Schema Helpers ────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_trade_id() -> str:
    """UUID4 trade identifier (benzersiz)."""
    return str(uuid.uuid4())


def make_trade_record(
    *,
    symbol: str,
    direction: str,
    cbdr_context: Dict[str, Any],
    entry_time: Any,
    entry_price: float,
    fvg: Optional[Dict[str, Any]],
    trigger: str,
    initial_sl: float,
    initial_tp: float,
    trailing_hops: List[Dict[str, Any]],
    exit_time: Any,
    exit_price: float,
    exit_reason: str,
    r_realized: float,
    risk_multiplier_used: float,
    duration_bars: int,
) -> Dict[str, Any]:
    """D129 B.4 trade record."""
    return {
        "trade_id": new_trade_id(),
        "symbol": symbol,
        "direction": direction.upper(),
        "cbdr_context": {
            "body_low": cbdr_context.get("body_low", 0.0),
            "body_high": cbdr_context.get("body_high", 0.0),
            "width_pct": cbdr_context.get("width_pct", 0.0),
            "bias": cbdr_context.get("bias", "NEUTRAL"),
        },
        "entry": {
            "time": str(entry_time),
            "price": entry_price,
            "fvg": {
                "top": (fvg or {}).get("top", 0.0),
                "bottom": (fvg or {}).get("bottom", 0.0),
            },
            "trigger": trigger,
        },
        "initial_sl": initial_sl,
        "initial_tp": initial_tp,
        "trailing_hops": trailing_hops or [],
        "exit": {
            "time": str(exit_time),
            "price": exit_price,
            "reason": exit_reason,
        },
        "r_realized": r_realized,
        "risk_multiplier_used": risk_multiplier_used,
        "duration_bars": duration_bars,
    }


# ─── Writer ────────────────────────────────────────────────────────


class TradeHistoryWriter:
    """Append-only JSON-Lines writer for trade_history.json.

    Her ``write(record)`` çağrısı bir satır ekler. Dosya JSON Lines
    formatındadır (her satır bağımsız JSON nesnesi).
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = Path(path or TRADE_HISTORY_FILENAME)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: Dict[str, Any]) -> None:
        """Trade record'unu dosyaya append et (JSON Lines)."""
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def count(self) -> int:
        """Mevcut satır sayısını say (0 = boş)."""
        if not self._path.exists():
            return 0
        with open(self._path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)

    def read_all(self) -> List[Dict[str, Any]]:
        """Tüm kayıtları oku (test/analiz için)."""
        if not self._path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
