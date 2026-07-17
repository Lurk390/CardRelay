import json
from pathlib import Path
from typing import Annotated

import typer

from card_relay import __version__
from card_relay.browser.profile import (
    browser_profile_directory,
    browser_profile_present,
    clear_browser_profile,
)
from card_relay.config import load_settings
from card_relay.destinations.mock import FileBackedMockDestinationAdapter
from card_relay.domain.enums import MatchStatus, OperationType
from card_relay.domain.models import CanonicalCollection, DestinationCatalogRecord, SourceSnapshot
from card_relay.domain.operations import SyncPlan
from card_relay.exceptions import CardRelayError
from card_relay.matching import match_collection
from card_relay.paths import config_path, data_directory
from card_relay.sources.collectr.browser_session import BrowserSessionManager
from card_relay.sources.collectr.csv_source import CollectrCsvSource
from card_relay.storage.database import create_database
from card_relay.storage.repositories import (
    MappingRepository,
    SnapshotRepository,
    SyncAuditRepository,
)
from card_relay.sync.executor import execute_plan
from card_relay.sync.planner import build_plan
from card_relay.sync.policy import SyncPolicy
from card_relay.sync.safeguards import assess_source_snapshot

app = typer.Typer(help="Sync your trading card collection from one source of truth to every app.")
collectr_app = typer.Typer(help="Collectr ingestion and browser-session commands.")
config_app = typer.Typer(help="Configuration commands.")
mappings_app = typer.Typer(help="Persistent mapping review commands.")
dex_app = typer.Typer(help="Dex read-only browser research commands.")
app.add_typer(collectr_app, name="collectr")
app.add_typer(config_app, name="config")
app.add_typer(mappings_app, name="mappings")
app.add_typer(dex_app, name="dex")


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


def _run_collectr_browser(url: str, action: str) -> None:
    settings = load_settings().collectr.browser
    profile = settings.profile_directory or browser_profile_directory()
    typer.echo(f"Opening a visible browser at {url}")
    typer.echo(f"Local browser profile: {profile}")
    typer.echo(
        "Authentication remains between you and the site; CardRelay never asks for a password."
    )
    manager = BrowserSessionManager(profile, settings.navigation_timeout_seconds)
    manager.run_visible(
        url,
        lambda: typer.prompt(
            f"Complete the user-controlled {action} flow in the browser, then press Enter",
            default="",
            show_default=False,
        ),
    )


@collectr_app.command("login")
def collectr_login(
    url: Annotated[str | None, typer.Option("--url")] = None,
) -> None:
    selected = url or load_settings().collectr.browser.research_url
    _run_collectr_browser(selected, "login or account discovery")
    typer.echo("Browser profile saved locally; authentication status remains unverified.")


@collectr_app.command("logout")
def collectr_logout(
    url: Annotated[str | None, typer.Option("--url")] = None,
) -> None:
    selected = url or load_settings().collectr.browser.research_url
    _run_collectr_browser(selected, "manual logout")
    typer.echo("Manual logout flow finished; use clear-session to remove all local browser state.")


@collectr_app.command("session-status")
def collectr_session_status(
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        {
            "profile_present": browser_profile_present(),
            "authentication_status": "unknown",
            "reason": "No verified Collectr web authentication contract exists yet.",
        },
        as_json,
    )


