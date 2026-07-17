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


def test_invalid_encoding_fails_safely(tmp_path: Path) -> None:
    path = tmp_path / "invalid.csv"
    path.write_bytes(b"Card,Set,Number,Qty\nFake,Set,1,1\xff")
    result = CollectrCsvSource(path).validate_access()
    assert not result.valid
    assert "UTF-8" in result.errors[0]


def test_duplicate_identity_with_conflicting_condition_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "conditions.csv"
    path.write_text(
        "Card,Set,Number,Qty,Condition\nFake,Set,1,1,Near Mint\nFake,Set,1,1,Played\n",
        encoding="utf-8",
    )
    result = CollectrCsvSource(path).validate_access()
    assert not result.valid
    assert "conflicting conditions" in result.errors[0]


def test_duplicate_identity_preserves_known_condition(tmp_path: Path) -> None:
    path = tmp_path / "conditions.csv"
    path.write_text(
        "Card,Set,Number,Qty,Condition\nFake,Set,1,1,\nFake,Set,1,2,Near Mint\n",
        encoding="utf-8",
    )
    entry = CollectrCsvSource(path).load_collection().entries[0]
    assert entry.quantity == 3
    assert entry.condition == "Near Mint"


def test_optional_grading_and_provenance_fields_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "graded.csv"
    path.write_text(
        "Card,Set,Number,Qty,Set Total,Grader,Grade,Cert,Rarity,Signed,Altered,Notes,Record ID\n"
        "Crystal Lynx,Frost Dream,4,1,80,Fixture Grading,9.5,CERT-FAKE,Rare,yes,no,"
        "Fictional note,row-42\n",
        encoding="utf-8",
    )
    entry = CollectrCsvSource(path).load_collection().entries[0]
    assert entry.identity.printed_set_total == 80
    assert entry.identity.grading_status == "graded"
    assert str(entry.identity.grade) == "9.5"
    assert entry.identity.certification_number == "CERT-FAKE"
    assert entry.rarity == "Rare"
    assert entry.identity.signed
    assert not entry.identity.altered
    assert entry.notes == "Fictional note"
    assert entry.source_record_id == "row-42"
