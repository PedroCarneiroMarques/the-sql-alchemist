from __future__ import annotations

from src.health import check_http, run_health_check


class TestHealthChecks:
    def test_startup_health_passes(self) -> None:
        report = run_health_check(startup=True)
        assert report["healthy"] is True
        assert report["checks"]["config"]["ok"] is True

    def test_http_check_reports_failure_for_invalid_url(self) -> None:
        ok, message = check_http("http://127.0.0.1:1/not-running")
        assert ok is False
        assert message

    def test_full_health_without_optional_checks(self) -> None:
        report = run_health_check()
        assert report["healthy"] is True
        assert "config" in report["checks"]
