---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, workflow, claude-code, hooks]
---
A {{c1::PreToolUse}} hook intercepts a tool call before it runs; matching the
{{c2::Bash}} tool lets it gate `git commit` invocations as a policy
enforcement point.

Extra: synapse-l4 · Pattern: Policy Enforcement Point via PreToolUse Interception
See: docs/journal/synapse-l4-2026-06-17T0502-journal-anki-precommit-hook.md

---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, workflow, hooks]
---
The pre-commit reminder hook returns permissionDecision {{c1::ask}} rather
than {{c2::deny}}, because deny is unconditional and would make the repo
uncommittable — ask pauses for a human-in-the-loop checkpoint while leaving
an escape hatch.

Extra: synapse-l4 · Decision: ask rather than deny
See: docs/journal/synapse-l4-2026-06-17T0502-journal-anki-precommit-hook.md

---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, hooks, dependency-free]
---
The hook guards on {{c1::command -v jq}}: it prefers jq to extract the command
field precisely, but falls back to grepping {{c2::raw stdin}} when jq is
absent — so a missing dependency degrades gracefully instead of causing
{{c3::silent hook failure}}.

Extra: synapse-l4 · Decision: jq-Preferred Extraction with a Raw-stdin Fallback
See: docs/journal/synapse-l4-2026-06-17T0502-journal-anki-precommit-hook.md

---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, claude-code, hooks]
---
A Claude Code hook can only fire on an actual {{c1::tool call}} (the
`git commit` Bash invocation), not on natural-language {{c2::intent}} like
asking for a commit message — so the commit itself is the gate, not the
request.

Extra: synapse-l4 · Challenge: A Hook Catches the Commit, Not the Intent
See: docs/journal/synapse-l4-2026-06-17T0502-journal-anki-precommit-hook.md

---
type: basic
deck: Rhizome::synapse-l4
tags: [synapse-l4, hooks, dependency-free]
---
Q: Why does a hook that hard-depends on jq make the *worst* kind of failure
when propagated to a machine without jq?

A: It fails silently. `jq: command not found` short-circuits the pipeline, so
the hook does nothing — but it still looks configured. A safety mechanism
that is dead while appearing alive gives false confidence the workflow is
enforced. Guarding with `command -v jq` and a raw-stdin fallback makes the
hook degrade to a working path instead of vanishing.

Extra: synapse-l4 · Anti-Pattern Avoided: Silent Hook Failure from an Assumed Dependency
See: docs/journal/synapse-l4-2026-06-17T0502-journal-anki-precommit-hook.md
