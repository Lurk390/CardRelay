# Adapter development

Destination adapters declare capabilities, retrieve normalized catalog/collection records, and apply already-approved operations. They must not redefine identity. Catalog records are revalidated, deduplicated by destination ID, deterministically ordered, and cached at the core boundary; conflicting identities for one destination ID fail closed. Validate all external responses, use explicit timeouts and bounded retries, redact secrets, classify partial failures, and test with sanitized fixtures without live CI dependencies.

