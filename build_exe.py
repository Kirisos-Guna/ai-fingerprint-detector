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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detector.version import APP_NAME as GUI_TITLE, APP_VERSION

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
    print("=== 1/4 Writing version resource ===")
    ver_parts = [int(x) for x in APP_VERSION.split(".")]
    while len(ver_parts) < 4:
        ver_parts.append(0)
    filever = ".".join(str(v) for v in ver_parts)
    icon = ROOT / "assets" / "icon.ico"
    version_file = ROOT / "version_info.txt"
    version_file.write_text(f"""# UTF-8
# Windows VERSIONINFO resource for Explorer metadata.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({ver_parts[0]}, {ver_parts[1]}, {ver_parts[2]}, {ver_parts[3]}),
    prodvers=({ver_parts[0]}, {ver_parts[1]}, {ver_parts[2]}, {ver_parts[3]}),
    mask=0x3F, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable("040904B0", [
        StringStruct("CompanyName", "Kirisos-Guna"),
        StringStruct("FileDescription", "AI chat model fingerprint detector"),
        StringStruct("FileVersion", "{filever}"),
        StringStruct("InternalName", "{APP_NAME}"),
        StringStruct("LegalCopyright", "MIT License (c) 2026 Kirisos-Guna"),
        StringStruct("OriginalFilename", "AIFingerprintDetector.exe"),
        StringStruct("ProductName", "{GUI_TITLE}"),
        StringStruct("ProductVersion", "{filever}"),
      ])
    ]),
    VarFileInfo([VarStruct("Translation", [1033, 1200])]),
  ],
)
""", encoding="utf-8")
    print("  version_info.txt:", APP_VERSION)

    print("=== 2/4 Cleaning previous build ===")
    for d in (ROOT / "build", ROOT / "dist"):
        if d.exists():
            shutil.rmtree(d)

    print("=== 2/4 Running PyInstaller ===")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", APP_NAME,
        "--icon", str(icon),
        "--version-file", str(version_file),
        "--add-data", str(icon) + ";assets",
        "--add-data", str(ROOT / "fingerprints" / "models.json") + ";fingerprints",
        "--collect-all", "customtkinter",
        "--collect-all", "playwright",
        "gui_app.py",
    ]
    print(" ", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    print("=== 3/4 Bundling Chromium into dist/ ===")
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
