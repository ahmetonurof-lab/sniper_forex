#!/usr/bin/env python
"""Step 2 — 65K M1 EURUSD parity regression harness (reproducible).

Freezes:
- exact dataset identity (fixture identity / raw dataset reference),
- first/last M1 timestamp, M1 count, duplicate/missing counts,
- sortedness check,
- M15 boundary counts,
- signal count and identities,
- first divergence layer and object pair (if any).

This harness does NOT modify StrategyRuntime; it only measures divergence.
"""

import json
from pathlib import Path


def harness_artifact_path() -> Path:
    return Path("results/research/65k_m1_eurusd_parity_artifact.json")


def freeze_artifact(
    dataset_identity: str,
    head_sha: str,
    raw_first: str,
    raw_last: str,
    m1_count: int,
    duplicate_count: int,
    missing_count: int,
    sorted_ok: bool,
    first_m15: str,
    last_m15: str,
    m15_count: int,
    signal_count: int,
    signal_ids: list,
    first_divergence: str | None = None,
    divergence_layer: str | None = None,
    divergence_pair: str | None = None,
):
    artifact = {
        "dataset_identity": dataset_identity,
        "dataset_reference": "data/icmarket_raw/EURUSD_Minute_2024_2026_RAW.csv",
        "head_sha": head_sha,
        "raw_first_timestamp": raw_first,
        "raw_last_timestamp": raw_last,
        "raw_m1_count": m1_count,
        "duplicate_m1_count": duplicate_count,
        "missing_m1_count": missing_count,
        "sortedness_check": sorted_ok,
        "first_m15_timestamp": first_m15,
        "last_m15_timestamp": last_m15,
        "m15_count": m15_count,
        "signal_count": signal_count,
        "signal_identities": signal_ids,
        "first_divergence": first_divergence,
        "first_divergence_layer": divergence_layer,
        "first_divergence_object_pair": divergence_pair,
    }
    harness_artifact_path().parent.mkdir(parents=True, exist_ok=True)
    with open(harness_artifact_path(), "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)
    return artifact


def load_artifact() -> dict:
    with open(harness_artifact_path(), "r", encoding="utf-8") as f:
        return json.load(f)
