from enum import StrEnum


class ExtractionCompleteness(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class IngestionMethod(StrEnum):
    CSV = "csv"
    BROWSER = "browser"


class Finish(StrEnum):
    NORMAL = "normal"
    FOIL = "foil"
    HOLO = "holo"
    REVERSE_HOLO = "reverse_holo"
    MASTER_BALL_REVERSE_HOLO = "master_ball_reverse_holo"
    CRACKED_ICE = "cracked_ice"
    COSMOS_HOLO = "cosmos_holo"
    STAMPED = "stamped"
    PROMO = "promo"
    UNKNOWN = "unknown"
    APPLICATION_SPECIFIC = "application_specific"


class Edition(StrEnum):
    FIRST = "first_edition"
    LIMITED = "limited"
    UNLIMITED = "unlimited"
    UNKNOWN = "unknown"


class MatchStatus(StrEnum):
    EXACT = "exact"
    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    REJECTED = "rejected"


class OperationType(StrEnum):
    ADD = "add_card"
    INCREASE = "increase_quantity"
    DECREASE = "decrease_quantity"
    REMOVE = "remove_card"
    NO_CHANGE = "no_change"
    MANUAL_REVIEW = "manual_review_required"
    UNSUPPORTED = "unsupported_operation"
    BLOCKED = "blocked_by_safety_policy"


class CollectrSourceMode(StrEnum):
    CSV = "csv"
    BROWSER = "browser"
    AUTO = "auto"
