# EXP 5F — Frozen EQ vs Dynamic Research EQ

## TANIM

Aynı motorun tek değişkenli EQ karşılaştırması.

- **Variant A (Frozen EQ)**: `eq = (sweep_price + range_opposite) / 2`
- **Variant B (Dynamic Research EQ)**: `research_eq = (swing_high + swing_low) / 2`

Tek değişken: EQ definition. Her şey aynı.

## POPULATION

- Symbols: ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'GBPJPY']
- Window: 180d
- Frozen EQ trades: **529**
- Dynamic EQ trades: **469**

## 1. SIDE-BY-SIDE COMPARISON

| Metric | Frozen EQ | Dynamic EQ | Delta |
|---|---|---|---|
| N | 529 | 469 | -60.00 |
| completed | 529 | 469 | -60.00 |
| WR% | 59.7 | 61.6 | +1.90 |
| AvgR | 0.968 | 0.884 | -0.08 |
| TotalR | 512.23 | 414.57 | -97.66 |
| MaxDD_R | 7.32 | 7.2 | -0.12 |
| MaxDD_% | 3.83 | 3.7 | -0.13 |
| PF | 3.4 | 3.3 | -0.10 |

## 2. PER-SYMBOL COMPARISON

| Symbol | Frozen N | Frozen WR% | Frozen AvgR | Dynamic N | Dynamic WR% | Dynamic AvgR | Delta N |
|---|---|---|---|---|---|---|---|
| EURUSD | 91 | 58.2 | 0.633 | 78 | 59.0 | 0.751 | -13 |
| GBPUSD | 82 | 53.7 | 1.031 | 72 | 51.4 | 0.795 | -10 |
| USDJPY | 85 | 58.8 | 0.728 | 73 | 60.3 | 0.733 | -12 |
| AUDUSD | 93 | 58.1 | 1.205 | 87 | 57.5 | 0.608 | -6 |
| USDCAD | 90 | 58.9 | 1.325 | 79 | 65.8 | 1.437 | -11 |
| GBPJPY | 88 | 70.5 | 0.874 | 80 | 75.0 | 0.985 | -8 |

## 3. TRADE-LEVEL ATTRIBUTION

| Category | N |
|---|---|
| Both variants traded | 385 |
| Only Frozen EQ | 144 |
| Only Dynamic EQ | 84 |

### Common Trades Outcome

| Variant | N | WR% | AvgR | TotalR | MaxDD_R | MaxDD_% | PF |
|---|---|---|---|---|---|---|---|
| Common-Frozen | 385 | 385 | 61.3 | 0.936 | 360.49 | 6.51 | 2.78 | 3.42 |
| Common-Dynamic | 385 | 385 | 61.3 | 0.946 | 364.35 | 6.51 | 2.72 | 3.45 |

### Only-Frozen EQ Trades

| Variant | N | WR% | AvgR | TotalR | MaxDD_R | MaxDD_% | PF |
|---|---|---|---|---|---|---|---|
| Only-Frozen | 144 | 144 | 55.6 | 1.054 | 151.74 | 9.0 | 7.58 | 3.37 |

### Only-Dynamic EQ Trades

| Variant | N | WR% | AvgR | TotalR | MaxDD_R | MaxDD_% | PF |
|---|---|---|---|---|---|---|---|
| Only-Dynamic | 84 | 84 | 63.1 | 0.598 | 50.22 | 5.57 | 4.41 | 2.62 |

## 4. DYNAMIC EQ NET IMPACT

- Dynamic EQ **added** 84 new trades (53 wins, 31 losses)
- Dynamic EQ **removed** 144 Frozen EQ trades (80 wins, 64 losses)

Observation-only. No commentary or decision.
