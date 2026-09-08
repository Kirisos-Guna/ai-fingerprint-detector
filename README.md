# AI Chat Model Fingerprint Detector

[![Build Windows exe](https://github.com/Kirisos-Guna/ai-fingerprint-detector/actions/workflows/build-release.yml/badge.svg)](https://github.com/Kirisos-Guna/ai-fingerprint-detector/actions/workflows/build-release.yml)

Determines which AI model **actually powers** a chat website — regardless of
what the site claims. It launches a real browser (Playwright), lets you
calibrate the site's UI once, then automatically sends a battery of probe
prompts, captures network traffic, and scores the evidence into a verdict
report.

## How it decides

| Signal | What it looks for | Weight |
|---|---|---|
| **Network** | Requests to known provider API domains (`api.deepseek.com`, `api.openai.com`, ...) and distinctive provider response headers | strongest |
| **Reasoning leak** | Literal `<think>...</think>` tags left in the DOM (DeepSeek-R1 family) | strong |
| **Censorship pairs** | A PRC-sensitive question gets deflected/refused while a structurally identical control question is answered normally (Tiananmen vs. Kent State, Taiwan vs. Kosovo, ...) | corroborating — identifies the *family*, not one exact model |
| **Self-ID** | Provider/model names surfacing in "what model are you" replies | weakest |

Each known model accumulates weighted points; the top scorer wins. Confidence
(`high/medium/low/none`) reflects how many independent signal categories agree.

Fingerprints live in `fingerprints/models.json` (OpenAI, Anthropic, Google,
Mistral, Meta, DeepSeek, Qwen, GLM/Zhipu, Moonshot Kimi, Baidu ERNIE) and are
easy to extend.

## Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
# First run on a site: guided calibration
python main.py https://example-chat.com

# Equivalent module form
python -m detector https://example-chat.com

# Tell the tool what the site claims to be -> enables claim-vs-verdict check
python main.py https://example-chat.com --claims claude

# Redo calibration (selectors changed, or calibration was wrong)
python main.py https://example-chat.com --calibrate

# Headless run (only after calibration is already saved)
python main.py https://example-chat.com --headless
```

### Options

| Flag | Effect |
|---|---|
| `--claims NAME` | What the site claims to be (`gpt-4`, `claude`, `deepseek`, ...). Adds a claim-vs-verdict comparison. |
| `--calibrate` | Force the calibration wizard even if this domain is already calibrated. |
| `--headless` | Run Chromium without a window. |
| `--report-dir DIR` | Write reports somewhere other than `reports/`. |
| `--no-network-capture` | Skip passive network fingerprinting. |

## Calibration (once per site)

The first run on a new domain walks you through:

1. **Chat input box** — auto-detected and highlighted in red; confirm or click
   the right element yourself.
2. **Send button** — auto-detected; or tell the tool the site sends on Enter.
3. **Response element** — you send any test message manually, wait for the AI
   reply to finish, then click directly on the reply text.

Selectors are saved to `config/sites/<domain>.json`, so later runs (including
headless ones) reuse them. Login sessions persist in `profiles/<domain>/`,
so a manual login you do once is reused on future runs.

## Reports

Every run writes two files to `reports/`:

- `report_<timestamp>.json` — the full machine-readable record: verdict, all
  scores, every pair classification, and every raw probe response.
- `report_<timestamp>.md` — the human-readable summary with the same data.

The terminal also prints a colorized verdict panel and censorship-pair table.

## Interpreting results

- **high confidence + network signal** — the page itself talked to that
  provider's API; about as direct as evidence gets.
- **censorship hits with a PRC family verdict** — the deflection-pattern
  fingerprint is present; note this identifies the *family* (DeepSeek/Qwen/
  GLM/Kimi/ERNIE), not which one specifically.
- **`empty` sensitive/control answers** — the response selector may be wrong,
  or the site rate-limited; check the raw responses in the report and consider
  re-running with `--calibrate`.
- **Confidence `none`** — no signal fired; the site may route through an
  aggregator the DB doesn't know about (extend `fingerprints/models.json`).

## Desktop GUI

```bash
python gui_app.py
```

Same pipeline as the CLI in a window: enter the chat site URL, optionally pick
what the site *claims* to be, and press **Run detection**. Calibration dialogs
appear as popups (the browser window itself is where you click elements during
first-time calibration). Live progress, verdict panel, and buttons to open the
JSON/Markdown reports are all in the app.

## Download prebuilt exe

Ready-made builds are attached to GitHub Releases (built automatically by
GitHub Actions on every `v*` tag, selftest-verified before upload):

```bash
gh release download --repo Kirisos-Guna/ai-fingerprint-detector --pattern "*-win64.zip"
```

or grab the zip from the Releases page and unzip anywhere.

## Windows .exe (build it yourself)

Build it yourself:

```bash
.venv/Scripts/python.exe build_exe.py
```

Output (in `dist/`):

- `AIFingerprintDetector.exe` (~56 MB)
- `chromium/` (portable Chromium used automatically by the exe)

Distribute the **entire `dist/` folder** (zip it). No Python, no browser
install, no setup needed on the target Windows 10/11 machine. Reports,
calibration caches, and browser profiles are created next to the exe.

Sanity-check any build without touching a real website:

```bash
dist/AIFingerprintDetector.exe --selftest
```

Note: the exe is unsigned, so Windows SmartScreen shows a warning on other
machines ("More info" -> "Run anyway").

## Project layout

```
main.py                    convenience entry point
gui_app.py                 desktop GUI (CustomTkinter) + --selftest
build_exe.py               PyInstaller build script (exe + bundled Chromium)
detector/
  paths.py                 frozen-aware path resolution
  cli.py                   argument parsing + run orchestration
  browser_session.py       persistent per-domain Chromium profiles
  calibration.py           UI selector auto-detect + click-to-pick wizard
  probes.py                censorship pairs, self-ID, formatting probes
  runner.py                sends probes, waits for streaming to settle
  network_capture.py       passive provider domain/header evidence
  analyzer.py              classification + weighted scoring + verdict
  fingerprint_db.py        loads fingerprints/models.json, claim aliases
  report.py                JSON / Markdown / rich console rendering
fingerprints/models.json   provider domain + header fingerprints
config/sites/              per-domain saved calibration (gitignored)
profiles/                  persistent browser profiles (gitignored)
reports/                   run output (gitignored)
```

## Extending the fingerprint DB

Add a model to `fingerprints/models.json`:

```json
"new_model": {
  "display_name": "New Model (Vendor)",
  "network": {
    "domains": ["api.newvendor.com"],
    "headers": ["x-newvendor-something"]
  },
  "notes": ""
}
```

Then add self-ID regexes in `detector/analyzer.py` (`_SELF_ID_PATTERNS`) and,
if relevant, family membership in `PRC_FAMILY` / `WESTERN_FAMILY`.

## License

MIT — see [LICENSE](LICENSE). You are free to use, modify, and redistribute
this tool, including commercially.

## Legal / responsible use

Only test sites you are authorized to test. Probing sends real prompts to the
target service and consumes its resources; respect their terms of service and
applicable law.
