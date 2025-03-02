from datetime import datetime, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from copilot_more.token_counter import TokenUsage

app = typer.Typer()
console = Console()


def parse_date(date_str: str) -> datetime:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as e:
        raise typer.BadParameter(f"Invalid date format. Use YYYY-MM-DD: {e}")


def handle_model_not_found(usage_tracker: TokenUsage, model: str):
    """Handle cases where a model name isn't found in the database."""
    available_models = usage_tracker.get_available_models()

    if not available_models:
        console.print("[yellow]No token usage data is available yet.[/yellow]")
        return

    console.print(f"[red]No data found for model: '{model}'[/red]")

    # Try to find a similar model
    similar_model = usage_tracker.find_similar_model(model)
    if similar_model:
        console.print(f"[yellow]Did you mean: [bold]{similar_model}[/bold]?[/yellow]")
        console.print(
            f'Try: token-usage last-hours --hours 1 --model "{similar_model}"'
        )

    # Show available models
    console.print("\n[cyan]Available models:[/cyan]")
    for available_model in available_models:
        console.print(f"  • [green]{available_model}[/green]")


def display_usage(
    result: dict,
    period_text: str,
    model: Optional[str] = None,
    usage_tracker: Optional[TokenUsage] = None,
):
    """Display token usage results in a formatted table."""
    if not result or (
        result["total_tokens"] == 0 and model is not None and usage_tracker is not None
    ):
        if model and usage_tracker:
            handle_model_not_found(usage_tracker, model)
        else:
            console.print(
                "[yellow]No usage data found for the specified period.[/yellow]"
            )
        return

    table = Table(title="Token Usage Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    table.add_row("Period", period_text)
    if "model" in result:
        table.add_row("Model", result["model"])
    table.add_row("Input Tokens", f"{result['total_input_tokens']:,}")
    table.add_row("Output Tokens", f"{result['total_output_tokens']:,}")
    table.add_row("Total Tokens", f"{result['total_tokens']:,}")

    console.print(table)


@app.command(name="date-range")
def get_usage_by_date(
    start_date: str = typer.Option(..., "--start-date", help="Start date (YYYY-MM-DD)"),
    end_date: str = typer.Option(..., "--end-date", help="End date (YYYY-MM-DD)"),
    model: Optional[str] = typer.Option(
        ..., "--model", help="Filter by model name (e.g., gpt-4)"
    ),
):
    """Query token usage statistics for a specific date range."""
    start = parse_date(start_date)
    end = parse_date(end_date)

    # Adjust end_date to include the entire day
    end = end + timedelta(days=1) - timedelta(microseconds=1)

    usage_tracker = TokenUsage()
    result = usage_tracker.query_usage(start, end, model)
    display_usage(result, f"{start.date()} to {end.date()}", model, usage_tracker)


@app.command(name="last-hours")
def get_usage_last_hours(
    hours: int = typer.Option(..., "--hours", help="Number of hours to look back"),
    model: Optional[str] = typer.Option(
        ..., "--model", help="Filter by model name (e.g., gpt-4)"
    ),
):
    """Query token usage statistics for the last X hours."""
    if hours <= 0:
        raise typer.BadParameter("Hours must be greater than 0")

    end = datetime.now()
    start = end - timedelta(hours=hours)

    usage_tracker = TokenUsage()
    result = usage_tracker.query_usage(start, end, model)
    display_usage(
        result, f"Last {hours} hour{'s' if hours != 1 else ''}", model, usage_tracker
    )


@app.command(name="list-models")
def list_available_models():
    """List all models with recorded token usage."""
    usage_tracker = TokenUsage()
    available_models = usage_tracker.get_available_models()

    if not available_models:
        console.print("[yellow]No token usage data recorded yet.[/yellow]")
        return

    table = Table(title="Available Models")
    table.add_column("Model Name", style="green")

    for model in available_models:
        table.add_row(model)

    console.print(table)


if __name__ == "__main__":
    app()
