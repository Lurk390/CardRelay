import json
from pathlib import Path

from typer.testing import CliRunner

from card_relay.cli import app

FIXTURE = Path(__file__).parents[1] / "fixtures" / "collectr" / "alternate_export.csv"


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


def test_browser_session_status_never_claims_authentication(tmp_path: Path) -> None:
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})
    result = runner.invoke(app, ["collectr", "session-status", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "profile_present": False,
        "authentication_status": "unknown",
        "reason": "No verified Collectr web authentication contract exists yet.",
    }

    dex = runner.invoke(app, ["dex", "session-status", "--json"])
    assert dex.exit_code == 0
    assert json.loads(dex.stdout)["authentication_status"] == "unknown"


def test_dex_schema_inspection_requires_explicit_acknowledgement(tmp_path: Path) -> None:
    runner = CliRunner(env={"CARD_RELAY_DATA_DIRECTORY": str(tmp_path)})
    result = runner.invoke(
        app,
        ["dex", "inspect-schema", "--cdp-url", "http://127.0.0.1:9222", "--json"],
    )
    assert result.exit_code == 2
    assert "--acknowledge-schema-inspection" in result.output
