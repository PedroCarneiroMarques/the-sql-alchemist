from __future__ import annotations

from src.i18n import configure_locale, get_locale, normalize_locale, profile_label, t, watchdog_label


class TestI18n:
    def test_normalize_locale_defaults_to_english(self) -> None:
        assert normalize_locale(None) == "en"
        assert normalize_locale("en") == "en"
        assert normalize_locale("EN-US") == "en"

    def test_normalize_locale_supports_portuguese(self) -> None:
        assert normalize_locale("pt") == "pt"
        assert normalize_locale("pt-PT") == "pt"

    def test_configure_locale_switches_strings(self) -> None:
        configure_locale("en")
        assert get_locale() == "en"
        assert t("app.title") == "The SQL Alchemist"

        configure_locale("pt")
        assert get_locale() == "pt"
        assert t("app.title") == "O SQL Alchemist"

    def test_translation_formatting(self) -> None:
        configure_locale("en")
        assert t("chat.model_used", model="mistral:7b") == "Model used: mistral:7b"

    def test_profile_and_watchdog_labels(self) -> None:
        configure_locale("pt")
        assert "Equilibrado" in profile_label("balanced")
        assert "Normal" in watchdog_label("normal")

    def test_missing_key_falls_back_to_key_name(self) -> None:
        configure_locale("en")
        assert t("missing.translation.key") == "missing.translation.key"
