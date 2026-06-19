from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest

from src.core import (
    ChatBI,
    add_cost_columns,
    add_watchdog_columns,
    aggregate_cost_by_airline,
    aggregate_watchdog_summary,
    build_airline_filter,
    dataframe_to_csv_bytes,
    detect_entity_column,
    explain_airline_comparison,
    explain_chat_result,
    explain_dashboard,
    get_airline_comparison,
    get_profile_chain,
    query_flight_kpis,
    recommend_chart,
    run_stored_chat_sql,
    resolve_profile_chain,
    normalize_model_profile,
    resolve_model_chain,
    normalize_watchdog_sensitivity,
    get_watchdog_settings,
    LOGGER_NAME,
    configure_logging,
    safe_get,
    safe_sorted_first_record,
    safe_sorted_top_n_records,
    sum_cost_columns,
    validate_dataset,
    validate_sql_query,
    write_dataframe_csv,
)


class TestChatBISqlSafety:
    def test_sanitize_sql_strips_fences(self, bi: ChatBI) -> None:
        raw = "```sql\nSELECT * FROM flights\n```"
        assert bi._sanitize_sql(raw) == "SELECT * FROM flights"

    def test_is_safe_query_accepts_select(self, bi: ChatBI) -> None:
        assert bi._is_safe_query("SELECT airline FROM flights") is True

    def test_is_safe_query_accepts_with_cte(self, bi: ChatBI) -> None:
        sql = (
            "WITH delayed AS (SELECT * FROM flights WHERE status = 'Delayed') "
            "SELECT airline, COUNT(*) AS delayed_flights FROM delayed GROUP BY airline"
        )
        assert bi._is_safe_query(sql) is True

    def test_is_safe_query_rejects_mutations(self, bi: ChatBI) -> None:
        assert bi._is_safe_query("DELETE FROM flights") is False
        assert bi._is_safe_query("SELECT 1; DROP TABLE flights") is False

    def test_is_safe_query_rejects_union(self, bi: ChatBI) -> None:
        sql = "SELECT airline FROM flights UNION SELECT airline FROM secrets"
        assert bi._is_safe_query(sql) is False

    def test_is_safe_query_rejects_unknown_table(self, bi: ChatBI) -> None:
        assert bi._is_safe_query("SELECT * FROM secrets") is False

    def test_validate_sql_query_messages(self) -> None:
        ok, reason = validate_sql_query("SELECT * FROM flights")
        assert ok is True
        assert reason == ""

        ok, reason = validate_sql_query("SELECT * FROM flights UNION SELECT * FROM flights")
        assert ok is False
        assert "forbidden keyword" in reason

    def test_build_prompt_includes_few_shot_examples(self, bi: ChatBI) -> None:
        prompt = bi._build_prompt("test question")
        assert "Which airlines have the highest average latency?" in prompt
        assert "Status values: On-Time, Delayed, Cancelled" in prompt
        assert "departure_time_of_day" in prompt
        assert "day_of_week" in prompt
        assert "route (derived" in prompt
        assert "test question" in prompt

    def test_ensure_limit_appends_default(self, bi: ChatBI) -> None:
        sql = "SELECT * FROM flights"
        assert bi._ensure_limit(sql) == "SELECT * FROM flights LIMIT 200"

    def test_ensure_limit_preserves_existing(self, bi: ChatBI) -> None:
        sql = "SELECT * FROM flights LIMIT 10"
        assert bi._ensure_limit(sql) == sql


class TestKeywordFallback:
    @pytest.mark.parametrize(
        ("question", "expected_fragment"),
        [
            ("average latency by airline", "AVG(latency_minutes)"),
            ("how many cancelled flights", "status = 'Cancelled'"),
            ("show delayed flights", "status IN ('Delayed', 'Cancelled')"),
            ("estimated total cost", "estimated_cost"),
            ("how many flights total", "GROUP BY status"),
            ("which routes have highest delay", "GROUP BY route"),
            ("delays by time of day", "departure_time_of_day"),
            ("delays by day of week", "day_of_week"),
            ("average latency by month", "departure_month"),
        ],
    )
    def test_keyword_fallback_sql(self, bi: ChatBI, question: str, expected_fragment: str) -> None:
        sql = bi._keyword_fallback_sql(question)
        assert expected_fragment in sql

    def test_ask_with_fallback_uses_keyword_when_model_missing(self, bi: ChatBI) -> None:
        result = bi.ask_with_fallback("how many flights by status", ["nonexistent-model"])
        assert result["success"] is True
        assert result["model"] == "keyword_fallback"
        assert not result["data"].empty


