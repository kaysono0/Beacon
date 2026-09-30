# Repository Guidelines

## Truth and Workflow Authority

Beacon keeps each durable fact in one owner:

- `CONTEXT.md`: project terminology and boundaries.
- `.private/TODO.md`: user-maintained todo list only; it does not select, order, or authorize work.
- `.private/docs/status.md`: current progress, gaps, impact, and direction; never a second queue.
- `.private/docs/status-history.md`: completed-work history only.
- `.private/docs/architecture/` and `.private/docs/adr/`: architecture and confirmed decisions.
- `.private/docs/workflows/`: validation and review contracts.
- `.private/docs/ai/ai_context.md`: quick context only; it must not define task state or workflow policy.
- `.private/docs/knowledge/`: indexed, reusable experience only; it does not own architecture, validation rules, or current status.
- `.private/docs/ai/ai_sessions.md`: private conversation material; update it only at the user's explicit request.

The governance documents under `.private/docs/` are local and Git-ignored. Public guides under `docs/` do not own project status, architecture, or workflow policy.

`AGENTS.md` defines collaboration and truth ownership. Validation commands and result semantics belong to `.private/docs/workflows/ci_validation_contract.md`; completion checks belong to `.private/docs/workflows/review_checklist.md`.

Domain documentation is rooted at `CONTEXT.md` and `.private/docs/adr/`.

## Context and Execution

The user's explicit request selects work; a referenced Issue or private spec supplies its detailed scope. Read only the relevant context, design, and validation documents. For code changes, follow `.private/docs/standards/coding_guidelines.md`; review non-trivial changes with `.private/docs/workflows/review_checklist.md` before claiming completion. Test and coverage changes must follow the test-effectiveness and source-completeness rules in `.private/docs/workflows/ci_validation_contract.md`; percentages or smoke alone do not establish correctness.

Before running or diagnosing real-media validation, read `.private/docs/knowledge/real-media/README.md` and open only a short topic whose symptom matches the current risk or failure. If none matches, continue from current reports and formal contracts; historical experience never supplies this run's verdict. If a real-media failure required diagnosis, record one pilot row using `.private/docs/knowledge/evaluation.md` before the final response, including when the cause remains unknown, and cite that local record in the final response. Do not load the evaluation page at task start.

Resolve questions that materially change design, verification, truth ownership, authority, or safety before editing. Continue authorized work when ordinary implementation details, rework, or fixable verification issues arise.

Use `.private/docs/standards/comment_guidelines.md` for added or revised comments. Beacon code comments are Chinese unless the file or external API contract requires otherwise.

Validation commands, reports, skipped semantics, and failure handling are owned by `.private/docs/workflows/ci_validation_contract.md`. Report failed checks and their impact accurately; do not claim a required check passed when it failed or was skipped.

When formal truth conflicts, stop that branch, identify its canonical owner, resolve the fact there, then align dependent summaries. When the user corrects formal design knowledge, get approval before changing formal design documents and update the affected status in the same change.

## Writeback and Closure

When a change alters current status, architecture, contracts, validation, platform behavior, security/logging rules, or workflow policy, update the affected canonical documents. Record durable completed work in `.private/docs/status-history.md`; capture ADR-worthy decisions in `.private/docs/adr/`.

Before closing non-trivial work:

- record concrete durable remaining work in its owning issue or private spec, and its current consequence in `.private/docs/status.md` when applicable; update `.private/TODO.md` only at the user's explicit request;
- add a review-log entry only for a reusable review, validation, or implementation lesson;
- preserve unrelated user changes and report actual verification evidence and gaps;
- state explicitly when no remaining work exists.
