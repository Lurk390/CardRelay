from card_relay.storage.database import create_database
from card_relay.storage.repositories import MappingRepository


def test_mapping_persistence(tmp_path) -> None:
    engine = create_database(tmp_path / "test.db")
    repository = MappingRepository(engine)
    repository.confirm("v1:abc", "mock", "mock-1")
    assert repository.list_confirmed("mock") == {"v1:abc": "mock-1"}
