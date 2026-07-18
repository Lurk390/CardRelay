# AGENTS.md

## Project

CardRelay synchronizes a user's trading-card collection from Collectr into Dex and, eventually, other collection applications.

Collectr is the source of truth.

The system should support:

* Collectr Pro users through exported files such as CSV.
* Free Collectr users through a safe, maintainable alternative import path.
* Deterministic normalization and card matching.
* Previewable, idempotent synchronization.
* Future destination adapters beyond Dex.
* A possible browser extension after the core import, matching, and sync logic is proven.

Accuracy and user-data safety are more important than speed or feature breadth.

---

## Instruction Priority

Follow instructions in this order:

1. The user's current request.
2. The closest applicable `AGENTS.md` or `AGENTS.override.md`.
3. Repository documentation and accepted project conventions.
4. This file.

Do not weaken a safety, testing, or approval requirement unless the user explicitly authorizes that specific exception.

---

## Operating Principles

* Understand before editing.
* Keep changes small and directly related to the request.
* Prefer simple, explicit code over clever abstractions.
* Reuse established repository patterns before creating new ones.
* Preserve existing behavior unless the task explicitly changes it.
* Never fabricate APIs, schemas, commands, test results, or external-service behavior.
* Distinguish verified facts from assumptions.
* Surface blockers and uncertainty clearly.
* Do not silently expand the task.
* Do not perform unrelated cleanup in a feature or bug-fix change.
* Do not optimize prematurely.
* Never trade collection accuracy for implementation convenience.

When requirements are ambiguous but a safe, reversible interpretation exists, make the smallest reasonable assumption and document it. Ask the user only when the ambiguity could cause destructive behavior, data loss, a public API change, a security problem, or substantial rework.

---

## Repository Discovery

Before changing code:

1. Read this file and any more-specific agent instructions.
2. Inspect the repository status and top-level structure.
3. Read the files directly related to the requested behavior.
4. Identify the package manager, runtime, frameworks, and existing commands from repository files.
5. Locate relevant tests before implementing.
6. Inspect nearby implementations and conventions.
7. Check current uncommitted changes and preserve work that is not yours.

Useful initial commands may include:

```sh
git status --short
git diff --stat
git diff
find .. -name AGENTS.md -o -name AGENTS.override.md
```

Use repository-defined commands rather than inventing new ones. Inspect files such as:

* `package.json`
* lockfiles
* workspace configuration
* build configuration
* test configuration
* lint and formatter configuration
* CI workflows
* `README.md`
* architecture or design documentation

Do not read the entire repository when targeted inspection is sufficient.

---

## Planning

For a localized, low-risk change, work directly.

Create or update an execution plan before implementation when work:

* spans multiple subsystems;
* changes schemas, sync semantics, or public interfaces;
* requires a migration;
* introduces a new integration or adapter;
* is destructive or difficult to reverse;
* is expected to require several independently testable stages;
* contains unresolved architectural decisions.

A useful plan states:

* the goal;
* relevant existing behavior;
* files or components likely to change;
* implementation stages;
* validation for each stage;
* important risks and assumptions;
* any decisions that require human approval.

Keep plans concise and update them when reality differs from the original approach. Do not continue following a plan that has been disproven by the codebase.

---

## Architecture Boundaries

Keep the core synchronization logic independent from delivery mechanisms and external-service details.

Prefer boundaries equivalent to:

```text
Collectr input
    -> source parser
    -> normalized collection model
    -> identity resolution
    -> sync plan / diff
    -> destination adapter
    -> Dex or another destination
```

The exact folder names may differ, but preserve these conceptual separations.

### Core domain

The core domain should not depend directly on:

* browser-extension APIs;
* UI frameworks;
* scraping libraries;
* filesystem-specific behavior;
* Dex transport details;
* Collectr page markup;
* a particular CSV parser.

### Source adapters

Source adapters convert external Collectr data into normalized internal records.

A source adapter must not directly write to Dex.

### Destination adapters

Destination adapters translate an approved sync plan into destination-specific operations.

A destination adapter must not redefine card identity or normalization rules.

### User interface

The UI should orchestrate and explain operations, not contain authoritative parsing, matching, or sync logic.

### Browser automation

Treat browser automation and scraping as replaceable boundary integrations. Isolate selectors, page assumptions, authentication handling, throttling, and extraction logic from the domain layer.

