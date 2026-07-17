# Architecture

CardRelay uses ports and adapters: source acquisition and parsing produce a canonical collection; matching resolves identities; planning compares desired and actual quantities; policy marks operations executable or blocked; destination adapters apply only approved operations. This keeps future browser-extension delivery and platform transports outside the domain.

Fingerprints use a version prefix plus SHA-256 over normalized game, set, collector number, language, finish, edition, grading state/company/grade, and promo state. Quantity is excluded. A future identity-field change requires a new prefix and an explicit mapping migration.

