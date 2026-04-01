"""
Instrumentation tests verify that Logfire setup doesn't break the pipeline.
Span structure and attribute assertions are manual — verified via Logfire UI.
"""

from unittest.mock import MagicMock, patch

import logfire

from src.observation.instrumentation import configure_logfire, instrument_fastapi, instrument_httpx


def test_configure_logfire_runs_without_token(monkeypatch: object) -> None:
    # When LOGFIRE_TOKEN is absent, configure_logfire must not raise
    with patch("src.observation.instrumentation.settings") as mock_settings:
        mock_settings.logfire_token = None
        configure_logfire()  # must not raise


def test_configure_logfire_runs_with_token(monkeypatch: object) -> None:
    with patch("src.observation.instrumentation.settings") as mock_settings:
        mock_settings.logfire_token = "test-token"
        with patch("src.observation.instrumentation.logfire.configure") as mock_configure:
            configure_logfire()
            mock_configure.assert_called_once_with(token="test-token")


def test_configure_logfire_uses_no_send_when_no_token() -> None:
    with patch("src.observation.instrumentation.settings") as mock_settings:
        mock_settings.logfire_token = None
        with patch("src.observation.instrumentation.logfire.configure") as mock_configure:
            configure_logfire()
            mock_configure.assert_called_once_with(send_to_logfire=False)


def test_instrument_fastapi_calls_logfire() -> None:
    app = MagicMock()
    with patch("src.observation.instrumentation.logfire.instrument_fastapi") as mock_inst:
        instrument_fastapi(app)
        mock_inst.assert_called_once_with(app)


def test_instrument_httpx_calls_logfire() -> None:
    with patch("src.observation.instrumentation.logfire.instrument_httpx") as mock_inst:
        instrument_httpx()
        mock_inst.assert_called_once()


def test_logfire_span_does_not_raise_in_no_op_mode() -> None:
    # Verify pipeline stages can create spans without a live Logfire connection
    logfire.configure(send_to_logfire=False)
    with logfire.span("test_span", key="value"):
        pass  # must not raise