---

## Domain Invariants

Preserve these invariants unless the user explicitly approves a design change.

### Source of truth

* Collectr is authoritative for managed collection state.
* Destination-only records must not be deleted merely because they are absent from an incomplete or failed import.
* Any merge behavior that departs from source-authoritative synchronization must be explicit.

### Identity

Do not assume a card name alone identifies a card.

Identity may depend on:

* game;
* set;
* set code;
* collector number;
* variant;
* printing;
* finish or foil treatment;
* language;
* edition;
* promotional status;
* grading state;
* other source-specific identifiers.

Keep identity resolution separate from mutable collection attributes such as quantity or condition.

### Quantities

* Quantities must never become negative.
* Missing quantity data must not silently become zero.
* Duplicate source rows must be handled deterministically.
* Quantity aggregation rules must be explicit and tested.

### Conditions and metadata

Do not silently collapse condition, language, finish, edition, grading, or variant distinctions unless the limitation is documented and surfaced to the user.

### Idempotency

Applying the same source state repeatedly should converge on the same destination state.

A successful retry must not:

* duplicate cards;
* multiply quantities;
* repeat one-time destructive actions;
* produce different mappings without new input or configuration.

### Determinism

Given the same:

* source data;
* destination state;
* mapping rules;
* configuration;
* application version;

the generated sync plan should be equivalent.

Do not introduce time, iteration order, network ordering, or random behavior into matching decisions unless explicitly controlled.

### Partial failure

A partial failure must not be presented as full success.

Where practical:

* build and validate the complete sync plan before applying it;
* track operations individually;
* make retries safe;
* preserve enough information to explain what succeeded and failed;
* avoid leaving the destination in a silently inconsistent state.

### Destructive changes

Deletion, quantity reduction, replacement, and broad remapping are destructive operations.

They require:

* an explicit sync-plan representation;
* a human-readable preview;
* clear counts and affected records;
* confirmation before application;
* tests covering accidental and repeated execution.

Default to dry-run behavior when a workflow is incomplete or uncertain.

---

## Matching Policy

Card matching is a high-risk subsystem.

Use the strongest stable identifiers available. Prefer exact, source-backed identifiers over fuzzy text matching.

A matching pipeline should generally distinguish:

1. Exact known identifier matches.
2. Exact normalized composite-key matches.
3. Explicitly maintained aliases or mapping overrides.
4. Carefully constrained fallback matching.
5. Unresolved or ambiguous records.

Never silently choose among multiple plausible candidates.

Ambiguous matches must become reviewable results, not guessed successes.

For every mapping outcome, preserve enough information to explain:

* the source record;
* the selected destination record;
* the rule that matched them;
* confidence or match class;
* why alternatives were rejected;
* whether user confirmation is required.

Any fuzzy matching must be:

* bounded;
* deterministic;
* separately testable;
* observable;
* disabled for destructive automatic synchronization unless confidence requirements are satisfied.

---

## Import Requirements

All import paths must converge on the same normalized model.

### CSV and exported files

* Treat external files as untrusted input.
* Validate headers and required fields.
* Handle encoding, quoting, delimiters, blank rows, and malformed values.
* Report row-level errors with safe context.
* Do not log entire user files by default.
* Keep parsing separate from normalization.
* Add fixtures for realistic and malformed exports.

### Free-user import path

A free-user path must not be a lower-integrity implementation.

If it uses browser extraction or automation:

* isolate selectors and page parsing;
* minimize requests and avoid aggressive crawling;
* respect authentication and session boundaries;
* never collect credentials directly when a safer session mechanism exists;
* avoid storing session secrets;
* detect unexpected page structures;
* fail closed rather than importing uncertain data;
* provide actionable diagnostics without exposing sensitive page content.

Do not implement behavior intended to bypass access controls, anti-bot protections, rate limits, or service restrictions.

### Compatibility

CSV and free-user imports representing the same collection should normalize into equivalent records. Add parity tests where fixtures allow it.

---

## External Services

Treat Collectr, Dex, and other external interfaces as unstable boundaries.

* Verify behavior from repository fixtures, captured contracts, or authoritative documentation.
* Do not guess undocumented endpoints or payload fields.
* Keep transport models separate from domain models.
* Validate responses at runtime.
* Set explicit timeouts.
* Handle rate limiting and transient failures.
* Use bounded retries with backoff where appropriate.
* Do not retry permanent validation or authorization failures blindly.
* Make write requests idempotent when the service supports it.
* Avoid logging tokens, cookies, full payloads, or personal collection data.

