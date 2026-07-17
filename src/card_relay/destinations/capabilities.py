from pydantic import BaseModel


class DestinationCapabilities(BaseModel):
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
