"""Tests for email tools — send, read, search, list_folders."""

from __future__ import annotations

import sys
from collections import namedtuple
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.tools.native.email_tools import (
    TOOL_DEFINITIONS,
    _parse_email_headers,
    _parse_email_with_preview,
    _parse_folder_name,
    handle_email_list_folders,
    handle_email_read,
    handle_email_search,
    handle_email_send,
)


# ── Helpers ───────────────────────────────────────────────────────────

# aioimaplib Response is a namedtuple(result, lines)
Response = namedtuple("Response", ["result", "lines"])


def _make_raw_email(
    from_: str = "alice@example.com",
    to: str = "bob@example.com",
    subject: str = "Test",
    date: str = "Mon, 1 Jan 2024 12:00:00 +0000",
    body: str = "Hello world",
) -> bytes:
    """Build a minimal RFC-822 email in bytes."""
    return (
        f"From: {from_}\r\n"
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {date}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body}"
    ).encode()


def _make_multipart_email(
    from_: str = "alice@example.com",
    to: str = "bob@example.com",
    subject: str = "Multi",
    body_text: str = "Plain text body",
) -> bytes:
    """Build a minimal multipart email in bytes."""
    boundary = "BOUNDARY123"
    return (
        f"From: {from_}\r\n"
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        f'Content-Type: multipart/alternative; boundary="{boundary}"\r\n'
        f"\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body_text}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"\r\n"
        f"<p>{body_text}</p>\r\n"
        f"--{boundary}--\r\n"
    ).encode()


def _mock_imap_client(
    search_result: str = "OK",
    search_uids: str = "1 2 3",
    fetch_result: str = "OK",
    fetch_lines: list[Any] | None = None,
    list_result: str = "OK",
    list_lines: list[str] | None = None,
) -> AsyncMock:
    """Create a mock IMAP4_SSL client."""
    client = AsyncMock()
    client.wait_hello_from_server = AsyncMock()
    client.login = AsyncMock()
    client.select = AsyncMock()
    client.logout = AsyncMock()

    client.search = AsyncMock(return_value=Response(search_result, [search_uids]))

    if fetch_lines is None:
        fetch_lines = [
            b"1 FETCH (RFC822 {100})",
            _make_raw_email(),
        ]
    client.fetch = AsyncMock(return_value=Response(fetch_result, fetch_lines))

    if list_lines is None:
        list_lines = [
            '(\\HasNoChildren) "/" "INBOX"',
            '(\\HasNoChildren) "/" "Sent"',
            '(\\HasNoChildren) "/" "Drafts"',
        ]
    client.list = AsyncMock(return_value=Response(list_result, list_lines))

    return client


# ── Tool definition tests ─────────────────────────────────────────────