@collectr_app.command("clear-session")
def collectr_clear_session(
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    if browser_profile_present() and not yes:
        typer.confirm("Delete the local Collectr browser profile?", abort=True)
    clear_browser_profile()
    typer.echo("Local Collectr browser profile removed.")


@collectr_app.command("inspect")
def collectr_inspect(
    url: Annotated[str | None, typer.Option("--url")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    selected = url or load_settings().collectr.browser.research_url
    settings = load_settings().collectr.browser
    profile = settings.profile_directory or browser_profile_directory()
    manager = BrowserSessionManager(profile, settings.navigation_timeout_seconds)
    diagnostics = manager.inspect_visible(
        selected,
        lambda: typer.prompt(
            "Browse the portfolio read-only, then press Enter",
            default="",
            show_default=False,
        ),
    )
    _emit(
        {
            **diagnostics.model_dump(),
            "collection_extracted": False,
            "completeness": "unknown",
        },
        as_json,
    )


DEX_WEB_URL = "https://app.dextcg.com/"


def _run_dex_browser(action: str) -> None:
    settings = load_settings().collectr.browser
    manager = BrowserSessionManager(
        browser_profile_directory("dex"), settings.navigation_timeout_seconds
    )
    manager.run_visible(
        DEX_WEB_URL,
        lambda: typer.prompt(
            f"Complete the user-controlled Dex {action}, then press Enter",
            default="",
            show_default=False,
        ),
    )


@dex_app.command("login")
def dex_login() -> None:
    _run_dex_browser("login")
    typer.echo("Dex browser profile saved locally; authentication remains unverified.")


@dex_app.command("session-status")
def dex_session_status(
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        {
            "profile_present": browser_profile_present("dex"),
            "authentication_status": "unknown",
            "reason": "Dex authentication markers have not yet been fixture-verified.",
        },
        as_json,
    )


@dex_app.command("clear-session")
def dex_clear_session(
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    if browser_profile_present("dex") and not yes:
        typer.confirm("Delete the local Dex browser profile?", abort=True)
    clear_browser_profile("dex")
    typer.echo("Local Dex browser profile removed.")


@dex_app.command("inspect")
def dex_inspect(
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    settings = load_settings().collectr.browser
    manager = BrowserSessionManager(
        browser_profile_directory("dex"), settings.navigation_timeout_seconds
    )
    diagnostics = manager.inspect_visible(
        DEX_WEB_URL,
        lambda: typer.prompt(
            "Browse your Dex collection read-only, then press Enter",
            default="",
            show_default=False,
        ),
    )
    _emit(
        {
            **diagnostics.model_dump(),
            "collection_extracted": False,
            "writes_enabled": False,
        },
        as_json,
    )


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
) -> tuple[SyncPlan, FileBackedMockDestinationAdapter, SourceSnapshot]:
    if source != "collectr-csv":
        raise typer.BadParameter("Milestone 1 supports --source collectr-csv")
    collection, adapter = _mock_workflow(csv_path, destination)
    mappings = MappingRepository(create_database(data_directory() / "card-relay.db"))
    matches = match_collection(
        collection,
        adapter.fetch_catalog(),
        mappings.list_confirmed(destination),
        mappings.list_rejected(destination),
    )
    effective_policy = policy or SyncPolicy()
    current_snapshot = _csv_source(csv_path).create_snapshot()
    repository = SnapshotRepository(create_database(data_directory() / "card-relay.db"))
    assessment = assess_source_snapshot(
        current_snapshot, repository.latest_trusted(), effective_policy
    )
    current_snapshot = current_snapshot.model_copy(
        update={"trusted_for_destructive_planning": assessment.destructive_planning_allowed}
    )
    item = build_plan(
        collection,
        adapter.fetch_collection(),
        matches,
        adapter.get_capabilities(),
        effective_policy,
        destination,
        assessment.destructive_planning_allowed,
    )
    item.warnings.extend(assessment.warnings)
    return (
        item,
        adapter,
        current_snapshot,
    )


def _plan_summary(item: SyncPlan, plan_id: int | None = None) -> dict[str, object]:
    counts = {kind.value: 0 for kind in OperationType}
    for operation in item.operations:
        counts[operation.operation_type.value] += 1
    return {
        "destination": item.destination,
        "source_completeness": item.source_completeness,
        "operations": counts,
        "executable_operations": len(item.executable_operations),
        "warnings": item.warnings,
        "plan_id": plan_id,
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
    mappings = MappingRepository(create_database(data_directory() / "card-relay.db"))
    results = match_collection(
        collection,
        adapter.fetch_catalog(),
        mappings.list_confirmed(destination),
        mappings.list_rejected(destination),
    )
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
    item, _, _ = _create_plan(csv_path, source, destination, policy)
    audit = SyncAuditRepository(create_database(data_directory() / "card-relay.db"))
    plan_id = audit.add_plan(item)
    _emit(_plan_summary(item, plan_id), as_json)


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
    item, adapter, current_snapshot = _create_plan(csv_path, source, destination, policy)
    audit = SyncAuditRepository(create_database(data_directory() / "card-relay.db"))
    plan_id = audit.add_plan(item)
    summary = _plan_summary(item, plan_id)
    if dry_run:
        result = execute_plan(item, adapter, dry_run=True)
        run_id = audit.add_run(plan_id, result)
        _emit({**summary, "run_id": run_id, "applied": False, "dry_run": True}, as_json)
        return
    if item.executable_operations and not yes:
        typer.confirm("Apply the listed safe operations?", abort=True)
    result = execute_plan(item, adapter, dry_run=False)
    run_id = audit.add_run(plan_id, result)
    if result.succeeded:
        SnapshotRepository(create_database(data_directory() / "card-relay.db")).add(
            current_snapshot
        )
    _emit(
        {
            **summary,
            "run_id": run_id,
            "applied": True,
            "dry_run": False,
            "succeeded": result.succeeded,
        },
        as_json,
    )
    if not result.succeeded:
        raise typer.Exit(8)


@mappings_app.command("list")
def mappings_list(
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    repository = MappingRepository(create_database(data_directory() / "card-relay.db"))
    records = repository.list_all()
    _emit({"count": len(records), "mappings": records}, as_json)


@mappings_app.command("review")
def mappings_review(
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        {
            "pending": [],
            "message": (
                "Probable and ambiguous review queue persistence is planned for Milestone 3."
            ),
        },
        as_json,
    )


@mappings_app.command("confirm")
def mappings_confirm(
    fingerprint: Annotated[str, typer.Argument()],
    destination_id: Annotated[str, typer.Argument()],
    destination: Annotated[str, typer.Option("--destination")] = "mock",
) -> None:
    repository = MappingRepository(create_database(data_directory() / "card-relay.db"))
    repository.confirm(fingerprint, destination, destination_id)
    typer.echo("mapping confirmed")


@mappings_app.command("reject")
def mappings_reject(
    fingerprint: Annotated[str, typer.Argument()],
    destination_id: Annotated[str, typer.Argument()],
    destination: Annotated[str, typer.Option("--destination")] = "mock",
) -> None:
    repository = MappingRepository(create_database(data_directory() / "card-relay.db"))
    repository.reject(fingerprint, destination, destination_id)
    typer.echo("mapping rejected")


def main() -> None:
    try:
        app()
    except CardRelayError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
