"""Central path resolution that works both from source and inside a
PyInstaller-frozen executable (onefile or onedir).

Read-only data shipped inside the bundle (fingerprints/) is resolved against
sys._MEIPASS when frozen. Writable per-user data (config/, profiles/,
reports/) always lives next to the executable when frozen, so users can find
and back it up; from source it stays in the project root as before.
"""
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def base_dir() -> Path:
    """Directory containing the project (source) or the exe (frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundled_data_dir() -> Path:
    """Directory holding read-only data shipped inside the bundle."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return base_dir()


def fingerprints_dir() -> Path:
    return bundled_data_dir() / "fingerprints"


def config_dir() -> Path:
    d = base_dir() / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sites_config_dir() -> Path:
    d = config_dir() / "sites"
    d.mkdir(parents=True, exist_ok=True)
    return d


def profiles_dir() -> Path:
    d = base_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reports_dir() -> Path:
    d = base_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_chromium_dir() -> Path:
    """Where the build script copies the Playwright Chromium for the exe."""
    return base_dir() / "chromium"
