from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core import (
    ChatBI,
    DATA_PATH,
    DEFAULT_CANCELLATION_COST,
    DEFAULT_DELAY_COST_PER_MINUTE,
    DEFAULT_MODEL_CHAIN,
    DEFAULT_MODEL_PROFILE,
    MODEL_PROFILE_LABELS,
    MODEL_PROFILES,
    SUGGESTED_QUESTIONS,
    WATCHDOG_SENSITIVITY_LABELS,
    DEFAULT_WATCHDOG_SENSITIVITY,
    add_watchdog_columns,
    aggregate_cost_by_airline,
    aggregate_watchdog_summary,
    dataframe_to_csv_bytes,
    explain_airline_wars,
    explain_chat_result,
    explain_dashboard,
    get_airline_wars,
    get_distinct_values,
    query_flight_kpis,
    recommend_chart,
    resolve_profile_chain,
    run_stored_chat_sql,
    default_airline_selection,
    sum_cost_columns,
    validate_dataset,
)

st.set_page_config(
    page_title="Neural Flight Bridge",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource(show_spinner=False)
def load_bi(csv_path: str) -> ChatBI | None:
    path = Path(csv_path)
    if not path.exists():
        return None
    return ChatBI(str(path))


def init_session_state() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
        return
    st.session_state.chat_history = compact_chat_history(st.session_state.chat_history)


def compact_chat_history(history: list[dict]) -> list[dict]:
    compacted: list[dict] = []
    for item in history:
        entry = {key: value for key, value in item.items() if key != "data"}
        if entry.get("success") and "row_count" not in entry:
            data = item.get("data")
            if data is not None:
                entry["row_count"] = len(data)
        compacted.append(entry)
    return compacted


def build_chat_history_entry(
    question: str,
    response: dict,
    explanation: str = "",
) -> dict:
    entry = {
        "question": question,
        "success": response["success"],
        "model": response.get("model"),
        "sql": response.get("sql", ""),
        "attempt_errors": response.get("attempt_errors", []),
    }
    if response["success"]:
        entry["explanation"] = explanation
        entry["row_count"] = len(response["data"])
    else:
        entry["error"] = response.get("error", "Unknown error")
    return entry


@st.cache_data(show_spinner=False)
def load_chat_result_data(csv_path: str, sql: str) -> pd.DataFrame:
    bi_instance = load_bi(csv_path)
    if bi_instance is None or not sql:
        return pd.DataFrame()
    try:
        return run_stored_chat_sql(bi_instance, sql)
    except ValueError:
        return pd.DataFrame()


def render_chat_assistant_success(item: dict, df: pd.DataFrame, key_prefix: str) -> None:
    st.caption(f"Model used: {item['model']}")
    st.code(item["sql"], language="sql")

    if item.get("explanation"):
        st.info(item["explanation"])

    if df.empty:
        st.warning("Could not reload stored query results.")
        return

    st.dataframe(df, use_container_width=True, height=260)
    render_csv_download(
        df,
        label="Download result CSV",
        filename=f"chat_result_{item.get('model', 'query')}.csv",
        key=f"{key_prefix}_csv",
    )
    render_auto_chart(df, key=f"{key_prefix}_chart")


def render_chat_assistant_failure(item: dict) -> None:
    st.error(item.get("error", "Unknown error"))
    if item.get("attempt_errors"):
        with st.expander("Model attempts"):
            for err in item["attempt_errors"]:
                st.write(f"- {err}")


def render_chat_history() -> None:
    for i, item in enumerate(st.session_state.chat_history):
        with st.chat_message("user"):
            st.markdown(item["question"])

        with st.chat_message("assistant"):
            if item.get("success"):
                df = load_chat_result_data(str(DATA_PATH), item.get("sql", ""))
                render_chat_assistant_success(item, df, key_prefix=f"history_{i}")
            else:
                render_chat_assistant_failure(item)


def render_csv_download(df: pd.DataFrame, label: str, filename: str, key: str) -> None:
    if df is None or df.empty:
        return
    st.download_button(
        label=label,
        data=dataframe_to_csv_bytes(df),
        file_name=filename,
        mime="text/csv",
        key=key,
        use_container_width=True,
    )


def render_auto_chart(df: pd.DataFrame, key: str) -> None:
    spec = recommend_chart(df)
    if spec.kind == "none" or not spec.x or not spec.y:
        return

    preview = df.head(20)
    st.subheader("Auto Chart")
    st.caption(spec.title)

    if spec.kind == "bar":
        fig = px.bar(preview, x=spec.x, y=spec.y, color=spec.color, title=spec.title)
    elif spec.kind == "line":
        fig = px.line(preview, x=spec.x, y=spec.y, color=spec.color, title=spec.title)
    else:
        fig = px.pie(preview, names=spec.x, values=spec.y, title=spec.title)

    fig.update_layout(height=400, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True, key=key)


def render_suggested_questions() -> Optional[str]:
    st.markdown("**Suggested Questions**")

    selected_prompt = None
    cols = st.columns(2)

    for i, question in enumerate(SUGGESTED_QUESTIONS):
        with cols[i % 2]:
            if st.button(question, key=f"suggestion_{i}", use_container_width=True):
                selected_prompt = question

    return selected_prompt


bi = load_bi(str(DATA_PATH))

if bi is None:
    st.error(f"❌ Ficheiro não encontrado: {DATA_PATH}")
    st.stop()

try:
    validate_dataset(bi)
except ValueError as exc:
    st.error(f"❌ {exc}")
    st.stop()

init_session_state()

st.title("🧠 The Neural Bridge")
st.caption("Natural language analytics powered by Streamlit, DuckDB and Ollama.")

available_models = bi.available_models() or DEFAULT_MODEL_CHAIN
profile_options = list(MODEL_PROFILES.keys())
default_profile_index = (
    profile_options.index(DEFAULT_MODEL_PROFILE)
    if DEFAULT_MODEL_PROFILE in profile_options
    else profile_options.index("balanced")
)

all_airlines = get_distinct_values(bi, "airline")
all_destinations = get_distinct_values(bi, "destination")

with st.sidebar:
    st.header("Settings")

    st.markdown("**Model profile**")
    model_profile = st.selectbox(
        "Execution strategy",
        options=profile_options,
        index=default_profile_index,
        format_func=lambda key: MODEL_PROFILE_LABELS.get(key, key),
    )

    use_custom_chain = st.checkbox("Custom model chain", value=False)

    if use_custom_chain:
        selected_chain = st.multiselect(
            "Execution order",
            options=available_models,
            default=resolve_profile_chain(model_profile, available_models),
        )
        if not selected_chain:
            selected_chain = resolve_profile_chain(model_profile, available_models)
    else:
        selected_chain = resolve_profile_chain(model_profile, available_models)

    st.caption(
        "The app tries models in order, then falls back to keyword SQL if needed.\n\n"
        f"Active chain: {', '.join(selected_chain)}"
    )

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

    st.subheader("Watchdog")

    sensitivity_options = list(WATCHDOG_SENSITIVITY_LABELS.keys())
    default_sensitivity_index = (
        sensitivity_options.index(DEFAULT_WATCHDOG_SENSITIVITY)
        if DEFAULT_WATCHDOG_SENSITIVITY in sensitivity_options
        else sensitivity_options.index("normal")
    )

    watchdog_sensitivity = st.selectbox(
        "Sensitivity",
        options=sensitivity_options,
        index=default_sensitivity_index,
        format_func=lambda key: WATCHDOG_SENSITIVITY_LABELS.get(key, key),
    )

    st.divider()
    st.header("Global Filters")

    default_airlines = default_airline_selection(all_airlines)

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
    airline_b = st.selectbox("Airline B", options=airline_b_options, index=0) if airline_b_options else None

    selected_destination = st.selectbox("Destination", options=all_destinations, index=0) if all_destinations else None

    if st.button("Clear chat history", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

tab1, tab2 = st.tabs(["📊 Visuals", "🗣️ Chat"])

with tab1:
    st.subheader("Real-Time Analytics")

    kpis = query_flight_kpis(bi, selected_airlines)

    filtered_df = add_watchdog_columns(
        bi,
        selected_airlines=selected_airlines,
        delay_cost_per_minute=delay_cost_per_minute,
        cancellation_cost=cancellation_cost,
        watchdog_sensitivity=watchdog_sensitivity,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Flights", f"{int(kpis['total_flights'] or 0):,}")
    c2.metric("Avg Latency", f"{float(kpis['avg_latency'] or 0):.1f} min")
    c3.metric("Delayed Flights", f"{int(kpis['delayed_count'] or 0):,}")

    costs = sum_cost_columns(filtered_df)

    c4, c5, c6 = st.columns(3)
    c4.metric("Total Cost (€)", f"{costs['total_cost']:,.0f}")
    c5.metric("Delay Cost (€)", f"{costs['delay_cost']:,.0f}")
    c6.metric("Cancellation Cost (€)", f"{costs['cancellation_cost']:,.0f}")

    reliable_count = int((filtered_df["quality_flag"] == "Reliable").sum()) if not filtered_df.empty else 0
    review_count = int((filtered_df["quality_flag"] == "Review").sum()) if not filtered_df.empty else 0
    high_risk_count = int((filtered_df["quality_flag"] == "High Risk").sum()) if not filtered_df.empty else 0

    c7, c8, c9 = st.columns(3)
    c7.metric("Reliable Rows", f"{reliable_count:,}")
    c8.metric("Review Rows", f"{review_count:,}")
    c9.metric("High Risk Rows", f"{high_risk_count:,}")

    cost_by_airline = aggregate_cost_by_airline(filtered_df)
    watchdog_summary = aggregate_watchdog_summary(filtered_df)

    st.subheader("Result Explanation")
    st.markdown(explain_dashboard(filtered_df, cost_by_airline))

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
            render_csv_download(
                cost_by_airline,
                label="Download cost by airline CSV",
                filename="cost_by_airline.csv",
                key="export_cost_by_airline",
            )
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
                airline_a=airline_a,
                airline_b=airline_b,
                selected_destination=selected_destination,
                delay_cost_per_minute=delay_cost_per_minute,
                cancellation_cost=cancellation_cost,
                selected_airlines=selected_airlines or None,
            )

            st.markdown(explain_airline_wars(wars_df, airline_a, airline_b, selected_destination))

            if wars_df.empty:
                st.info("No route comparison data available for the selected airline pair and destination.")
            else:
                render_csv_download(
                    wars_df,
                    label="Download Airline Wars CSV",
                    filename=f"airline_wars_{airline_a}_vs_{airline_b}_{selected_destination}.csv",
                    key="export_airline_wars",
                )
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
                    ["airline", "avg_latency", "on_time_rate_pct", "cancellation_rate_pct", "total_cost_eur"]
                ].melt(id_vars="airline", var_name="metric", value_name="value")

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
        export_cols = st.columns(2)
        with export_cols[0]:
            render_csv_download(
                filtered_df,
                label="Download filtered data CSV",
                filename="filtered_flights.csv",
                key="export_filtered_data",
            )
        with export_cols[1]:
            render_csv_download(
                watchdog_summary,
                label="Download watchdog summary CSV",
                filename="watchdog_summary.csv",
                key="export_watchdog_summary",
            )
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
                render_chat_assistant_success(
                    {
                        "model": response["model"],
                        "sql": response["sql"],
                        "explanation": explanation,
                    },
                    response["data"],
                    key_prefix=f"live_{len(st.session_state.chat_history)}",
                )

                if response["attempt_errors"]:
                    with st.expander("Earlier failed attempts"):
                        for err in response["attempt_errors"]:
                            st.write(f"- {err}")

            st.session_state.chat_history.append(
                build_chat_history_entry(final_prompt, response, explanation)
            )
        else:
            with st.chat_message("assistant"):
                render_chat_assistant_failure(response)

            st.session_state.chat_history.append(build_chat_history_entry(final_prompt, response))

st.markdown("---")
st.caption(
    "DuckDB + Ollama + Streamlit integrated with model fallback, suggested prompts, "
    "business impact, watchdog quality checks, airline rivalry analysis, and result explanations."
)
