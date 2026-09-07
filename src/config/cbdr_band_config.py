#!/usr/bin/env python
"""CBDR band-width percentile config — D139 (rev.4 §2/§5, Reis-onaylı).

DATA-ONLY module: carries the measured CBDR band-width percentile
thresholds per pair. It contains NO runtime logic and is consumed by
nothing yet (rev.4 §7.2: "uygulama ayrı iş — bot/risk.py değişikliği
Reis onayıyla"). Wiring a consumer is a separate, explicitly authorized
task.

Provenance chain (AGENTS.md §8.1):
  * Source table: results/cbdr_calibration_results.md §2
    ("Yan yana — tam 6h kova, Sal–Cum anahtarlı, n=144 her çift"),
    computed from cBot raw logs in results/cbdr_calibration/
    (36 weeks × 6 cycles, closed=True rows only).
  * rev.4 §123 rule: p25/p75/p90 are written to production config with
    the measured values from that table; rounding = 3 significant
    digits.
  * Reis written approval: D138/D139 (memory-bank/HAKEM_EYE_20260903.md
    D137 block + activeContext.md D137-EK).
  * USDCHF & NZDUSD: initially entered as labelled (verified=False,
    matching_bot_report.md §6.1 Seçenek B — no feather data at D139
    time). Verified 2026-09-07 via matching-bot run 20260907_150541
    ( Reis operator order): RAW m1 → feather (65.728/65.711 15m bars,
    validate ALL PASS) → MATCH_A body 0/0 both pairs; sweep 100%
    tol-attributed; closed 6/6 (Sat); single NZDUSD 07-14 1.5-pip
    data-source note (§10.6, root-caused: single-1m-bar bucket drop).
    Flags flipped to verified=True per matching_bot_report.md §10.4
    ("eşleşme-temizliği 7/7 parite") + Reis approval D157.

Regime semantics (rev.4 §117-120, per pair, own percentiles):
  * width <  p25          → "sıkışma"   (compressed)
  * p25 ≤ width < p75     → "tipik"     (typical)
  * p75 ≤ width < p90     → "yükselmiş" (elevated)
  * width ≥ p90           → "makro"     (macro)

Excluded by design (matching_bot_report.md §6.2): the rev.4
"Cmt-anahtarlı döngüler ayrı percentile seti" decision is NOT
implementable in production — SessionManager discards those cycles
(locked=False at reset). The Saturday-keyed bucket is therefore NOT
carried here; production never classifies those cycles.
"""

from typing import Dict, NamedTuple


# 3-significant-digit rounding per rev.4 §123.
# Fields are the rev.4 §2 table columns (percent of band-low, %).
class BandWidthPercentiles(NamedTuple):
    """Measured CBDR band-width percentile thresholds for one pair (%)."""

    p25: float
    p75: float
    p90: float
    median: float  # informational (rev.4 §2 medyan column)
    verified: bool  # True = matching-bot verified; False = labelled entry


# rev.4 §2 table, transcribed verbatim (3 significant digits).
# Order follows the report's ranking (narrow → wide median).
CBDR_BAND_PERCENTILES: Dict[str, BandWidthPercentiles] = {
    "USDCAD": BandWidthPercentiles(p25=0.0841, p75=0.143, p90=0.210, median=0.107, verified=True),
    "EURUSD": BandWidthPercentiles(p25=0.0866, p75=0.166, p90=0.267, median=0.112, verified=True),
    "GBPUSD": BandWidthPercentiles(p25=0.0996, p75=0.184, p90=0.281, median=0.128, verified=True),
    "USDJPY": BandWidthPercentiles(p25=0.106, p75=0.223, p90=0.361, median=0.164, verified=True),
    "AUDUSD": BandWidthPercentiles(p25=0.145, p75=0.290, p90=0.466, median=0.196, verified=True),
    # Verified 2026-09-07 (matching-bot run 20260907_150541, §10.3/§10.4):
    # MATCH_A body 0/0 both pairs; values unchanged (measured cBot-log
    # percentiles, rev.4 §2).
    "USDCHF": BandWidthPercentiles(p25=0.152, p75=0.254, p90=0.374, median=0.203, verified=True),
    "NZDUSD": BandWidthPercentiles(p25=0.182, p75=0.365, p90=0.520, median=0.234, verified=True),
}

# Regime classification thresholds, per pair (rev.4 §117-120).
# regime = "sıkışma" | "tipik" | "yükselmiş" | "makro"
REGIME_NAMES = ("sikisma", "tipik", "yukselmis", "makro")


def classify_width_regime(symbol: str, width_pct: float) -> str:
    """Classify a CBDR band width into its per-pair regime.

    Pure function over the data above; no runtime state. Returns one of
    REGIME_NAMES. Unknown symbols raise KeyError (fail-loud, no silent
    fallback — AGENTS.md §19).
    """
    p = CBDR_BAND_PERCENTILES[symbol]
    if width_pct < p.p25:
        return "sikisma"
    if width_pct < p.p75:
        return "tipik"
    if width_pct < p.p90:
        return "yukselmis"
    return "makro"


def get_band_percentiles(symbol: str) -> BandWidthPercentiles:
    """Fail-loud accessor for the per-pair percentile row."""
    return CBDR_BAND_PERCENTILES[symbol]
