# 5. Cloud LLM provider (Groq) available for PII-heavy work, opt-in

- Status: Accepted
- Date: 2026-07-27

## Context

ADR 0002 set the guardrail: "Ollama local LLM by default (PII-safe); cloud
free tiers (Gemini/Groq) only for non-PII burst work." In practice, testing
the app end-to-end on a machine without Ollama installed surfaced the real
cost of that guardrail: Ollama requires installing a separate runtime and
pulling multi-GB model weights before the app does anything at all. For a
first run, or a machine where installing new system software isn't wanted,
that is a hard stop — every screen in the UI is gated behind a working LLM
connection.

CV parsing and cover-letter generation are exactly the PII-heavy work ADR
0002 reserved for the local LLM. There was no non-PII path to route around
this: the entire onboarding flow needs to read the CV.

## Decision

Add `CloudLLMClient` in `core/llm.py` as an OpenAI-compatible cloud provider
(Groq's free tier by default: no credit card, serves the Llama family the
existing prompts are already tuned for). It subclasses `LocalLLMClient` and
overrides only the three HTTP-touching methods (`check_connection`,
`list_models`, `generate_text`); JSON cleaning, retry, and schema validation
are inherited unchanged, since every caller reaches the LLM through that
shared pipeline.

Unlike ADR 0002's original framing, this is **not** restricted to non-PII
work. The sidebar lets the user pick Ollama or Groq for any operation,
including CV parsing and cover-letter drafting. This is a deliberate
deviation, made explicit rather than silently building around the guardrail:

- The choice is **opt-in** — Ollama remains the default provider.
- The tradeoff is **surfaced at the point of choice**: the sidebar shows a
  caption when Groq is selected ("Prompts leave this machine..."), the
  `CloudLLMClient` docstring states it plainly, and `.env.example` repeats it
  next to `GROQ_API_KEY`.
- Nothing is fabricated or hidden: the user sees exactly which provider is
  connected before any PII-bearing prompt is sent.

## Consequences

- The app now has a genuine zero-install path to a working end-to-end demo
  (sign up for a free Groq key, paste it into `.env`), which matters for
  first-run adoption and for testing on machines without Ollama.
- The local-first privacy guarantee in `CLAUDE.md` and ADR 0002 is now a
  *default*, not an *invariant* — a user who picks Groq for CV parsing does
  send resume content to a third party. This is a real, not cosmetic,
  weakening of the original guardrail, accepted because the alternative
  (Ollama-only) makes the app unusable without a multi-GB local install.
- If a future phase adds multi-user or hosted deployment, this decision
  needs revisiting: an operator silently defaulting all users to a cloud
  provider would violate the spirit of ADR 0002 even though each individual
  choice is opt-in today. The guardrail this ADR narrows is: cloud calls
  must remain a **visible, per-user, per-session choice**, never a
  default flipped once for everyone.
- `core/llm.py` now has two classes to keep behaviorally identical from the
  caller's perspective (same `generate_json`/`generate_with_schema` surface);
  any new capability added to one needs the same duck-typed shape on both,
  or callers doing `isinstance` checks will need updating — none do today.
