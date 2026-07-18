from card_relay.domain.enums import CollectrSourceMode
from card_relay.exceptions import SourceValidationError
from card_relay.sources.base import CollectionSource
from card_relay.sources.collectr.csv_source import CollectrCsvSource
from card_relay.sources.collectr.models import CollectrSourceConfig


def create_collectr_source(
    mode: CollectrSourceMode, config: CollectrSourceConfig
) -> CollectionSource:
    if mode in {CollectrSourceMode.CSV, CollectrSourceMode.AUTO} and config.csv_path is not None:
        return CollectrCsvSource(config.csv_path, config.column_aliases)
    if mode is CollectrSourceMode.CSV:
        raise SourceValidationError("CSV mode requires an explicit CSV path")
    raise SourceValidationError(
        "browser mode requires a live capture provider; use the Collectr browser CLI"
    )
