from pydantic import BaseModel, Field, model_validator


class SyncPolicy(BaseModel):
    dry_run: bool = True
    allow_additions: bool = True
    allow_quantity_increases: bool = True
    allow_quantity_decreases: bool = False
    allow_removals: bool = False
    maximum_removal_count: int = Field(default=0, ge=0)
    maximum_removal_percent: float = Field(default=0, ge=0, le=100)
    fail_on_incomplete_source: bool = True
    collection_drop_warning_percent: float = Field(default=10, ge=0, le=100)
    collection_drop_failure_percent: float = Field(default=25, ge=0, le=100)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "SyncPolicy":
        if self.collection_drop_warning_percent > self.collection_drop_failure_percent:
            raise ValueError("collection drop warning threshold cannot exceed failure threshold")
        return self
