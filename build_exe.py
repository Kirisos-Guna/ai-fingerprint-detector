"""Builds a Windows exe of the GUI app with PyInstaller and bundles Chromium.

Usage:  .venv/Scripts/python.exe build_exe.py

Produces dist/AIFingerprintDetector.exe + dist/chromium/ (portable browser).
Distribute the whole dist/ folder (zip it).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
APP_NAME = "AIFingerprintDetector"


def find_playwright_chromium() -> Path:
    """Locate the downloaded Playwright Chromium build directory."""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not base.exists():
        raise SystemExit("Playwright browsers not found; run: playwright install chromium")
    dirs = sorted(base.glob("chromium-*"))
    if not dirs:
        raise SystemExit("No chromium-* directory in " + str(base))
    build = dirs[-1]
    for sub in ("chrome-win64", "chrome-win"):
        candidate = build / sub
        if candidate.exists():
            return candidate
    raise SystemExit("Unexpected Chromium layout inside " + str(build))


def main():
    print("=== 1/3 Cleaning previous build ===")
    for d in (ROOT / "build", ROOT / "dist"):
        if d.exists():
            shutil.rmtree(d)

    print("=== 2/3 Running PyInstaller ===")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", APP_NAME,
        "--add-data", str(ROOT / "fingerprints" / "models.json") + ";fingerprints",
        "--collect-all", "customtkinter",
        "--collect-all", "playwright",
        "gui_app.py",
    ]
    print(" ", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    print("=== 3/3 Bundling Chromium into dist/ ===")
    src = find_playwright_chromium()
    dest = DIST / "chromium"
    print("  copying", src, "->", dest)
    shutil.copytree(src, dest, dirs_exist_ok=True)

    exe = DIST / (APP_NAME + ".exe")
    if not exe.exists():
        raise SystemExit("Build failed: exe not produced")
    size_mb = exe.stat().st_size / 1e6
    print(f"\nDone. {exe} ({size_mb:.0f} MB) + {dest}")
    print("Distribute the entire dist/ folder.")


if __name__ == "__main__":
    main()
