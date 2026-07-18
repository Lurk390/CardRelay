import json
import re
from pathlib import Path

from typer.testing import CliRunner

from card_relay.cli import app
from card_relay.sources.collectr.browser_source import CollectrBrowserSource

FIXTURE = Path(__file__).parents[1] / "fixtures" / "collectr" / "alternate_export.csv"
BROWSER_FIXTURES = Path(__file__).parents[1] / "fixtures" / "collectr"


def test_cli_mock_sync_defaults_to_dry_run_and_is_idempotent(tmp_path: Path) -> None:
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})
    common = ["--csv", str(FIXTURE), "--destination", "mock", "--json"]

    dry_run = runner.invoke(app, ["sync", *common])
    assert dry_run.exit_code == 0
    assert json.loads(dry_run.stdout)["dry_run"] is True
    assert not (tmp_path / "mock" / "collection.json").exists()

    applied = runner.invoke(app, ["sync", *common, "--apply", "--yes"])
    assert applied.exit_code == 0
    assert json.loads(applied.stdout)["executable_operations"] == 2

    second = runner.invoke(app, ["plan", *common])
    assert second.exit_code == 0
    assert json.loads(second.stdout)["executable_operations"] == 0


def test_cli_match_reports_exact_records(tmp_path: Path) -> None:
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})
    result = runner.invoke(
        app,
        ["match", "--csv", str(FIXTURE), "--destination", "mock", "--json"],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["matches"]["exact"] == 2


def test_yes_does_not_enable_quantity_decreases(tmp_path: Path) -> None:
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})
    common = ["--csv", str(FIXTURE), "--destination", "mock", "--json"]
    assert runner.invoke(app, ["sync", *common, "--apply", "--yes"]).exit_code == 0

    state_path = tmp_path / "mock" / "collection.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state[0]["quantity"] += 10
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = runner.invoke(app, ["sync", *common, "--apply", "--yes"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["operations"]["decrease_quantity"] == 1
    assert payload["executable_operations"] == 0
    unchanged = json.loads(state_path.read_text(encoding="utf-8"))
    assert unchanged[0]["quantity"] == state[0]["quantity"]


def test_trusted_snapshot_drop_blocks_opted_in_destruction(tmp_path: Path) -> None:
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})
    original = ["--csv", str(FIXTURE), "--destination", "mock", "--json"]
    assert runner.invoke(app, ["sync", *original, "--apply", "--yes"]).exit_code == 0

    smaller = tmp_path / "smaller.csv"
    smaller.write_text(
        "Card,Set,Number,Quantity,Language,Finish\nEmbermouse,Mythic Sparks,1,1,English,Normal\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "plan",
            "--csv",
            str(smaller),
            "--destination",
            "mock",
            "--allow-quantity-decreases",
            "--allow-removals",
            "--maximum-removal-count",
            "10",
            "--maximum-removal-percent",
            "100",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["executable_operations"] == 0
    assert any("failure threshold" in warning for warning in payload["warnings"])


def test_mapping_commands_persist_confirmed_and_rejected_state(tmp_path: Path) -> None:
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})
    confirm = runner.invoke(app, ["mappings", "confirm", "v1:fixture", "mock-card"])
    assert confirm.exit_code == 0
    listed = runner.invoke(app, ["mappings", "list", "--json"])
    assert json.loads(listed.stdout)["mappings"][0]["status"] == "confirmed"
    reject = runner.invoke(app, ["mappings", "reject", "v1:fixture", "mock-card"])
    assert reject.exit_code == 0
    listed = runner.invoke(app, ["mappings", "list", "--json"])
    assert json.loads(listed.stdout)["mappings"][0]["status"] == "rejected"


def test_browser_session_status_reports_missing_profile(tmp_path: Path) -> None:
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})
    result = runner.invoke(app, ["collectr", "session-status", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "profile_present": False,
        "authentication_status": "signed_out",
        "profile_usable": False,
        "portfolio_page_reached": False,
        "reason": "No local Collectr browser profile exists.",
    }

    dex = runner.invoke(app, ["dex", "session-status", "--json"])
    assert dex.exit_code == 0
    assert json.loads(dex.stdout)["authentication_status"] == "unknown"


def test_collectr_login_accepts_loopback_cdp_browser(monkeypatch) -> None:
    invocation: dict[str, str | None] = {}

    def run_browser(url: str, action: str, cdp_url: str | None = None) -> None:
        invocation.update(url=url, action=action, cdp_url=cdp_url)

    monkeypatch.setattr("card_relay.cli._run_collectr_browser", run_browser)
    result = CliRunner().invoke(
        app,
        ["collectr", "login", "--cdp-url", "http://127.0.0.1:9222"],
    )

    assert result.exit_code == 0
    assert invocation == {
        "url": "https://app.getcollectr.com/portfolio",
        "action": "login or account discovery",
        "cdp_url": "http://127.0.0.1:9222",
    }


def test_dex_schema_inspection_requires_explicit_acknowledgement(tmp_path: Path) -> None:
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})
    result = runner.invoke(
        app,
        ["dex", "inspect-schema", "--cdp-url", "http://127.0.0.1:9222", "--json"],
    )
    assert result.exit_code == 2
    plain_output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--acknowledge-schema-inspection" in plain_output


def test_browser_source_can_apply_safe_additions_but_partial_omissions_stay_blocked(
    monkeypatch, tmp_path: Path
) -> None:
    current_fixture = "browser_structured_complete.json"

    def browser_source() -> CollectrBrowserSource:
        return CollectrBrowserSource(
            lambda: json.loads((BROWSER_FIXTURES / current_fixture).read_text(encoding="utf-8"))
        )

    monkeypatch.setattr("card_relay.cli._browser_source", browser_source)
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})

    imported = runner.invoke(app, ["collectr", "import", "--browser", "--json"])
    assert imported.exit_code == 0
    assert json.loads(imported.stdout)["source_method"] == "browser"

    applied = runner.invoke(
        app,
        ["sync", "--browser", "--destination", "mock", "--apply", "--yes", "--json"],
    )
    assert applied.exit_code == 0
    assert json.loads(applied.stdout)["executable_operations"] == 3

    current_fixture = "browser_partial.json"
    partial = runner.invoke(
        app,
        [
            "plan",
            "--browser",
            "--destination",
            "mock",
            "--allow-removals",
            "--maximum-removal-count",
            "10",
            "--maximum-removal-percent",
            "100",
            "--json",
        ],
    )
    assert partial.exit_code == 0
    payload = json.loads(partial.stdout)
    assert payload["source_completeness"] == "incomplete"
    assert payload["operations"]["remove_card"] == 2
    assert payload["executable_operations"] == 0
