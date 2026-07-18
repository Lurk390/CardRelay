from pathlib import Path

from card_relay.domain.enums import Edition, ExtractionCompleteness, Finish
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


def test_verified_portfolio_schema_preserves_games_finishes_grading_and_watchlist() -> None:
    source = CollectrCsvSource(FIXTURES / "portfolio_export.csv")
    collection = source.load_collection()

    assert len(collection.entries) == 3
    assert collection.total_quantity == 4
    by_number = {entry.identity.collector_number: entry for entry in collection.entries}
    assert by_number["1"].identity.game == "pokemon"
    assert by_number["1"].identity.finish is Finish.HOLO
    assert by_number["7"].identity.game == "magic: the gathering"
    assert by_number["7"].identity.finish is Finish.FOIL
    assert by_number["9"].identity.grading_status == "graded"
    assert by_number["9"].identity.grading_company == "CGC"
    assert str(by_number["9"].identity.grade) == "10.0"
    assert source.validate_access().warnings == ["skipped 1 watchlist-only row(s) without quantity"]
    snapshot = source.create_snapshot()
    assert snapshot.completeness is ExtractionCompleteness.COMPLETE
    assert snapshot.invalid_record_count == 0
    assert snapshot.trusted_for_destructive_planning


def test_invalid_quantity_fails_whole_import(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("Card,Set,Number,Qty\nFake,Set,1,-2\n", encoding="utf-8")
    result = CollectrCsvSource(path).validate_access()
    assert not result.valid
    assert "greater than zero" in result.errors[0]


def test_blank_watchlist_quantity_is_not_treated_as_zero(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.csv"
    path.write_text(
        "Product Name,Set,Card Number,Quantity,Watchlist\nWatched Fixture,Fixture Set,1,,true\n",
        encoding="utf-8",
    )
    source = CollectrCsvSource(path)

    assert source.load_collection().entries == []
    assert source.validate_access().warnings == ["skipped 1 watchlist-only row(s) without quantity"]


def test_blank_non_watchlist_quantity_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "missing-quantity.csv"
    path.write_text(
        "Product Name,Set,Card Number,Quantity,Watchlist\nHeld Fixture,Fixture Set,1,,false\n",
        encoding="utf-8",
    )

    result = CollectrCsvSource(path).validate_access()
    assert not result.valid
    assert "row 2" in result.errors[0]


def test_blank_collector_number_makes_source_incomplete_without_exposing_name(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing-number.csv"
    private_name = "PRIVATE-CARD-NAME"
    path.write_text(
        f"Product Name,Set,Card Number,Quantity\n{private_name},Fixture Set,,1\n",
        encoding="utf-8",
    )

    source = CollectrCsvSource(path)
    result = source.validate_access()
    snapshot = source.create_snapshot()
    assert result.valid
    assert result.record_count == 0
    assert "collector number is missing" in result.warnings[0]
    assert private_name not in result.warnings[0]
    assert snapshot.completeness is ExtractionCompleteness.INCOMPLETE
    assert snapshot.invalid_record_count == 1
    assert not snapshot.trusted_for_destructive_planning


def test_collectr_variance_editions_remain_distinct(tmp_path: Path) -> None:
    path = tmp_path / "editions.csv"
    path.write_text(
        "Product Name,Set,Card Number,Quantity,Variance\n"
        "First Fixture,Fixture Set,1,1,1st Edition\n"
        "Limited Fixture,Fixture Set,2,1,Limited\n"
        "Unlimited Fixture,Fixture Set,3,1,Unlimited\n"
        "Master Fixture,Fixture Set,4,1,Master Ball Reverse Holo\n",
        encoding="utf-8",
    )
    collection = CollectrCsvSource(path).load_collection()
    by_number = {entry.identity.collector_number: entry for entry in collection.entries}

    assert by_number["1"].identity.edition is Edition.FIRST
    assert by_number["2"].identity.edition is Edition.LIMITED
    assert by_number["3"].identity.edition is Edition.UNLIMITED
    assert by_number["4"].identity.finish is Finish.MASTER_BALL_REVERSE_HOLO


def test_unknown_finish_is_skipped_and_marks_source_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "unsupported-finish.csv"
    path.write_text(
        "Product Name,Set,Card Number,Quantity,Variance\n"
        "Unknown Fixture,Fixture Set,1,1,Unverified Finish\n",
        encoding="utf-8",
    )
    source = CollectrCsvSource(path)

    assert source.load_collection().entries == []
    assert source.load_collection().completeness is ExtractionCompleteness.INCOMPLETE
    assert "finish is unsupported" in source.validate_access().warnings[0]
    assert source.create_snapshot().invalid_record_count == 1
    assert not source.create_snapshot().trusted_for_destructive_planning


def test_invalid_encoding_fails_safely(tmp_path: Path) -> None:
    path = tmp_path / "invalid.csv"
    path.write_bytes(b"Card,Set,Number,Qty\nFake,Set,1,1\xff")
    result = CollectrCsvSource(path).validate_access()
    assert not result.valid
    assert "UTF-8" in result.errors[0]


def test_duplicate_identity_with_conflicting_condition_is_explicitly_mixed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conditions.csv"
    path.write_text(
        "Card,Set,Number,Qty,Condition\nFake,Set,1,1,Near Mint\nFake,Set,1,1,Played\n",
        encoding="utf-8",
    )
    source = CollectrCsvSource(path)
    entry = source.load_collection().entries[0]
    result = source.validate_access()
    assert result.valid
    assert entry.quantity == 2
    assert entry.condition == "mixed"
    assert source.load_collection().completeness is ExtractionCompleteness.INCOMPLETE
    assert not source.create_snapshot().trusted_for_destructive_planning
    assert any("condition recorded as mixed" in warning for warning in result.warnings)


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
