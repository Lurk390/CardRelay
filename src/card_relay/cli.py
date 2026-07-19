import json
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import urlparse

import typer

from card_relay import __version__
from card_relay.browser.profile import (
    browser_profile_directory,
    browser_profile_present,
    clear_browser_profile,
)
from card_relay.config import load_settings
from card_relay.destinations.base import DestinationAdapter
from card_relay.destinations.mock import FileBackedMockDestinationAdapter
from card_relay.domain.enums import MatchStatus, OperationType
from card_relay.domain.models import CanonicalCollection, DestinationCatalogRecord, SourceSnapshot
from card_relay.domain.operations import SyncPlan
from card_relay.domain.results import MatchResult
from card_relay.exceptions import CardRelayError
from card_relay.extension.companion import serve_companion
from card_relay.matching import match_collection
from card_relay.paths import config_path, data_directory
from card_relay.sources.base import CollectionSource
from card_relay.sources.collectr.browser_capture import CollectrPortfolioCaptureSession
from card_relay.sources.collectr.browser_session import BrowserSessionManager
from card_relay.sources.collectr.browser_source import CollectrBrowserSource
from card_relay.sources.collectr.csv_source import CollectrCsvSource
from card_relay.storage.database import create_database
from card_relay.storage.repositories import (
    CatalogCacheRepository,
    MappingRepository,
    MappingReviewRepository,
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
catalog_app = typer.Typer(help="Destination catalog cache commands.")
dex_app = typer.Typer(help="Dex read-only browser research commands.")
extension_app = typer.Typer(help="Browser-extension companion commands.")
app.add_typer(collectr_app, name="collectr")
app.add_typer(config_app, name="config")
app.add_typer(mappings_app, name="mappings")
app.add_typer(catalog_app, name="catalog")
app.add_typer(dex_app, name="dex")
app.add_typer(extension_app, name="extension")


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
            "browser_integration": "available",
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


def _browser_source() -> CollectrBrowserSource:
    settings = load_settings().collectr.browser
    profile = settings.profile_directory or browser_profile_directory()
    session = CollectrPortfolioCaptureSession(
        profile,
        settings.navigation_timeout_seconds,
        settings.request_delay_seconds,
        settings.maximum_batches,
    )
    return CollectrBrowserSource(session.capture_visible)


def _selected_collectr_source(
    csv_path: Path | None, browser: bool
) -> CollectrCsvSource | CollectrBrowserSource:
    if (csv_path is None and not browser) or (csv_path is not None and browser):
        raise typer.BadParameter("choose exactly one source: --csv PATH or --browser")
    return _browser_source() if browser else _csv_source(cast(Path, csv_path))


@collectr_app.command("validate")
def validate(
    csv_path: Annotated[Path | None, typer.Option("--csv", exists=True, dir_okay=False)] = None,
    browser: Annotated[bool, typer.Option("--browser")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    result = _selected_collectr_source(csv_path, browser).validate_access()
    _emit(result.model_dump(), as_json)
    if not result.valid:
        raise typer.Exit(2)


@collectr_app.command("import")
def import_collection(
    csv_path: Annotated[Path | None, typer.Option("--csv", exists=True, dir_okay=False)] = None,
    browser: Annotated[bool, typer.Option("--browser")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    source = _selected_collectr_source(csv_path, browser)
    collection = source.load_collection()
    browser_diagnostics = (
        source.diagnostics().model_dump(mode="json")
        if isinstance(source, CollectrBrowserSource)
        else None
    )
    _emit(
        {
            "source_method": "browser" if browser else "csv",
            "completeness": collection.completeness,
            "unique_entries": len(collection.entries),
            "total_quantity": collection.total_quantity,
            "warnings": collection.warnings,
            "extraction_diagnostics": browser_diagnostics,
        },
        as_json,
    )


@collectr_app.command("snapshot")
def snapshot(
    csv_path: Annotated[Path | None, typer.Option("--csv", exists=True, dir_okay=False)] = None,
    browser: Annotated[bool, typer.Option("--browser")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    item = _selected_collectr_source(csv_path, browser).create_snapshot()
    engine = create_database(data_directory() / "card-relay.db")
    SnapshotRepository(engine).add(item)
    _emit(item.model_dump(mode="json"), as_json)


def _run_collectr_browser(url: str, action: str, cdp_url: str | None = None) -> None:
    settings = load_settings().collectr.browser
    profile = settings.profile_directory or browser_profile_directory()
    typer.echo(f"Opening a visible browser at {url}")
    typer.echo(f"Local browser profile: {profile}")
    typer.echo(
        "Authentication remains between you and the site; CardRelay never asks for a password."
    )
    if cdp_url is not None:
        typer.echo(f"Attaching only to the loopback Chrome endpoint: {cdp_url}")
    manager = BrowserSessionManager(profile, settings.navigation_timeout_seconds)
    manager.run_visible(
        url,
        lambda: typer.prompt(
            f"Complete the user-controlled {action} flow in the browser, then press Enter",
            default="",
            show_default=False,
        ),
        cdp_url,
    )


@collectr_app.command("login")
def collectr_login(
    url: Annotated[str | None, typer.Option("--url")] = None,
    cdp_url: Annotated[str | None, typer.Option("--cdp-url")] = None,
) -> None:
    selected = url or load_settings().collectr.browser.research_url
    _run_collectr_browser(selected, "login or account discovery", cdp_url)
    typer.echo("Browser profile saved locally; use session-status to verify portfolio access.")


@collectr_app.command("logout")
def collectr_logout(
    url: Annotated[str | None, typer.Option("--url")] = None,
    cdp_url: Annotated[str | None, typer.Option("--cdp-url")] = None,
) -> None:
    selected = url or load_settings().collectr.browser.research_url
    _run_collectr_browser(selected, "manual logout", cdp_url)
    typer.echo("Manual logout flow finished; use clear-session to remove all local browser state.")


@collectr_app.command("session-status")
def collectr_session_status(
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    settings = load_settings().collectr.browser
    profile = settings.profile_directory or browser_profile_directory()
    if not browser_profile_present(profile_directory=profile):
        _emit(
            {
                "profile_present": False,
                "authentication_status": "signed_out",
                "profile_usable": False,
                "portfolio_page_reached": False,
                "reason": "No local Collectr browser profile exists.",
            },
            as_json,
        )
        return
    diagnostics = CollectrPortfolioCaptureSession(
        profile,
        settings.navigation_timeout_seconds,
        settings.request_delay_seconds,
        settings.maximum_batches,
    ).session_status()
    _emit({"profile_present": True, **diagnostics.model_dump()}, as_json)


@collectr_app.command("clear-session")
def collectr_clear_session(
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    settings = load_settings().collectr.browser
    profile = settings.profile_directory or browser_profile_directory()
    if browser_profile_present(profile_directory=profile) and not yes:
        typer.confirm("Delete the local Collectr browser profile?", abort=True)
    clear_browser_profile(profile_directory=profile)
    typer.echo("Local Collectr browser profile removed.")


@collectr_app.command("inspect")
def collectr_inspect(
    url: Annotated[str | None, typer.Option("--url")] = None,
    cdp_url: Annotated[str | None, typer.Option("--cdp-url")] = None,
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
        cdp_url,
    )
    _emit(
        {
            **diagnostics.model_dump(),
            "collection_extracted": False,
            "completeness": "unknown",
        },
        as_json,
    )


@extension_app.command("serve")
def extension_serve(
    port: Annotated[int, typer.Option("--port", min=1024, max=65535)] = 8765,
) -> None:
    server, token = serve_companion(data_directory() / "card-relay.db", port)
    typer.echo(f"CardRelay extension companion listening on http://127.0.0.1:{port}")
    typer.echo("Destination writes: disabled")
    typer.echo(f"Pairing token: {token}")
    typer.echo("Keep this terminal open. Press Ctrl+C to stop the companion.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("CardRelay extension companion stopped.")
    finally:
        server.server_close()


DEX_WEB_URL = "https://app.dextcg.com/"


def _run_dex_browser(action: str, cdp_url: str | None = None) -> None:
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
        cdp_url,
    )


@dex_app.command("login")
def dex_login(
    cdp_url: Annotated[str | None, typer.Option("--cdp-url")] = None,
) -> None:
    _run_dex_browser("login", cdp_url)
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
    cdp_url: Annotated[str | None, typer.Option("--cdp-url")] = None,
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
        cdp_url,
    )
    _emit(
        {
            **diagnostics.model_dump(),
            "collection_extracted": False,
            "writes_enabled": False,
        },
        as_json,
    )


@dex_app.command("inspect-schema")
def dex_inspect_schema(
    cdp_url: Annotated[str, typer.Option("--cdp-url")],
    acknowledge: Annotated[
        bool,
        typer.Option(
            "--acknowledge-schema-inspection",
            help="Allow transient JSON parsing with values discarded immediately.",
        ),
    ] = False,
    capture_seconds: Annotated[
        int,
        typer.Option("--capture-seconds", min=1, max=30),
    ] = 5,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if not acknowledge:
        raise typer.BadParameter(
            "schema inspection requires --acknowledge-schema-inspection because it transiently "
            "parses JSON response bodies"
        )
    settings = load_settings().collectr.browser
    manager = BrowserSessionManager(
        browser_profile_directory("dex"), settings.navigation_timeout_seconds
    )
    expected_hostname = urlparse(DEX_WEB_URL).hostname
    if expected_hostname is None:
        raise RuntimeError("Dex web URL must include a hostname")
    diagnostics = manager.inspect_active_cdp_page_schema(
        cdp_url,
        expected_hostname,
        capture_seconds,
    )
    _emit(
        {
            **diagnostics.model_dump(),
            "capture_boundary": "schema-only-in-memory",
            "raw_values_retained": False,
            "writes_enabled": False,
        },
        as_json,
    )


def _workflow_source(
    csv_path: Path | None, browser: bool, source_name: str
) -> tuple[CollectionSource, str]:
    if source_name not in {"collectr-csv", "collectr-browser"}:
        raise typer.BadParameter("--source must be collectr-csv or collectr-browser")
    use_browser = browser or source_name == "collectr-browser"
    return _selected_collectr_source(csv_path, use_browser), (
        "collectr-browser" if use_browser else "collectr-csv"
    )


def _mock_workflow(
    collection: CanonicalCollection, destination: str
) -> FileBackedMockDestinationAdapter:
    if destination != "mock":
        raise typer.BadParameter("only the mock destination is available before Milestone 4")
    catalog = [
        DestinationCatalogRecord(
            destination_id=f"mock:{entry.fingerprint.split(':', 1)[1][:16]}",
            identity=entry.identity,
        )
        for entry in collection.entries
    ]
    return FileBackedMockDestinationAdapter(catalog, data_directory() / "mock" / "collection.json")


def _match_for_destination(
    collection: CanonicalCollection,
    adapter: DestinationAdapter,
    destination: str,
) -> list[MatchResult]:
    engine = create_database(data_directory() / "card-relay.db")
    mappings = MappingRepository(engine)
    catalog = adapter.fetch_catalog()
    CatalogCacheRepository(engine).replace(destination, catalog)
    matching = load_settings().matching
    results = match_collection(
        collection,
        catalog,
        mappings.list_confirmed(destination),
        mappings.list_rejected(destination),
        minimum_probable_score=matching.minimum_probable_score,
        allow_fuzzy_matching=matching.allow_fuzzy_matching,
        require_variant_match=matching.require_variant_match,
        require_language_match=matching.require_language_match,
        ambiguity_score_margin=matching.ambiguity_score_margin,
    )
    MappingReviewRepository(engine).update(destination, collection, results)
    return results


def _create_plan(
    source: CollectionSource, destination: str, policy: SyncPolicy | None = None
) -> tuple[SyncPlan, FileBackedMockDestinationAdapter, SourceSnapshot]:
    collection = source.load_collection()
    adapter = _mock_workflow(collection, destination)
    matches = _match_for_destination(collection, adapter, destination)
    effective_policy = policy or SyncPolicy()
    current_snapshot = source.create_snapshot()
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
    csv_path: Annotated[Path | None, typer.Option("--csv", exists=True, dir_okay=False)] = None,
    browser: Annotated[bool, typer.Option("--browser")] = False,
    source: Annotated[str, typer.Option("--source")] = "collectr-csv",
    destination: Annotated[str, typer.Option("--destination")] = "mock",
    details: Annotated[bool, typer.Option("--details")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    selected_source, source_name = _workflow_source(csv_path, browser, source)
    collection = selected_source.load_collection()
    adapter = _mock_workflow(collection, destination)
    results = _match_for_destination(collection, adapter, destination)
    counts = {status.value: 0 for status in MatchStatus}
    for result in results:
        counts[result.status.value] += 1
    payload: dict[str, object] = {
        "source": source_name,
        "destination": destination,
        "matches": counts,
        "pending_review": sum(
            result.status in {MatchStatus.PROBABLE, MatchStatus.AMBIGUOUS} for result in results
        ),
    }
    if details:
        payload["results"] = [result.model_dump(mode="json") for result in results]
    _emit(payload, as_json)


@app.command()
def plan(
    csv_path: Annotated[Path | None, typer.Option("--csv", exists=True, dir_okay=False)] = None,
    browser: Annotated[bool, typer.Option("--browser")] = False,
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
    selected_source, _ = _workflow_source(csv_path, browser, source)
    item, _, _ = _create_plan(selected_source, destination, policy)
    audit = SyncAuditRepository(create_database(data_directory() / "card-relay.db"))
    plan_id = audit.add_plan(item)
    _emit(_plan_summary(item, plan_id), as_json)


@app.command()
def sync(
    csv_path: Annotated[Path | None, typer.Option("--csv", exists=True, dir_okay=False)] = None,
    browser: Annotated[bool, typer.Option("--browser")] = False,
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
    selected_source, _ = _workflow_source(csv_path, browser, source)
    item, adapter, current_snapshot = _create_plan(selected_source, destination, policy)
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
    destination: Annotated[str | None, typer.Option("--destination")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    repository = MappingReviewRepository(create_database(data_directory() / "card-relay.db"))
    pending = repository.list_pending(destination)
    _emit({"count": len(pending), "pending": pending}, as_json)


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


@catalog_app.command("cache-status")
def catalog_cache_status(
    destination: Annotated[str, typer.Option("--destination")] = "mock",
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    repository = CatalogCacheRepository(create_database(data_directory() / "card-relay.db"))
    cached = repository.get(destination)
    if cached is None:
        _emit({"destination": destination, "cached": False, "record_count": 0}, as_json)
        return
    cached_at, records = cached
    _emit(
        {
            "destination": destination,
            "cached": True,
            "cached_at": cached_at.isoformat(),
            "record_count": len(records),
        },
        as_json,
    )


def main() -> int:
    try:
        app()
    except CardRelayError as error:
        typer.echo(str(error), err=True)
        return 2
    return 0
