from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

from config import ConfigurationError, get_config, validate_config

DEFAULT_STREAMLIT_HEALTH_URL = "http://127.0.0.1:8501/_stcore/health"


def check_http(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return False, f"unexpected status {response.status}"
            return True, "ok"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def check_ollama(host: str, timeout: int) -> tuple[bool, str]:
    url = f"{host.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=min(timeout, 10)) as response:
            if response.status != 200:
                return False, f"unexpected status {response.status}"
            return True, "ok"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def run_health_check(
    *,
    startup: bool = False,
    http_url: str | None = None,
    check_ollama: bool = False,
) -> dict[str, Any]:
    results: dict[str, Any] = {"healthy": True, "checks": {}}

    try:
        cfg = validate_config()
        results["checks"]["config"] = {"ok": True, "data_path": cfg["DATA_PATH"]}
    except ConfigurationError as exc:
        results["healthy"] = False
        results["checks"]["config"] = {"ok": False, "error": str(exc)}
        return results

    if startup:
        return results

    if check_ollama:
        cfg = get_config()
        ok, message = check_ollama(cfg["OLLAMA_HOST"], int(cfg["OLLAMA_TIMEOUT"]))
        results["checks"]["ollama"] = {"ok": ok, "message": message}
        if not ok:
            results["healthy"] = False

    if http_url:
        ok, message = check_http(http_url)
        results["checks"]["http"] = {"ok": ok, "url": http_url, "message": message}
        if not ok:
            results["healthy"] = False

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Health checks for deployment and Docker.")
    parser.add_argument(
        "--startup",
        action="store_true",
        help="Validate configuration and dataset only (used before app boot).",
    )
    parser.add_argument(
        "--http",
        nargs="?",
        const=DEFAULT_STREAMLIT_HEALTH_URL,
        default=None,
        help="Check the Streamlit HTTP health endpoint.",
    )
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Check that the configured Ollama host responds.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )
    args = parser.parse_args(argv)

    if args.startup:
        report = run_health_check(startup=True)
    else:
        report = run_health_check(http_url=args.http, check_ollama=args.ollama)

    if args.json:
        print(json.dumps(report, indent=2))
    elif report["healthy"]:
        print("healthy")
    else:
        print("unhealthy")
        for name, payload in report["checks"].items():
            if not payload.get("ok", False):
                print(f"- {name}: {payload.get('error') or payload.get('message')}")

    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
