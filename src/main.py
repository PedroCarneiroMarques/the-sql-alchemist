from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import validate_config
from src.i18n import configure_locale, t, watchdog_label
from src.core import (
    ChatBI,
    DATA_PATH,
    DEFAULT_CANCELLATION_COST,
    DEFAULT_DELAY_COST_PER_MINUTE,
    DEFAULT_MODEL_PROFILE,
    MODEL_PROFILES,
    SUGGESTED_QUESTIONS,
    DEFAULT_WATCHDOG_SENSITIVITY,
    add_watchdog_columns,
    aggregate_cost_by_airline,
    explain_airline_wars,
    explain_chat_result,
    explain_dashboard,
    get_airline_wars,
    get_distinct_values,
    query_flight_kpis,
    resolve_profile_chain,
    default_airline_selection,
    normalize_model_profile,
    normalize_watchdog_sensitivity,
    validate_dataset,
    write_dataframe_csv,
)

console = Console()
EXPORTS_DIR = PROJECT_ROOT / "exports"


@dataclass
class CliSession:
    selected_airlines: list[str]
    selected_chain: list[str]
    active_profile: str = DEFAULT_MODEL_PROFILE
    watchdog_sensitivity: str = DEFAULT_WATCHDOG_SENSITIVITY
    last_export_df: pd.DataFrame | None = None
    last_export_name: str = "query_result"


def print_dataframe(df: pd.DataFrame, title: str = "Results", max_rows: int = 20) -> None:
    if df is None or df.empty:
        console.print(f"[yellow]{t('cli.no_rows')}[/yellow]")
        return

    preview = df.head(max_rows).copy()
    table = Table(title=title, show_lines=False)

    for col in preview.columns:
        table.add_column(str(col), overflow="fold")

    for _, row in preview.iterrows():
        table.add_row(*[str(x) for x in row.tolist()])

    console.print(table)

    if len(df) > max_rows:
        console.print(f"[dim]{t('cli.showing_rows', shown=max_rows, total=len(df))}[/dim]")


def print_attempt_errors(attempt_errors: list[str]) -> None:
    if not attempt_errors:
        return
    console.print(f"[bold yellow]{t('cli.model_attempts')}:[/bold yellow]")
    for err in attempt_errors:
        console.print(f"- {err}")


def print_kpis(bi: ChatBI, selected_airlines: list[str], filtered_df: pd.DataFrame) -> None:
    kpis = query_flight_kpis(bi, selected_airlines)
    total_cost = float(filtered_df["total_cost_eur"].sum()) if not filtered_df.empty else 0

    console.print(Panel.fit(
        f"{t('cli.total_flights')}: {int(kpis['total_flights'] or 0):,}\n"
        f"{t('cli.avg_latency')}: {float(kpis['avg_latency'] or 0):.1f} min\n"
        f"{t('cli.delayed_flights')}: {int(kpis['delayed_count'] or 0):,}\n"
        f"{t('cli.total_cost')}: €{total_cost:,.0f}",
        title=t("cli.dashboard_kpis"),
        border_style="cyan",
    ))


def print_numbered_options(options: list[str], title: str) -> None:
    console.print(f"[bold]{title}[/bold]")
    for index, option in enumerate(options, start=1):
        console.print(f"  {index}. {option}")


def remember_export(session: CliSession, df: pd.DataFrame, name: str) -> None:
    if df is not None and not df.empty:
        session.last_export_df = df
        session.last_export_name = name


def parse_selection(raw: str, options: list[str]) -> list[str]:
    value = raw.strip()
    if not value or value.lower() == "all":
        return list(options)
    if value.lower() == "none":
        return []

    selected: list[str] = []
    for part in re.split(r"[,;]", value):
        token = part.strip()
        if not token:
            continue
        if token.isdigit():
            index = int(token) - 1
            if 0 <= index < len(options):
                selected.append(options[index])
            continue
        matches = [option for option in options if option.lower() == token.lower()]
        if matches:
            selected.append(matches[0])
    return list(dict.fromkeys(selected))


def prompt_list_selection(options: list[str], title: str, allow_multiple: bool = True) -> list[str]:
    if not options:
        return []

    print_numbered_options(options, title)
    hint = t("cli.choose_multi") if allow_multiple else t("cli.choose")
    extra = t("cli.choose_all_hint") if allow_multiple else ""
    raw = Prompt.ask(f"{hint}{extra}", default="1" if not allow_multiple else "")
    selected = parse_selection(raw, options)
    if allow_multiple:
        return selected
    return selected[:1]


def prompt_single_selection(options: list[str], title: str, default_index: int = 0) -> str | None:
    if not options:
        return None
    print_numbered_options(options, title)
    default = str(default_index + 1)
    raw = Prompt.ask(t("cli.choose"), default=default)
    selected = parse_selection(raw, options)
    return selected[0] if selected else options[default_index]


