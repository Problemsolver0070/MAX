"""Email tools — send via SMTP, read/search/list via IMAP."""

from __future__ import annotations

import email as email_stdlib
import email.utils
import logging
from email.message import EmailMessage
from typing import Any

from max.tools.registry import ToolDefinition

logger = logging.getLogger(__name__)

# Graceful imports — tools degrade cleanly if libraries are missing.
try:
    import aiosmtplib

    HAS_AIOSMTPLIB = True
except ImportError:
    aiosmtplib = None  # type: ignore[assignment]
    HAS_AIOSMTPLIB = False

try:
    import aioimaplib

    HAS_AIOIMAPLIB = True
except ImportError:
    aioimaplib = None  # type: ignore[assignment]
    HAS_AIOIMAPLIB = False


def _get_settings_value(key: str) -> str:
    """Try to load a setting from the Max Settings object.

    Returns empty string if Settings is unavailable (e.g. missing env vars).
    """
    try:
        from max.config import Settings

        settings = Settings()  # type: ignore[call-arg]
        return str(getattr(settings, key, ""))
    except Exception:
        return ""


def _resolve_smtp(inputs: dict[str, Any]) -> tuple[str, int, str, str]:
    """Resolve SMTP connection params from inputs or Settings fallback."""
    host = inputs.get("smtp_host") or _get_settings_value("email_smtp_host")
    port = inputs.get("smtp_port") or int(_get_settings_value("email_smtp_port") or "587")
    user = inputs.get("user") or _get_settings_value("email_user")
    password = inputs.get("password") or _get_settings_value("email_password")
    return host, int(port), user, password


def _resolve_imap(inputs: dict[str, Any]) -> tuple[str, str, str]:
    """Resolve IMAP connection params from inputs or Settings fallback."""
    host = inputs.get("imap_host") or _get_settings_value("email_imap_host")
    user = inputs.get("user") or _get_settings_value("email_user")
    password = inputs.get("password") or _get_settings_value("email_password")
    return host, user, password


# ── Tool definitions ──────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="email.send",
        category="communication",
        description="Send an email via SMTP.",
        permissions=["network.smtp"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address(es), comma-separated",
                },
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
                "cc": {"type": "string", "description": "CC recipients, comma-separated"},
                "bcc": {"type": "string", "description": "BCC recipients, comma-separated"},
                "smtp_host": {"type": "string", "description": "SMTP server hostname"},
                "smtp_port": {"type": "integer", "description": "SMTP server port", "default": 587},
                "user": {"type": "string", "description": "SMTP username"},
                "password": {"type": "string", "description": "SMTP password"},
            },
            "required": ["to", "subject", "body"],
        },
    ),
    ToolDefinition(
        tool_id="email.read",
        category="communication",
        description="Read recent emails from an IMAP mailbox.",
        permissions=["network.imap"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Mailbox folder", "default": "INBOX"},
                "count": {
                    "type": "integer",
                    "description": "Number of recent messages to fetch",
                    "default": 10,
                },
                "imap_host": {"type": "string", "description": "IMAP server hostname"},
                "user": {"type": "string", "description": "IMAP username"},
                "password": {"type": "string", "description": "IMAP password"},
            },
        },
    ),
    ToolDefinition(
        tool_id="email.search",
        category="communication",
        description="Search emails in an IMAP mailbox.",
        permissions=["network.imap"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "criteria": {
                    "type": "string",
                    "description": "IMAP SEARCH criteria (e.g. 'FROM alice SUBJECT hello')",
                },
                "folder": {"type": "string", "description": "Mailbox folder", "default": "INBOX"},
                "imap_host": {"type": "string", "description": "IMAP server hostname"},
                "user": {"type": "string", "description": "IMAP username"},
                "password": {"type": "string", "description": "IMAP password"},
            },
            "required": ["criteria"],
        },
    ),
    ToolDefinition(
        tool_id="email.list_folders",
        category="communication",
        description="List available email folders on the IMAP server.",
        permissions=["network.imap"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "imap_host": {"type": "string", "description": "IMAP server hostname"},
                "user": {"type": "string", "description": "IMAP username"},
                "password": {"type": "string", "description": "IMAP password"},
            },
        },
    ),
]


# ── IMAP helpers ──────────────────────────────────────────────────────


async def _imap_connect(host: str, user: str, password: str) -> Any:
    """Create an IMAP4_SSL connection, wait for greeting, and login."""
    client = aioimaplib.IMAP4_SSL(host=host)
    await client.wait_hello_from_server()
    await client.login(user, password)
    return client


def _parse_email_headers(raw_bytes: bytes) -> dict[str, str]:
    """Parse an email message from bytes and return header summary."""
    msg = email_stdlib.message_from_bytes(raw_bytes)
    return {
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
    }


def _parse_email_with_preview(raw_bytes: bytes, preview_length: int = 200) -> dict[str, str]:
    """Parse an email message and include a body preview."""
    msg = email_stdlib.message_from_bytes(raw_bytes)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(errors="replace")

    return {
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "body_preview": body[:preview_length],
    }


def _extract_message_bytes(fetch_lines: list[Any]) -> list[bytes]:
    """Extract raw email bytes from IMAP FETCH response lines.

    aioimaplib returns alternating lines: a FETCH metadata line
    (e.g. ``b'1 FETCH (RFC822 {100})'``) followed by the raw bytes of
    the message.  We skip metadata lines and collect only the actual
    email content by checking for RFC-822 headers.
    """
    import re

    fetch_meta = re.compile(rb"^\d+\s+FETCH\s+\(")

    messages: list[bytes] = []
    for line in fetch_lines:
        if isinstance(line, bytes) and line.strip():
            # Skip IMAP protocol metadata lines
            if fetch_meta.match(line):
                continue
            messages.append(line)
    return messages


