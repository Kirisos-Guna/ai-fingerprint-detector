"""Sends probe prompts through the calibrated chat UI and collects responses.

Handles the generic send flow (fill input, click send or press Enter) and the
harder problem of knowing when a streaming AI response has finished: we wait
until the response element's text stops growing for a settle period.
"""
import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

MAX_RESPONSE_WAIT_S = 120   # absolute cap on one response
SETTLE_S = 5                # text must be unchanged this long to count as done
POLL_INTERVAL_S = 0.4


def get_response_texts(page: Page, response_selector: str) -> list:
    """Return the text of every response bubble matching the repeatable selector."""
    return page.evaluate(
        """
        (sel) => Array.from(document.querySelectorAll(sel)).map(el => el.innerText.trim())
        """,
        response_selector,
    )


def wait_for_response(page: Page, response_selector: str, before_count: int) -> str:
    """Wait for a new response bubble to appear AND finish streaming.

    before_count is how many response bubbles existed before this probe was
    sent; the new reply is expected to be the (before_count+1)-th element.
    """
    deadline = time.time() + MAX_RESPONSE_WAIT_S
    last_len = -1
    last_change = time.time()

    while time.time() < deadline:
        texts = get_response_texts(page, response_selector)

        if len(texts) > before_count:
            current = texts[before_count]  # newest bubble
            if len(current) != last_len:
                last_len = len(current)
                last_change = time.time()
            elif time.time() - last_change >= SETTLE_S and len(current) > 0:
                return current

        # neither a new bubble nor any growth yet -- keep waiting quietly
        time.sleep(POLL_INTERVAL_S)

    # Timed out: return whatever is in the newest bubble (possibly empty)
    texts = get_response_texts(page, response_selector)
    return texts[before_count] if len(texts) > before_count else ""


def send_message(page: Page, input_selector: str, send_selector: Optional[str],
                 use_enter: bool, prompt: str):
    """Type a prompt into the chat input and trigger sending."""
    box = page.locator(input_selector).first
    box.wait_for(state="visible", timeout=15000)
    box.click()
    box.fill("")            # clear any leftover text
    box.press_sequentially(prompt, delay=10)

    if use_enter or not send_selector:
        box.press("Enter")
    else:
        page.locator(send_selector).first.click()


def run_probes(page: Page, calibration: dict, probes: list, on_progress=None) -> dict:
    """Run every probe and return {probe_label: response_text}.

    on_progress, if given, is called as on_progress(done, total, label).
    """
    results = {}
    input_sel = calibration["input_selector"]
    send_sel = calibration.get("send_selector")
    use_enter = calibration.get("use_enter", False)
    resp_sel = calibration["response_selector"]

    for i, (category, label, prompt) in enumerate(probes):
        # count how many bubbles exist right now so we can spot the new one
        before_count = len(get_response_texts(page, resp_sel))

        try:
            send_message(page, input_sel, send_sel, use_enter, prompt)
        except PlaywrightTimeoutError:
            results[label] = "[ERROR] could not find or fill the chat input box"
            if on_progress:
                on_progress(i + 1, len(probes), label)
            continue

        answer = wait_for_response(page, resp_sel, before_count)
        results[label] = answer

        if on_progress:
            on_progress(i + 1, len(probes), label)

        # small gap so the UI can fully reset between messages
        time.sleep(1.5)

    return results
