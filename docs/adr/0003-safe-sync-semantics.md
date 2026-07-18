# ADR 0003: Safe sync semantics

Accepted. Dry-run is default. Additions/increases are initially safer; decreases/removals are separately disabled and removals require their own flag and thresholds. Incomplete extraction, including an intentional partial browser observation, blocks destruction. Records omitted from a partial observation retain unknown source state and must not generate decreases or removals. Suspicious collection drops also block destruction. Opt-in may expand only after integration reliability is demonstrated.

