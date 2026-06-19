#!/usr/bin/env python3
"""Capture Streamlit UI screenshots for README documentation.

Requires: pip install playwright && playwright install chromium
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "docs" / "images"
APP_PATH = PROJECT_ROOT / "src" / "app.py"


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.5)
    raise RuntimeError(f"Streamlit did not start within {timeout}s at {url}")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install Playwright first: pip install playwright && playwright install chromium")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    port = pick_free_port()
    base_url = f"http://127.0.0.1:{port}"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP_PATH),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        wait_for_server(base_url)
        time.sleep(2)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base_url, wait_until="networkidle")
            page.wait_for_timeout(2500)

            page.screenshot(path=str(OUTPUT_DIR / "dashboard-overview.png"))

            wars_heading = page.locator(
                '[data-testid="stMainBlockContainer"] h3:has-text("Airline Wars")'
            ).last
            wars_heading.scroll_into_view_if_needed()
            page.wait_for_timeout(1000)
            box = wars_heading.evaluate(
                """el => {
                    const rect = el.getBoundingClientRect();
                    return {
                        x: Math.max(0, rect.x - 24),
                        y: Math.max(0, rect.y - 16),
                        width: Math.min(window.innerWidth - 48, 1392),
                        height: 780,
                    };
                }"""
            )
            page.screenshot(path=str(OUTPUT_DIR / "airline-wars.png"), clip=box)

            page.get_by_role("tab", name="Chat").click()
            page.wait_for_timeout(1000)
            page.get_by_role(
                "button",
                name="Which airlines have the highest average latency?",
            ).click()
            page.wait_for_selector('[data-testid="stCode"]', timeout=30000)
            page.wait_for_timeout(2000)
            chat_block = page.locator('[data-testid="stChatMessage"]').last
            chat_block.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            box = chat_block.evaluate(
                """el => {
                    const rect = el.getBoundingClientRect();
                    const top = Math.max(0, rect.y - 120);
                    return {
                        x: 280,
                        y: top,
                        width: Math.min(window.innerWidth - 300, 1160),
                        height: Math.min(820, window.innerHeight - top - 24),
                    };
                }"""
            )
            page.screenshot(path=str(OUTPUT_DIR / "chat-analysis.png"), clip=box)

            browser.close()

        print(f"Saved screenshots to {OUTPUT_DIR}/")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
