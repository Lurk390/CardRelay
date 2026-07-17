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
