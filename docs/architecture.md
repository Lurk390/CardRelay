# Architecture

CardRelay uses ports and adapters: source acquisition and parsing produce a canonical collection; matching resolves identities; planning compares desired and actual quantities; policy marks operations executable or blocked; destination adapters apply only approved operations. This keeps future browser-extension delivery and platform transports outside the domain.

Fingerprint schema `v2` uses a version prefix plus SHA-256 over normalized game, set, collector number, language, finish, edition, grading state/company/grade/certification, promo, signed, and altered state. Quantity is excluded. Schema `v1` did not include certification, signed, or altered state; stored mappings require an explicit migration rather than silent reuse after a version change.
