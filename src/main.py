from __future__ import annotations

from pathlib import Path
from typing import Optional, Any
import re

import duckdb
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from ollama import Client

try:
    from config import get_config
except Exception:
    def get_config() -> dict[str, Any]:
        project_root = Path(__file__).resolve().parents[1]
        return {
            "OLLAMA_HOST": "http://localhost:11434",
            "OLLAMA_TIMEOUT": 180,
            "DATA_PATH": str(project_root / "data" / "flights.csv"),
            "DEFAULT_DELAY_COST_PER_MINUTE": 50,
            "DEFAULT_CANCELLATION_COST": 200,
            "DEFAULT_MODEL_CHAIN": [
                "mistral:7b",
                "phi4:14b",
                "qwen2.5-coder:14b",
                "gemma4:26b",
                "qwen3.6:27b",
                "qwen3.6:35b-a3b",
                "deepseek-r1:8b",
            ],
        }

CFG = get_config()
console = Console()

APP_DIR = Path(__file__).resolve().parent
DATA_PATH = Path(CFG["DATA_PATH"])
OLLAMA_HOST = CFG["OLLAMA_HOST"]
OLLAMA_TIMEOUT = CFG["OLLAMA_TIMEOUT"]
DEFAULT_MODEL_CHAIN = CFG["DEFAULT_MODEL_CHAIN"]
DEFAULT_DELAY_COST_PER_MINUTE = CFG["DEFAULT_DELAY_COST_PER_MINUTE"]
DEFAULT_CANCELLATION_COST = CFG["DEFAULT_CANCELLATION_COST"]

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


class ChatBI:
    def __init__(self, csv_path: str, model_chain: list[str]):
        self.csv_path = csv_path
        self.model_chain = model_chain
        self.client = Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT)
        self.db = duckdb.connect(database=":memory:")
        self._load_table()

    def _load_table(self):
        """
        Força o esquema da tabela flights ao ler o CSV, evitando tipos LIST/VARCHAR[].
        """
        self.db.execute(
            """
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
            """,
            [self.csv_path],
        )

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
        sql_upper = sql.upper().strip()
        blocked_tokens = [
            "INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "TRUNCATE ",
            "CREATE ", "REPLACE ", "COPY ", "ATTACH ", "DETACH ", "INSTALL ",
            "LOAD ", "CALL ", "EXPORT ", "VACUUM ", "PRAGMA "
        ]
        if not sql_upper.startswith("SELECT "):
            return False
        return not any(token in sql_upper for token in blocked_tokens)

    def _ensure_limit(self, sql: str, default_limit: int = 200) -> str:
        if re.search(r"\bLIMIT\s+\d+\b", sql, flags=re.IGNORECASE):
            return sql
        return f"{sql} LIMIT {default_limit}"

    def _build_prompt(self, question: str) -> str:
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

    def ask_with_fallback(self, question: str, model_chain: list[str]):
        errors = []

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
    return records if records else {}


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

    object_cols = [
        c for c in df.columns
        if df[c].dtype == "object" or str(df[c].dtype).startswith("string")
    ]
    return object_cols if object_cols else None


def build_airline_filter(selected_airlines: list[str]) -> tuple[str, list]:
    if not selected_airlines:
        return "", []
    placeholders = ",".join(["?"] * len(selected_airlines))
    return f"WHERE airline IN ({placeholders})", selected_airlines


