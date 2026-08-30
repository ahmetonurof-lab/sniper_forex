#!/usr/bin/env python
"""SNIPER FOREX — Data Loader

Reads Feather files and provides normalized Bar objects.
Only input: data/feather/*.feather
No CSV fallback.
"""

from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from src.strategy.models import Bar


class DataLoader:
    """Deterministic data loader from Feather files.

    Rules:
    - Only reads from data/feather/*.feather
    - No CSV fallback
    - Timestamps normalized to UTC (as-is from MT5)
    - OHLCV columns standardized
    - Chronological ordering guaranteed
    - Duplicate and invalid OHLC checks
    """

    def __init__(self, feather_dir: Optional[Path] = None):
        """Initialize DataLoader.

        Args:
            feather_dir: Path to feather directory.
                        Defaults to data/feather/
        """
        if feather_dir is None:
            feather_dir = Path(__file__).parent.parent.parent / "data" / "feather"

        self.feather_dir = Path(feather_dir)

        if not self.feather_dir.exists():
            raise FileNotFoundError(f"Feather directory not found: {self.feather_dir}")

    def list_symbols(self) -> List[str]:
        """List all available symbols."""
        return sorted([f.stem.replace("_1m", "") for f in self.feather_dir.glob("*.feather")])

    def load(self, symbol: str) -> List[Bar]:
        """Load all bars for a symbol as list of Bar objects.

        Optimized: uses zip() instead of iterrows().
        """
        feather_path = self.feather_dir / f"{symbol}_1m.feather"

        if not feather_path.exists():
            raise FileNotFoundError(f"Feather file not found: {feather_path}")

        df = pd.read_feather(feather_path)

        required = ["timestamp", "open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing column: {col}")

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.drop_duplicates(subset="timestamp", keep="first")

        # Bulk OHLC validation
        ohlc_ok = (
            (df["high"] >= df["open"]).all()
            and (df["high"] >= df["close"]).all()
            and (df["low"] <= df["open"]).all()
            and (df["low"] <= df["close"]).all()
            and (df["high"] >= df["low"]).all()
            and (df["open"] > 0).all()
            and (df["high"] > 0).all()
            and (df["low"] > 0).all()
            and (df["close"] > 0).all()
        )
        if not ohlc_ok:
            raise ValueError(f"Invalid OHLC in {symbol}")

        # Fast Bar creation using zip
        timestamps = df["timestamp"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        volumes = df["volume"].values

        bars = [
            Bar(
                index=i,
                timestamp=pd.Timestamp(ts),
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
            )
            for i, ts, o, h, l, c, v in zip(
                range(len(timestamps)), timestamps, opens, highs, lows, closes, volumes
            )
        ]

        return bars

    def load_dataframe(self, symbol: str) -> pd.DataFrame:
        """Load as DataFrame (for aggregation, etc.)."""
        feather_path = self.feather_dir / f"{symbol}_1m.feather"
        df = pd.read_feather(feather_path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def get_symbol_info(self, symbol: str) -> Dict:
        """Get metadata about a symbol's data."""
        bars = self.load(symbol)
        if not bars:
            return {"symbol": symbol, "rows": 0}

        return {
            "symbol": symbol,
            "rows": len(bars),
            "first_timestamp": bars[0].timestamp,
            "last_timestamp": bars[-1].timestamp,
            "date_range_days": (bars[-1].timestamp - bars[0].timestamp).days,
        }
