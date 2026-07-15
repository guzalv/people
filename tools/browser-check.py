"""Real-browser smoke test over CDP.

Sandboxed sessions can't launch browsers, but they can attach to one the user
started outside the sandbox:

  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --remote-debugging-port=9222 --user-data-dir=/tmp/claude-chrome

Env: BASE (app under test, default http://127.0.0.1:8768 — use a scratch DB,
the flow mutates data), CDP_URL (default http://127.0.0.1:9222),
SHOTS (dir for screenshots, optional).

Run: .venv/bin/python tools/browser-check.py
"""

import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE", "http://127.0.0.1:8768")
CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
SHOTS = os.environ.get("SHOTS")

console_errors: list[str] = []


def shot(page, name):
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, name))


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        page.goto(BASE + "/", wait_until="networkidle")
        shot(page, "browser-1-home.png")
        print("ok home loaded")

        # create a person through the UI
        page.click('button[data-add="persons"]')
        page.fill("form.card input", "Browser Test")
        page.click("form.card button")
        page.wait_for_selector('h1:has-text("Browser Test")')
        print("ok person created")

        # Food section: add a value in the Likes row
        likes_row = page.locator(".food-row").filter(
            has=page.locator(".label", has_text=re.compile(r"^Likes$"))
        )
        likes_row.locator('input[placeholder="add…"]').fill("tomatoes")
        likes_row.locator(".combo-list button.create").click()
        likes_row.locator(".chip.like", has_text="tomatoes").wait_for()
        print("ok likes chip added")

        # fact
        page.fill('input[placeholder="something they mentioned…"]', "met at the gym")
        page.keyboard.press("Enter")
        page.wait_for_selector('.fact:has-text("met at the gym")')
        shot(page, "browser-2-person.png")
        print("ok fact added")

        # meal plan report
        page.goto(BASE + "/#/plan", wait_until="networkidle")
        page.locator("label.check").filter(has_text="Browser Test").locator(
            "input"
        ).check()
        page.wait_for_selector('.report-section.serve:has-text("tomatoes")')
        shot(page, "browser-3-plan.png")
        print("ok meal plan report")

        context.close()
        browser.close()  # detaches only; the user's Chrome keeps running

    if console_errors:
        print("CONSOLE/PAGE ERRORS:", json.dumps(console_errors, indent=2))
        return 1
    print("BROWSER CHECK OK (real Chrome via CDP)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
