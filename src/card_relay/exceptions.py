class CardRelayError(Exception):
    """Base error safe to display to a user."""


class SourceValidationError(CardRelayError):
    pass


class IncompleteSourceError(CardRelayError):
    pass


class IntegrationUnavailableError(CardRelayError):
    pass