def handle_filter(session: CliSession, all_airlines: list[str]) -> None:
    current = ", ".join(session.selected_airlines) if session.selected_airlines else t("cli.all_airlines")
    console.print(f"[dim]{t('cli.current_filter')}:[/dim] {current}")
    session.selected_airlines = prompt_list_selection(all_airlines, t("cli.select_airlines"))
    if session.selected_airlines:
        console.print(f"[green]{t('cli.filter_updated')}:[/green] {', '.join(session.selected_airlines)}")
    else:
        console.print(f"[green]{t('cli.filter_cleared')}:[/green] {t('cli.all_airlines')}")


def handle_profile(session: CliSession, available_models: list[str], args: list[str]) -> None:
    if not args:
        console.print(f"[bold]{t('cli.active_profile')}:[/bold] {session.active_profile}")
        console.print(f"[bold]{t('cli.active_chain')}:[/bold] {', '.join(session.selected_chain)}")
        console.print(f"[bold]{t('cli.available_profiles')}:[/bold]")
        for name, chain in MODEL_PROFILES.items():
            marker = t("cli.active") if name == session.active_profile else ""
            console.print(f"  {name}{marker}: {', '.join(chain)}")
        console.print(t("cli.profile_usage"))
        return

    profile = args[0].lower()
    try:
        session.active_profile = normalize_model_profile(profile)
        session.selected_chain = resolve_profile_chain(session.active_profile, available_models)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    console.print(
        f"[green]{t('cli.profile_set', profile=profile)}:[/green] {', '.join(session.selected_chain)}"
    )


def handle_watchdog(session: CliSession, args: list[str]) -> None:
    if not args:
        console.print(f"[bold]{t('cli.active_watchdog')}:[/bold] {session.watchdog_sensitivity}")
        for name in ("relaxed", "normal", "strict"):
            marker = t("cli.active") if name == session.watchdog_sensitivity else ""
            console.print(f"  {name}{marker}: {watchdog_label(name)}")
        console.print(t("cli.watchdog_usage"))
        return

    try:
        session.watchdog_sensitivity = normalize_watchdog_sensitivity(args[0])
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    console.print(t("cli.watchdog_set", value=session.watchdog_sensitivity))


def handle_export(session: CliSession, filename: str | None = None) -> None:
    if session.last_export_df is None or session.last_export_df.empty:
        console.print(f"[yellow]{t('cli.nothing_to_export')}[/yellow]")
        return

    if filename:
        output_name = filename if filename.endswith(".csv") else f"{filename}.csv"
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_name = f"{session.last_export_name}_{timestamp}.csv"

    output_path = EXPORTS_DIR / output_name
    try:
        write_dataframe_csv(session.last_export_df, output_path)
        console.print(f"[green]{t('cli.exported_rows', rows=len(session.last_export_df))}[/green] {output_path}")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")


def handle_wars(
    bi: ChatBI,
    session: CliSession,
    all_airlines: list[str],
    all_destinations: list[str],
    args: list[str],
) -> None:
    if len(all_airlines) < 2 or not all_destinations:
        console.print(f"[yellow]{t('cli.not_enough_wars_data')}[/yellow]")
        return

    wars_pool = session.selected_airlines if session.selected_airlines else all_airlines

    if len(args) >= 3:
        airline_a, airline_b, destination = args[0], args[1], args[2]
    else:
        airline_a = prompt_single_selection(wars_pool, t("settings.airline_a"), default_index=0)
        airline_b_options = [airline for airline in wars_pool if airline != airline_a]
        if not airline_b_options:
            airline_b_options = [airline for airline in all_airlines if airline != airline_a]
        airline_b = prompt_single_selection(airline_b_options, t("settings.airline_b"), default_index=0)
        destination = prompt_single_selection(all_destinations, t("settings.destination"), default_index=0)

    if not airline_a or not airline_b or not destination:
        console.print(f"[yellow]{t('cli.wars_cancelled')}[/yellow]")
        return

    wars_df = get_airline_wars(
        bi=bi,
        airline_a=airline_a,
        airline_b=airline_b,
        selected_destination=destination,
        delay_cost_per_minute=DEFAULT_DELAY_COST_PER_MINUTE,
        cancellation_cost=DEFAULT_CANCELLATION_COST,
        selected_airlines=session.selected_airlines or None,
    )

    console.print(explain_airline_wars(wars_df, airline_a, airline_b, destination))
    print_dataframe(wars_df, title=t("settings.airline_wars"), max_rows=10)
    remember_export(session, wars_df, "airline_wars")
    console.print(f"[dim]{t('cli.export_tip')}[/dim]")


