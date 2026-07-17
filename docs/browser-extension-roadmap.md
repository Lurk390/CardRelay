# Browser extension roadmap

A Manifest V3 extension should offer Sync now, periodic alarms, status, preview, explicit write approval, ambiguity and blocked-operation notifications, browser-managed/local encrypted state, and narrow permissions.

Two options remain open: a loopback-only authenticated local companion reuses Python, SQLite, and adapters but adds installation and local-auth complexity; a TypeScript core removes the service but duplicates critical logic and needs strict parity/version tests. Decide after browser and Dex integrations stabilize, based on security, installability, parity cost, and browser storage limits.

