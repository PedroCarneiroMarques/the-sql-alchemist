from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

import duckdb
import pandas as pd
import sqlparse
from ollama import Client
from sqlparse.tokens import Keyword

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config

CFG = get_config()

DATA_PATH = Path(CFG["DATA_PATH"])
OLLAMA_HOST = CFG["OLLAMA_HOST"]
OLLAMA_TIMEOUT = CFG["OLLAMA_TIMEOUT"]
DEFAULT_MODEL_CHAIN = CFG["DEFAULT_MODEL_CHAIN"]
DEFAULT_MODEL_PROFILE = CFG["DEFAULT_MODEL_PROFILE"]
MODEL_PROFILES: dict[str, list[str]] = CFG["MODEL_PROFILES"]
MODEL_PROFILE_LABELS = {
    "fast": "Fast — smallest model, quickest responses",
    "balanced": "Balanced — default fallback chain",
    "accurate": "Accurate — larger models first",
}
DEFAULT_DELAY_COST_PER_MINUTE = CFG["DEFAULT_DELAY_COST_PER_MINUTE"]
DEFAULT_CANCELLATION_COST = CFG["DEFAULT_CANCELLATION_COST"]
DEFAULT_WATCHDOG_SENSITIVITY = CFG["DEFAULT_WATCHDOG_SENSITIVITY"]

WATCHDOG_SENSITIVITY_LABELS = {
    "relaxed": "Relaxed — fewer Review/High Risk flags",
    "normal": "Normal — balanced anomaly detection",
    "strict": "Strict — more Review/High Risk flags",
}


@dataclass(frozen=True)
class WatchdogSettings:
    review_percentile: float
    high_risk_percentile: float
    review_std_multiplier: float
    high_risk_std_multiplier: float
    review_score: int = 65
    high_risk_score: int = 95
    cancelled_score: int = 100


WATCHDOG_SENSITIVITY_PROFILES: dict[str, WatchdogSettings] = {
    "relaxed": WatchdogSettings(
        review_percentile=0.98,
        high_risk_percentile=0.995,
        review_std_multiplier=3.0,
        high_risk_std_multiplier=4.0,
    ),
    "normal": WatchdogSettings(
        review_percentile=0.95,
        high_risk_percentile=0.99,
        review_std_multiplier=2.0,
        high_risk_std_multiplier=3.0,
    ),
    "strict": WatchdogSettings(
        review_percentile=0.90,
        high_risk_percentile=0.95,
        review_std_multiplier=1.5,
        high_risk_std_multiplier=2.0,
    ),
}

REQUIRED_COLUMNS = {
    "flight_id",
    "airline",
    "origin",
    "destination",
    "departure_time",
    "arrival_time",
    "latency_minutes",
    "status",
}

SUGGESTED_QUESTIONS = [
    "Which airlines have the highest average latency?",
    "How many flights were cancelled by airline?",
    "Show delayed flights ordered by latency.",
    "What is the distribution of flight statuses?",
    "Which routes have the highest average delay?",
    "What is the estimated total cost by airline?",
    "Which destinations have the most delayed flights?",
    "Show the top 10 most expensive disrupted flights.",
    "Which airlines have the best on-time performance?",
    "Compare average latency and cancellations by airline.",
]

FLIGHTS_LOAD_SQL = """
CREATE OR REPLACE TABLE flights AS
SELECT *
FROM read_csv_auto(
    ?,
    header = true,
    types = {
        'flight_id': 'BIGINT',
        'airline': 'VARCHAR',
        'origin': 'VARCHAR',
        'destination': 'VARCHAR',
        'departure_time': 'VARCHAR',
        'arrival_time': 'VARCHAR',
        'latency_minutes': 'DOUBLE',
        'status': 'VARCHAR'
    }
)
"""

BLOCKED_SQL_TOKENS = (
    "INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "TRUNCATE ",
    "CREATE ", "REPLACE ", "COPY ", "ATTACH ", "DETACH ", "INSTALL ",
    "LOAD ", "CALL ", "EXPORT ", "VACUUM ", "PRAGMA ",
)

ALLOWED_TABLES = frozenset({"flights"})

