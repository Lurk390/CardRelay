import json
from pathlib import Path
from typing import Annotated

import typer

from card_relay import __version__
from card_relay.config import load_settings
from card_relay.exceptions import CardRelayError
from card_relay.paths import config_path, data_directory
from card_relay.sources.collectr.csv_source import CollectrCsvSource
from card_relay.storage.database import create_database
from card_relay.storage.repositories import SnapshotRepository

app = typer.Typer(help="Sync your trading card collection from one source of truth to every app.")
collectr_app = typer.Typer(help="Collectr ingestion and browser-session commands.")
config_app = typer.Typer(help="Configuration commands.")
mappings_app = typer.Typer(help="Persistent mapping review commands.")
app.add_typer(collectr_app, name="collectr")
app.add_typer(config_app, name="config")
app.add_typer(mappings_app, name="mappings")


def _emit(payload: dict[str, object], as_json: bool) -> None:
    typer.echo(
        json.dumps(payload, indent=2, default=str)
        if as_json
        else "\n".join(f"{key}: {value}" for key, value in payload.items())
    )


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def doctor(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    _emit(
        {
            "status": "ok",
            "data_directory": str(directory),
            "storage_writable": True,
            "browser_integration": "scaffolded",
            "dex_integration": "scaffolded",
        },
        as_json,
    )


@config_app.command("path")
def show_config_path() -> None:
    typer.echo(config_path())


@config_app.command("show")
def show_config(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    _emit(load_settings().model_dump(mode="json"), as_json)


def _csv_source(csv_path: Path) -> CollectrCsvSource:
    return CollectrCsvSource(csv_path, load_settings().collectr.csv.column_aliases)


@collectr_app.command("validate")
def validate(
    csv_path: Annotated[Path, typer.Option("--csv", exists=True, dir_okay=False)],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    result = _csv_source(csv_path).validate_access()
    _emit(result.model_dump(), as_json)
    if not result.valid:
        raise typer.Exit(2)


@collectr_app.command("import")
def import_collection(
    csv_path: Annotated[Path | None, typer.Option("--csv", exists=True, dir_okay=False)] = None,
    browser: Annotated[bool, typer.Option("--browser")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if browser or csv_path is None:
        raise typer.BadParameter("browser ingestion is scaffolded for Milestone 2; provide --csv")
    collection = _csv_source(csv_path).load_collection()
    _emit(
        {
            "source_method": "csv",
            "completeness": collection.completeness,
            "unique_entries": len(collection.entries),
            "total_quantity": collection.total_quantity,
            "warnings": collection.warnings,
        },
        as_json,
    )


@collectr_app.command("snapshot")
def snapshot(
    csv_path: Annotated[Path | None, typer.Option("--csv", exists=True, dir_okay=False)] = None,
    browser: Annotated[bool, typer.Option("--browser")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if browser or csv_path is None:
        raise typer.BadParameter("browser ingestion is scaffolded for Milestone 2; provide --csv")
    item = _csv_source(csv_path).create_snapshot()
    engine = create_database(data_directory() / "card-relay.db")
    SnapshotRepository(engine).add(item)
    _emit(item.model_dump(mode="json"), as_json)


def _scaffold(name: str) -> None:
    typer.echo(
        f"Collectr browser {name} is scaffolded for Milestone 2; no live action was performed."
    )
    raise typer.Exit(7)


for command_name in ("login", "logout", "session-status", "clear-session", "inspect"):
    collectr_app.command(command_name)(lambda name=command_name: _scaffold(name))


@app.command()
def match() -> None:
    typer.echo("Use the Python matching API with a fixture-backed destination in Milestone 1.")


@app.command()
def plan() -> None:
    typer.echo(
        "Use the Python planning API with the mock adapter in Milestone 1; writes remain dry-run."
    )


@app.command()
def sync(
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Skip confirmation; does not enable destructive operations."),
    ] = False,
) -> None:
    typer.echo(
        "Mock sync requires an application-provided catalog; "
        f"dry-run safety remains enabled (yes={yes})."
    )


for command_name in ("list", "review", "confirm", "reject"):
    mappings_app.command(command_name)(
        lambda name=command_name: typer.echo(f"mapping {name}: no pending mappings")
    )


def main() -> None:
    try:
        app()
    except CardRelayError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
