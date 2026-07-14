# ADR 0008 — Automated Live LLM Test Tier (Real Ollama Backend)

**Date:** 2026-07-04
**Status:** Accepted

---

## Context

TESTING.md is explicit that real LLM calls are not automated — cost, latency, and non-determinism are the stated reasons, and every `extractor_test.py` case mocks the Instructor-patched client. That's correct for CI, but it leaves a real gap: `extract()`'s LLM fallback path (the branch taken when `_try_direct_extraction` misses) has never been exercised against an actual model. It has only ever been exercised against a mock that returns whatever fixture the test hands it.

That gap now matters concretely because inference is migrating from Gemini Flash to a locally-run Ollama model (`qwen3.5:9b-q4_K_M`) over Tailscale. But today `config.py` has no `base_url` field at all — `_default_client()` constructs `instructor.from_openai(AsyncOpenAI(api_key=settings.openai_api_key))` with no override, so it can only ever talk to the real OpenAI API. There is currently no way to point Synapse-L4 at Ollama without a code change, live test tier or not.

Inference now runs against a self-hosted Ollama instance reachable over Tailscale at ~84ms RTT, rather than a metered third-party API. That changes which of TESTING.md's three stated reasons for excluding real LLM calls (cost, latency, non-determinism) still apply: cost and latency don't, for a self-hosted model on a low-latency private link. Only non-determinism remains relevant, and that's an assertion-design problem (loose assertions on schema/enum conformance rather than exact values), not a reason to keep the tier gated behind a human decision to run it.

This suite is a portfolio piece, not a production service. There's no intent to run it against a CI-joined tailnet — the Tailscale connection exists between machines used for local development, not as infrastructure to provision for a hosted or self-hosted CI runner. So "automated" here means "runs without a human deciding whether to invoke it," not "runs in GitHub Actions." The live tier runs locally, same as the rest of the suite; this ADR does not introduce a CI workflow.

`judge.py` is out of scope here — it's pure rule-based Python per ADR-0004, no LLM involved. This ADR only concerns the `extract()` stage.

---

## Decision

**Add a live test tier that exercises `extract()`'s LLM path against the real Ollama endpoint, run locally as a standard part of the test suite invocation — gated by a fast reachability probe that skips (not fails) if the host is unavailable, rather than by a human-triggered opt-in flag. No CI integration.**

Concretely:

1. **`config.py`** gains `llm_base_url: str | None = None`. `_default_client()` passes `base_url=settings.llm_base_url` to `AsyncOpenAI` when set; `None` preserves today's behavior exactly (real OpenAI, no override).
2. **`.env.example`** gains a commented note under the LLM Provider section: `# LLM_BASE_URL=http://<tailscale-host>:11434/v1`.
3. **New `tests/live/`** directory (outside `src/`) containing `extractor_live_test.py`, plus a `conftest.py` fixture that does a short-timeout (~1–2s) GET against the Ollama host's `/api/tags` before the module's tests run. On failure, tests are skipped with a clear reason string (`"Ollama host unreachable: <detail>"`) rather than failing the run — same best-effort/circuit-breaker posture already used for the judge model in arbiter-l8.
4. Invoked with `uv run pytest tests/live/ -v` as a normal local command, same as `uv run pytest` for the mocked suite. Not merged into `testpaths`, so it doesn't run under a bare `uv run pytest` — it's a second command, not a hidden default.
5. Assertions stay deliberately loose: schema conformance (`AxiomDraft` construction succeeds, `status`/`domain` land in the valid enum, `anomaly_score` in `[0.0, 1.0]`) — not exact field values. A real model's output for an ambiguous fixture isn't reproducible run to run the way a mock's return value is.
6. Test fixtures reuse the same deliberately-unstructured payloads from `extractor_test.py` that miss `_try_direct_extraction`, so the LLM path is actually exercised rather than short-circuited by the fast path.

**No CI, no Tailscale-in-CI.** This suite doesn't run in GitHub Actions, and the Tailscale connection is between machines used for local development — not something to provision for a hosted or self-hosted runner. The reachability probe exists so the tier degrades gracefully on a local machine where the Ollama host happens to be off, not to support a CI topology that doesn't exist for this project.

---

## Rationale

1. **Mocking and live-testing answer different questions.** The mocked suite proves the contract (Instructor retries on validation failure, `ExtractionError` raised correctly, prompt structure correct). It cannot prove that a real `qwen3.5:9b-q4_K_M` response actually conforms to that contract. Both are needed; neither replaces the other.

2. **The missing `base_url` is a real blocker, not a hypothetical.** Without it, "online tests with Synapse-L4" isn't possible regardless of test-tier design — the client has nowhere else to point. This ADR treats that plumbing as in-scope rather than a separate ticket, since the test tier is meaningless without it.

