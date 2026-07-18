from pydantic import BaseModel, Field, model_validator

from card_relay.domain.enums import ExtractionCompleteness
from card_relay.domain.models import CanonicalCollection
from card_relay.exceptions import IntegrationUnavailableError


class BrowserExtractionDiagnostics(BaseModel):
    """Completeness evidence retained without private collection payloads."""

    completeness: ExtractionCompleteness = ExtractionCompleteness.UNKNOWN
    observed_record_count: int = Field(default=0, ge=0)
    visible_total: int | None = Field(default=None, ge=0)
    observed_page_count: int = Field(default=0, ge=0)
    expected_page_count: int | None = Field(default=None, ge=1)
    pagination_complete: bool = False
    schema_recognized: bool = False
    warnings: list[str] = Field(default_factory=list)

    @property
    def completeness_checks_passed(self) -> bool:
        return (
            self.schema_recognized
            and self.pagination_complete
            and self.visible_total is not None
            and self.observed_record_count == self.visible_total
            and self.expected_page_count is not None
            and self.observed_page_count == self.expected_page_count
        )

    @property
    def trusted_for_destructive_planning(self) -> bool:
        return (
            self.completeness is ExtractionCompleteness.COMPLETE and self.completeness_checks_passed
        )

    @model_validator(mode="after")
    def complete_claim_requires_evidence(self) -> "BrowserExtractionDiagnostics":
        if (
            self.completeness is ExtractionCompleteness.COMPLETE
            and not self.completeness_checks_passed
        ):
            raise ValueError("complete browser extraction requires all completeness checks")
        return self


class BrowserFixtureParseResult(BaseModel):
    collection: CanonicalCollection
    diagnostics: BrowserExtractionDiagnostics

    @model_validator(mode="after")
    def completeness_matches_collection(self) -> "BrowserFixtureParseResult":
        if self.collection.completeness is not self.diagnostics.completeness:
            raise ValueError("collection and browser diagnostics completeness must match")
        return self


class CollectrBrowserFixtureParser:
    """Fail-closed boundary pending a sanitized Collectr browser response fixture."""

    parser_name = "collectr_browser_fixture"
    parser_version = "0"

    def parse(self, payload: object) -> BrowserFixtureParseResult:
        del payload
        raise IntegrationUnavailableError(
            "Collectr browser fixture parsing requires a sanitized, verified response contract"
        )
