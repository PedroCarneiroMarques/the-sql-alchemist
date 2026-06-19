from __future__ import annotations

import pandas as pd
import pytest

from src.core import (
    ChatBI,
    add_cost_columns,
    add_watchdog_columns,
    build_airline_filter,
    dataframe_to_csv_bytes,
    detect_entity_column,
    explain_airline_wars,
    explain_chat_result,
    explain_dashboard,
    get_airline_wars,
    safe_get,
    safe_sorted_first_record,
    safe_sorted_top_n_records,
    validate_dataset,
)


class TestChatBISqlSafety:
    def test_sanitize_sql_strips_fences(self, bi: ChatBI) -> None:
        raw = "```sql\nSELECT * FROM flights\n```"
        assert bi._sanitize_sql(raw) == "SELECT * FROM flights"

    def test_is_safe_query_accepts_select(self, bi: ChatBI) -> None:
        assert bi._is_safe_query("SELECT airline FROM flights") is True

    def test_is_safe_query_rejects_mutations(self, bi: ChatBI) -> None:
        assert bi._is_safe_query("DELETE FROM flights") is False
        assert bi._is_safe_query("SELECT 1; DROP TABLE flights") is False

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


class TestAirlineWars:
    def test_get_airline_wars_returns_two_airlines(self, bi: ChatBI) -> None:
        airlines = bi.dataframe(
            "SELECT DISTINCT airline FROM flights WHERE destination = 'JFK' LIMIT 2"
        )["airline"].tolist()
        if len(airlines) < 2:
            pytest.skip("Not enough airlines for JFK in dataset")

        wars_df = get_airline_wars(bi, airlines[0], airlines[1], "JFK")
        assert len(wars_df) == 2
        assert "on_time_rate_pct" in wars_df.columns

    def test_explain_airline_wars_uses_distinct_winner_and_loser(self, bi: ChatBI) -> None:
        wars_df = get_airline_wars(bi, "Lufthansa", "easyJet", "JFK")
        if len(wars_df) < 2:
            pytest.skip("Insufficient route data")

        explanation = explain_airline_wars(wars_df, "Lufthansa", "easyJet", "JFK")
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

    def test_dataframe_to_csv_bytes_roundtrip(self) -> None:
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        csv_bytes = dataframe_to_csv_bytes(df)
        assert csv_bytes.startswith(b"a,b")
        assert b"1,x" in csv_bytes

    def test_dataframe_to_csv_bytes_empty(self) -> None:
        assert dataframe_to_csv_bytes(pd.DataFrame()) == b""
