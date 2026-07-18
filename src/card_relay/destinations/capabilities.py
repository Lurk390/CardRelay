import unicodedata

from pydantic import BaseModel


def _game_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_marks.strip().casefold().split())


class DestinationCapabilities(BaseModel):
    supported_games: frozenset[str] | None = None
    catalog_retrieval: bool = True
    collection_retrieval: bool = True
    additions: bool = False
    quantity_increases: bool = False
    quantity_decreases: bool = False
    removals: bool = False
    variants: bool = True
    graded_cards: bool = True
    condition: bool = True
    language: bool = True
    dry_run_simulation: bool = True
    rollback: bool = False
    bulk_operations: bool = False

    def supports_game(self, game: str) -> bool:
        if self.supported_games is None:
            return True
        return _game_key(game) in {_game_key(value) for value in self.supported_games}
