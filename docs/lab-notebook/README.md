# G1 Jev Swarm Lab — Research Lab Notebook

This directory records **how the research evolved**, not only the final successful numbers.

The machine-readable experiment evidence remains authoritative for measured facts:

```text
protocol
→ source revision
→ run manifest
→ metrics
→ events
→ aggregate
→ report
```

The lab notebook adds the missing research context:

```text
question
→ hypothesis
→ difficulty
→ failed attempt
→ diagnosis
→ intervention
→ measured result
→ limitation
→ next decision
```

## Important provenance note

As of 2026-10-06, the GitHub remote only contains the original Phase 0 repository baseline. The implementation/evidence branches for Phases 1–2.1 were completed locally by Codex but have not yet been pushed because the local machine has no GitHub CLI, SSH key, or cached HTTPS credentials.

Therefore, the entries in this notebook are a **faithful reconstruction from the completed local experiment reports**, including their branch names, commit SHAs, protocol hashes, measured results, negative findings, and audits. They do **not** claim that the corresponding raw artifacts are already present on the GitHub remote.

Once those experiment branches are pushed, this notebook should link directly to the relevant code, reports, and artifacts.

## Visual entry point

- [Visual research summary](visual-summary.md) — timeline, experiment comparisons, integrity flow and architecture.

## Notebook map

- [Research timeline](timeline.md)
- [Phase 1 — Embodied execution layer](phase1-embodied-execution.md)
- [Phase 2 — Mission runtime and language](phase2-mission-language.md)
- [Phase 2.2 — LLM Mission Compiler](phase2.2-llm-compiler.md)
- [Negative results and failed hypotheses](negative-results.md)
- [Integrity incidents and corrections](integrity-incidents.md)
- [Research decisions](research-decisions.md)

## Recording rule going forward

Every completed research phase should add an entry containing:

1. **Question** — what we wanted to know.
2. **Baseline** — exact branch / commit / frozen protocol.
3. **Hypothesis** — what we expected before running the experiment.
4. **Difficulty** — what blocked or complicated the experiment.
5. **Reasoning** — why a particular intervention was chosen.
6. **Intervention** — exactly what changed.
7. **Result** — measured result, including negative results.
8. **What did not work** — failed attempts, confounders, bugs.
9. **What we cannot claim** — explicit interpretation boundary.
10. **Decision** — why the project moved to the next phase.
11. **Evidence pointers** — protocol hash, source SHA, report and artifact path.

A polished demo without this chain is not treated as research evidence.
