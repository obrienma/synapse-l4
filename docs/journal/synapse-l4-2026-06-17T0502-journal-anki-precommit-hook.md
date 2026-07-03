---
id: synapse-l4-2026-06-17T0502-journal-anki-precommit-hook
repo: synapse-l4
title: "Enforcing the journal-anki step with a pre-commit reminder hook"
date: 2026-06-17
tags: [workflow, claude-code, hooks, pretooluse, git-commit, journal-anki, dependency-free]
files: [.claude/settings.local.json]
---

### Pattern: Policy Enforcement Point via PreToolUse Interception
The journaling rule (write a `docs/journal/` entry before committing) was
documented in CLAUDE.md but unenforced — it relied on Claude noticing and
following the instruction, which it demonstrably did not when asked for a
commit message. A Claude Code `PreToolUse` hook on the `Bash` tool turns the
documented norm into a *policy enforcement point*: the hook intercepts the
tool call before the side-effecting `git commit` runs and interposes a
checkpoint. The enforcement lives in the harness, not in Claude's
discretion — the same reason a pre-commit gate is more reliable than a code
review checklist nobody reads.

### Decision: `ask` rather than `deny`
The hook returns `permissionDecision: "ask"`, not `"deny"`. `deny` is
unconditional — it would block *every* commit forever, with no escape hatch,
making the repo uncommittable. `ask` pauses for a human-in-the-loop
confirmation with a reminder reason, then proceeds on approval. The tradeoff
is explicit: this is a *reminder with friction*, not hard enforcement — a
determined approval still lets an unjournaled commit through. That is the
correct altitude for a workflow nudge; a hard block would be hostile to
trivial commits (typo fixes, config tweaks) that warrant no journal entry.

### Challenge: jq Not Installed — the Idiom Assumed a Missing Dependency
This was the hardest part of the phase. The idiomatic way to read a hook's
input is `jq -r '.tool_input.command'`, and every example in the config skill
assumed `jq` was present. It was not installed in this WSL2 environment, so
the canonical command produced `jq: command not found` — the pipeline
short-circuited and the hook did *nothing*. The symptom was a hook that
appeared correctly configured but never fired. Root cause: an unstated
runtime dependency. First fix was to drop jq entirely and grep raw stdin;
the final design (below) restores jq but no longer *depends* on it.

### Decision: jq-Preferred Extraction with a Raw-stdin Fallback
Because this hook is being propagated to other repos and machines, hard-
depending on jq would carry the silent-failure risk to every one of them.
The command therefore checks `command -v jq`: if present, it extracts the
command field precisely with `jq -r '.tool_input.command // empty'`; if
absent, it falls back to grepping raw stdin. jq is preferred because field-
scoped extraction avoids false positives — grepping the whole payload trips
on the literal string `git commit` appearing anywhere (a `git log`
invocation, an `echo`, even the hook's own setup commands), whereas matching
only the extracted command does not. The fallback keeps the hook working,
not silently dead, on any box where jq has not been installed yet.

### Anti-Pattern Avoided: Silent Hook Failure from an Assumed Dependency
The trap is shipping a safety mechanism that hard-depends on a tool that may
be absent. When it is absent, the mechanism fails *silently* and gives false
confidence that the workflow is enforced — the worst failure mode a guard can
have, because nothing signals that the guard is dead. The `command -v jq`
guard with a fallback sidesteps it: the hook degrades to a working path
rather than vanishing. This is the same lesson the jq challenge taught,
promoted from accident to design principle for propagation.

### Challenge: A Hook Catches the Commit, Not the Intent
The original trigger that exposed the gap was the prompt "commit msg pls" —
a natural-language request, not a tool call. No hook can fire on that: hooks
key off tool invocations, and asking for a commit message is just
conversation. The hook therefore guards the *actual* `git commit` execution
(the last and most important gate), but cannot enforce journaling at the
moment the message is first requested. This is an accepted limitation, not a
bug — the commit itself is the side-effecting event worth gating.
