---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, compliance-domain]
---
synapse-l4's `ComplianceDomain` Literal currently allows `aml`, `gdpr`, `hipaa`, and {{c1::saas}} — the last added to support Xylem-L6's SaaS API activity integration (ADR-0007).

Extra: synapse-l4 · Decision: No New ADR
See: docs/journal/synapse-l4-2026-07-18T2026-saas-domain-support.md

---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, compliance-domain, single-source-of-truth]
---
`{{c1::_VALID_DOMAINS}}` is a frozenset in `extractor.py` that independently duplicates `axiom.py`'s `ComplianceDomain` Literal instead of deriving from it — a new domain value must be added to both by hand.

Extra: synapse-l4 · Challenge: Three Independent Enumerations
See: docs/journal/synapse-l4-2026-07-18T2026-saas-domain-support.md

---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, compliance-domain, single-source-of-truth]
---
Adding a new `ComplianceDomain` value in synapse-l4 requires editing {{c1::three}} independent places: the `Literal` itself, `extractor.py`'s `_VALID_DOMAINS` frozenset, and the LLM extraction prompt's enumerated domain list.

Extra: synapse-l4 · Challenge: Three Independent Enumerations
See: docs/journal/synapse-l4-2026-07-18T2026-saas-domain-support.md

---
type: basic
deck: Rhizome::synapse-l4
tags: [synapse-l4, compliance-domain, single-source-of-truth]
---
Q: Why wasn't `_VALID_DOMAINS` refactored to derive from `ComplianceDomain` via `typing.get_args()` when `"saas"` was added, given the duplication was already known to be risky?

A: The fix was scoped to unblocking a named cross-repo dependency (Xylem-L6's ADR-0007); refactoring to a single source of truth would have expanded the diff for a concern the change didn't ask to solve. Deferred until the duplication actually causes a real bug, consistent with "wait until it hurts" rather than fixing speculatively.

Extra: synapse-l4 · Decision: Leave Duplication In Place
See: docs/journal/synapse-l4-2026-07-18T2026-saas-domain-support.md
