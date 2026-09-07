# CBDRCalibrationBot — cTrader Automate Scaffold

D132 Adım 4 deliverable. This folder contains a **complete, self-contained**
cTrader Automate Python cBot project that can be compiled and deployed
directly in the cTrader platform.

> **cTrader 5.9.10 verified (2026-09-06):** `dotnet build` → **SUCCESS, 0 errors.**
> Output: `CBDRCalibrationBot.algo` (198KB).

## Architecture

```
CBDRCalibrationBot.csproj          ← .NET 6.0 project file (cTrader 5.9 format)
CBDRCalibrationBot.cs              ← partial Robot subclass (SourceGenerators)
CBDRCalibrationBotBridge.cs        ← C#→Python bridge (lifecycle proxies)
config.json                        ← 6 parameters (cTrader 5.9 SourceGenerators)
EngineHelper.cs                    ← Python runtime init (Spotware standard)
BaseBridge.cs                      ← Timer + Exception bridge (Spotware standard)
SafeExecuteMethodProxy.cs          ← Safe Python method invocation (Spotware standard)
EmbeddedResourceProvider.cs        ← Assembly resource reader (Spotware standard)
PythonHooks.cs                     ← In-memory Python module loader (Spotware standard)
PythonManifest.cs                  ← Manifest POCO (Spotware standard)
EmbeddedResources.manifest.json    ← Lists embedded .py files
requirements.txt                   ← Python deps (stdlib-only, required by csproj)
cbdr_calibration_bot.py            ← Presentation shim (Adım 2+3)
core.py                            ← Pure compute engine (Adım 2)
robot_wrapper.py                   ← Order helpers (Spotware standard, not used by cal bot)
```

## cTrader 5.9 Parameter System (IMPORTANT)

cTrader 5.9.10 uses **`cTrader.Automate.SourceGenerators` + `config.json`** —
NOT the old `[Parameter]` attributes. Key rules:

- Class must be `public partial class CBDRCalibrationBot : Robot`
- Parameters live in `config.json` (`Name` field → `api.<Name>` in Python)
- Valid `Type` values: `Integer`, `Double`, `Boolean`, `String`, `Enum`,
  `Color`, `TimeFrame`, `Symbol`, `DateTime`, `DateOnly`, `TimeSpan`, ...
  (`"Int"` is INVALID — use `"Integer"`)
- `PlatformVersion` type does NOT exist in 5.9.10 — do not use
  `SetPlatformVersion` / `IsPlatformVersionSupported`
- `EngineHelper.Run(Action, Action<Exception>)` is REQUIRED
- `requirements.txt` is REQUIRED (referenced by `.csproj`)
- `using cAlgo.API;` is REQUIRED in the Robot file

## C# Parameters (surfaced to cTrader UI / Optimizer)

| Parameter               | Default | Range         | Step | Group |
|------------------------|---------|---------------|------|-------|
| Eps Minutes            | 15      | 1 – 60        | 1    | CBDR  |
| ATR Period             | 96      | 1 – 500       | 1    | CBDR  |
| Sweep ATR Tolerance Mult | 0.02  | 0.0 – 0.5     | 0.01 | CBDR  |
| Sweep Default Tolerance  | 0.0   | 0.0 – 0.01    | 0.001| CBDR  |
| Span Start HHMM       | 1900    | 0 – 2359      | 100  | CBDR  |
| Span End HHMM         | 100     | 0 – 2359      | 100  | CBDR  |

## Deployment (MT5-EA style)

**ONE cBot per chart, same code, re-attach per pair.**

1. Open cTrader Automate IDE (or Visual Studio with cTrader SDK).
2. Create a new Python cBot project (or copy this folder).
3. Copy all files from this scaffold into the project.
4. Build — cTrader compiles the C# bridge, which embeds the .py files.
5. Attach to a chart (e.g., EURUSD M15).
6. The bot reads `api.SymbolName` / `api.Bars` — no multi-symbol code needed.
7. Repeat for each pair: EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD.

## Build (command line, verified)

```bash
export PATH="/c/Users/Administrator/AppData/Local/Microsoft/dotnet:$PATH"
cd "C:\Users\Administrator\Documents\cAlgo\Sources\Robots\CBDRCalibrationBot\CBDRCalibrationBot"
dotnet build
```

Requires .NET 6 SDK (installed to user-local dir, added to PATH).

## Optimizer (single-symbol, 6 sequential runs)

```python
# From docs/ctrader_python_cbot_api_research.md §7.3:
# Optimizer calls get_fitness() per symbol. For multi-symbol calibration,
# run 6 sequential optimizer passes (one per pair), collect width distributions,
# then merge into a single calibration table.
```

## Python Import Fix

The scaffold copy of `cbdr_calibration_bot.py` uses:
```python
from core import (...)
```
instead of the development copy's `from src.ctrader.cbot.core import (...)`.
This is required because the cTrader in-memory importer registers modules
by filename (without extension).

## Spotware Infrastructure Files

Files marked "Spotware standard" are copied verbatim from
[spotware/ctrader-python-algo-samples](https://github.com/spotware/ctrader-python-algo-samples)
(MIT licensed). They are identical across all Python algo samples and should
NOT be modified. To upgrade, re-copy from the Spotware samples repository.

## Known Limitations

- `SafeExecuteMethodProxy` silently no-ops for undefined Python methods.
  If a lifecycle method is missing in Python, it won't raise an error.
- The optimizer's `GetFitness()` returns 0 — implement per-pair fitness
  logic when Adım 5 calibration run is ready.
- cTrader 5.9.10 no longer has `PlatformVersion` — the platform-version
  guard from older Spotware samples was removed.
