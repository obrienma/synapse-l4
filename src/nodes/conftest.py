import pytest

import src.nodes.extractor as extractor_module
from config import settings


@pytest.fixture(autouse=True)
def disable_llm_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force llm_dry_run=False for all extractor tests.

    LLM_DRY_RUN=true in .env would otherwise intercept every extract() call
    and return the stub, breaking tests that exercise the LLM path.
    Tests that want dry-run behaviour must patch settings explicitly.
    """
    monkeypatch.setattr(settings, "llm_dry_run", False)