Tests must not depend on live external services unless they are explicitly designated integration tests and safely configured.

---

## Security and Privacy

Assume collection data, account identifiers, exports, cookies, and tokens are private.

Never:

* commit secrets;
* print secrets to logs;
* place credentials in URLs;
* expose authentication data in errors;
* store raw credentials;
* weaken TLS verification;
* execute imported content;
* trust filenames or external paths;
* use unsafe deserialization;
* add telemetry without explicit approval;
* send user data to a new third party without explicit approval.

Use environment variables or the project's established secret-management mechanism.

Any test fixture derived from real user data must be anonymized and minimized.

Review dependency additions for:

* maintenance status;
* license compatibility;
* install footprint;
* transitive risk;
* whether the standard library or an existing dependency is sufficient.

Do not add a dependency for trivial functionality.

---

## Implementation Standards

### Scope

* Make the smallest coherent change that fully solves the request.
* Avoid drive-by formatting and renaming.
* Do not change generated files manually unless the repository requires it.
* Do not modify lockfiles unless dependency resolution actually changes.
* Do not alter public APIs incidentally.
* Remove obsolete code only when the task makes it obsolete and tests prove removal is safe.

### Types and validation

* Prefer precise types over broad casts.
* Avoid `any`, unchecked casts, and non-null assertions unless justified.
* Validate data at external boundaries.
* Represent invalid, unresolved, and ambiguous states explicitly.
* Do not use exceptions as ordinary control flow when the project has a clearer result type or error convention.

### Errors

Errors should explain:

* what operation failed;
* which safe identifier is relevant;
* whether retrying may help;
* what the user or caller can do next.

Preserve underlying causes where the language supports it. Do not expose secrets or excessive user data.

### Logging

Use structured, appropriately leveled logging.

Never log:

* access tokens;
* cookies;
* authorization headers;
* raw credentials;
* full private exports;
* unnecessary personal collection details.

Logs for sync operations should favor counts, safe identifiers, stages, and outcomes.

### Comments

Comments should explain intent, invariants, external constraints, or non-obvious tradeoffs. Do not narrate straightforward syntax.

### Documentation

Update documentation when a change affects:

* setup;
* configuration;
* environment variables;
* commands;
* architecture;
* import formats;
* sync behavior;
* destructive-operation semantics;
* supported or unsupported cases.

---

## Testing Strategy

Tests are part of the implementation, not optional follow-up work.

For behavior changes:

1. Add or update a test that demonstrates the required behavior.
2. Confirm the test meaningfully exercises the changed path.
3. Implement the smallest correct change.
4. Run the focused test.
5. Run the broader relevant suite.
6. Run all repository-required checks before completion.

A regression fix should include a test that fails without the fix whenever practical.

### Priority test areas

Give especially strong coverage to:

* card identity resolution;
* set and collector-number normalization;
* variants, finishes, languages, editions, and conditions;
* duplicate source rows;
* quantity changes;
* empty and malformed imports;
* CSV/free-import parity;
* ambiguous matches;
* unresolved cards;
* idempotent repeated sync;
* interrupted and retried sync;
* partial destination failure;
* dry-run behavior;
* destructive-operation confirmation;
* authentication and redaction;
* external-response validation.

### Test quality

Tests should verify behavior, not merely implementation details.

Avoid:

* assertions that cannot fail meaningfully;
* snapshots for complex domain behavior when explicit assertions are clearer;
* excessive mocking of the logic under test;
* tests whose success depends on execution order;
* live-network dependencies in normal test suites;
* rewriting tests solely to accommodate an incorrect implementation.

Use fixtures that are small, readable, anonymized, and representative.

### Property and invariant tests

Where supported by the stack, consider property-based or table-driven tests for normalization, matching, quantities, and idempotency.

Important properties include:

```text
normalize(normalize(x)) == normalize(x)

plan(source, destination) == plan(source, destination)

apply(plan(source, destination), destination) converges to source policy

apply(same_plan_twice) does not duplicate effects
```

Adapt these expressions to the actual domain semantics rather than copying them mechanically.

---

## Validation Commands

