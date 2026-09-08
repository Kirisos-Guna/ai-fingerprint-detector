"""Resolves the chat input box, send mechanism, and response container for a
site, so probes can be sent generically on any chat UI.

Strategy: try to auto-detect each element with a heuristic, show the user a
red highlight and ask for confirmation. If auto-detect fails or is wrong,
fall back to asking the user to click the element directly in the browser.
Results are cached per-domain in config/sites/<domain>.json so this only
needs to happen once per site.

All user interaction goes through injectable UI callbacks (DEFAULT_UIS) so a
GUI can substitute thread-safe dialogs without touching this logic.
"""
import json
import time

from detector import paths

from playwright.sync_api import Page

CONFIG_DIR = paths.sites_config_dir()

# Computes a reasonably unique CSS selector path for an arbitrary clicked element.
_CSS_PATH_JS = """
function cssPath(el) {
    if (!(el instanceof Element)) return null;
    const path = [];
    while (el && el.nodeType === Node.ELEMENT_NODE) {
        let selector = el.nodeName.toLowerCase();
        if (el.id) {
            selector += '#' + el.id;
            path.unshift(selector);
            break;
        } else {
            let sib = el, nth = 1;
            while (sib.previousElementSibling) {
                sib = sib.previousElementSibling;
                if (sib.nodeName.toLowerCase() === el.nodeName.toLowerCase()) nth++;
            }
            if (nth !== 1) selector += ':nth-of-type(' + nth + ')';
        }
        path.unshift(selector);
        el = el.parentElement;
        if (path.length > 8) break;
    }
    return path.join(' > ');
}
"""

# Walk up from a clicked element to the nearest ancestor with classes, used
# for the response bubble so future lookups can match ALL sibling messages.
_REPEATABLE_JS = """
function findRepeatableSelector(el) {
    let node = el;
    for (let i = 0; i < 6 && node; i++) {
        if (node.classList && node.classList.length > 0) {
            return node.tagName.toLowerCase() + '.' +
                Array.from(node.classList).map(c => CSS.escape(c)).join('.');
        }
        node = node.parentElement;
    }
    return null;
}
"""

# Default UI callbacks (console). The GUI injects thread-safe equivalents.
DEFAULT_UIS = {
    "confirm": lambda prompt: input(f"{prompt} [Y/n]: ").strip().lower() in ("", "y", "yes"),
    "prompt": input,
    "notify": print,
}


def load_calibration(domain: str):
    path = CONFIG_DIR / f"{domain}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_calibration(domain: str, data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / f"{domain}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _click_and_capture(page: Page, instruction: str, repeatable: bool,
                       ui: dict | None = None) -> str:
    ui = ui or DEFAULT_UIS
    ui["notify"](f"\n>>> {instruction}")
    ui["notify"]("    (Click the element in the browser window now...)")
    setup_js = _CSS_PATH_JS + (_REPEATABLE_JS if repeatable else "") + """
        window.__calibrationDone = false;
        window.__calibrationSelector = null;
        window.__calibrationHandler = function(e) {
            e.preventDefault();
            e.stopPropagation();
    """
    if repeatable:
        setup_js += """
            const repeatableSel = findRepeatableSelector(e.target);
            window.__calibrationSelector = repeatableSel || cssPath(e.target);
        """
    else:
        setup_js += """
            window.__calibrationSelector = cssPath(e.target);
        """
    setup_js += """
            window.__calibrationDone = true;
            document.removeEventListener('click', window.__calibrationHandler, true);
        };
        document.addEventListener('click', window.__calibrationHandler, true);
    """
    page.evaluate(setup_js)

    while True:
        done = page.evaluate("window.__calibrationDone === true")
        if done:
            break
        time.sleep(0.2)

    selector = page.evaluate("window.__calibrationSelector")
    ui["notify"](f"    Captured selector: {selector}")
    return selector


def manual_pick_element(page: Page, instruction: str, ui: dict | None = None) -> str:
    return _click_and_capture(page, instruction, repeatable=False, ui=ui)


def manual_pick_repeatable_element(page: Page, instruction: str,
                                   ui: dict | None = None) -> str:
    return _click_and_capture(page, instruction, repeatable=True, ui=ui)


