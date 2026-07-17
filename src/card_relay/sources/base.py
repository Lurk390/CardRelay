from typing import Protocol

from card_relay.domain.models import CanonicalCollection, SourceSnapshot
from card_relay.domain.results import SourceValidationResult


class CollectionSource(Protocol):
    source_name: str

    def validate_access(self) -> SourceValidationResult: ...

    def load_collection(self) -> CanonicalCollection: ...

    def create_snapshot(self) -> SourceSnapshot: ...
