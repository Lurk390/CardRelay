import json
from pathlib import Path
from typing import Annotated

import typer

from card_relay import __version__
from card_relay.config import load_settings
from card_relay.destinations.mock import FileBackedMockDestinationAdapter
from card_relay.domain.enums import MatchStatus, OperationType
from card_relay.domain.models import CanonicalCollection, DestinationCatalogRecord
from card_relay.domain.operations import SyncPlan
from card_relay.exceptions import CardRelayError
from card_relay.matching import match_collection
from card_relay.paths import config_path, data_directory
from card_relay.sources.collectr.csv_source import CollectrCsvSource
from card_relay.storage.database import create_database
from card_relay.storage.repositories import SnapshotRepository
from card_relay.sync.executor import execute_plan
from card_relay.sync.planner import build_plan
from card_relay.sync.policy import SyncPolicy

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


def _mock_workflow(
    csv_path: Path, destination: str
) -> tuple[CanonicalCollection, FileBackedMockDestinationAdapter]:
    if destination != "mock":
        raise typer.BadParameter("only the mock destination is available in Milestone 1")
    collection = _csv_source(csv_path).load_collection()
    catalog = [
        DestinationCatalogRecord(
            destination_id=f"mock:{entry.fingerprint.split(':', 1)[1][:16]}",
            identity=entry.identity,
        )
        for entry in collection.entries
    ]
    return collection, FileBackedMockDestinationAdapter(
        catalog, data_directory() / "mock" / "collection.json"
    )


def _create_plan(
    csv_path: Path, source: str, destination: str, policy: SyncPolicy | None = None
) -> tuple[SyncPlan, FileBackedMockDestinationAdapter]:
    if source != "collectr-csv":
        raise typer.BadParameter("Milestone 1 supports --source collectr-csv")
    collection, adapter = _mock_workflow(csv_path, destination)
    matches = match_collection(collection, adapter.fetch_catalog())
    return (
        build_plan(
            collection,
            adapter.fetch_collection(),
            matches,
            adapter.get_capabilities(),
            policy or SyncPolicy(),
            destination,
        ),
        adapter,
    )


def _plan_summary(item: SyncPlan) -> dict[str, object]:
    counts = {kind.value: 0 for kind in OperationType}
    for operation in item.operations:
        counts[operation.operation_type.value] += 1
    return {
        "destination": item.destination,
        "source_completeness": item.source_completeness,
        "operations": counts,
        "executable_operations": len(item.executable_operations),
        "warnings": item.warnings,
    }


@app.command()
def match(
    csv_path: Annotated[Path, typer.Option("--csv", exists=True, dir_okay=False)],
    source: Annotated[str, typer.Option("--source")] = "collectr-csv",
    destination: Annotated[str, typer.Option("--destination")] = "mock",
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if source != "collectr-csv":
        raise typer.BadParameter("Milestone 1 supports --source collectr-csv")
    collection, adapter = _mock_workflow(csv_path, destination)
    results = match_collection(collection, adapter.fetch_catalog())
    counts = {status.value: 0 for status in MatchStatus}
    for result in results:
        counts[result.status.value] += 1
    _emit({"source": source, "destination": destination, "matches": counts}, as_json)


@app.command()
def plan(
    csv_path: Annotated[Path, typer.Option("--csv", exists=True, dir_okay=False)],
    source: Annotated[str, typer.Option("--source")] = "collectr-csv",
    destination: Annotated[str, typer.Option("--destination")] = "mock",
    allow_quantity_decreases: Annotated[bool, typer.Option("--allow-quantity-decreases")] = False,
    allow_removals: Annotated[bool, typer.Option("--allow-removals")] = False,
    maximum_removal_count: Annotated[int, typer.Option("--maximum-removal-count")] = 0,
    maximum_removal_percent: Annotated[float, typer.Option("--maximum-removal-percent")] = 0,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    policy = SyncPolicy(
        allow_quantity_decreases=allow_quantity_decreases,
        allow_removals=allow_removals,
        maximum_removal_count=maximum_removal_count,
        maximum_removal_percent=maximum_removal_percent,
    )
    item, _ = _create_plan(csv_path, source, destination, policy)
    _emit(_plan_summary(item), as_json)


@app.command()
def sync(
    csv_path: Annotated[Path, typer.Option("--csv", exists=True, dir_okay=False)],
    source: Annotated[str, typer.Option("--source")] = "collectr-csv",
    destination: Annotated[str, typer.Option("--destination")] = "mock",
    dry_run: Annotated[bool, typer.Option("--dry-run/--apply")] = True,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Skip confirmation; does not enable destructive operations."),
    ] = False,
    allow_quantity_decreases: Annotated[bool, typer.Option("--allow-quantity-decreases")] = False,
    allow_removals: Annotated[bool, typer.Option("--allow-removals")] = False,
    maximum_removal_count: Annotated[int, typer.Option("--maximum-removal-count")] = 0,
    maximum_removal_percent: Annotated[float, typer.Option("--maximum-removal-percent")] = 0,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    policy = SyncPolicy(
        dry_run=dry_run,
        allow_quantity_decreases=allow_quantity_decreases,
        allow_removals=allow_removals,
        maximum_removal_count=maximum_removal_count,
        maximum_removal_percent=maximum_removal_percent,
    )
    item, adapter = _create_plan(csv_path, source, destination, policy)
    summary = _plan_summary(item)
    if dry_run:
        _emit({**summary, "applied": False, "dry_run": True}, as_json)
        return
    if item.executable_operations and not yes:
        typer.confirm("Apply the listed safe operations?", abort=True)
    result = execute_plan(item, adapter, dry_run=False)
    _emit(
        {**summary, "applied": True, "dry_run": False, "succeeded": result.succeeded},
        as_json,
    )
    if not result.succeeded:
        raise typer.Exit(8)


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
