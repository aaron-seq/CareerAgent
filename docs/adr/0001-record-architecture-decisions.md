# 1. Record architecture decisions

- Status: Accepted
- Date: 2026-07-23

## Context

As CareerAgent grows from a single-file Streamlit prototype into a phased
platform (see `ROADMAP.md`), significant technical decisions will accumulate.
Work happens across many short, resumable sessions. Without a durable record of
*why* choices were made, future sessions (human or AI) re-litigate settled
questions and lose context.

## Decision

We will keep Architecture Decision Records (ADRs) in `docs/adr/`, one Markdown
file per significant decision, numbered sequentially
(`NNNN-title-in-kebab-case.md`). Each ADR states Context, Decision, and
Consequences, and carries a Status (Proposed / Accepted / Superseded) and Date.

An ADR is required whenever a phase makes a significant or hard-to-reverse
decision (per the Definition of Done in `CLAUDE.md`). Superseded ADRs are kept
for history and marked as such, linking to the ADR that replaces them.

The format is a lightweight variant of Michael Nygard's ADR template.

## Consequences

- Decisions and their rationale are discoverable in-repo and version-controlled.
- Onboarding (and stateful AI resumption) is faster.
- Small overhead: contributors must write an ADR for significant choices, and
  keep the numbering sequential.
