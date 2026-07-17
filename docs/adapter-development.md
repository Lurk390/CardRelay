# Adapter development

Destination adapters declare capabilities, retrieve normalized catalog/collection records, and apply already-approved operations. They must not redefine identity. Validate all external responses, use explicit timeouts and bounded retries, redact secrets, classify partial failures, and test with sanitized fixtures without live CI dependencies.

