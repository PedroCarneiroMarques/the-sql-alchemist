from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core import (
    ChatBI,
    DATA_PATH,
    DEFAULT_CANCELLATION_COST,
    DEFAULT_DELAY_COST_PER_MINUTE,
    DEFAULT_MODEL_CHAIN,
    SUGGESTED_QUESTIONS,
    add_watchdog_columns,
    aggregate_cost_by_airline,
    explain_airline_wars,
    explain_chat_result,
    explain_dashboard,
    get_airline_wars,
    get_distinct_values,
    query_flight_kpis,
    resolve_model_chain,
    default_airline_selection,
    validate_dataset,
)

console = Console()


def print_dataframe(df: pd.DataFrame, title: str = "Results", max_rows: int = 20) -> None:
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


def print_attempt_errors(attempt_errors: list[str]) -> None:
    if not attempt_errors:
        return
    console.print("[bold yellow]Model attempts:[/bold yellow]")
    for err in attempt_errors:
        console.print(f"- {err}")


def print_kpis(bi: ChatBI, selected_airlines: list[str], filtered_df: pd.DataFrame) -> None:
    kpis = query_flight_kpis(bi, selected_airlines)
    total_cost = float(filtered_df["total_cost_eur"].sum()) if not filtered_df.empty else 0

    console.print(Panel.fit(
        f"Total Flights: {int(kpis['total_flights'] or 0):,}\n"
        f"Avg Latency: {float(kpis['avg_latency'] or 0):.1f} min\n"
        f"Delayed Flights: {int(kpis['delayed_count'] or 0):,}\n"
        f"Total Cost: €{total_cost:,.0f}",
        title="Dashboard KPIs",
        border_style="cyan",
    ))


def run_cli(bi: ChatBI) -> None:
    all_airlines = get_distinct_values(bi, "airline")
    all_destinations = get_distinct_values(bi, "destination")

    selected_chain = resolve_model_chain(bi.available_models())
    selected_airlines = default_airline_selection(all_airlines)

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

            cost_by_airline = aggregate_cost_by_airline(filtered_df)

            print_kpis(bi, selected_airlines, filtered_df)
            console.print(explain_dashboard(filtered_df, cost_by_airline))
            print_dataframe(cost_by_airline, title="Cost of Chaos", max_rows=10)

            watchdog_cols = [
                "flight_id", "airline", "destination", "latency_minutes",
                "quality_flag", "quality_score", "total_cost_eur",
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

            wars_pool = selected_airlines if selected_airlines else all_airlines
            airline_a = wars_pool[0]
            airline_b = wars_pool[1] if len(wars_pool) > 1 else all_airlines[1]
            destination = all_destinations[0]

            wars_df = get_airline_wars(
                bi=bi,
                airline_a=airline_a,
                airline_b=airline_b,
                selected_destination=destination,
                delay_cost_per_minute=DEFAULT_DELAY_COST_PER_MINUTE,
                cancellation_cost=DEFAULT_CANCELLATION_COST,
                selected_airlines=selected_airlines or None,
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


def main() -> None:
    if not DATA_PATH.exists():
        console.print(f"[red]Data file not found: {DATA_PATH}[/red]")
        return

    try:
        bi = ChatBI(str(DATA_PATH))
        validate_dataset(bi)
        run_cli(bi)
    except Exception as exc:
        console.print(f"[red]Startup failed: {exc}[/red]")


if __name__ == "__main__":
    main()
