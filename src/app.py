import sys
from pathlib import Path
from typing import Optional, Any
import re

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st
from ollama import Client

from config import get_config


st.set_page_config(
    page_title="Neural Flight Bridge",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)


CFG = get_config()

APP_DIR = Path(__file__).resolve().parent
DATA_PATH = Path(CFG["DATA_PATH"])
OLLAMA_HOST = CFG.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_TIMEOUT = CFG.get("OLLAMA_TIMEOUT", 180)
DEFAULT_MODEL_CHAIN = CFG.get(
    "DEFAULT_MODEL_CHAIN",
    [
        "mistral:7b",
        "phi4:14b",
        "qwen2.5-coder:14b",
        "gemma4:26b",
        "qwen3.6:27b",
        "qwen3.6:35b-a3b",
        "deepseek-r1:8b",
    ],
)
DEFAULT_DELAY_COST_PER_MINUTE = CFG.get("DEFAULT_DELAY_COST_PER_MINUTE", 50)
DEFAULT_CANCELLATION_COST = CFG.get("DEFAULT_CANCELLATION_COST", 200)


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


class WebChatBI:
    def __init__(self, csv_path: str, model_chain: list[str]):
        self.csv_path = csv_path
        self.model_chain = model_chain
        self.client = Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT)
        self.db = duckdb.connect(database=":memory:")
        self._load_table()

    def _load_table(self):
        self.db.execute(
            """
            CREATE OR REPLACE TABLE flights AS
            SELECT * FROM read_csv_auto(?)
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
            "LOAD ", "CALL ", "EXPORT ", "VACUUM ", "PRAGMA ",
        ]

        if not sql_upper.startswith("SELECT "):
            return False

        if ";" in sql:
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
            return False, "", f"{model_name}: model request failed ({exc})"

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
                    errors.append(f"{model_name}: SQL execution failed ({exc})")
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
            errors.append(f"fallback: query execution failed ({exc})")
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
    if value is None:
        return default
    return value


def safe_first_record(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        return {}
    records = df.reset_index(drop=True).head(1).to_dict("records")
    return records if records else {}


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

    preferred = preferred or [
        "airline",
        "destination",
        "origin",
        "route",
        "status",
    ]

    for col in preferred:
        if col in df.columns:
            return col

    object_cols = [
        c for c in df.columns
        if df[c].dtype == "object" or str(df[c].dtype).startswith("string")
    ]
    return object_cols if object_cols else None


def add_cost_columns(
    df: pd.DataFrame,
    delay_cost_per_minute: int = 50,
    cancellation_cost: int = 200,
) -> pd.DataFrame:
    df = df.copy()

    if df.empty:
        for col in ["delay_cost_eur", "cancellation_cost_eur", "total_cost_eur"]:
            if col not in df.columns:
                df[col] = pd.Series(dtype="float64")
        return df

    required_cols = {"status", "latency_minutes"}
    missing = required_cols - set(df.columns)
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


def build_airline_filter(selected_airlines: list[str]) -> tuple[str, list]:
    if not selected_airlines:
        return "", []
    placeholders = ",".join(["?"] * len(selected_airlines))
    return f"WHERE airline IN ({placeholders})", selected_airlines


def add_watchdog_columns(
    bi: WebChatBI,
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
    df = add_cost_columns(
        df,
        delay_cost_per_minute=delay_cost_per_minute,
        cancellation_cost=cancellation_cost,
    )
    return df


def get_airline_wars(
    bi: WebChatBI,
    selected_airlines: list[str],
    airline_a: str,
    airline_b: str,
    selected_destination: str,
    delay_cost_per_minute: int,
    cancellation_cost: int,
) -> pd.DataFrame:
    base_params = []
    where_clauses = []

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
            RANK() OVER (
                PARTITION BY destination
                ORDER BY avg_latency ASC
            ) AS latency_rank,
            DENSE_RANK() OVER (
                PARTITION BY destination
                ORDER BY on_time_rate DESC
            ) AS punctuality_rank,
            PERCENT_RANK() OVER (
                PARTITION BY destination
                ORDER BY avg_latency ASC
            ) AS latency_percent_rank
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


def explain_dashboard(
    filtered_df: pd.DataFrame,
    cost_by_airline: pd.DataFrame,
    watchdog_summary: pd.DataFrame,
) -> str:
    if filtered_df.empty:
        return "No data is available for the current filters."

    total_flights = len(filtered_df)
    avg_latency = pd.to_numeric(filtered_df["latency_minutes"], errors="coerce").fillna(0).mean()
    total_cost = pd.to_numeric(filtered_df["total_cost_eur"], errors="coerce").fillna(0).sum()

    top_cost_record = safe_sorted_first_record(
        cost_by_airline,
        sort_col="total_cost_eur",
        ascending=False,
    )
    top_cost_airline = safe_get(top_cost_record, "airline")

    high_risk_rows = int((filtered_df["quality_flag"] == "High Risk").sum())
    review_rows = int((filtered_df["quality_flag"] == "Review").sum())

    parts = [
        f"The current selection contains {total_flights:,} flights with an average latency of {avg_latency:.1f} minutes.",
        f"Estimated disruption cost is €{total_cost:,.0f}.",
    ]

    if top_cost_airline:
        parts.append(f"{top_cost_airline} is currently the largest cost driver in the filtered view.")

    if high_risk_rows > 0:
        parts.append(
            f"Watchdog flagged {high_risk_rows:,} rows as High Risk and {review_rows:,} rows for Review, suggesting closer validation."
        )
    elif review_rows > 0:
        parts.append(
            f"Watchdog flagged {review_rows:,} rows for Review, while no rows were classified as High Risk."
        )
    else:
        parts.append("Watchdog did not identify major anomalies in the current filtered dataset.")

    return " ".join(parts)


def explain_airline_wars(
    wars_df: pd.DataFrame,
    airline_a: str,
    airline_b: str,
    destination: str,
) -> str:
    if wars_df is None or wars_df.empty or len(wars_df) < 2:
        return f"There is not enough data to compare {airline_a} and {airline_b} on {destination}."

    top_two = safe_sorted_top_n_records(
        wars_df,
        sort_col="avg_latency",
        n=2,
        ascending=True,
    )

    if len(top_two) < 2:
        return f"There is not enough data to compare {airline_a} and {airline_b} on {destination}."

    winner = top_two
    loser = top_two

    winner_airline = safe_get(winner, "airline", "Unknown")
    loser_airline = safe_get(loser, "airline", "Unknown")
    winner_avg_latency = float(safe_get(winner, "avg_latency", 0) or 0)
    loser_avg_latency = float(safe_get(loser, "avg_latency", 0) or 0)
    winner_on_time = float(safe_get(winner, "on_time_rate_pct", 0) or 0)
    loser_on_time = float(safe_get(loser, "on_time_rate_pct", 0) or 0)
    winner_cost = float(safe_get(winner, "total_cost_eur", 0) or 0)
    loser_cost = float(safe_get(loser, "total_cost_eur", 0) or 0)

    return (
        f"On destination {destination}, {winner_airline} currently leads this rivalry with lower average latency "
        f"({winner_avg_latency:.1f} min vs {loser_avg_latency:.1f} min), "
        f"better on-time performance ({winner_on_time:.1f}% vs {loser_on_time:.1f}%), "
        f"and a route cost of €{winner_cost:,.0f} compared with €{loser_cost:,.0f}."
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
            f"This result answers the question '{question}' with {row_count} rows. "
            f"{safe_get(top_row, entity_col, 'The leading entity')} has the highest estimated cost at "
            f"€{float(safe_get(top_row, 'estimated_cost', 0) or 0):,.0f}."
        )

    if "avg_latency" in df.columns and entity_col:
        top_row = safe_sorted_first_record(df, "avg_latency", ascending=False)
        return (
            f"This result answers the question '{question}' with {row_count} rows. "
            f"{safe_get(top_row, entity_col, 'The leading entity')} shows the highest average latency at "
            f"{float(safe_get(top_row, 'avg_latency', 0) or 0):.1f} minutes."
        )

    if "cancelled_flights" in df.columns and entity_col:
        top_row = safe_sorted_first_record(df, "cancelled_flights", ascending=False)
        return (
            f"This result answers the question '{question}' with {row_count} rows. "
            f"{safe_get(top_row, entity_col, 'The leading entity')} has the highest cancelled flight count at "
            f"{int(float(safe_get(top_row, 'cancelled_flights', 0) or 0))}."
        )

    if entity_col and numeric_cols:
        top_metric = next((col for col in numeric_cols if isinstance(col, str)), None)

        if not top_metric:
            return f"This result answers the question '{question}' with {row_count} rows."

        top_row = safe_sorted_first_record(df, top_metric, ascending=False)
        top_value = safe_get(top_row, top_metric, 0)

        try:
            top_value_fmt = f"{float(top_value):,.1f}"
        except Exception:
            top_value_fmt = str(top_value)

        return (
            f"This result answers the question '{question}' with {row_count} rows. "
            f"{safe_get(top_row, entity_col, 'The leading entity')} has the highest value for "
            f"{str(top_metric).replace('_', ' ')} at {top_value_fmt}."
        )

    if numeric_cols:
        return (
            f"This result answers the question '{question}' with {row_count} rows and {len(numeric_cols)} numeric fields, "
            "which makes it suitable for quick visual comparison."
        )

    return f"This result answers the question '{question}' with {row_count} rows."


@st.cache_resource(show_spinner=False)
def load_bi(csv_path: str):
    path = Path(csv_path)
    if not path.exists():
        return None
    return WebChatBI(str(path), DEFAULT_MODEL_CHAIN)


def init_session_state():
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []


def render_chat_history():
    for item in st.session_state.chat_history:
        with st.chat_message("user"):
            st.markdown(item["question"])

        with st.chat_message("assistant"):
            if item.get("success"):
                st.caption(f"Model used: {item['model']}")
                st.code(item["sql"], language="sql")

                if item.get("explanation"):
                    st.info(item["explanation"])

                st.dataframe(item["data"], use_container_width=True, height=260)
            else:
                st.error(item.get("error", "Unknown error"))
                if item.get("attempt_errors"):
                    with st.expander("Model attempts"):
                        for err in item["attempt_errors"]:
                            st.write(f"- {err}")


def render_suggested_questions() -> Optional[str]:
    st.markdown("**Suggested Questions**")

    selected_prompt = None
    cols = st.columns(2)

    for i, question in enumerate(SUGGESTED_QUESTIONS):
        with cols[i % 2]:
            if st.button(
                question,
                key=f"suggestion_{i}",
                use_container_width=True,
            ):
                selected_prompt = question

    return selected_prompt


bi = load_bi(str(DATA_PATH))

if bi is None:
    st.error(f"❌ Ficheiro não encontrado: {DATA_PATH}")
    st.stop()

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

table_cols = set(bi.get_columns())
missing_cols = required_cols - table_cols

if missing_cols:
    st.error(f"❌ Missing required columns: {', '.join(sorted(missing_cols))}")
    st.stop()

init_session_state()

st.title("🧠 The Neural Bridge")
st.caption("Natural language analytics powered by Streamlit, DuckDB and Ollama.")

available_models = bi.available_models()
default_chain = [m for m in DEFAULT_MODEL_CHAIN if m in available_models] or DEFAULT_MODEL_CHAIN

all_airlines_df = bi.dataframe(
    "SELECT DISTINCT airline FROM flights WHERE airline IS NOT NULL ORDER BY airline"
)
all_airlines = all_airlines_df["airline"].tolist()

all_destinations_df = bi.dataframe(
    "SELECT DISTINCT destination FROM flights WHERE destination IS NOT NULL ORDER BY destination"
)
all_destinations = all_destinations_df["destination"].tolist()

with st.sidebar:
    st.header("Settings")

    st.markdown("**Model fallback chain**")
    selected_chain = st.multiselect(
        "Execution order",
        options=available_models or DEFAULT_MODEL_CHAIN,
        default=default_chain,
    )

    if not selected_chain:
        selected_chain = default_chain

    st.caption("The app will try the fastest/smallest model first, then escalate.")

    st.subheader("Business Impact")

    delay_cost_per_minute = st.number_input(
        "Delay cost per minute (€)",
        min_value=0,
        value=DEFAULT_DELAY_COST_PER_MINUTE,
        step=5,
    )

    cancellation_cost = st.number_input(
        "Cancellation cost (€)",
        min_value=0,
        value=DEFAULT_CANCELLATION_COST,
        step=10,
    )

    st.divider()
    st.header("Global Filters")

    default_airlines = all_airlines[:3] if len(all_airlines) >= 3 else all_airlines

    selected_airlines = st.multiselect(
        "Airlines",
        options=all_airlines,
        default=default_airlines,
    )

    st.divider()
    st.header("Airline Wars")

    wars_airlines = selected_airlines if selected_airlines else all_airlines

    if wars_airlines:
        airline_a = st.selectbox("Airline A", options=wars_airlines, index=0)
    else:
        airline_a = None

    airline_b_candidates = [a for a in wars_airlines if a != airline_a]
    airline_b_options = airline_b_candidates if airline_b_candidates else wars_airlines
    if airline_b_options:
        airline_b = st.selectbox("Airline B", options=airline_b_options, index=0)
    else:
        airline_b = None

    if all_destinations:
        selected_destination = st.selectbox("Destination", options=all_destinations, index=0)
    else:
        selected_destination = None

    if st.button("Clear chat history", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

filter_sql, filter_params = build_airline_filter(selected_airlines)

tab1, tab2 = st.tabs(["📊 Visuals", "🗣️ Chat"])

with tab1:
    st.subheader("Real-Time Analytics")

    total_flights = bi.scalar(
        f"SELECT COUNT(*) FROM flights {filter_sql}",
        filter_params,
    )

    avg_latency = bi.scalar(
        f"SELECT AVG(latency_minutes) FROM flights {filter_sql}",
        filter_params,
    )

    delayed_count = bi.scalar(
        f"SELECT COUNT(*) FROM flights {filter_sql} {'AND' if filter_sql else 'WHERE'} status = ?",
        filter_params + ["Delayed"],
    )

    filtered_df = add_watchdog_columns(
        bi,
        selected_airlines=selected_airlines,
        delay_cost_per_minute=delay_cost_per_minute,
        cancellation_cost=cancellation_cost,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Flights", f"{int(total_flights or 0):,}")
    c2.metric("Avg Latency", f"{float(avg_latency or 0):.1f} min")
    c3.metric("Delayed Flights", f"{int(delayed_count or 0):,}")

    total_cost = float(pd.to_numeric(filtered_df["total_cost_eur"], errors="coerce").fillna(0).sum()) if not filtered_df.empty else 0
    delay_cost_total = float(pd.to_numeric(filtered_df["delay_cost_eur"], errors="coerce").fillna(0).sum()) if not filtered_df.empty else 0
    cancellation_cost_total = float(pd.to_numeric(filtered_df["cancellation_cost_eur"], errors="coerce").fillna(0).sum()) if not filtered_df.empty else 0

    c4, c5, c6 = st.columns(3)
    c4.metric("Total Cost (€)", f"{total_cost:,.0f}")
    c5.metric("Delay Cost (€)", f"{delay_cost_total:,.0f}")
    c6.metric("Cancellation Cost (€)", f"{cancellation_cost_total:,.0f}")

    reliable_count = int((filtered_df["quality_flag"] == "Reliable").sum()) if not filtered_df.empty else 0
    review_count = int((filtered_df["quality_flag"] == "Review").sum()) if not filtered_df.empty else 0
    high_risk_count = int((filtered_df["quality_flag"] == "High Risk").sum()) if not filtered_df.empty else 0

    c7, c8, c9 = st.columns(3)
    c7.metric("Reliable Rows", f"{reliable_count:,}")
    c8.metric("Review Rows", f"{review_count:,}")
    c9.metric("High Risk Rows", f"{high_risk_count:,}")

    cost_by_airline = (
        filtered_df.groupby("airline", as_index=False)
        .agg(
            total_cost_eur=("total_cost_eur", "sum"),
            delay_cost_eur=("delay_cost_eur", "sum"),
            cancellation_cost_eur=("cancellation_cost_eur", "sum"),
        )
        .sort_values("total_cost_eur", ascending=False)
    ) if not filtered_df.empty else pd.DataFrame()

    watchdog_summary = (
        filtered_df.groupby("quality_flag", as_index=False)
        .agg(
            rows=("flight_id", "count"),
            avg_latency=("latency_minutes", "mean"),
            total_cost_eur=("total_cost_eur", "sum"),
        )
    ) if not filtered_df.empty else pd.DataFrame()

    st.subheader("Result Explanation")
    st.markdown(explain_dashboard(filtered_df, cost_by_airline, watchdog_summary))

    if filtered_df.empty:
        st.warning("No data available for the current filter selection.")
    else:
        col_plot1, col_plot2 = st.columns(2)

        with col_plot1:
            fig = px.line(
                filtered_df,
                x="flight_id",
                y="latency_minutes",
                color="airline",
                title="Latency Timeline",
            )
            fig.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig, use_container_width=True)

        with col_plot2:
            impacted_df = (
                filtered_df[filtered_df["latency_minutes"] > 0]
                .groupby("airline", as_index=False)
                .agg(
                    total_latency=("latency_minutes", "sum"),
                    flights=("flight_id", "count"),
                )
                .sort_values("total_latency", ascending=False)
            )

            if impacted_df.empty:
                st.info("No delayed flights in current selection.")
            else:
                fig2 = px.bar(
                    impacted_df,
                    x="airline",
                    y="total_latency",
                    color="flights",
                    title="Impacted Airlines",
                )
                fig2.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Cost of Chaos")

        if cost_by_airline.empty:
            st.info("No cost impact available for the current selection.")
        else:
            fig3 = px.bar(
                cost_by_airline,
                x="airline",
                y="total_cost_eur",
                color="total_cost_eur",
                title="Estimated Total Cost by Airline",
                text_auto=".0f",
            )
            fig3.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig3, use_container_width=True)

        st.subheader("Watchdog")

        if not watchdog_summary.empty:
            quality_order = ["Reliable", "Review", "High Risk"]
            watchdog_summary["quality_flag"] = pd.Categorical(
                watchdog_summary["quality_flag"],
                categories=quality_order,
                ordered=True,
            )
            watchdog_summary = watchdog_summary.sort_values("quality_flag")

            fig4 = px.bar(
                watchdog_summary,
                x="quality_flag",
                y="rows",
                color="quality_flag",
                color_discrete_map={
                    "Reliable": "#2e8b57",
                    "Review": "#e0a800",
                    "High Risk": "#d62728",
                },
                title="Watchdog Quality Distribution",
                text_auto=True,
            )
            fig4.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig4, use_container_width=True)

        st.subheader("Airline Wars")

        if airline_a and airline_b and selected_destination:
            wars_df = get_airline_wars(
                bi=bi,
                selected_airlines=selected_airlines,
                airline_a=airline_a,
                airline_b=airline_b,
                selected_destination=selected_destination,
                delay_cost_per_minute=delay_cost_per_minute,
                cancellation_cost=cancellation_cost,
            )

            st.markdown(explain_airline_wars(wars_df, airline_a, airline_b, selected_destination))

            if wars_df.empty:
                st.info("No route comparison data available for the selected airline pair and destination.")
            else:
                st.dataframe(
                    wars_df,
                    use_container_width=True,
                    height=220,
                    column_config={
                        "avg_latency": st.column_config.NumberColumn("Avg Latency", format="%.1f"),
                        "on_time_rate_pct": st.column_config.NumberColumn("On-Time %", format="%.1f"),
                        "cancellation_rate_pct": st.column_config.NumberColumn("Cancellation %", format="%.1f"),
                        "total_cost_eur": st.column_config.NumberColumn("Total Cost (€)", format="%.0f"),
                        "latency_rank": st.column_config.NumberColumn("Latency Rank", format="%d"),
                        "punctuality_rank": st.column_config.NumberColumn("Punctuality Rank", format="%d"),
                        "latency_percent_rank_pct": st.column_config.NumberColumn("Latency Percent Rank", format="%.1f"),
                    },
                )

                wars_long = wars_df[
                    [
                        "airline",
                        "avg_latency",
                        "on_time_rate_pct",
                        "cancellation_rate_pct",
                        "total_cost_eur",
                    ]
                ].melt(
                    id_vars="airline",
                    var_name="metric",
                    value_name="value",
                )

                fig5 = px.bar(
                    wars_long,
                    x="metric",
                    y="value",
                    color="airline",
                    barmode="group",
                    title=f"Airline Wars: {airline_a} vs {airline_b} ({selected_destination})",
                )
                fig5.update_layout(height=450, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig5, use_container_width=True)

        st.subheader("Filtered Data")
        st.dataframe(
            filtered_df,
            use_container_width=True,
            height=360,
            column_config={
                "quality_flag": st.column_config.Column("Quality Flag"),
                "quality_score": st.column_config.NumberColumn("Quality Score", format="%d"),
                "total_cost_eur": st.column_config.NumberColumn("Total Cost (€)", format="%.0f"),
                "delay_cost_eur": st.column_config.NumberColumn("Delay Cost (€)", format="%.0f"),
                "cancellation_cost_eur": st.column_config.NumberColumn("Cancellation Cost (€)", format="%.0f"),
                "avg_latency_airline": st.column_config.NumberColumn("Airline Avg Latency", format="%.1f"),
                "std_latency_airline": st.column_config.NumberColumn("Airline StdDev", format="%.1f"),
                "p95_latency_airline": st.column_config.NumberColumn("Airline P95", format="%.1f"),
                "p99_latency_airline": st.column_config.NumberColumn("Airline P99", format="%.1f"),
            },
        )

with tab2:
    st.subheader("Ask the Analyst")
    render_chat_history()

    suggested_prompt = render_suggested_questions()
    prompt = st.chat_input("Ask a question about the flights data")

    final_prompt = suggested_prompt or prompt

    if final_prompt:
        with st.chat_message("user"):
            st.markdown(final_prompt)

        with st.spinner("Generating SQL and escalating model if needed..."):
            response = bi.ask_with_fallback(final_prompt, selected_chain)

        if response["success"]:
            explanation = explain_chat_result(final_prompt, response["data"])

            with st.chat_message("assistant"):
                st.success(f"Answered with: {response['model']}")
                st.code(response["sql"], language="sql")
                st.info(explanation)
                st.dataframe(response["data"], use_container_width=True, height=260)

                numeric_cols = response["data"].select_dtypes(include="number").columns.tolist()
                if numeric_cols:
                    st.subheader("Auto Chart")
                    st.bar_chart(response["data"][numeric_cols].head(20))

                if response["attempt_errors"]:
                    with st.expander("Earlier failed attempts"):
                        for err in response["attempt_errors"]:
                            st.write(f"- {err}")

            st.session_state.chat_history.append(
                {
                    "question": final_prompt,
                    "success": True,
                    "model": response["model"],
                    "sql": response["sql"],
                    "data": response["data"],
                    "explanation": explanation,
                    "attempt_errors": response["attempt_errors"],
                }
            )
        else:
            with st.chat_message("assistant"):
                st.error(response["error"])
                with st.expander("Model attempts"):
                    for err in response["attempt_errors"]:
                        st.write(f"- {err}")

            st.session_state.chat_history.append(
                {
                    "question": final_prompt,
                    "success": False,
                    "model": None,
                    "sql": response["sql"],
                    "data": None,
                    "error": response["error"],
                    "attempt_errors": response["attempt_errors"],
                }
            )

st.markdown("---")
st.caption(
    "DuckDB + Ollama + Streamlit integrated with model fallback, suggested prompts, business impact, watchdog quality checks, airline rivalry analysis, and result explanations."
)