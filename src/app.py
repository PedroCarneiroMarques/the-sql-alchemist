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
    REQUIRED_COLUMNS,
    SUGGESTED_QUESTIONS,
    add_watchdog_columns,
    build_airline_filter,
    dataframe_to_csv_bytes,
    explain_airline_wars,
    explain_chat_result,
    explain_dashboard,
    get_airline_wars,
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
    return ChatBI(str(path), DEFAULT_MODEL_CHAIN)


def init_session_state() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []


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


def render_chat_history() -> None:
    for i, item in enumerate(st.session_state.chat_history):
        with st.chat_message("user"):
            st.markdown(item["question"])

        with st.chat_message("assistant"):
            if item.get("success"):
                st.caption(f"Model used: {item['model']}")
                st.code(item["sql"], language="sql")

                if item.get("explanation"):
                    st.info(item["explanation"])

                st.dataframe(item["data"], use_container_width=True, height=260)
                render_csv_download(
                    item["data"],
                    label="Download result CSV",
                    filename=f"chat_result_{item.get('model', 'query')}.csv",
                    key=f"history_csv_{i}",
                )
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
            if st.button(question, key=f"suggestion_{i}", use_container_width=True):
                selected_prompt = question

    return selected_prompt


bi = load_bi(str(DATA_PATH))

if bi is None:
    st.error(f"❌ Ficheiro não encontrado: {DATA_PATH}")
    st.stop()

missing_cols = REQUIRED_COLUMNS - set(bi.get_columns())
if missing_cols:
    st.error(f"❌ Missing required columns: {', '.join(sorted(missing_cols))}")
    st.stop()

init_session_state()

st.title("🧠 The Neural Bridge")
st.caption("Natural language analytics powered by Streamlit, DuckDB and Ollama.")

available_models = bi.available_models()
default_chain = [m for m in DEFAULT_MODEL_CHAIN if m in available_models] or DEFAULT_MODEL_CHAIN

all_airlines = bi.dataframe(
    "SELECT DISTINCT airline FROM flights WHERE airline IS NOT NULL ORDER BY airline"
)["airline"].tolist()

all_destinations = bi.dataframe(
    "SELECT DISTINCT destination FROM flights WHERE destination IS NOT NULL ORDER BY destination"
)["destination"].tolist()

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
    airline_b = st.selectbox("Airline B", options=airline_b_options, index=0) if airline_b_options else None

    selected_destination = st.selectbox("Destination", options=all_destinations, index=0) if all_destinations else None

    if st.button("Clear chat history", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

filter_sql, filter_params = build_airline_filter(selected_airlines)

tab1, tab2 = st.tabs(["📊 Visuals", "🗣️ Chat"])

with tab1:
    st.subheader("Real-Time Analytics")

    total_flights = bi.scalar(f"SELECT COUNT(*) FROM flights {filter_sql}", filter_params)
    avg_latency = bi.scalar(f"SELECT AVG(latency_minutes) FROM flights {filter_sql}", filter_params)
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
                st.code(response["sql"], language="sql")
                st.info(explanation)
                st.dataframe(response["data"], use_container_width=True, height=260)
                render_csv_download(
                    response["data"],
                    label="Download result CSV",
                    filename=f"chat_result_{response['model']}.csv",
                    key=f"chat_csv_{len(st.session_state.chat_history)}",
                )

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
    "DuckDB + Ollama + Streamlit integrated with model fallback, suggested prompts, "
    "business impact, watchdog quality checks, airline rivalry analysis, and result explanations."
)
