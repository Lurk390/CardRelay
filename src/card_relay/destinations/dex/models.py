from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
DexQuantity = Annotated[int, Field(strict=True, ge=0)]


class DexNestedModel(BaseModel):
    """Validated fields from a nested catalog object.

    The schema inspection was depth-bounded, so nested catalog additions are accepted while the
    identity-bearing fields CardRelay relies on remain required and typed.
    """

    model_config = ConfigDict(extra="allow")


class DexSet(DexNestedModel):
    id: NonEmptyString
    name: NonEmptyString
    set_id: NonEmptyString = Field(alias="setId")


class DexVariant(DexNestedModel):
    type: NonEmptyString


class DexCard(DexNestedModel):
    id: NonEmptyString
    card_id: NonEmptyString = Field(alias="cardId")
    name: NonEmptyString
    number: NonEmptyString
    set_id: NonEmptyString = Field(alias="setId")
    set: DexSet
    variants: list[DexVariant]

    @model_validator(mode="after")
    def identifiers_are_consistent(self) -> "DexCard":
        if self.set_id != self.set.set_id:
            raise ValueError("card setId must match nested set setId")
        return self


class DexCollectionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyString
    user_id: NonEmptyString = Field(alias="userId")
    card_id: NonEmptyString = Field(alias="cardId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    card: DexCard
    quantities: dict[NonEmptyString, DexQuantity]

    @model_validator(mode="after")
    def identifiers_are_consistent(self) -> "DexCollectionEntry":
        if self.card_id != self.card.card_id:
            raise ValueError("entry cardId must match nested card cardId")
        return self

    @property
    def total_quantity(self) -> int:
        return sum(self.quantities.values())


class DexCollectionPage(BaseModel):
    """Provisional, read-only Dex collection page transport contract."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(strict=True, ge=1)
    page_size: int = Field(alias="pageSize", strict=True, ge=1)
    result: list[DexCollectionEntry]
    total_items: int = Field(alias="totalItems", strict=True, ge=0)
    total_pages: int = Field(alias="totalPages", strict=True, ge=1)

    @model_validator(mode="after")
    def pagination_is_consistent(self) -> "DexCollectionPage":
        if self.page > self.total_pages:
            raise ValueError("page cannot exceed totalPages")
        if len(self.result) > self.page_size:
            raise ValueError("result count cannot exceed pageSize")
        if len(self.result) > self.total_items:
            raise ValueError("result count cannot exceed totalItems")
        return self
