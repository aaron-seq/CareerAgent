# Project status and continuation

Checkpoint: 2026-11-02 (Asia/Kolkata). Current cleanup is
[#95](https://github.com/aaron-seq/CareerAgent/issues/95), branch
`codex/95-maintenance-cleanup`, based on main
[`627a8b3`](https://github.com/aaron-seq/CareerAgent/commit/627a8b34fcdce134a0a922665902b0855c147184).
The [private cleanup and bug-review Project](https://github.com/users/aaron-seq/projects/8)
tracks this pass. [PR #100](https://github.com/aaron-seq/CareerAgent/pull/100)
contains the implementation, measured changes and current checks. It remains
draft and unmerged; [milestone 3](https://github.com/aaron-seq/CareerAgent/milestone/3)
stays open until reviewed delivery is merged.
The retry exposed dependency advisories.
[#101](https://github.com/aaron-seq/CareerAgent/issues/101) tracks the reviewed
pypdf/pyasn1 patch repair; retain its security floors and the strict audit gate.

<a id="resume-editor"></a>

## Delivered and active work

- [Resume editor PR #90](https://github.com/aaron-seq/CareerAgent/pull/90) is
  merged, including literal TeX punctuation and combining-accent fixes #91/#94.
  [Post-merge CI](https://github.com/aaron-seq/CareerAgent/actions/runs/40927437036)
  passed 954 Python tests on each Linux 3.11/3.12/3.13 graph, 63 Node tests,
  lint/type, dependency audits and the functional Docker check. These are
  published CI results. [Usage](docs/USAGE.md) owns editor and manual Overleaf
  import instructions; no live Overleaf account or ATS service test is implied.
- This cleanup consolidates the roadmap, extension handoff and phase template;
  corrects stale navigation and the US dataset example; removes one private
  unused helper; and excludes five exact maintenance docs from the runtime
  image. Runtime code/assets, licenses, migrations and unrelated dependency
  pins remain.
- Retain historical validation reports, screenshots, ADRs and instructions.
  Local credentials, personal files, databases, downloaded datasets and caches
  are preserved. Image/clone size savings are not claimed without measurement.

<a id="validation-and-limits"></a>

## Validation and follow-ups

Baseline: 216 tracked files / 4,129,405 Git-blob bytes; 16,312 maintained source
lines; 32 Markdown files / 23,728 whitespace words; Git-archive ZIP 1,960,632
bytes. #95's PR records same-scope final metrics and checks.

Native lint/format, type and Node checks passed during cleanup. The earlier
Windows import restriction did not recur: a retry collected all 954 tests
without changing OS policy. Collection alone does not execute tests; use
[#101](https://github.com/aaron-seq/CareerAgent/issues/101) and
[PR #100](https://github.com/aaron-seq/CareerAgent/pull/100) for the full native
retry's actual results and environment. Agent-run strict pip-audit 2.10.1
passed all three updated graphs (97/96/96 packages, zero advisory rows/skips).
The [PR checks](https://github.com/aaron-seq/CareerAgent/pull/100/checks) own
final-head validation of the frozen Linux graphs and runtime image. Local
Docker's Linux daemon is unavailable. Alternate-graph bug reproductions are
identified separately in their issues.

Three agents covered baseline/checks, core bugs/dead code, and docs/packaging.
The orchestrator reran #96–#99 and reviewed the complete diff. Reviews are
delegated system perspectives, not independent human approval.

Existing write-failure issues [#89](https://github.com/aaron-seq/CareerAgent/issues/89),
[#92](https://github.com/aaron-seq/CareerAgent/issues/92) and
[#93](https://github.com/aaron-seq/CareerAgent/issues/93), location identity
[#67](https://github.com/aaron-seq/CareerAgent/issues/67)/[#75](https://github.com/aaron-seq/CareerAgent/issues/75),
and new import/company/salary/download findings
[#96](https://github.com/aaron-seq/CareerAgent/issues/96)–[#99](https://github.com/aaron-seq/CareerAgent/issues/99)
are follow-ups in Project 8. Security prerequisites
[#38](https://github.com/aaron-seq/CareerAgent/issues/38),
[#41](https://github.com/aaron-seq/CareerAgent/issues/41) and
[#42](https://github.com/aaron-seq/CareerAgent/issues/42) remain separate.

<a id="prior-work-and-continuation"></a>

## Continuation

The editor and earlier cleanup goals are complete in merged PRs #90 and #86.
Bug discovery and GitHub reporting are complete; the linked fixes remain Todo.
Review #100's final diff, checks and retained evidence before merging it.
No deployment or data migration is part of this cleanup. Reverting its
documentation/packaging must preserve #101's security floors and locks or a
separately reviewed safe successor. Prior editor/compiler/browser evidence and
earlier cleanup measurements
remain in the [previous checkpoint](https://github.com/aaron-seq/CareerAgent/blob/627a8b34fcdce134a0a922665902b0855c147184/PROGRESS.md)
and [Project 7](https://github.com/users/aaron-seq/projects/7).