FORBIDDEN_SQL_KEYWORDS = frozenset({
    "UNION", "INTERSECT", "EXCEPT", "INSERT", "UPDATE", "DELETE",
    "DROP", "ALTER", "CREATE", "REPLACE", "COPY", "ATTACH", "DETACH",
    "INSTALL", "LOAD", "CALL", "EXPORT", "VACUUM", "PRAGMA", "INTO",
})

FEW_SHOT_EXAMPLES: list[tuple[str, str]] = [
    (
        "Which airlines have the highest average latency?",
        "SELECT airline, ROUND(AVG(latency_minutes), 2) AS avg_latency "
        "FROM flights GROUP BY airline ORDER BY avg_latency DESC LIMIT 200",
    ),
    (
        "How many flights were cancelled by airline?",
        "SELECT airline, COUNT(*) AS cancelled_flights FROM flights "
        "WHERE status = 'Cancelled' GROUP BY airline ORDER BY cancelled_flights DESC LIMIT 200",
    ),
    (
        "What is the distribution of flight statuses?",
        "SELECT status, COUNT(*) AS total_flights FROM flights "
        "GROUP BY status ORDER BY total_flights DESC LIMIT 200",
    ),
    (
        "Which routes have the highest average delay?",
        "SELECT origin, destination, ROUND(AVG(latency_minutes), 2) AS avg_latency "
        "FROM flights WHERE status IN ('Delayed', 'Cancelled') "
        "GROUP BY origin, destination ORDER BY avg_latency DESC LIMIT 200",
    ),
    (
        "Show the top 10 most expensive disrupted flights.",
        "SELECT flight_id, airline, destination, latency_minutes, status, "
        "(CASE WHEN status = 'Delayed' THEN latency_minutes * 50 "
        "WHEN status = 'Cancelled' THEN 200 ELSE 0 END) AS estimated_cost "
        "FROM flights WHERE status IN ('Delayed', 'Cancelled') "
        "ORDER BY estimated_cost DESC LIMIT 10",
    ),
]