class TestHelpers:
    def test_safe_get_handles_none(self) -> None:
        assert safe_get({"a": None}, "a", "default") == "default"
        assert safe_get("not-a-dict", "a", 1) == 1

    def test_safe_sorted_first_record_returns_dict(self) -> None:
        df = pd.DataFrame({"airline": ["B", "A"], "cost": [10, 20]})
        record = safe_sorted_first_record(df, "cost", ascending=False)
        assert record == {"airline": "A", "cost": 20}

    def test_safe_sorted_top_n_records(self) -> None:
        df = pd.DataFrame({"airline": ["C", "A", "B"], "latency": [30, 10, 20]})
        records = safe_sorted_top_n_records(df, "latency", n=2, ascending=True)
        assert len(records) == 2
        assert records[0]["airline"] == "A"
        assert records[1]["airline"] == "B"

    def test_detect_entity_column_prefers_airline(self) -> None:
        df = pd.DataFrame({"airline": ["X"], "latency_minutes": [1]})
        assert detect_entity_column(df) == "airline"

    def test_detect_entity_column_falls_back_to_text(self) -> None:
        df = pd.DataFrame({"foo": [1], "bar": ["x"]})
        assert detect_entity_column(df) == "bar"

    def test_build_airline_filter_empty(self) -> None:
        sql, params = build_airline_filter([])
        assert sql == ""
        assert params == []

    def test_build_airline_filter_with_values(self) -> None:
        sql, params = build_airline_filter(["A", "B"])
        assert sql == "WHERE airline IN (?,?)"
        assert params == ["A", "B"]


class TestCostAndWatchdog:
    def test_add_cost_columns_delayed_and_cancelled(self) -> None:
        df = pd.DataFrame(
            {
                "status": ["Delayed", "Cancelled", "On-Time"],
                "latency_minutes": [10, 0, 0],
            }
        )
        result = add_cost_columns(df, delay_cost_per_minute=50, cancellation_cost=200)
        assert result.loc[0, "delay_cost_eur"] == 500
        assert result.loc[1, "cancellation_cost_eur"] == 200
        assert result.loc[2, "total_cost_eur"] == 0

    def test_add_cost_columns_requires_columns(self) -> None:
        with pytest.raises(ValueError, match="Missing required columns"):
            add_cost_columns(pd.DataFrame({"status": ["Delayed"]}))

    def test_add_watchdog_columns_adds_quality_flags(self, bi: ChatBI) -> None:
        df = add_watchdog_columns(bi, selected_airlines=[])
        assert "quality_flag" in df.columns
        assert "total_cost_eur" in df.columns
        assert set(df["quality_flag"].unique()).issubset({"Reliable", "Review", "High Risk"})


class TestAirlineComparison:
    def test_get_airline_comparison_returns_two_airlines(self, bi: ChatBI) -> None:
        airlines = bi.dataframe(
            "SELECT DISTINCT airline FROM flights WHERE destination = 'JFK' LIMIT 2"
        )["airline"].tolist()
        if len(airlines) < 2:
            pytest.skip("Not enough airlines for JFK in dataset")

        comparison_df = get_airline_comparison(bi, airlines[0], airlines[1], "JFK")
        assert len(comparison_df) == 2
        assert "on_time_rate_pct" in comparison_df.columns

    def test_explain_airline_comparison_uses_distinct_winner_and_loser(self, bi: ChatBI) -> None:
        comparison_df = get_airline_comparison(bi, "Lufthansa", "easyJet", "JFK")
        if len(comparison_df) < 2:
            pytest.skip("Insufficient route data")

        explanation = explain_airline_comparison(comparison_df, "Lufthansa", "easyJet", "JFK")
        assert "leads on JFK" in explanation
        assert "vs" in explanation


