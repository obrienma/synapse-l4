# ADR 0005 — uv over Poetry / pip + venv

**Date:** 2026-03-31
**Status:** Accepted

---

## Context

Python project tooling has historically been fragmented: `pip` + `venv` + `pip-tools` for basic dependency management, or `Poetry` for a more integrated experience. A newer entrant, `uv` (from Astral, the creators of Ruff), provides a Rust-based drop-in replacement for `pip`, `venv`, `pip-tools`, and `pipx` — with significantly faster resolution and install times.

---

## Decision

**Use `uv` with `pyproject.toml` for all dependency management and script execution.**

---

## Rationale

1. **Speed**: `uv` resolves and installs packages 10–100x faster than `pip` + `pip-tools`. This matters in CI and when onboarding.

2. **Single tool**: `uv sync`, `uv run`, `uv add`, `uv lock` replace `pip install`, `pip-compile`, `python -m venv`, and `pipx`. No separate tool for virtual environment management.

3. **`pyproject.toml` native**: All metadata lives in `pyproject.toml` (PEP 517/621). No `setup.py`, no `requirements.txt` alongside a `pyproject.toml`, no lock file format invented by the tool.

4. **`uv run` for scripts**: `uv run pytest`, `uv run fastapi dev` — scripts run in the managed venv without manually activating it. Consistent across environments.

5. **Lock file**: `uv.lock` is deterministic and cross-platform. Equivalent to `poetry.lock` but faster to generate and update.

---

## Alternatives Rejected

**pip + venv + pip-tools**: Works, but three separate tools. `pip-compile` for lock files is slow. No unified script runner.

**Poetry**: More mature than `uv` but significantly slower resolution. Plugin ecosystem adds complexity. `poetry run` is equivalent to `uv run` but slower.

**Conda**: Environment management for scientific computing — inappropriate overhead for a microservice. No `pyproject.toml` native support.

---

## Consequences

- All contributors use `uv sync` to set up the environment — no `pip install -r requirements.txt`.
- New dependencies: `uv add <package>` (updates `pyproject.toml` and `uv.lock`).
- Remove dependencies: `uv remove <package>`.
- CI installs `uv` as a build step before `uv sync`.
- `uv.lock` is committed to version control — ensures reproducible installs across environments.
