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

from config import validate_config
from src.i18n import (
    SUPPORTED_LOCALES,
    configure_locale,
    profile_label,
    t,
    watchdog_label,
)
from src.core import (
    ChatBI,
    DATA_PATH,
    DEFAULT_CANCELLATION_COST,
    DEFAULT_DELAY_COST_PER_MINUTE,
    DEFAULT_MODEL_CHAIN,
    DEFAULT_MODEL_PROFILE,
    MODEL_PROFILES,
    SUGGESTED_QUESTIONS,
    DEFAULT_WATCHDOG_SENSITIVITY,
    add_watchdog_columns,
    aggregate_cost_by_airline,
    aggregate_watchdog_summary,
    dataframe_to_csv_bytes,
    explain_airline_comparison,
    explain_chat_result,
    explain_dashboard,
    get_airline_comparison,
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
    page_title="The SQL Alchemist",
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


def init_locale() -> None:
    if "ui_locale" not in st.session_state:
        st.session_state.ui_locale = configure_locale()
        return
    configure_locale(st.session_state.ui_locale)


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
    st.caption(t("chat.model_used", model=item["model"]))
    st.code(item["sql"], language="sql")

    if item.get("explanation"):
        st.info(item["explanation"])

    if df.empty:
        st.warning(t("chat.reload_failed"))
        return

    st.dataframe(df, use_container_width=True, height=260)
    render_csv_download(
        df,
        label=t("chat.download_csv"),
        filename=f"chat_result_{item.get('model', 'query')}.csv",
        key=f"{key_prefix}_csv",
    )
    render_auto_chart(df, key=f"{key_prefix}_chart")


def render_chat_assistant_failure(item: dict) -> None:
    st.error(item.get("error", t("chat.unknown_error")))
    if item.get("attempt_errors"):
        with st.expander(t("chat.model_attempts")):
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
    st.subheader(t("chat.auto_chart"))
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
    st.markdown(f"**{t('chat.suggested_questions')}**")

    selected_prompt = None
    cols = st.columns(2)

    for i, question in enumerate(SUGGESTED_QUESTIONS):
        with cols[i % 2]:
            if st.button(question, key=f"suggestion_{i}", use_container_width=True):
                selected_prompt = question

    return selected_prompt


bi = load_bi(str(DATA_PATH))

try:
    validate_config()
except Exception as exc:
    configure_locale()
    st.error(f"❌ {exc}")
    st.stop()

if bi is None:
    configure_locale()
    st.error(f"❌ {t('app.file_not_found', path=DATA_PATH)}")
    st.stop()

try:
    validate_dataset(bi)
except ValueError as exc:
    st.error(f"❌ {exc}")
    st.stop()

init_session_state()
init_locale()

st.title(f"🧠 {t('app.title')}")
st.caption(t("app.subtitle"))

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
    st.header(t("settings.title"))

    locale_options = list(SUPPORTED_LOCALES)
    current_locale = st.session_state.ui_locale
    locale_index = locale_options.index(current_locale) if current_locale in locale_options else 0
    selected_locale = st.selectbox(
        t("settings.language"),
        options=locale_options,
        index=locale_index,
        format_func=lambda code: t(f"locale.{code}"),
    )
    if selected_locale != current_locale:
        st.session_state.ui_locale = selected_locale
        configure_locale(selected_locale)
        st.rerun()

    st.markdown(f"**{t('settings.model_profile')}**")
    model_profile = st.selectbox(
        t("settings.execution_strategy"),
        options=profile_options,
        index=default_profile_index,
        format_func=profile_label,
    )

    use_custom_chain = st.checkbox(t("settings.custom_model_chain"), value=False)

    if use_custom_chain:
        selected_chain = st.multiselect(
            t("settings.execution_order"),
            options=available_models,
            default=resolve_profile_chain(model_profile, available_models),
        )
        if not selected_chain:
            selected_chain = resolve_profile_chain(model_profile, available_models)
    else:
        selected_chain = resolve_profile_chain(model_profile, available_models)

    st.caption(t("settings.model_chain_help", chain=", ".join(selected_chain)))

    st.subheader(t("settings.business_impact"))

    delay_cost_per_minute = st.number_input(
        t("settings.delay_cost"),
        min_value=0,
        value=DEFAULT_DELAY_COST_PER_MINUTE,
        step=5,
    )

    cancellation_cost = st.number_input(
        t("settings.cancellation_cost"),
        min_value=0,
        value=DEFAULT_CANCELLATION_COST,
        step=10,
    )

    st.subheader(t("settings.watchdog"))

    sensitivity_options = list({"relaxed", "normal", "strict"})
    default_sensitivity_index = (
        sensitivity_options.index(DEFAULT_WATCHDOG_SENSITIVITY)
        if DEFAULT_WATCHDOG_SENSITIVITY in sensitivity_options
        else sensitivity_options.index("normal")
    )

    watchdog_sensitivity = st.selectbox(
        t("settings.sensitivity"),
        options=sensitivity_options,
        index=default_sensitivity_index,
        format_func=watchdog_label,
    )

    st.divider()
    st.header(t("settings.global_filters"))

    default_airlines = default_airline_selection(all_airlines)

    selected_airlines = st.multiselect(
        t("settings.airlines"),
        options=all_airlines,
        default=default_airlines,
    )

    st.divider()
    st.header(t("settings.airline_comparison"))

    wars_airlines = selected_airlines if selected_airlines else all_airlines

    if wars_airlines:
        airline_a = st.selectbox(t("settings.airline_a"), options=wars_airlines, index=0)
    else:
        airline_a = None

    airline_b_candidates = [a for a in wars_airlines if a != airline_a]
    airline_b_options = airline_b_candidates if airline_b_candidates else wars_airlines
    airline_b = st.selectbox(t("settings.airline_b"), options=airline_b_options, index=0) if airline_b_options else None

    selected_destination = (
        st.selectbox(t("settings.destination"), options=all_destinations, index=0)
        if all_destinations
        else None
    )

    if st.button(t("settings.clear_chat"), use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

tab1, tab2 = st.tabs([f"📊 {t('tab.visuals')}", f"🗣️ {t('tab.chat')}"])

with tab1:
    st.subheader(t("visuals.real_time"))

    kpis = query_flight_kpis(bi, selected_airlines)

    filtered_df = add_watchdog_columns(
        bi,
        selected_airlines=selected_airlines,
        delay_cost_per_minute=delay_cost_per_minute,
        cancellation_cost=cancellation_cost,
        watchdog_sensitivity=watchdog_sensitivity,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric(t("visuals.total_flights"), f"{int(kpis['total_flights'] or 0):,}")
    c2.metric(t("visuals.avg_latency"), f"{float(kpis['avg_latency'] or 0):.1f} min")
    c3.metric(t("visuals.delayed_flights"), f"{int(kpis['delayed_count'] or 0):,}")

    costs = sum_cost_columns(filtered_df)

    c4, c5, c6 = st.columns(3)
    c4.metric(t("visuals.total_cost"), f"{costs['total_cost']:,.0f}")
    c5.metric(t("visuals.delay_cost"), f"{costs['delay_cost']:,.0f}")
    c6.metric(t("visuals.cancellation_cost"), f"{costs['cancellation_cost']:,.0f}")

    reliable_count = int((filtered_df["quality_flag"] == "Reliable").sum()) if not filtered_df.empty else 0
    review_count = int((filtered_df["quality_flag"] == "Review").sum()) if not filtered_df.empty else 0
    high_risk_count = int((filtered_df["quality_flag"] == "High Risk").sum()) if not filtered_df.empty else 0

    c7, c8, c9 = st.columns(3)
    c7.metric(t("visuals.reliable_rows"), f"{reliable_count:,}")
    c8.metric(t("visuals.review_rows"), f"{review_count:,}")
    c9.metric(t("visuals.high_risk_rows"), f"{high_risk_count:,}")

    cost_by_airline = aggregate_cost_by_airline(filtered_df)
    watchdog_summary = aggregate_watchdog_summary(filtered_df)

    st.subheader(t("visuals.result_explanation"))
    st.markdown(explain_dashboard(filtered_df, cost_by_airline))

    if filtered_df.empty:
        st.warning(t("visuals.no_data"))
    else:
        col_plot1, col_plot2 = st.columns(2)

        with col_plot1:
            fig = px.line(
                filtered_df,
                x="flight_id",
                y="latency_minutes",
                color="airline",
                title=t("visuals.latency_timeline"),
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
                st.info(t("visuals.no_delayed_flights"))
            else:
                fig2 = px.bar(
                    impacted_df,
                    x="airline",
                    y="total_latency",
                    color="flights",
                    title=t("visuals.impacted_airlines"),
                )
                fig2.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig2, use_container_width=True)

        st.subheader(t("visuals.disruption_cost"))

        if cost_by_airline.empty:
            st.info(t("visuals.no_cost_impact"))
        else:
            render_csv_download(
                cost_by_airline,
                label=t("export.download_cost_csv"),
                filename="cost_by_airline.csv",
                key="export_cost_by_airline",
            )
            fig3 = px.bar(
                cost_by_airline,
                x="airline",
                y="total_cost_eur",
                color="total_cost_eur",
                title=t("visuals.estimated_cost_by_airline"),
                text_auto=".0f",
            )
            fig3.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig3, use_container_width=True)

        st.subheader(t("settings.watchdog"))

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
                title=t("visuals.watchdog_distribution"),
                text_auto=True,
            )
            fig4.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig4, use_container_width=True)

        st.subheader(t("settings.airline_comparison"))

        if airline_a and airline_b and selected_destination:
            wars_df = get_airline_comparison(
                bi=bi,
                airline_a=airline_a,
                airline_b=airline_b,
                selected_destination=selected_destination,
                delay_cost_per_minute=delay_cost_per_minute,
                cancellation_cost=cancellation_cost,
                selected_airlines=selected_airlines or None,
            )

            st.markdown(explain_airline_comparison(wars_df, airline_a, airline_b, selected_destination))

            if wars_df.empty:
                st.info(t("visuals.no_route_comparison"))
            else:
                render_csv_download(
                    wars_df,
                    label=t("export.download_comparison_csv"),
                    filename=f"airline_comparison_{airline_a}_vs_{airline_b}_{selected_destination}.csv",
                    key="export_airline_comparison",
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
                    title=t(
                        "visuals.comparison_chart_title",
                        airline_a=airline_a,
                        airline_b=airline_b,
                        destination=selected_destination,
                    ),
                )
                fig5.update_layout(height=450, margin=dict(l=20, r=20, t=50, b=20))
                st.plotly_chart(fig5, use_container_width=True)

        st.subheader(t("visuals.filtered_data"))
        export_cols = st.columns(2)
        with export_cols[0]:
            render_csv_download(
                filtered_df,
                label=t("export.download_filtered_csv"),
                filename="filtered_flights.csv",
                key="export_filtered_data",
            )
        with export_cols[1]:
            render_csv_download(
                watchdog_summary,
                label=t("export.download_watchdog_csv"),
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
    st.subheader(t("chat.ask_analyst"))
    render_chat_history()

    suggested_prompt = render_suggested_questions()
    prompt = st.chat_input(t("chat.input_placeholder"))

    final_prompt = suggested_prompt or prompt

    if final_prompt:
        with st.chat_message("user"):
            st.markdown(final_prompt)

        with st.spinner("Generating SQL and escalating model if needed..."):
            response = bi.ask_with_fallback(final_prompt, selected_chain)

        if response["success"]:
            explanation = explain_chat_result(final_prompt, response["data"])

            with st.chat_message("assistant"):
                st.success(t("chat.answered_with", model=response["model"]))
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
                    with st.expander(t("chat.earlier_failed_attempts")):
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
st.caption(t("app.footer"))
