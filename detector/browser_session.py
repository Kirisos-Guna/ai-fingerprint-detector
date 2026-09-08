"""Persistent browser session management.

Uses a persistent Chromium profile per target domain so that a manual login
you perform once is reused on future runs against the same site.
"""
from urllib.parse import urlparse

from detector import paths

from playwright.sync_api import sync_playwright

PROFILES_DIR = paths.profiles_dir()


def domain_for(url: str) -> str:
    netloc = urlparse(url).netloc
    if not netloc:
        # allow bare "example.com" input without scheme
        netloc = urlparse("https://" + url).netloc
    return netloc.replace(":", "_")


def normalize_url(url: str) -> str:
    if not urlparse(url).scheme:
        return "https://" + url
    return url


def launch_session(url: str, headless: bool = False):
    """Launch (or reuse) a persistent browser profile for the target site's domain.

    Returns (playwright, context, page). Caller is responsible for closing
    both `context` and stopping `playwright` when done.
    """
    domain = domain_for(url)
    profile_dir = PROFILES_DIR / domain
    executable_path = paths.bundled_chromium_dir() / "chrome.exe"
    profile_dir.mkdir(parents=True, exist_ok=True)

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        executable_path=str(executable_path) if executable_path.exists() else None,
        viewport={"width": 1366, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(normalize_url(url), wait_until="domcontentloaded")
    return pw, context, page