class TestToolDefinitions:
    """Verify the 4 tool definitions are correct."""

    def test_four_tools_defined(self):
        assert len(TOOL_DEFINITIONS) == 4

    def test_tool_ids(self):
        ids = {t.tool_id for t in TOOL_DEFINITIONS}
        assert ids == {"email.send", "email.read", "email.search", "email.list_folders"}

    def test_all_category_communication(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.category == "communication", f"{tool.tool_id} has wrong category"

    def test_all_provider_native(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.provider_id == "native", f"{tool.tool_id} has wrong provider"

    def test_send_required_fields(self):
        send = next(t for t in TOOL_DEFINITIONS if t.tool_id == "email.send")
        assert set(send.input_schema["required"]) == {"to", "subject", "body"}

    def test_search_required_fields(self):
        search = next(t for t in TOOL_DEFINITIONS if t.tool_id == "email.search")
        assert "criteria" in search.input_schema["required"]

    def test_read_has_folder_and_count(self):
        read = next(t for t in TOOL_DEFINITIONS if t.tool_id == "email.read")
        props = read.input_schema["properties"]
        assert "folder" in props
        assert "count" in props

    def test_list_folders_has_connection_params(self):
        lf = next(t for t in TOOL_DEFINITIONS if t.tool_id == "email.list_folders")
        props = lf.input_schema["properties"]
        assert "imap_host" in props
        assert "user" in props
        assert "password" in props


# ── Parser tests ──────────────────────────────────────────────────────


class TestParsers:
    """Test email parsing helpers."""

    def test_parse_email_headers(self):
        raw = _make_raw_email(from_="sender@x.com", subject="Hi")
        result = _parse_email_headers(raw)
        assert result["from"] == "sender@x.com"
        assert result["subject"] == "Hi"
        assert "body_preview" not in result

    def test_parse_email_with_preview_plain(self):
        raw = _make_raw_email(body="Preview content here")
        result = _parse_email_with_preview(raw)
        assert "Preview content here" in result["body_preview"]
        assert result["from"] == "alice@example.com"

    def test_parse_email_with_preview_multipart(self):
        raw = _make_multipart_email(body_text="Multi body")
        result = _parse_email_with_preview(raw)
        assert "Multi body" in result["body_preview"]

    def test_parse_email_preview_truncation(self):
        raw = _make_raw_email(body="X" * 500)
        result = _parse_email_with_preview(raw, preview_length=100)
        assert len(result["body_preview"]) == 100

    def test_parse_folder_name_quoted(self):
        assert _parse_folder_name('(\\HasNoChildren) "/" "INBOX"') == "INBOX"
        assert _parse_folder_name('(\\HasNoChildren) "/" "Sent Mail"') == "Sent Mail"

    def test_parse_folder_name_unquoted(self):
        assert _parse_folder_name("(\\HasNoChildren) / INBOX") == "INBOX"

    def test_parse_folder_name_empty(self):
        assert _parse_folder_name("") is None
        assert _parse_folder_name(None) is None  # type: ignore[arg-type]


# ── email.send tests ──────────────────────────────────────────────────


class TestEmailSend:
    """Tests for handle_email_send."""

    @pytest.mark.asyncio
    async def test_send_success(self):
        with patch("max.tools.native.email_tools.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock(return_value=({}, "<msg-id-123@example.com>"))

            result = await handle_email_send({
                "to": "bob@example.com",
                "subject": "Hello",
                "body": "Hi Bob",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "user": "me@example.com",
                "password": "secret",
            })

            assert result["sent"] is True
            assert result["message_id"] == "<msg-id-123@example.com>"
            mock_smtp.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_with_cc_bcc(self):
        with patch("max.tools.native.email_tools.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock(return_value=({}, "<msg-456>"))

            result = await handle_email_send({
                "to": "bob@example.com",
                "subject": "With CC",
                "body": "Body",
                "cc": "carol@example.com",
                "bcc": "dave@example.com",
                "smtp_host": "smtp.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert result["sent"] is True
            # Verify the EmailMessage was constructed with CC and BCC
            call_args = mock_smtp.send.call_args
            msg = call_args[0][0]
            assert msg["Cc"] == "carol@example.com"
            assert msg["Bcc"] == "dave@example.com"

    @pytest.mark.asyncio
    async def test_send_failure(self):
        with patch("max.tools.native.email_tools.aiosmtplib") as mock_smtp:
            mock_smtp.send = AsyncMock(side_effect=Exception("Connection refused"))

            result = await handle_email_send({
                "to": "bob@example.com",
                "subject": "Fail",
                "body": "Body",
                "smtp_host": "smtp.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert result["sent"] is False
            assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_send_no_host(self):
        with patch("max.tools.native.email_tools._get_settings_value", return_value=""):
            result = await handle_email_send({
                "to": "bob@example.com",
                "subject": "No host",
                "body": "Body",
            })
            assert "error" in result
            assert "SMTP host" in result["error"]

    @pytest.mark.asyncio
    async def test_send_missing_dep(self):
        with patch("max.tools.native.email_tools.HAS_AIOSMTPLIB", False):
            result = await handle_email_send({
                "to": "bob@example.com",
                "subject": "X",
                "body": "Y",
            })
            assert "error" in result
            assert "aiosmtplib" in result["error"]

    @pytest.mark.asyncio
    async def test_send_settings_fallback(self):
        """Verify connection params fall back to Settings env vars."""
        settings_map = {
            "email_smtp_host": "fallback.smtp.com",
            "email_smtp_port": "465",
            "email_user": "fallback@example.com",
            "email_password": "fb_pass",
        }

        with (
            patch("max.tools.native.email_tools._get_settings_value", side_effect=lambda k: settings_map.get(k, "")),
            patch("max.tools.native.email_tools.aiosmtplib") as mock_smtp,
        ):
            mock_smtp.send = AsyncMock(return_value=({}, "<fb-id>"))

            result = await handle_email_send({
                "to": "bob@example.com",
                "subject": "Fallback",
                "body": "Test",
            })

            assert result["sent"] is True
            call_args = mock_smtp.send.call_args
            assert call_args.kwargs["hostname"] == "fallback.smtp.com"
            assert call_args.kwargs["port"] == 465


# ── email.read tests ──────────────────────────────────────────────────


class TestEmailRead:
    """Tests for handle_email_read."""

    @pytest.mark.asyncio
    async def test_read_success(self):
        mock_client = _mock_imap_client(
            search_uids="1 2 3",
            fetch_lines=[
                b"1 FETCH (RFC822 {100})",
                _make_raw_email(subject="Msg1"),
                b"2 FETCH (RFC822 {100})",
                _make_raw_email(subject="Msg2"),
                b"3 FETCH (RFC822 {100})",
                _make_raw_email(subject="Msg3"),
            ],
        )

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_read({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
                "folder": "INBOX",
                "count": 10,
            })

            assert "messages" in result
            assert len(result["messages"]) == 3
            assert result["messages"][0]["subject"] == "Msg1"
            mock_client.select.assert_awaited_once_with("INBOX")
            mock_client.logout.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_read_respects_count(self):
        """Only the last N UIDs should be fetched."""
        mock_client = _mock_imap_client(
            search_uids="10 20 30 40 50",
            fetch_lines=[
                b"40 FETCH (RFC822 {100})",
                _make_raw_email(subject="Msg40"),
                b"50 FETCH (RFC822 {100})",
                _make_raw_email(subject="Msg50"),
            ],
        )

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_read({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
                "count": 2,
            })

            # Fetch should be called with only the last 2 UIDs
            mock_client.fetch.assert_awaited_once()
            fetch_call_uid = mock_client.fetch.call_args[0][0]
            assert fetch_call_uid == "40,50"

    @pytest.mark.asyncio
    async def test_read_empty_mailbox(self):
        mock_client = _mock_imap_client(search_uids="")

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_read({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert result["messages"] == []
            mock_client.fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_read_search_failure(self):
        mock_client = _mock_imap_client(search_result="NO")

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_read({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert "error" in result

    @pytest.mark.asyncio
    async def test_read_no_host(self):
        with patch("max.tools.native.email_tools._get_settings_value", return_value=""):
            result = await handle_email_read({})
            assert "error" in result
            assert "IMAP host" in result["error"]

    @pytest.mark.asyncio
    async def test_read_missing_dep(self):
        with patch("max.tools.native.email_tools.HAS_AIOIMAPLIB", False):
            result = await handle_email_read({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })
            assert "error" in result
            assert "aioimaplib" in result["error"]

    @pytest.mark.asyncio
    async def test_read_connection_error(self):
        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(side_effect=Exception("Connection failed"))

            result = await handle_email_read({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert "error" in result
            assert "Connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_read_default_folder(self):
        """Default folder should be INBOX when not specified."""
        mock_client = _mock_imap_client(search_uids="")

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            await handle_email_read({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            mock_client.select.assert_awaited_once_with("INBOX")

    @pytest.mark.asyncio
    async def test_read_settings_fallback(self):
        """Verify IMAP params fall back to Settings env vars."""
        settings_map = {
            "email_imap_host": "fallback.imap.com",
            "email_user": "fallback@example.com",
            "email_password": "fb_pass",
        }
        mock_client = _mock_imap_client(search_uids="")

        with (
            patch("max.tools.native.email_tools._get_settings_value", side_effect=lambda k: settings_map.get(k, "")),
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_read({})

            mock_imap.IMAP4_SSL.assert_called_once_with(host="fallback.imap.com")
            mock_client.login.assert_awaited_once_with("fallback@example.com", "fb_pass")


# ── email.search tests ────────────────────────────────────────────────


class TestEmailSearch:
    """Tests for handle_email_search."""

    @pytest.mark.asyncio
    async def test_search_success(self):
        raw = _make_raw_email(from_="alice@x.com", subject="Found")
        mock_client = _mock_imap_client(
            search_uids="5 10",
            fetch_lines=[
                b"5 FETCH (RFC822.HEADER {200})",
                raw,
            ],
        )

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_search({
                "criteria": "FROM alice",
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert "messages" in result
            assert "count" in result
            assert result["count"] >= 1
            mock_client.search.assert_awaited_once_with("FROM alice")
            mock_client.logout.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        mock_client = _mock_imap_client(search_uids="")

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_search({
                "criteria": "FROM nobody",
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert result["messages"] == []
            assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_search_custom_folder(self):
        mock_client = _mock_imap_client(search_uids="")

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            await handle_email_search({
                "criteria": "ALL",
                "folder": "Sent",
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            mock_client.select.assert_awaited_once_with("Sent")

    @pytest.mark.asyncio
    async def test_search_failure(self):
        mock_client = _mock_imap_client(search_result="NO")

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_search({
                "criteria": "BAD CRITERIA",
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert "error" in result

    @pytest.mark.asyncio
    async def test_search_no_host(self):
        with patch("max.tools.native.email_tools._get_settings_value", return_value=""):
            result = await handle_email_search({"criteria": "ALL"})
            assert "error" in result
            assert "IMAP host" in result["error"]

    @pytest.mark.asyncio
    async def test_search_missing_dep(self):
        with patch("max.tools.native.email_tools.HAS_AIOIMAPLIB", False):
            result = await handle_email_search({
                "criteria": "ALL",
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })
            assert "error" in result
            assert "aioimaplib" in result["error"]


# ── email.list_folders tests ──────────────────────────────────────────


class TestEmailListFolders:
    """Tests for handle_email_list_folders."""

    @pytest.mark.asyncio
    async def test_list_folders_success(self):
        mock_client = _mock_imap_client(
            list_lines=[
                '(\\HasNoChildren) "/" "INBOX"',
                '(\\HasNoChildren) "/" "Sent"',
                '(\\HasNoChildren) "/" "Trash"',
            ],
        )

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_list_folders({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert "folders" in result
            assert "INBOX" in result["folders"]
            assert "Sent" in result["folders"]
            assert "Trash" in result["folders"]
            mock_client.logout.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_folders_empty(self):
        mock_client = _mock_imap_client(list_lines=[])

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_list_folders({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert result["folders"] == []

    @pytest.mark.asyncio
    async def test_list_folders_failure(self):
        mock_client = _mock_imap_client(list_result="NO")

        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_list_folders({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert "error" in result

    @pytest.mark.asyncio
    async def test_list_folders_no_host(self):
        with patch("max.tools.native.email_tools._get_settings_value", return_value=""):
            result = await handle_email_list_folders({})
            assert "error" in result
            assert "IMAP host" in result["error"]

    @pytest.mark.asyncio
    async def test_list_folders_missing_dep(self):
        with patch("max.tools.native.email_tools.HAS_AIOIMAPLIB", False):
            result = await handle_email_list_folders({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })
            assert "error" in result
            assert "aioimaplib" in result["error"]

    @pytest.mark.asyncio
    async def test_list_folders_connection_error(self):
        with (
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
            patch("max.tools.native.email_tools._get_settings_value", return_value=""),
        ):
            mock_imap.IMAP4_SSL = MagicMock(side_effect=Exception("Auth failed"))

            result = await handle_email_list_folders({
                "imap_host": "imap.example.com",
                "user": "me@example.com",
                "password": "pass",
            })

            assert "error" in result
            assert "Auth failed" in result["error"]

    @pytest.mark.asyncio
    async def test_list_folders_settings_fallback(self):
        """Verify IMAP params fall back to Settings env vars."""
        settings_map = {
            "email_imap_host": "fallback.imap.com",
            "email_user": "fallback@example.com",
            "email_password": "fb_pass",
        }
        mock_client = _mock_imap_client(list_lines=[])

        with (
            patch("max.tools.native.email_tools._get_settings_value", side_effect=lambda k: settings_map.get(k, "")),
            patch("max.tools.native.email_tools.aioimaplib") as mock_imap,
        ):
            mock_imap.IMAP4_SSL = MagicMock(return_value=mock_client)

            result = await handle_email_list_folders({})

            mock_imap.IMAP4_SSL.assert_called_once_with(host="fallback.imap.com")
            mock_client.login.assert_awaited_once_with("fallback@example.com", "fb_pass")
