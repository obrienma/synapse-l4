---
id: synapse-l4-2026-07-18T2026-saas-domain-support
repo: synapse-l4
title: "Add saas to ComplianceDomain"
date: 2026-07-18
tags: [compliance-domain, structured-generation, single-source-of-truth, cross-repo-dependency]
files: [src/models/axiom.py, src/nodes/extractor.py, src/models/axiom_test.py]
---

### Challenge: Three independent enumerations of the same closed set

Widening `ComplianceDomain`'s `Literal` to include `"saas"` wasn't sufficient on its own. Grepping for every place the domain set is checked surfaced two more independent copies: `extractor.py`'s `_VALID_DOMAINS` frozenset (consulted by `_valid_domain()` to sanitise untrusted values before constructing an `AxiomDraft`) and the LLM extraction prompt's own text enumerating valid domains for the unstructured-payload fallback path. Neither derives from the `Literal` — each was hand-written at its own call site when the domain concept was first introduced. Missing either would have left `"saas"` in an inconsistent state: valid at the type level but rejected at runtime (stale frozenset), or never proposed by the LLM even though it's a legal value (stale prompt). Fixed all three in the same change, and extended the existing exhaustive parametrized test (`test_axiom_accepts_valid_domain`) to cover `"saas"` so a future omission of the `Literal` or the frozenset has a chance of being caught — a stale prompt wouldn't be, since Instructor's deterministic fast path bypasses the LLM entirely for already-structured payloads like this one.

### Decision: Leave the duplication in place, don't refactor to a single source of truth now

Fixed all three call sites by hand rather than introducing something like `typing.get_args(ComplianceDomain)` to derive `_VALID_DOMAINS` and the prompt text from the `Literal` directly. A real fix would eliminate this class of omission permanently, but doing it as a side effect of an unrelated one-value domain addition would have expanded the diff's blast radius for a fix that didn't ask for it. Deferred until the duplication actually causes a real bug — consistent with "wait until it hurts" rather than fixing speculatively. Recorded as a `CLAUDE.md` "Known Challenges & Gotchas" entry so the next domain addition doesn't rediscover this from scratch.

### Decision: No new ADR for this change

Treated this as exercising an already-decided extension point — `axiom.py`'s own comment says "Extend this Literal as new policy corpora are added" — rather than a new architectural decision requiring its own ADR. Keeps the ADR log reserved for decisions with real alternatives actually weighed, not every mechanical use of an already-open extension point. The cost: the "three places, not one" gotcha found here is recorded only in `CLAUDE.md` and this journal entry, not as its own discoverable ADR — acceptable since it's an implementation detail, not an architecture decision.