def _parse_folder_name(line: str) -> str | None:
    """Extract folder name from an IMAP LIST response line.

    Example line: '(\\HasNoChildren) "/" "INBOX"'
    """
    if not line or not isinstance(line, str):
        return None
    # The folder name is the last quoted string or word
    parts = line.rsplit('" "', 1)
    if len(parts) == 2:
        return parts[1].rstrip('"')
    parts = line.rsplit(" ", 1)
    if len(parts) == 2:
        return parts[1].strip('"')
    return None


# ── Handlers ──────────────────────────────────────────────────────────


async def handle_email_send(inputs: dict[str, Any]) -> dict[str, Any]:
    """Send an email via SMTP."""
    if not HAS_AIOSMTPLIB:
        return {"error": "aiosmtplib is not installed. Run: pip install aiosmtplib"}

    host, port, user, password = _resolve_smtp(inputs)
    if not host:
        return {"error": "SMTP host not configured. Provide smtp_host or set EMAIL_SMTP_HOST."}

    msg = EmailMessage()
    msg["To"] = inputs["to"]
    msg["Subject"] = inputs["subject"]
    msg["From"] = user or inputs.get("user", "")
    if inputs.get("cc"):
        msg["Cc"] = inputs["cc"]
    if inputs.get("bcc"):
        msg["Bcc"] = inputs["bcc"]
    msg.set_content(inputs["body"])

    try:
        responses, message_id = await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=user or None,
            password=password or None,
            start_tls=True,
        )
        return {"sent": True, "message_id": message_id}
    except Exception as exc:
        logger.exception("Failed to send email")
        return {"sent": False, "error": str(exc)}


async def handle_email_read(inputs: dict[str, Any]) -> dict[str, Any]:
    """Read recent emails from an IMAP mailbox."""
    if not HAS_AIOIMAPLIB:
        return {"error": "aioimaplib is not installed. Run: pip install aioimaplib"}

    host, user, password = _resolve_imap(inputs)
    if not host:
        return {"error": "IMAP host not configured. Provide imap_host or set EMAIL_IMAP_HOST."}

    folder = inputs.get("folder", "INBOX")
    count = inputs.get("count", 10)

    try:
        client = await _imap_connect(host, user, password)
        try:
            await client.select(folder)

            # Search for all messages, take the last N
            search_response = await client.search("ALL")
            if search_response.result != "OK":
                return {"error": f"IMAP search failed: {search_response.result}"}

            # search_response.lines is a list; first element contains space-separated UIDs
            uids_line = search_response.lines[0] if search_response.lines else ""
            all_uids = uids_line.split() if uids_line else []
            recent_uids = all_uids[-count:]

            messages: list[dict[str, str]] = []
            if recent_uids:
                uid_set = ",".join(recent_uids)
                fetch_response = await client.fetch(uid_set, "(RFC822)")
                raw_messages = _extract_message_bytes(fetch_response.lines)
                for raw in raw_messages:
                    messages.append(_parse_email_with_preview(raw))

            return {"messages": messages}
        finally:
            await client.logout()
    except Exception as exc:
        logger.exception("Failed to read emails")
        return {"error": str(exc)}


async def handle_email_search(inputs: dict[str, Any]) -> dict[str, Any]:
    """Search emails in an IMAP mailbox."""
    if not HAS_AIOIMAPLIB:
        return {"error": "aioimaplib is not installed. Run: pip install aioimaplib"}

    host, user, password = _resolve_imap(inputs)
    if not host:
        return {"error": "IMAP host not configured. Provide imap_host or set EMAIL_IMAP_HOST."}

    folder = inputs.get("folder", "INBOX")
    criteria = inputs["criteria"]

    try:
        client = await _imap_connect(host, user, password)
        try:
            await client.select(folder)

            search_response = await client.search(criteria)
            if search_response.result != "OK":
                return {"error": f"IMAP search failed: {search_response.result}"}

            uids_line = search_response.lines[0] if search_response.lines else ""
            uids = uids_line.split() if uids_line else []

            messages: list[dict[str, str]] = []
            if uids:
                uid_set = ",".join(uids)
                fetch_response = await client.fetch(uid_set, "(RFC822.HEADER)")
                raw_messages = _extract_message_bytes(fetch_response.lines)
                for raw in raw_messages:
                    messages.append(_parse_email_headers(raw))

            return {"messages": messages, "count": len(messages)}
        finally:
            await client.logout()
    except Exception as exc:
        logger.exception("Failed to search emails")
        return {"error": str(exc)}


async def handle_email_list_folders(inputs: dict[str, Any]) -> dict[str, Any]:
    """List available email folders on the IMAP server."""
    if not HAS_AIOIMAPLIB:
        return {"error": "aioimaplib is not installed. Run: pip install aioimaplib"}

    host, user, password = _resolve_imap(inputs)
    if not host:
        return {"error": "IMAP host not configured. Provide imap_host or set EMAIL_IMAP_HOST."}

    try:
        client = await _imap_connect(host, user, password)
        try:
            list_response = await client.list('""', "*")
            if list_response.result != "OK":
                return {"error": f"IMAP LIST failed: {list_response.result}"}

            folders: list[str] = []
            for line in list_response.lines:
                name = _parse_folder_name(line)
                if name:
                    folders.append(name)

            return {"folders": folders}
        finally:
            await client.logout()
    except Exception as exc:
        logger.exception("Failed to list folders")
        return {"error": str(exc)}
