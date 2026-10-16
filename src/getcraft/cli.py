"""GetCraft command line interface."""

import typer
from rich.console import Console

app = typer.Typer(no_args_is_help=True)
console = Console(markup=False)


@app.command()
def status() -> None:
    """Show the current implementation status."""
    console.print("GetCraft scaffold ready; downloads are not implemented.")