def try_auto_detect_input(page: Page):
    """Attempt to find the chat input automatically. Returns a selector or None."""
    return page.evaluate(_CSS_PATH_JS + """
        () => {
            const els = Array.from(document.querySelectorAll('textarea, [contenteditable="true"], input[type="text"]'));
            const visible = els.filter(el => {
                const rect = el.getBoundingClientRect();
                return rect.width > 100 && rect.height > 15 && getComputedStyle(el).display !== 'none';
            });
            if (visible.length === 0) return null;
            const scored = visible.map(el => {
                const rect = el.getBoundingClientRect();
                const ph = (el.getAttribute('placeholder') || '').toLowerCase();
                let score = rect.width * rect.height;
                if (/message|ask|chat|prompt|type|send/.test(ph)) score *= 3;
                score += (window.innerHeight - rect.top);
                return { el, score };
            });
            scored.sort((a, b) => b.score - a.score);
            return cssPath(scored[0].el);
        }
    """)


def try_auto_detect_send(page: Page, input_selector: str):
    """Attempt to find a send button near the input. Returns a selector or None."""
    return page.evaluate(_CSS_PATH_JS + """
        (inputSelector) => {
            const input = document.querySelector(inputSelector);
            if (!input) return null;
            const container = input.closest('form') || input.parentElement?.parentElement || document.body;
            const buttons = Array.from(container.querySelectorAll('button, [role="button"]'));
            const guess = buttons.find(b => {
                const label = (b.getAttribute('aria-label') || b.textContent || '').toLowerCase();
                return /send|submit|\bask\b|\bgo\b/.test(label);
            });
            return guess ? cssPath(guess) : null;
        }
    """, input_selector)


def highlight(page: Page, selector: str):
    if not selector:
        return
    page.evaluate("""
        (sel) => {
            const el = document.querySelector(sel);
            if (el) {
                el.style.outline = '3px solid red';
                el.scrollIntoView({block: 'center'});
            }
        }
    """, selector)


def unhighlight(page: Page, selector: str):
    if not selector:
        return
    page.evaluate("""
        (sel) => {
            const el = document.querySelector(sel);
            if (el) el.style.outline = '';
        }
    """, selector)


def confirm(prompt: str, ui: dict | None = None) -> bool:
    ui = ui or DEFAULT_UIS
    return bool(ui["confirm"](prompt))


def calibrate(page: Page, domain: str, force: bool = False,
              ui: dict | None = None) -> dict:
    """Resolve input/send/response selectors for this site.

    Uses auto-detect with a highlight + confirm step, falling back to manual
    click-to-select. Caches the resolved selectors per-domain.

    `ui` may override the console callbacks: keys "confirm" (question -> bool),
    "prompt" (question -> str), "notify" (text -> None). Defaults are console
    input()/print(), so behavior from the CLI is unchanged.
    """
    ui = ui or DEFAULT_UIS

    if not force:
        cached = load_calibration(domain)
        if cached:
            ui["notify"](f"Using saved calibration for {domain} "
                         f"(config/sites/{domain}.json). Pass --calibrate to redo it.")
            return cached

    ui["notify"]("\n=== Calibration ===")

    input_selector = try_auto_detect_input(page)
    if input_selector:
        highlight(page, input_selector)
        ok = confirm("Auto-detected the chat MESSAGE INPUT box (highlighted in red). Is this correct?", ui)
        unhighlight(page, input_selector)
        if not ok:
            input_selector = None
    if not input_selector:
        input_selector = manual_pick_element(page, "Click the chat MESSAGE INPUT box.", ui)

    send_selector = try_auto_detect_send(page, input_selector)
    use_enter = False
    if send_selector:
        highlight(page, send_selector)
        ok = confirm("Auto-detected the SEND button (highlighted in red). Is this correct?", ui)
        unhighlight(page, send_selector)
        if not ok:
            send_selector = None
    if not send_selector:
        if confirm("No send button confirmed. Does this site send messages by pressing Enter?", ui):
            use_enter = True
        else:
            send_selector = manual_pick_element(page, "Click the SEND button.", ui)

    ui["notify"](
        "\nNow let's find the response area. Type and send a short test message "
        "yourself (e.g. 'hello') using the site's normal method, and wait for the "
        "reply to fully finish."
    )
    ui["prompt"]("Press Enter here once the AI's reply has fully finished... ")
    response_selector = manual_pick_repeatable_element(
        page, "Click directly on the AI's reply text (the response you just received).", ui
    )

    data = {
        "domain": domain,
        "input_selector": input_selector,
        "send_selector": send_selector,
        "use_enter": use_enter,
        "response_selector": response_selector,
    }
    save_calibration(domain, data)
    ui["notify"](f"Calibration saved to config/sites/{domain}.json\n")
    return data
