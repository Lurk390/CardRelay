# ADR 0003: Safe sync semantics

Accepted. Dry-run is default. Additions/increases are initially safer; decreases/removals are separately disabled and removals require their own flag and thresholds. Incomplete extraction and suspicious collection drops block destruction. Opt-in may expand only after integration reliability is demonstrated.