3. **Cost and latency no longer justify manual-only.** TESTING.md's three reasons for exclusion were cost, latency, non-determinism. A self-hosted model removes per-call cost entirely, and ~84ms Tailscale RTT is negligible against a test suite's normal runtime. Keeping this behind a human-triggered flag after those two reasons stop applying just adds friction for no remaining benefit.

4. **Reachability-gated skip, not a human flag, is the correct mechanism — even locally.** The remaining reason — non-determinism — doesn't argue for a human deciding whether to run it; it argues for loose assertions (point 6 below). What *does* need a gate is host availability: the partner machine can simply be off. A short-timeout reachability probe with skip-on-failure is the same best-effort/circuit-breaker shape already used for the arbiter-l8 judge — reusing a pattern already validated elsewhere rather than inventing a new one.

5. **No CI, on purpose.** This is a portfolio suite, not a production service with a release pipeline to gate. There's no intent to provision a Tailscale-joined runner (hosted or self-hosted) for something that only ever needs to run on the developer's own machines. Introducing CI machinery here would be solving a problem — "how does an untrusted third-party runner reach a private LLM host" — that doesn't exist for this project's actual use case, and risks reading as infrastructure complexity added without a real trigger, which cuts against the "wait until it hurts" discipline this suite otherwise follows.

6. **Loose assertions are the point, not a shortcut.** A live test asserting an exact `anomaly_score` match against a golden value will be flaky by construction — that's the non-determinism TESTING.md already warned about. Asserting schema/enum conformance is the actual thing worth checking: "does the real model still play ball with this schema and prompt," not "does it produce byte-identical output to gpt-4o-mini."

---

## Alternatives Rejected

**Manual opt-in via an env-var flag, gating the tier off by default.** Rejected — this treats the tier as if it still carried the cost/latency concerns of a metered third-party API. Once those don't apply, a flag someone has to remember to set adds friction with no remaining benefit; a reachability probe already handles the one thing that does still need gating (host availability).

**Wire the tier into GitHub Actions CI with a Tailscale-joined runner.** Rejected — this is a portfolio suite with no production deployment target, not a service with a release pipeline. There's no consumer of a green CI badge here, and provisioning tailnet access for a hosted runner solves a problem — third-party-runner-reaches-private-host — that this project doesn't have. Standing up that machinery would itself be the kind of premature infrastructure the "wait until it hurts" discipline is meant to avoid.

**`@pytest.mark.live` on tests colocated in `extractor_test.py`, filtered via `-m "not live"`.** Rejected — same outcome as the `tests/live/` directory approach with more config surface (marker registration, a filter flag to remember) and a silent-failure mode (forgetting the filter would fire live calls unexpectedly during a normal `uv run pytest src/`).

**Hard-fail if Ollama is unreachable, instead of skip.** Rejected — the host has no uptime guarantee. A hard fail on host downtime conflates "the code is wrong" with "the machine happened to be off," which is exactly the ambiguity a skip-with-reason avoids.

**VCR-style cassette replay (`vcrpy`) of recorded Ollama responses for deterministic "semi-live" tests.** Rejected for now per "wait until it hurts" — adds a recording/replay dependency before there's evidence the live tier needs output-stability guarantees beyond schema/enum conformance.

**Route this through arbiter-l8's online pipeline instead of an in-repo test.** Rejected as a *replacement* — different purpose and cadence. arbiter-l8's online pipeline is for continuous precision/recall/F1 measurement across many fixtures against the judge-availability circuit breaker; this ADR is a local smoke check that the extractor's LLM path is wired correctly at all. arbiter-l8 consuming Synapse-L4's extractor as an eval subject later (planned) is complementary, not a substitute.

---

## Consequences

- `config.py`: new `llm_base_url: str | None = None` field; `_default_client()` updated to pass it through.
- `.env.example`: new commented `LLM_BASE_URL` line.
- New `tests/live/extractor_live_test.py` + `tests/live/conftest.py` (reachability probe fixture). Still excluded from `testpaths`, so a bare `uv run pytest` is unaffected — the live tier is invoked explicitly via `uv run pytest tests/live/ -v`.
- **No CI changes.** No `.github/workflows/` directory is introduced by this ADR, in any of the three repos.
- `docs/TESTING.md`: "What Is Not Automated" table's "Real LLM calls" row is removed or re-labeled — it no longer requires a human decision to run, just a second local command. New "Live Test Tier" section documents the probe/skip behavior, why assertions stay loose, and that this is intentionally local-only.
- Once `OllamaDriver` lands in Sentinel-L7 (parallel, upstream work), the same `llm_base_url` pattern is available for Sentinel-L7's own config if not already covered by `ComplianceManager` — worth checking for duplication at that point rather than assuming divergence is fine.
- A CI need for this suite would be a distinct future decision with its own trigger — not something this ADR pre-solves.