def _extract_cte_names(sql: str) -> set[str]:
    names = set(re.findall(r"\bWITH\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE))
    names.update(re.findall(r",\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(", sql, flags=re.IGNORECASE))
    return {name.lower() for name in names}


def _extract_referenced_tables(sql: str) -> set[str]:
    tables: set[str] = set()
    patterns = (
        r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, sql, flags=re.IGNORECASE):
            tables.add(match.group(1).lower())
    return tables


def validate_sql_query(sql: str) -> tuple[bool, str]:
    if not sql or not sql.strip():
        return False, "empty query"

    if ";" in sql:
        return False, "multi-statement queries are not allowed"

    statements = sqlparse.parse(sql)
    if len(statements) != 1:
        return False, "only a single statement is allowed"

    statement = statements[0]
    first_token = statement.token_first(skip_cm=True)
    if first_token is None:
        return False, "empty statement"

    first_word = first_token.value.upper()
    if first_word not in {"SELECT", "WITH"}:
        return False, "only SELECT queries are allowed"

    for token in statement.flatten():
        if token.ttype is Keyword and token.value.upper() in FORBIDDEN_SQL_KEYWORDS:
            return False, f"forbidden keyword: {token.value.upper()}"

    sql_upper = sql.upper()
    if any(token in sql_upper for token in BLOCKED_SQL_TOKENS):
        return False, "query contains blocked SQL operation"

    referenced_tables = _extract_referenced_tables(sql)
    if not referenced_tables:
        return False, "no table reference found"

    allowed_refs = ALLOWED_TABLES | _extract_cte_names(sql)
    disallowed = referenced_tables - allowed_refs
    if disallowed:
        return False, f"table not allowed: {', '.join(sorted(disallowed))}"

    return True, ""


class ChatBI:
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.client = Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT)
        self.db = duckdb.connect(database=":memory:")
        self._load_table()

    def _load_table(self) -> None:
        self.db.execute(FLIGHTS_LOAD_SQL, [self.csv_path])

    def get_columns(self) -> list[str]:
        return self.db.execute("SELECT * FROM flights LIMIT 0").df().columns.tolist()

    def scalar(self, query: str, params: Optional[list] = None):
        params = params or []
        row = self.db.execute(query, params).fetchone()
        return row[0] if row else None

    def dataframe(self, query: str, params: Optional[list] = None) -> pd.DataFrame:
        params = params or []
        return self.db.execute(query, params).df()

    def available_models(self) -> list[str]:
        try:
            response = self.client.list()
            models = response.get("models", [])
            return [
                m.get("model") or m.get("name")
                for m in models
                if m.get("model") or m.get("name")
            ]
        except Exception:
            return []

    def _sanitize_sql(self, raw_sql: str) -> str:
        cleaned = raw_sql.strip()
        cleaned = re.sub(r"^```sql\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(";")
        return cleaned

    def _is_safe_query(self, sql: str) -> bool:
        ok, _ = validate_sql_query(sql)
        return ok

    def _ensure_limit(self, sql: str, default_limit: int = 200) -> str:
        if re.search(r"\bLIMIT\s+\d+\b", sql, flags=re.IGNORECASE):
            return sql
        return f"{sql} LIMIT {default_limit}"

    def _build_prompt(self, question: str) -> str:
        examples = "\n\n".join(
            f"Question: {example_q}\nSQL: {example_sql}"
            for example_q, example_sql in FEW_SHOT_EXAMPLES
        )
        return f"""
You are a DuckDB SQL generator.

Table: flights

Columns:
- flight_id
- airline
- origin
- destination
- departure_time
- arrival_time
- latency_minutes
- status

Status values: On-Time, Delayed, Cancelled

Examples:
{examples}

User question:
{question}

Rules:
- Return exactly one SQL SELECT statement only.
- Never return markdown, explanations, comments, or code fences.
- Use only the flights table and listed columns.
- Prefer aggregated answers when user asks for trends, averages, totals, rankings.
- Add ORDER BY when useful.
- Limit output to 200 rows unless the user explicitly asks for all rows.
        """.strip()

    def _try_model_sql(self, model_name: str, question: str) -> tuple[bool, str, str]:
        try:
            response = self.client.chat(
                model=model_name,
                messages=[{"role": "user", "content": self._build_prompt(question)}],
            )
            raw_sql = response["message"]["content"]
            sql = self._sanitize_sql(raw_sql)

            if not self._is_safe_query(sql):
                return False, "", f"{model_name}: generated unsafe or invalid SQL"

            sql = self._ensure_limit(sql)
            return True, sql, ""
        except Exception as exc:
            return False, "", f"{model_name}: {exc}"

    def _keyword_fallback_sql(self, question: str) -> str:
        q = question.lower()

        if any(k in q for k in ("average", "avg", "mean")) and "latency" in q:
            return (
                "SELECT airline, ROUND(AVG(latency_minutes), 2) AS avg_latency "
                "FROM flights GROUP BY airline ORDER BY avg_latency DESC"
            )

        if any(k in q for k in ("cancel", "cancelled")):
            return (
                "SELECT airline, COUNT(*) AS cancelled_flights "
                "FROM flights WHERE status = 'Cancelled' "
                "GROUP BY airline ORDER BY cancelled_flights DESC"
            )

        if any(k in q for k in ("delay", "delayed", "late")):
            return (
                "SELECT flight_id, airline, origin, destination, latency_minutes, status "
                "FROM flights WHERE status IN ('Delayed', 'Cancelled') "
                "ORDER BY latency_minutes DESC LIMIT 25"
            )

        if "cost" in q or "expensive" in q:
            return (
                "SELECT airline, "
                f"SUM(CASE WHEN status = 'Delayed' THEN latency_minutes * {DEFAULT_DELAY_COST_PER_MINUTE} ELSE 0 END) + "
                f"SUM(CASE WHEN status = 'Cancelled' THEN {DEFAULT_CANCELLATION_COST} ELSE 0 END) AS estimated_cost "
                "FROM flights GROUP BY airline ORDER BY estimated_cost DESC"
            )

        if any(k in q for k in ("count", "how many", "total")):
            return (
                "SELECT status, COUNT(*) AS total_flights "
                "FROM flights GROUP BY status ORDER BY total_flights DESC"
            )

        return "SELECT * FROM flights ORDER BY flight_id DESC LIMIT 25"

    def ask_with_fallback(self, question: str, model_chain: list[str]) -> dict[str, Any]:
        errors: list[str] = []

        for model_name in model_chain:
            success, sql, err = self._try_model_sql(model_name, question)
            if success:
                try:
                    df = self.dataframe(sql)
                    return {
                        "success": True,
                        "model": model_name,
                        "data": df,
                        "sql": sql,
                        "error": "",
                        "attempt_errors": errors,
                    }
                except Exception as exc:
                    errors.append(f"{model_name}: SQL execution failed - {exc}")
            else:
                errors.append(err)

        fallback_sql = self._keyword_fallback_sql(question)

        try:
            df = self.dataframe(fallback_sql)
            return {
                "success": True,
                "model": "keyword_fallback",
                "data": df,
                "sql": fallback_sql,
                "error": "",
                "attempt_errors": errors,
            }
        except Exception as exc:
            errors.append(f"fallback: {exc}")
            return {
                "success": False,
                "model": None,
                "data": None,
                "sql": fallback_sql,
                "error": "All models and fallback failed.",
                "attempt_errors": errors,
            }


def safe_get(record: dict[str, Any], key: str, default: Any = None) -> Any:
    if not isinstance(record, dict):
        return default
    value = record.get(key, default)
    return default if value is None else value


def safe_sorted_first_record(
    df: pd.DataFrame,
    sort_col: str | list[str],
    ascending: bool = False,
) -> dict[str, Any]:
    if df is None or df.empty:
        return {}

    if isinstance(sort_col, (list, tuple)):
        sort_col = next((c for c in sort_col if isinstance(c, str) and c in df.columns), None)

    if not sort_col or sort_col not in df.columns:
        return {}

    ordered = df.sort_values(sort_col, ascending=ascending).reset_index(drop=True)
    records = ordered.head(1).to_dict("records")
    return records[0] if records else {}


def safe_sorted_top_n_records(
    df: pd.DataFrame,
    sort_col: str,
    n: int = 2,
    ascending: bool = False,
) -> list[dict[str, Any]]:
    if df is None or df.empty or sort_col not in df.columns or n <= 0:
        return []
    ordered = df.sort_values(sort_col, ascending=ascending).reset_index(drop=True)
    return ordered.head(n).to_dict("records")


def detect_entity_column(df: pd.DataFrame, preferred: list[str] | None = None) -> Optional[str]:
    if df is None or df.empty:
        return None

    preferred = preferred or ["airline", "destination", "origin", "route", "status"]
    for col in preferred:
        if col in df.columns:
            return col

    object_cols = df.select_dtypes(include=["object", "string", "category"]).columns.tolist()
    return object_cols[0] if object_cols else None


def build_airline_filter(selected_airlines: list[str]) -> tuple[str, list]:
    if not selected_airlines:
        return "", []
    placeholders = ",".join(["?"] * len(selected_airlines))
    return f"WHERE airline IN ({placeholders})", selected_airlines


def add_cost_columns(
    df: pd.DataFrame,
    delay_cost_per_minute: int = DEFAULT_DELAY_COST_PER_MINUTE,
    cancellation_cost: int = DEFAULT_CANCELLATION_COST,
) -> pd.DataFrame:
    df = df.copy()

    if df.empty:
        for col in ("delay_cost_eur", "cancellation_cost_eur", "total_cost_eur"):
            if col not in df.columns:
                df[col] = pd.Series(dtype="float64")
        return df

    missing = {"status", "latency_minutes"} - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns for cost calculation: {', '.join(sorted(missing))}")

    df["delay_cost_eur"] = 0.0
    df["cancellation_cost_eur"] = 0.0

    delayed_mask = df["status"].eq("Delayed")
    cancelled_mask = df["status"].eq("Cancelled")

    df.loc[delayed_mask, "delay_cost_eur"] = (
        pd.to_numeric(df.loc[delayed_mask, "latency_minutes"], errors="coerce").fillna(0)
        * delay_cost_per_minute
    )
    df.loc[cancelled_mask, "cancellation_cost_eur"] = float(cancellation_cost)
    df["total_cost_eur"] = df["delay_cost_eur"] + df["cancellation_cost_eur"]
    return df


def add_watchdog_columns(
    bi: ChatBI,
    selected_airlines: list[str],
    delay_cost_per_minute: int = DEFAULT_DELAY_COST_PER_MINUTE,
    cancellation_cost: int = DEFAULT_CANCELLATION_COST,
    watchdog_sensitivity: str = DEFAULT_WATCHDOG_SENSITIVITY,
) -> pd.DataFrame:
    settings = get_watchdog_settings(watchdog_sensitivity)
    filter_sql, filter_params = build_airline_filter(selected_airlines)

    query = f"""
    WITH base AS (
        SELECT *
        FROM flights
        {filter_sql}
    ),
    airline_stats AS (
        SELECT
            airline,
            AVG(COALESCE(latency_minutes, 0)) AS avg_latency,
            STDDEV_POP(COALESCE(latency_minutes, 0)) AS std_latency,
            QUANTILE_CONT(COALESCE(latency_minutes, 0), {settings.review_percentile}) AS review_latency,
            QUANTILE_CONT(COALESCE(latency_minutes, 0), {settings.high_risk_percentile}) AS high_risk_latency
        FROM base
        GROUP BY airline
    )
    SELECT
        b.*,
        COALESCE(s.avg_latency, 0) AS avg_latency_airline,
        COALESCE(s.std_latency, 0) AS std_latency_airline,
        COALESCE(s.review_latency, 0) AS p95_latency_airline,
        COALESCE(s.high_risk_latency, 0) AS p99_latency_airline,
        CASE
            WHEN b.status = 'Cancelled' THEN {settings.cancelled_score}
            WHEN COALESCE(b.latency_minutes, 0) >= COALESCE(s.high_risk_latency, 0)
                 AND COALESCE(b.latency_minutes, 0) > COALESCE(s.avg_latency, 0) + {settings.high_risk_std_multiplier} * COALESCE(s.std_latency, 0)
                THEN {settings.high_risk_score}
            WHEN COALESCE(b.latency_minutes, 0) >= COALESCE(s.review_latency, 0)
                 OR COALESCE(b.latency_minutes, 0) > COALESCE(s.avg_latency, 0) + {settings.review_std_multiplier} * COALESCE(s.std_latency, 0)
                THEN {settings.review_score}
            ELSE 15
        END AS quality_score,
        CASE
            WHEN b.status = 'Cancelled' THEN 'High Risk'
            WHEN COALESCE(b.latency_minutes, 0) >= COALESCE(s.high_risk_latency, 0)
                 AND COALESCE(b.latency_minutes, 0) > COALESCE(s.avg_latency, 0) + {settings.high_risk_std_multiplier} * COALESCE(s.std_latency, 0)
                THEN 'High Risk'
            WHEN COALESCE(b.latency_minutes, 0) >= COALESCE(s.review_latency, 0)
                 OR COALESCE(b.latency_minutes, 0) > COALESCE(s.avg_latency, 0) + {settings.review_std_multiplier} * COALESCE(s.std_latency, 0)
                THEN 'Review'
            ELSE 'Reliable'
        END AS quality_flag
    FROM base b
    LEFT JOIN airline_stats s
        ON b.airline = s.airline
    """

    df = bi.dataframe(query, filter_params)
    return add_cost_columns(df, delay_cost_per_minute, cancellation_cost)


def get_airline_wars(
    bi: ChatBI,
    airline_a: str,
    airline_b: str,
    selected_destination: str,
    delay_cost_per_minute: int = DEFAULT_DELAY_COST_PER_MINUTE,
    cancellation_cost: int = DEFAULT_CANCELLATION_COST,
    selected_airlines: Optional[list[str]] = None,
) -> pd.DataFrame:
    base_params: list[Any] = []
    where_clauses: list[str] = []

    if selected_airlines:
        placeholders = ",".join(["?"] * len(selected_airlines))
        where_clauses.append(f"airline IN ({placeholders})")
        base_params.extend(selected_airlines)

    where_clauses.append("destination = ?")
    base_params.append(selected_destination)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    query = f"""
    WITH route_base AS (
        SELECT *
        FROM flights
        {where_sql}
    ),
    airline_metrics AS (
        SELECT
            airline,
            destination,
            COUNT(*) AS total_flights,
            AVG(COALESCE(latency_minutes, 0)) AS avg_latency,
            AVG(CASE WHEN status = 'On-Time' THEN 1.0 ELSE 0.0 END) AS on_time_rate,
            AVG(CASE WHEN status = 'Cancelled' THEN 1.0 ELSE 0.0 END) AS cancellation_rate,
            SUM(CASE WHEN status = 'Delayed' THEN COALESCE(latency_minutes, 0) * ? ELSE 0 END) +
            SUM(CASE WHEN status = 'Cancelled' THEN ? ELSE 0 END) AS total_cost_eur
        FROM route_base
        GROUP BY airline, destination
    ),
    ranked AS (
        SELECT
            *,
            RANK() OVER (PARTITION BY destination ORDER BY avg_latency ASC) AS latency_rank,
            DENSE_RANK() OVER (PARTITION BY destination ORDER BY on_time_rate DESC) AS punctuality_rank,
            PERCENT_RANK() OVER (PARTITION BY destination ORDER BY avg_latency ASC) AS latency_percent_rank
        FROM airline_metrics
    )
    SELECT *
    FROM ranked
    WHERE airline IN (?, ?)
    ORDER BY avg_latency ASC
    """

    query_params = base_params + [delay_cost_per_minute, cancellation_cost, airline_a, airline_b]
    df = bi.dataframe(query, query_params)

    if not df.empty:
        df["on_time_rate_pct"] = pd.to_numeric(df["on_time_rate"], errors="coerce").fillna(0) * 100
        df["cancellation_rate_pct"] = pd.to_numeric(df["cancellation_rate"], errors="coerce").fillna(0) * 100
        df["latency_percent_rank_pct"] = pd.to_numeric(df["latency_percent_rank"], errors="coerce").fillna(0) * 100

    return df


def explain_dashboard(filtered_df: pd.DataFrame, cost_by_airline: pd.DataFrame) -> str:
    if filtered_df.empty:
        return "No data is available for the current filters."

    total_flights = len(filtered_df)
    avg_latency = pd.to_numeric(filtered_df["latency_minutes"], errors="coerce").fillna(0).mean()
    total_cost = pd.to_numeric(filtered_df["total_cost_eur"], errors="coerce").fillna(0).sum()

    top_cost_record = safe_sorted_first_record(cost_by_airline, sort_col="total_cost_eur", ascending=False)
    top_cost_airline = safe_get(top_cost_record, "airline")

    high_risk_rows = int((filtered_df["quality_flag"] == "High Risk").sum())
    review_rows = int((filtered_df["quality_flag"] == "Review").sum())

    parts = [
        f"Current selection: {total_flights:,} flights.",
        f"Average latency: {avg_latency:.1f} min.",
        f"Estimated disruption cost: €{total_cost:,.0f}.",
    ]

    if top_cost_airline:
        parts.append(f"Largest cost driver: {top_cost_airline}.")

    if high_risk_rows > 0:
        parts.append(f"Watchdog flagged {high_risk_rows:,} High Risk rows and {review_rows:,} Review rows.")
    elif review_rows > 0:
        parts.append(f"Watchdog flagged {review_rows:,} Review rows and no High Risk rows.")
    else:
        parts.append("Watchdog found no major anomalies.")

    return " ".join(parts)


def explain_airline_wars(wars_df: pd.DataFrame, airline_a: str, airline_b: str, destination: str) -> str:
    if wars_df is None or wars_df.empty or len(wars_df) < 2:
        return f"Not enough data to compare {airline_a} and {airline_b} on {destination}."

    top_two = safe_sorted_top_n_records(wars_df, sort_col="avg_latency", n=2, ascending=True)
    if len(top_two) < 2:
        return f"Not enough data to compare {airline_a} and {airline_b} on {destination}."

    winner = top_two[0]
    loser = top_two[1]

    return (
        f"{safe_get(winner, 'airline', 'Unknown')} leads on {destination} with lower average latency "
        f"({float(safe_get(winner, 'avg_latency', 0)):.1f} vs {float(safe_get(loser, 'avg_latency', 0)):.1f} min), "
        f"better on-time rate ({float(safe_get(winner, 'on_time_rate_pct', 0)):.1f}% vs {float(safe_get(loser, 'on_time_rate_pct', 0)):.1f}%), "
        f"and lower route cost (€{float(safe_get(winner, 'total_cost_eur', 0)):,.0f} vs €{float(safe_get(loser, 'total_cost_eur', 0)):,.0f})."
    )


def explain_chat_result(question: str, df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "The query returned no rows for the current request."

    row_count = len(df)
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    entity_col = detect_entity_column(df)

    if "estimated_cost" in df.columns and entity_col:
        top_row = safe_sorted_first_record(df, "estimated_cost", ascending=False)
        return (
            f"'{question}' returned {row_count} rows. "
            f"{safe_get(top_row, entity_col, 'The leading entity')} has the highest estimated cost."
        )

    if "avg_latency" in df.columns and entity_col:
        top_row = safe_sorted_first_record(df, "avg_latency", ascending=False)
        return (
            f"'{question}' returned {row_count} rows. "
            f"{safe_get(top_row, entity_col, 'The leading entity')} has the highest average latency."
        )

    if "cancelled_flights" in df.columns and entity_col:
        top_row = safe_sorted_first_record(df, "cancelled_flights", ascending=False)
        return (
            f"'{question}' returned {row_count} rows. "
            f"{safe_get(top_row, entity_col, 'The leading entity')} has the most cancellations."
        )

    if entity_col and numeric_cols:
        top_metric = numeric_cols[0]
        top_row = safe_sorted_first_record(df, top_metric, ascending=False)
        return (
            f"'{question}' returned {row_count} rows. "
            f"{safe_get(top_row, entity_col, 'The leading entity')} leads on {top_metric.replace('_', ' ')}."
        )

    return f"'{question}' returned {row_count} rows."


def validate_dataset(bi: ChatBI) -> None:
    missing = REQUIRED_COLUMNS - set(bi.get_columns())
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    if df is None or df.empty:
        return b""
    return df.to_csv(index=False).encode("utf-8")


def write_dataframe_csv(df: pd.DataFrame, path: Path | str) -> Path:
    output_path = Path(path)
    if df is None or df.empty:
        raise ValueError("Cannot export an empty dataframe")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(dataframe_to_csv_bytes(df))
    return output_path


def get_distinct_values(bi: ChatBI, column: str) -> list[str]:
    allowed = {"airline", "destination", "origin", "status"}
    if column not in allowed:
        raise ValueError(f"Unsupported column for distinct lookup: {column}")
    return bi.dataframe(
        f"SELECT DISTINCT {column} FROM flights WHERE {column} IS NOT NULL ORDER BY {column}"
    )[column].tolist()


def query_flight_kpis(bi: ChatBI, selected_airlines: list[str]) -> dict[str, Any]:
    filter_sql, filter_params = build_airline_filter(selected_airlines)
    return {
        "total_flights": bi.scalar(f"SELECT COUNT(*) FROM flights {filter_sql}", filter_params),
        "avg_latency": bi.scalar(f"SELECT AVG(latency_minutes) FROM flights {filter_sql}", filter_params),
        "delayed_count": bi.scalar(
            f"SELECT COUNT(*) FROM flights {filter_sql} {'AND' if filter_sql else 'WHERE'} status = ?",
            filter_params + ["Delayed"],
        ),
    }


def aggregate_cost_by_airline(filtered_df: pd.DataFrame) -> pd.DataFrame:
    if filtered_df.empty:
        return pd.DataFrame()
    return (
        filtered_df.groupby("airline", as_index=False)
        .agg(
            total_cost_eur=("total_cost_eur", "sum"),
            delay_cost_eur=("delay_cost_eur", "sum"),
            cancellation_cost_eur=("cancellation_cost_eur", "sum"),
        )
        .sort_values("total_cost_eur", ascending=False)
    )


def aggregate_watchdog_summary(filtered_df: pd.DataFrame) -> pd.DataFrame:
    if filtered_df.empty:
        return pd.DataFrame()
    return (
        filtered_df.groupby("quality_flag", as_index=False)
        .agg(
            rows=("flight_id", "count"),
            avg_latency=("latency_minutes", "mean"),
            total_cost_eur=("total_cost_eur", "sum"),
        )
    )


def sum_cost_columns(filtered_df: pd.DataFrame) -> dict[str, float]:
    if filtered_df.empty:
        return {"total_cost": 0.0, "delay_cost": 0.0, "cancellation_cost": 0.0}
    return {
        "total_cost": float(pd.to_numeric(filtered_df["total_cost_eur"], errors="coerce").fillna(0).sum()),
        "delay_cost": float(pd.to_numeric(filtered_df["delay_cost_eur"], errors="coerce").fillna(0).sum()),
        "cancellation_cost": float(
            pd.to_numeric(filtered_df["cancellation_cost_eur"], errors="coerce").fillna(0).sum()
        ),
    }


def resolve_model_chain(
    available_models: list[str],
    default_chain: list[str] | None = None,
) -> list[str]:
    default_chain = default_chain or DEFAULT_MODEL_CHAIN
    selected = [m for m in default_chain if m in available_models]
    return selected or default_chain


def normalize_model_profile(profile: str) -> str:
    key = profile.lower().strip()
    if key not in MODEL_PROFILES:
        valid = ", ".join(MODEL_PROFILES)
        raise ValueError(f"Unknown model profile '{profile}'. Choose: {valid}")
    return key


def get_profile_chain(profile: str) -> list[str]:
    return list(MODEL_PROFILES[normalize_model_profile(profile)])


def normalize_watchdog_sensitivity(sensitivity: str) -> str:
    key = sensitivity.lower().strip()
    if key not in WATCHDOG_SENSITIVITY_PROFILES:
        valid = ", ".join(WATCHDOG_SENSITIVITY_PROFILES)
        raise ValueError(f"Unknown watchdog sensitivity '{sensitivity}'. Choose: {valid}")
    return key


def get_watchdog_settings(sensitivity: str) -> WatchdogSettings:
    return WATCHDOG_SENSITIVITY_PROFILES[normalize_watchdog_sensitivity(sensitivity)]


def resolve_profile_chain(profile: str, available_models: list[str]) -> list[str]:
    return resolve_model_chain(available_models, get_profile_chain(profile))


def default_airline_selection(all_airlines: list[str], limit: int = 3) -> list[str]:
    return all_airlines[:limit] if len(all_airlines) >= limit else all_airlines


ChartKind = Literal["bar", "line", "pie", "none"]

PRIMARY_METRIC_COLUMNS = (
    "estimated_cost",
    "avg_latency",
    "cancelled_flights",
    "total_flights",
    "total_cost_eur",
    "latency_minutes",
)


@dataclass(frozen=True)
class ChartSpec:
    kind: ChartKind
    x: str | None = None
    y: str | None = None
    color: str | None = None
    title: str = ""


def _categorical_columns(df: pd.DataFrame) -> list[str]:
    return df.select_dtypes(include=["object", "string", "category"]).columns.tolist()


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    return df.select_dtypes(include="number").columns.tolist()


def _pick_primary_metric(numeric_cols: list[str]) -> str | None:
    for column in PRIMARY_METRIC_COLUMNS:
        if column in numeric_cols:
            return column
    return numeric_cols[0] if numeric_cols else None


def recommend_chart(df: pd.DataFrame) -> ChartSpec:
    if df is None or df.empty:
        return ChartSpec(kind="none")

    numeric_cols = _numeric_columns(df)
    if not numeric_cols:
        return ChartSpec(kind="none")

    entity_col = detect_entity_column(df)
    categorical_cols = _categorical_columns(df)
    metric = _pick_primary_metric([col for col in numeric_cols if col != "flight_id"])

    if "status" in df.columns and metric and df["status"].nunique() <= 6 and len(df) <= 20:
        if entity_col == "status" or categorical_cols == ["status"]:
            return ChartSpec(
                kind="pie",
                x="status",
                y=metric,
                title=f"{metric.replace('_', ' ').title()} by status",
            )

    if "latency_minutes" in numeric_cols and "flight_id" in df.columns and len(df) > 3:
        color = entity_col if entity_col and entity_col not in {"flight_id"} else None
        return ChartSpec(
            kind="line",
            x="flight_id",
            y="latency_minutes",
            color=color,
            title="Latency by flight",
        )

    if metric and entity_col and entity_col != metric:
        return ChartSpec(
            kind="bar",
            x=entity_col,
            y=metric,
            title=f"{metric.replace('_', ' ').title()} by {entity_col.replace('_', ' ').title()}",
        )

    if categorical_cols and metric:
        x_col = categorical_cols[0]
        if x_col != metric:
            return ChartSpec(
                kind="bar",
                x=x_col,
                y=metric,
                title=f"{metric.replace('_', ' ').title()} by {x_col.replace('_', ' ').title()}",
            )

    if metric and len(df) > 1:
        return ChartSpec(
            kind="line",
            x=df.columns[0],
            y=metric,
            title=f"{metric.replace('_', ' ').title()} trend",
        )

    return ChartSpec(kind="none")
