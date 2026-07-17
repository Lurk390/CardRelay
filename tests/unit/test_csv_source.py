from pathlib import Path

from card_relay.sources.collectr.csv_source import CollectrCsvSource

FIXTURES = Path(__file__).parents[1] / "fixtures" / "collectr"


def test_plausible_schema_aggregates_duplicates() -> None:
    source = CollectrCsvSource(FIXTURES / "plausible_export.csv")
    collection = source.load_collection()
    assert len(collection.entries) == 3
    assert collection.total_quantity == 5
    assert source.create_snapshot().duplicate_record_count == 1


def test_alternate_schema_produces_normalized_records() -> None:
    collection = CollectrCsvSource(FIXTURES / "alternate_export.csv").load_collection()
    assert [(entry.identity.collector_number, entry.quantity) for entry in collection.entries] == [
        ("1", 3),
        ("7", 1),
    ]


def test_invalid_quantity_fails_whole_import(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("Card,Set,Number,Qty\nFake,Set,1,-2\n", encoding="utf-8")
    result = CollectrCsvSource(path).validate_access()
    assert not result.valid
    assert "greater than zero" in result.errors[0]