Discover commands from the repository. Do not assume a package manager or script name.

Before reporting completion, run all applicable existing checks, typically including:

* formatting verification;
* linting;
* static analysis;
* type checking;
* unit tests;
* integration tests;
* build;
* generated-file or schema checks;
* relevant end-to-end tests.

Prefer the repository's CI-equivalent command when one exists.

If the full suite is too costly for an intermediate iteration, run focused checks first, but run all required checks before committing.

Never claim a command passed unless it was actually executed successfully in the current working state.

When a check cannot run:

* state the exact command;
* explain why it could not run;
* report any checks that did run;
* do not describe the change as fully validated.

Do not bypass failures by:

* disabling tests;
* weakening assertions;
* adding blanket ignores;
* suppressing type errors;
* changing lint configuration;
* deleting failing coverage;
* using force flags;

unless the task specifically requires that change and the reason is documented.

---

## Working Tree Safety

The repository may contain user work or changes from another agent.

* Inspect `git status` before editing.
* Do not discard changes you did not create.
* Do not use `git reset --hard`.
* Do not use `git clean -fd`.
* Do not overwrite files merely to restore them.
* Do not rewrite history.
* Do not force push.
* Do not amend an existing commit unless the user explicitly requests it.
* Avoid stashing user changes unless explicitly requested.
* Keep edits compatible with unrelated local changes where possible.

If another change overlaps the task, preserve it and work around it. Explain a genuine conflict rather than destroying work.

---

## Git and Commit Policy

The agent may commit and push completed, validated, in-scope work without separate user authorization unless the user explicitly asks it not to.

A commit is permitted only when all of the following are true:

1. The requested implementation is complete.
2. The diff has been reviewed for accidental changes.
3. Applicable validation has passed.
4. The working tree contains no unexplained changes.
5. The agent has summarized the result and validation.

Design decisions that materially affect product behavior, architecture, destructive synchronization policy, external-service risk, or dependency adoption still require explicit user approval before implementation.

Before committing:

* review the diff and status again;
* stage only intended files;
* create one focused commit unless the user requests otherwise;
* report the resulting commit summary.

After a successful commit, the agent may push the current branch unless the user asks it not to or the task requires preserving the commit locally. Never force push.

Do not create, update, or merge a pull request unless explicitly requested.

---

## Pull Request Preparation

When asked to prepare a pull request:

* ensure the branch is focused;
* compare against the correct base branch;
* review the entire PR diff, not only the latest edit;
* run required validation;
* identify migration or rollout concerns;
* update relevant documentation;
* write a factual description.

A pull-request description should include:

```md
## Summary

## Why

## Implementation

## Validation

## Risks and limitations

## Screenshots or examples
```

Include screenshots or examples only when relevant.

Do not claim that an AI review, CI check, or human approval occurred unless it actually occurred.

---

## Independent Pull Request Review Mode

When the task is to review a pull request, switch from implementation mode to independent review mode.

The review must begin with fresh context. Do not rely on the implementation agent's hidden reasoning, prior conversation, confidence, or summary as evidence of correctness.

Use only:

* the task or issue;
* the PR description;
* applicable repository instructions;
* the checked-out repository;
* the base branch;
* the complete PR diff;
* tests and documentation;
* verified external contracts when needed.

### Reviewer restrictions

Unless the user explicitly requests a separate fix pass, the reviewer must not:

* edit files;
* generate a corrective patch;
* commit;
* push;
* approve the PR;
* merge;
* dismiss findings;
* change tests to make the PR pass.

The reviewer's job is to identify and explain material issues independently.

### Review procedure

1. Read the task, PR description, and repository instructions.
2. Determine the intended base and head revisions.
3. Inspect the complete diff.
4. Read directly related surrounding code.
5. Identify affected invariants and callers.
6. Inspect existing and changed tests.
7. Run focused checks when useful.
8. Test concrete failure hypotheses.
9. Report only verified, actionable findings.
10. State the final advisory verdict.

Do not stop after reading the diff when understanding a change requires nearby code, schemas, callers, or tests.

### Review priorities

Review in this order:

1. Data loss or corruption.
2. Incorrect synchronization behavior.
3. Incorrect card identity resolution.
4. Authentication, secret, or privacy exposure.
5. Non-idempotent or unsafe retries.
6. Destructive behavior without preview or confirmation.
7. Partial-failure inconsistencies.
8. Regressions in existing import paths.
9. Incorrect external-service assumptions.
10. Missing tests that conceal a material defect.
11. Significant performance or reliability regressions.
12. Maintainability problems likely to cause correctness issues.

