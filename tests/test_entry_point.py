"""Tests for the Max entry point."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestEntryPoint:
    def test_module_importable(self):
        import max.__main__

        assert hasattr(max.__main__, "main")

    @patch("max.__main__.uvicorn")
    @patch("max.__main__.create_app")
    def test_main_calls_uvicorn_run(self, mock_create, mock_uvicorn):
        from max.__main__ import main

        mock_app = MagicMock()
        mock_create.return_value = mock_app

        # Patch Settings to avoid needing env vars
        with patch("max.__main__.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(max_host="0.0.0.0", max_port=8080)
            main()

        mock_uvicorn.run.assert_called_once()
        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["host"] == "0.0.0.0"
        assert call_kwargs[1]["port"] == 8080

    @patch("max.__main__.uvicorn")
    @patch("max.__main__.create_app")
    def test_main_uses_settings_port(self, mock_create, mock_uvicorn):
        from max.__main__ import main

        mock_create.return_value = MagicMock()

        with patch("max.__main__.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(max_host="127.0.0.1", max_port=9090)
            main()

        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["host"] == "127.0.0.1"
        assert call_kwargs[1]["port"] == 9090

    @patch("max.__main__.uvicorn")
    @patch("max.__main__.create_app")
    def test_main_passes_log_level(self, mock_create, mock_uvicorn):
        from max.__main__ import main

        mock_create.return_value = MagicMock()

        with patch("max.__main__.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(max_host="0.0.0.0", max_port=8080)
            main()

        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["log_level"] == "info"

    @patch("max.__main__.uvicorn")
    @patch("max.__main__.create_app")
    def test_main_disables_access_log(self, mock_create, mock_uvicorn):
        from max.__main__ import main

        mock_create.return_value = MagicMock()

        with patch("max.__main__.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(max_host="0.0.0.0", max_port=8080)
            main()

        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["access_log"] is False

    @patch("max.__main__.uvicorn")
    @patch("max.__main__.create_app")
    def test_main_passes_app_to_uvicorn(self, mock_create, mock_uvicorn):
        from max.__main__ import main

        mock_app = MagicMock()
        mock_create.return_value = mock_app

        with patch("max.__main__.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(max_host="0.0.0.0", max_port=8080)
            main()

        # First positional arg should be the app
        call_args = mock_uvicorn.run.call_args
        assert call_args[0][0] is mock_app

    def test_creates_fastapi_app(self):
        from fastapi import FastAPI

        from max.app import create_app

        app = create_app()
        assert isinstance(app, FastAPI)