class TestExplanations:
    def test_explain_dashboard_with_data(self, bi: ChatBI) -> None:
        filtered_df = add_watchdog_columns(bi, selected_airlines=[])
        cost_by_airline = (
            filtered_df.groupby("airline", as_index=False)
            .agg(total_cost_eur=("total_cost_eur", "sum"))
            .sort_values("total_cost_eur", ascending=False)
        )
        explanation = explain_dashboard(filtered_df.head(100), cost_by_airline.head(5))
        assert "flights" in explanation
        assert "latency" in explanation.lower()

    def test_explain_dashboard_empty(self) -> None:
        assert explain_dashboard(pd.DataFrame(), pd.DataFrame()) == "No data is available for the current filters."

    def test_explain_chat_result_avg_latency(self) -> None:
        df = pd.DataFrame({"airline": ["A", "B"], "avg_latency": [12.0, 20.0]})
        explanation = explain_chat_result("avg latency", df)
        assert "B" in explanation
        assert "highest average latency" in explanation

    def test_explain_chat_result_empty(self) -> None:
        assert explain_chat_result("test", pd.DataFrame()) == "The query returned no rows for the current request."


class TestDatasetAndExport:
    def test_validate_dataset_passes(self, bi: ChatBI) -> None:
        validate_dataset(bi)

    def test_enriched_columns_exist(self, bi: ChatBI) -> None:
        columns = set(bi.get_columns())
        assert "route" in columns
        assert "departure_hour" in columns
        assert "departure_time_of_day" in columns
        assert "scheduled_duration_minutes" in columns

    def test_route_format(self, bi: ChatBI) -> None:
        sample = bi.dataframe("SELECT route, origin, destination FROM flights LIMIT 1")
        row = sample.iloc[0]
        assert row["route"] == f"{row['origin']} → {row['destination']}"

    def test_departure_hour_parsing(self, bi: ChatBI) -> None:
        sample = bi.dataframe(
            "SELECT departure_time, departure_hour, departure_minute "
            "FROM flights WHERE flight_id = 1"
        )
        assert int(sample.iloc[0]["departure_hour"]) == 9
        assert int(sample.iloc[0]["departure_minute"]) == 10

    def test_scheduled_duration_handles_overnight(self, bi: ChatBI) -> None:
        sample = bi.dataframe(
            "SELECT departure_time, arrival_time, scheduled_duration_minutes "
            "FROM flights WHERE flight_id = 76"
        )
        assert int(sample.iloc[0]["scheduled_duration_minutes"]) == 438

    def test_departure_time_of_day_values(self, bi: ChatBI) -> None:
        values = set(
            bi.dataframe("SELECT DISTINCT departure_time_of_day FROM flights")[
                "departure_time_of_day"
            ].tolist()
        )
        assert values.issubset({"Morning", "Afternoon", "Evening", "Night"})
        assert len(values) > 1

    def test_calendar_columns_exist(self, bi: ChatBI) -> None:
        columns = set(bi.get_columns())
        assert "day_of_week" in columns
        assert "departure_month" in columns
        assert "departure_year" in columns

    def test_day_of_week_is_populated(self, bi: ChatBI) -> None:
        values = bi.dataframe("SELECT DISTINCT day_of_week FROM flights")["day_of_week"].tolist()
        assert len(values) >= 5

    def test_run_stored_chat_sql_reexecutes_valid_query(self, bi: ChatBI) -> None:
        sql = "SELECT airline FROM flights LIMIT 3"
        df = run_stored_chat_sql(bi, sql)
        assert len(df) == 3

    def test_run_stored_chat_sql_rejects_unsafe_query(self, bi: ChatBI) -> None:
        with pytest.raises(ValueError, match="no longer valid"):
            run_stored_chat_sql(bi, "DROP TABLE flights")

    def test_dataframe_to_csv_bytes_roundtrip(self) -> None:
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        csv_bytes = dataframe_to_csv_bytes(df)
        assert csv_bytes.startswith(b"a,b")
        assert b"1,x" in csv_bytes

    def test_dataframe_to_csv_bytes_empty(self) -> None:
        assert dataframe_to_csv_bytes(pd.DataFrame()) == b""

    def test_write_dataframe_csv(self, tmp_path: Path) -> None:
        df = pd.DataFrame({"airline": ["A"], "latency_minutes": [10]})
        output = write_dataframe_csv(df, tmp_path / "out.csv")
        assert output.exists()
        assert "airline" in output.read_text(encoding="utf-8")


