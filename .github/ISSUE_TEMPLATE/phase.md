---
name: Roadmap phase
about: Track a phase of the CareerAgent roadmap (see ROADMAP.md)
title: "[Phase N] <short title>"
labels: ["roadmap"]
assignees: []
---

## Phase
<!-- Which roadmap phase is this? e.g. "Phase 1 — Data layer". See ROADMAP.md. -->

## Goal
<!-- One or two sentences on what this phase delivers and why. -->

## Scope / tasks
<!-- Concrete, checkable units of work. -->
- [ ]
- [ ]
- [ ]

## Acceptance criteria
<!-- Copy the phase's AC from ROADMAP.md and make each item checkable. -->
- [ ]
- [ ]

## Definition of done (every phase)
- [ ] Code complete
- [ ] Tests added and green (`pytest`); external APIs mocked
- [ ] Lint clean (`ruff check .`) and formatted (`ruff format --check .`)
- [ ] Docs updated (README / ARCHITECTURE as needed)
- [ ] `PROGRESS.md` updated (status + next action)
- [ ] ADR added under `docs/adr/` if a significant decision was made

## Guardrails check (see CLAUDE.md)
- [ ] Human-in-the-loop preserved before any submit action (if applicable)
- [ ] APIs/JSON-LD preferred over scraping; robots.txt + rate limits honored
- [ ] No fabricated candidate data; PII kept local/encrypted where applicable

## Notes / links
<!-- ADRs, research references (docs/RESEARCH.md), related issues/PRs. -->