def add_cost_columns(
    df: pd.DataFrame,
    delay_cost_per_minute: int = 50,
    cancellation_cost: int = 200,
) -> pd.DataFrame:
    df = df.copy()

    if df.empty:
        df["delay_cost_eur"] = pd.Series(dtype="float64")
        df["cancellation_cost_eur"] = pd.Series(dtype="float64")
        df["total_cost_eur"] = pd.Series(dtype="float64")
        return df

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
    delay_cost_per_minute: int = 50,
    cancellation_cost: int = 200,
) -> pd.DataFrame:
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
            QUANTILE_CONT(COALESCE(latency_minutes, 0), 0.95) AS p95_latency,
            QUANTILE_CONT(COALESCE(latency_minutes, 0), 0.99) AS p99_latency
        FROM base
        GROUP BY airline
    )
    SELECT
        b.*,
        COALESCE(s.avg_latency, 0) AS avg_latency_airline,
        COALESCE(s.std_latency, 0) AS std_latency_airline,
        COALESCE(s.p95_latency, 0) AS p95_latency_airline,
        COALESCE(s.p99_latency, 0) AS p99_latency_airline,
        CASE
            WHEN b.status = 'Cancelled' THEN 100
            WHEN COALESCE(b.latency_minutes, 0) >= COALESCE(s.p99_latency, 0)
                 AND COALESCE(b.latency_minutes, 0) > COALESCE(s.avg_latency, 0) + 3 * COALESCE(s.std_latency, 0)
                THEN 95
            WHEN COALESCE(b.latency_minutes, 0) >= COALESCE(s.p95_latency, 0)
                 OR COALESCE(b.latency_minutes, 0) > COALESCE(s.avg_latency, 0) + 2 * COALESCE(s.std_latency, 0)
                THEN 65
            ELSE 15
        END AS quality_score,
        CASE
            WHEN b.status = 'Cancelled' THEN 'High Risk'
            WHEN COALESCE(b.latency_minutes, 0) >= COALESCE(s.p99_latency, 0)
                 AND COALESCE(b.latency_minutes, 0) > COALESCE(s.avg_latency, 0) + 3 * COALESCE(s.std_latency, 0)
                THEN 'High Risk'
            WHEN COALESCE(b.latency_minutes, 0) >= COALESCE(s.p95_latency, 0)
                 OR COALESCE(b.latency_minutes, 0) > COALESCE(s.avg_latency, 0) + 2 * COALESCE(s.std_latency, 0)
                THEN 'Review'
            ELSE 'Reliable'
        END AS quality_flag
    FROM base b
    LEFT JOIN airline_stats s
        ON b.airline = s.airline
    """

    df = bi.dataframe(query, filter_params)
    return add_cost_columns(df, delay_cost_per_minute, cancellation_cost)


def _escape_literal(value: Any) -> str:
    """
    Garante string simples para injetar em literal SQL:
    - Se vier lista/tuplo, usa o primeiro elemento.
    - Converte para str e escapa aspas simples.
    """
    if isinstance(value, (list, tuple)):
        value = value if value else ""
    value_str = str(value)
    return value_str.replace("'", "''")


def get_airline_wars(
    bi: ChatBI,
    airline_a: str,
    airline_b: str,
    selected_destination: str,
    delay_cost_per_minute: int,
    cancellation_cost: int,
) -> pd.DataFrame:
    """
    Compara airline_a vs airline_b num destino concreto.
    Evita binding de parâmetros no IN, usando literals escapados.
    """
    a = _escape_literal(airline_a)
    b = _escape_literal(airline_b)
    dest = _escape_literal(selected_destination)

    query = f"""
    WITH route_base AS (
        SELECT *
        FROM flights
        WHERE airline IN ('{a}', '{b}')
          AND destination = '{dest}'
    ),
    airline_metrics AS (
        SELECT
            airline,
            destination,
            COUNT(*) AS total_flights,
            AVG(COALESCE(latency_minutes, 0)) AS avg_latency,
            AVG(CASE WHEN status = 'On-Time' THEN 1.0 ELSE 0.0 END) AS on_time_rate,
            AVG(CASE WHEN status = 'Cancelled' THEN 1.0 ELSE 0.0 END) AS cancellation_rate,
            SUM(CASE WHEN status = 'Delayed' THEN COALESCE(latency_minutes, 0) * {delay_cost_per_minute} ELSE 0 END) +
            SUM(CASE WHEN status = 'Cancelled' THEN {cancellation_cost} ELSE 0 END) AS total_cost_eur
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
    SELECT
        *
    FROM ranked
    ORDER BY avg_latency ASC
    """

    df = bi.dataframe(query)

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

    winner = top_two
    loser = top_two

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
        top_metric = numeric_cols
        top_row = safe_sorted_first_record(df, top_metric, ascending=False)
        return (
            f"'{question}' returned {row_count} rows. "
            f"{safe_get(top_row, entity_col, 'The leading entity')} leads on {str(top_metric).replace('_', ' ')}."
        )

    return f"'{question}' returned {row_count} rows."


def print_dataframe(df: pd.DataFrame, title: str = "Results", max_rows: int = 20):
    if df is None or df.empty:
        console.print("[yellow]No rows returned.[/yellow]")
        return

    preview = df.head(max_rows).copy()
    table = Table(title=title, show_lines=False)

    for col in preview.columns:
        table.add_column(str(col), overflow="fold")

    for _, row in preview.iterrows():
        table.add_row(*[str(x) for x in row.tolist()])

    console.print(table)

    if len(df) > max_rows:
        console.print(f"[dim]Showing {max_rows} of {len(df)} rows.[/dim]")


def print_attempt_errors(attempt_errors: list[str]):
    if not attempt_errors:
        return
    console.print("[bold yellow]Model attempts:[/bold yellow]")
    for err in attempt_errors:
        console.print(f"- {err}")


def print_kpis(bi: ChatBI, selected_airlines: list[str], filtered_df: pd.DataFrame):
    filter_sql, filter_params = build_airline_filter(selected_airlines)
    total_flights = bi.scalar(f"SELECT COUNT(*) FROM flights {filter_sql}", filter_params)
    avg_latency = bi.scalar(f"SELECT AVG(latency_minutes) FROM flights {filter_sql}", filter_params)
    delayed_count = bi.scalar(
        f"SELECT COUNT(*) FROM flights {filter_sql} {'AND' if filter_sql else 'WHERE'} status = ?",
        filter_params + ["Delayed"],
    )
    total_cost = float(filtered_df["total_cost_eur"].sum()) if not filtered_df.empty else 0

    console.print(Panel.fit(
        f"Total Flights: {int(total_flights or 0):,}\n"
        f"Avg Latency: {float(avg_latency or 0):.1f} min\n"
        f"Delayed Flights: {int(delayed_count or 0):,}\n"
        f"Total Cost: €{total_cost:,.0f}",
        title="Dashboard KPIs",
        border_style="cyan",
    ))


def run_cli(bi: ChatBI):
    all_airlines = bi.dataframe(
        "SELECT DISTINCT airline FROM flights WHERE airline IS NOT NULL ORDER BY airline"
    )["airline"].tolist()

    all_destinations = bi.dataframe(
        "SELECT DISTINCT destination FROM flights WHERE destination IS NOT NULL ORDER BY destination"
    )["destination"].tolist()

    available_models = bi.available_models()
    selected_chain = [m for m in DEFAULT_MODEL_CHAIN if m in available_models] or DEFAULT_MODEL_CHAIN
    selected_airlines = all_airlines[:3] if len(all_airlines) >= 3 else all_airlines

    console.print(Panel.fit(
        "The SQL Alchemist CLI is ready.\n"
        "Type a natural-language question, or use one of the commands below:\n"
        "  /help        Show commands\n"
        "  /suggest     Show suggested questions\n"
        "  /dashboard   Show KPI summary + Watchdog\n"
        "  /wars        Show Airline Wars snapshot\n"
        "  /models      Show active model chain\n"
        "  /quit        Exit",
        title="Neural Flight Bridge CLI",
        border_style="green",
    ))

    while True:
        user_input = Prompt.ask("[bold blue]The Alchemist[/bold blue]").strip()

        if user_input.lower() in {"quit", "exit", "q", "/quit"}:
            console.print("[red]Session closed.[/red]")
            break

        if user_input == "/help":
            console.print("Use /suggest, /dashboard, /wars, /models, or ask a question in plain English.")
            continue

        if user_input == "/suggest":
            for i, q in enumerate(SUGGESTED_QUESTIONS, start=1):
                console.print(f"{i}. {q}")
            continue

        if user_input == "/models":
            console.print("Active model chain:")
            for model in selected_chain:
                console.print(f"- {model}")
            continue

        if user_input == "/dashboard":
            filtered_df = add_watchdog_columns(
                bi,
                selected_airlines=selected_airlines,
                delay_cost_per_minute=DEFAULT_DELAY_COST_PER_MINUTE,
                cancellation_cost=DEFAULT_CANCELLATION_COST,
            )

            cost_by_airline = (
                filtered_df.groupby("airline", as_index=False)
                .agg(
                    total_cost_eur=("total_cost_eur", "sum"),
                    delay_cost_eur=("delay_cost_eur", "sum"),
                    cancellation_cost_eur=("cancellation_cost_eur", "sum"),
                )
                .sort_values("total_cost_eur", ascending=False)
            ) if not filtered_df.empty else pd.DataFrame()

            print_kpis(bi, selected_airlines, filtered_df)
            console.print(explain_dashboard(filtered_df, cost_by_airline))

            print_dataframe(cost_by_airline, title="Cost of Chaos", max_rows=10)

            watchdog_cols = [
                "flight_id",
                "airline",
                "destination",
                "latency_minutes",
                "quality_flag",
                "quality_score",
                "total_cost_eur",
            ]
            existing_watchdog_cols = [c for c in watchdog_cols if c in filtered_df.columns]
            print_dataframe(
                filtered_df[existing_watchdog_cols],
                title="Watchdog Preview",
                max_rows=15,
            )
            continue

        if user_input == "/wars":
            if len(all_airlines) < 2 or not all_destinations:
                console.print("[yellow]Not enough data for Airline Wars.[/yellow]")
                continue

            airline_a = selected_airlines if selected_airlines else all_airlines
            airline_b = selected_airlines if len(selected_airlines) > 1 else all_airlines
            destination = all_destinations

            wars_df = get_airline_wars(
                bi=bi,
                airline_a=airline_a,
                airline_b=airline_b,
                selected_destination=destination,
                delay_cost_per_minute=DEFAULT_DELAY_COST_PER_MINUTE,
                cancellation_cost=DEFAULT_CANCELLATION_COST,
            )

            console.print(explain_airline_wars(wars_df, airline_a, airline_b, destination))
            print_dataframe(wars_df, title="Airline Wars", max_rows=10)
            continue

        response = bi.ask_with_fallback(user_input, selected_chain)

        if response["success"]:
            console.print(Panel.fit(response["sql"], title=f"SQL via {response['model']}", border_style="magenta"))
            console.print(explain_chat_result(user_input, response["data"]))
            print_dataframe(response["data"], title="Query Result", max_rows=20)
            print_attempt_errors(response["attempt_errors"])
        else:
            console.print(f"[red]{response['error']}[/red]")
            print_attempt_errors(response["attempt_errors"])


def validate_dataset(bi: ChatBI):
    required_cols = {
        "flight_id",
        "airline",
        "origin",
        "destination",
        "departure_time",
        "arrival_time",
        "latency_minutes",
        "status",
    }
    missing = required_cols - set(bi.get_columns())
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")


def main():
    if not DATA_PATH.exists():
        console.print(f"[red]Data file not found: {DATA_PATH}[/red]")
        return

    try:
        bi = ChatBI(str(DATA_PATH), DEFAULT_MODEL_CHAIN)
        validate_dataset(bi)
        run_cli(bi)
    except Exception as exc:
        console.print(f"[red]Startup failed: {exc}[/red]")


if __name__ == "__main__":
    main()