class TestAnalyticsHelpers:
    def test_query_flight_kpis(self, bi: ChatBI) -> None:
        kpis = query_flight_kpis(bi, [])
        assert int(kpis["total_flights"] or 0) > 0
        assert kpis["avg_latency"] is not None

    def test_aggregate_cost_by_airline(self, bi: ChatBI) -> None:
        filtered_df = add_watchdog_columns(bi, selected_airlines=[])
        cost_df = aggregate_cost_by_airline(filtered_df.head(200))
        assert "total_cost_eur" in cost_df.columns
        assert not cost_df.empty

    def test_aggregate_watchdog_summary(self, bi: ChatBI) -> None:
        filtered_df = add_watchdog_columns(bi, selected_airlines=[])
        summary = aggregate_watchdog_summary(filtered_df.head(200))
        assert "quality_flag" in summary.columns

    def test_sum_cost_columns(self, bi: ChatBI) -> None:
        filtered_df = add_watchdog_columns(bi, selected_airlines=[])
        costs = sum_cost_columns(filtered_df.head(50))
        assert costs["total_cost"] >= 0

    def test_resolve_model_chain(self) -> None:
        chain = resolve_model_chain(["mistral:7b"], default_chain=["mistral:7b", "phi4:14b"])
        assert chain == ["mistral:7b"]


class TestChartRecommendation:
    def test_recommend_bar_for_entity_metric(self) -> None:
        df = pd.DataFrame({"airline": ["A", "B"], "avg_latency": [10.0, 20.0]})
        spec = recommend_chart(df)
        assert spec.kind == "bar"
        assert spec.x == "airline"
        assert spec.y == "avg_latency"

    def test_recommend_pie_for_status_distribution(self) -> None:
        df = pd.DataFrame({"status": ["On-Time", "Delayed"], "total_flights": [100, 50]})
        spec = recommend_chart(df)
        assert spec.kind == "pie"
        assert spec.x == "status"
        assert spec.y == "total_flights"

    def test_recommend_line_for_flight_latency(self) -> None:
        df = pd.DataFrame(
            {
                "flight_id": [1, 2, 3, 4],
                "airline": ["A", "A", "B", "B"],
                "latency_minutes": [5.0, 10.0, 15.0, 20.0],
            }
        )
        spec = recommend_chart(df)
        assert spec.kind == "line"
        assert spec.x == "flight_id"
        assert spec.y == "latency_minutes"

    def test_recommend_none_for_empty(self) -> None:
        assert recommend_chart(pd.DataFrame()).kind == "none"


class TestModelProfiles:
    def test_get_profile_chain_fast(self) -> None:
        chain = get_profile_chain("fast")
        assert chain
        assert chain[0] == "mistral:7b"

    def test_normalize_invalid_profile(self) -> None:
        with pytest.raises(ValueError, match="Unknown model profile"):
            normalize_model_profile("turbo")

    def test_resolve_profile_chain_filters_available(self) -> None:
        chain = resolve_profile_chain("fast", ["mistral:7b", "other-model"])
        assert chain == ["mistral:7b"]

    def test_balanced_profile_uses_default_chain(self) -> None:
        from src.core import DEFAULT_MODEL_CHAIN

        chain = get_profile_chain("balanced")
        assert chain == DEFAULT_MODEL_CHAIN


class TestWatchdogSensitivity:
    def test_normalize_invalid_sensitivity(self) -> None:
        with pytest.raises(ValueError, match="Unknown watchdog sensitivity"):
            normalize_watchdog_sensitivity("lax")

    def test_get_watchdog_settings_normal(self) -> None:
        settings = get_watchdog_settings("normal")
        assert settings.review_percentile == 0.95
        assert settings.high_risk_std_multiplier == 3.0

    def test_strict_flags_more_rows_than_relaxed(self, bi: ChatBI) -> None:
        relaxed = add_watchdog_columns(bi, selected_airlines=[], watchdog_sensitivity="relaxed")
        strict = add_watchdog_columns(bi, selected_airlines=[], watchdog_sensitivity="strict")

        relaxed_flagged = int(relaxed["quality_flag"].isin(["Review", "High Risk"]).sum())
        strict_flagged = int(strict["quality_flag"].isin(["Review", "High Risk"]).sum())
        assert strict_flagged >= relaxed_flagged


class TestLogging:
    def test_configure_logging_is_idempotent(self) -> None:
        first = configure_logging()
        second = configure_logging()
        assert first is second

    def test_ask_with_fallback_logs_keyword_fallback(self, bi: ChatBI, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            bi.ask_with_fallback("how many flights by status", ["nonexistent-model"])
        messages = " ".join(record.message for record in caplog.records).lower()
        assert "keyword fallback" in messages