Do not report:

* personal style preferences;
* harmless naming differences;
* formatting covered by automated tools;
* speculative concerns without a plausible failure path;
* unrelated pre-existing problems;
* broad refactoring ideas that are not required for correctness.

### CardRelay review checklist

Verify whether the change:

* preserves Collectr as the declared source of truth;
* distinguishes sets, collector numbers, variants, finishes, languages, editions, and conditions correctly;
* avoids card-name-only identity matching;
* handles duplicates and quantities deterministically;
* keeps CSV and free-user inputs compatible at the normalized layer;
* exposes ambiguous matches rather than guessing;
* produces an inspectable sync plan;
* remains idempotent across repeated runs;
* makes retries safe;
* reports partial failures accurately;
* protects tokens, cookies, exports, and collection data;
* avoids undocumented external-service assumptions;
* includes meaningful tests that would fail for a subtly incorrect implementation.

### Finding standard

Every finding must include:

* severity;
* relevant file and line or smallest useful range;
* concise defect description;
* concrete failure scenario;
* expected behavior;
* evidence from the code or a reproducible check.

Use these severities:

* **P0 — Critical:** Immediate widespread data loss, secret compromise, or unusable system.
* **P1 — High:** Likely data corruption, security failure, or major broken workflow.
* **P2 — Medium:** Material correctness or reliability defect under realistic conditions.
* **P3 — Low:** Limited but real defect worth fixing; do not use for style preferences.

Prefer fewer high-confidence findings over many weak possibilities.

A missing test is a finding only when it leaves material changed behavior unverified. Explain what defect the missing test could allow.

### Review output

Use this structure:

```md
## Findings

### [P1] Concise finding title

`path/to/file.ext:line`

Explain the concrete failure, triggering conditions, evidence, and expected behavior.

## Questions

Only include questions that block a confident assessment.

## Validation performed

List code paths inspected and commands actually run.

## Verdict

BLOCK | CONCERNS | PASS

Brief rationale.
```

Verdict meanings:

* **BLOCK:** At least one verified P0 or P1 issue, or another defect that makes merging unsafe.
* **CONCERNS:** Material P2/P3 issues, incomplete validation, or unresolved risk requiring human judgment.
* **PASS:** No material issue was found in the reviewed scope.

`PASS` means no material defect was found. It does not prove correctness and never authorizes merging.

---

## Self-Review Before Completion

Before presenting implementation work:

1. Read the full diff.
2. Remove accidental edits and debug output.
3. Check for secrets or sensitive fixture data.
4. Verify error and edge-case behavior.
5. Confirm tests exercise the intended behavior.
6. Confirm documentation matches the implementation.
7. Run required checks.
8. Inspect `git status`.
9. Summarize limitations honestly.

Ask:

* Could this lose, duplicate, or misidentify a card?
* Could retrying produce a different result?
* Could malformed or partial input be mistaken for an empty collection?
* Could an ambiguous match be applied automatically?
* Could a failure be reported as success?
* Could private data appear in logs or committed fixtures?
* Did the implementation change behavior outside the requested scope?
* Would the test fail if the implementation were subtly wrong?

Resolve discovered issues before committing.

---

## Completion Report

End implementation tasks with:

```md
## Completed

- What changed
- Why this approach was used

## Validation

- `command` — passed
- `command` — passed

## Remaining considerations

- Known limitation, follow-up, or `None`

## Git status

- Commit and push status
```

Keep the report factual and concise.

Do not say:

* “fully tested” when only focused tests ran;
* “production-ready” without evidence;
* “backward compatible” without checking;
* “no regressions” merely because tests passed;
* “done” while required validation is failing.

---

## Human Authority

The user remains the final authority over:

* product behavior;
* architecture;
* destructive sync policy;
* external-service risk;
* dependency adoption;
* pull-request creation;
* approvals;
* merges;
* releases.

Routine validated commits and pushes do not require separate approval. The agent may recommend a design decision but must not impersonate human approval for one.

No AI-generated review, test result, or confidence statement overrides the requirement for explicit human authorization on design decisions or destructive external actions.