def handle_dashboard(bi: ChatBI, session: CliSession) -> None:
    filtered_df = add_watchdog_columns(
        bi,
        selected_airlines=session.selected_airlines,
        delay_cost_per_minute=DEFAULT_DELAY_COST_PER_MINUTE,
        cancellation_cost=DEFAULT_CANCELLATION_COST,
        watchdog_sensitivity=session.watchdog_sensitivity,
    )
    cost_by_airline = aggregate_cost_by_airline(filtered_df)

    print_kpis(bi, session.selected_airlines, filtered_df)
    console.print(explain_dashboard(filtered_df, cost_by_airline))
    print_dataframe(cost_by_airline, title=t("cli.cost_of_chaos"), max_rows=10)

    watchdog_cols = [
        "flight_id", "airline", "destination", "latency_minutes",
        "quality_flag", "quality_score", "total_cost_eur",
    ]
    existing_watchdog_cols = [c for c in watchdog_cols if c in filtered_df.columns]
    watchdog_preview = filtered_df[existing_watchdog_cols]
    print_dataframe(watchdog_preview, title=t("cli.watchdog_preview"), max_rows=15)

    remember_export(session, filtered_df, "dashboard")
    console.print(f"[dim]{t('cli.export_dashboard_tip')}[/dim]")


def run_cli(bi: ChatBI) -> None:
    all_airlines = get_distinct_values(bi, "airline")
    all_destinations = get_distinct_values(bi, "destination")

    session = CliSession(
        selected_airlines=default_airline_selection(all_airlines),
        selected_chain=resolve_profile_chain(DEFAULT_MODEL_PROFILE, bi.available_models()),
        active_profile=DEFAULT_MODEL_PROFILE,
        watchdog_sensitivity=DEFAULT_WATCHDOG_SENSITIVITY,
    )

    console.print(Panel.fit(
        t("cli.ready"),
        title=t("cli.title"),
        border_style="green",
    ))
    filter_label = ", ".join(session.selected_airlines) if session.selected_airlines else t("cli.all_airlines")
    console.print(
        f"[dim]{t('cli.active_profile')}:[/dim] {session.active_profile} | "
        f"[dim]{t('cli.watchdog')}:[/dim] {session.watchdog_sensitivity} | "
        f"[dim]{t('cli.airline_filter')}:[/dim] {filter_label}"
    )

    while True:
        user_input = Prompt.ask(f"[bold blue]{t('cli.prompt')}[/bold blue]").strip()

        if user_input.lower() in {"quit", "exit", "q", "/quit"}:
            console.print(f"[red]{t('cli.session_closed')}[/red]")
            break

        if user_input == "/help":
            console.print(t("cli.help"))
            continue

        if user_input == "/suggest":
            for i, q in enumerate(SUGGESTED_QUESTIONS, start=1):
                console.print(f"{i}. {q}")
            continue

        if user_input == "/models":
            console.print(f"{t('cli.active_profile')}: {session.active_profile}")
            console.print(f"{t('cli.active_model_chain')}:")
            for model in session.selected_chain:
                console.print(f"- {model}")
            continue

        if user_input == "/filter":
            handle_filter(session, all_airlines)
            continue

        if user_input == "/dashboard":
            handle_dashboard(bi, session)
            continue

        if user_input.startswith("/profile"):
            args = user_input.split()[1:]
            handle_profile(session, bi.available_models(), args)
            continue

        if user_input.startswith("/watchdog"):
            args = user_input.split()[1:]
            handle_watchdog(session, args)
            continue

        if user_input.startswith("/wars"):
            args = user_input.split()[1:]
            handle_wars(bi, session, all_airlines, all_destinations, args)
            continue

        if user_input.startswith("/export"):
            parts = user_input.split(maxsplit=1)
            filename = parts[1].strip() if len(parts) > 1 else None
            handle_export(session, filename)
            continue

        response = bi.ask_with_fallback(user_input, session.selected_chain)

        if response["success"]:
            console.print(
                Panel.fit(
                    response["sql"],
                    title=t("cli.sql_via", model=response["model"]),
                    border_style="magenta",
                )
            )
            console.print(explain_chat_result(user_input, response["data"]))
            print_dataframe(response["data"], title=t("cli.query_result"), max_rows=20)
            remember_export(session, response["data"], "query_result")
            console.print(f"[dim]{t('cli.export_tip')}[/dim]")
            print_attempt_errors(response["attempt_errors"])
        else:
            console.print(f"[red]{response['error']}[/red]")
            print_attempt_errors(response["attempt_errors"])


def main() -> None:
    parser = argparse.ArgumentParser(description="The SQL Alchemist CLI")
    parser.add_argument("--lang", choices=["en", "pt"], default=None, help="UI language (en or pt)")
    args = parser.parse_args()
    configure_locale(args.lang)

    try:
        validate_config()
    except Exception as exc:
        console.print(f"[red]{t('cli.startup_failed', error=exc)}[/red]")
        return

    try:
        bi = ChatBI(str(DATA_PATH))
        validate_dataset(bi)
        run_cli(bi)
    except Exception as exc:
        console.print(f"[red]{t('cli.startup_failed', error=exc)}[/red]")


if __name__ == "__main__":
    main()
