"""Tests for calendar tools — CalDAV list/create/update/delete.

All tests mock caldav and icalendar — no real CalDAV server needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from max.tools.native.calendar_tools import (
    TOOL_DEFINITIONS,
    handle_calendar_create_event,
    handle_calendar_delete_event,
    handle_calendar_list_events,
    handle_calendar_update_event,
)


# ── Fixtures ──────────────────────────────────────────────────────────


SAMPLE_VCAL = (
    "BEGIN:VCALENDAR\r\n"
    "PRODID:-//Test//EN\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:test-uid-123\r\n"
    "SUMMARY:Team Standup\r\n"
    "DTSTART:20250115T090000Z\r\n"
    "DTEND:20250115T093000Z\r\n"
    "LOCATION:Conference Room A\r\n"
    "DESCRIPTION:Daily standup meeting\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

SAMPLE_VCAL_MINIMAL = (
    "BEGIN:VCALENDAR\r\n"
    "PRODID:-//Test//EN\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:test-uid-456\r\n"
    "SUMMARY:Quick Chat\r\n"
    "DTSTART:20250115T140000Z\r\n"
    "DTEND:20250115T143000Z\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def _make_mock_event(vcal_data: str) -> MagicMock:
    """Create a mock caldav event with the given vCalendar data."""
    mock_event = MagicMock()
    mock_event.data = vcal_data
    return mock_event


def _make_mock_calendar(events: list | None = None) -> MagicMock:
    """Create a mock caldav calendar."""
    mock_cal = MagicMock()
    mock_cal.date_search.return_value = events or []
    mock_cal.save_event.return_value = None
    mock_cal.event_by_uid.return_value = _make_mock_event(SAMPLE_VCAL)
    return mock_cal


def _make_mock_dav_client(calendar: MagicMock | None = None) -> MagicMock:
    """Create a mock DAVClient with principal and calendars chain."""
    mock_client_cls = MagicMock()
    mock_client = MagicMock()
    mock_principal = MagicMock()
    cal = calendar or _make_mock_calendar()
    mock_principal.calendars.return_value = [cal]
    mock_client.principal.return_value = mock_principal
    mock_client_cls.return_value = mock_client
    return mock_client_cls


BASE_INPUTS = {
    "caldav_url": "https://caldav.example.com/dav",
    "user": "testuser",
    "password": "testpass",
}


# ── Tool Definition Tests ────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_four_definitions(self):
        assert len(TOOL_DEFINITIONS) == 4

    def test_all_productivity_category(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.category == "productivity", f"{tool.tool_id} has category {tool.category}"

    def test_all_native_provider(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.provider_id == "native", f"{tool.tool_id} has provider {tool.provider_id}"

    def test_tool_ids(self):
        ids = {t.tool_id for t in TOOL_DEFINITIONS}
        assert ids == {
            "calendar.list_events",
            "calendar.create_event",
            "calendar.update_event",
            "calendar.delete_event",
        }

    def test_list_events_schema_requires_start_end(self):
        tool = next(t for t in TOOL_DEFINITIONS if t.tool_id == "calendar.list_events")
        assert "start" in tool.input_schema["required"]
        assert "end" in tool.input_schema["required"]

    def test_create_event_schema_requires_summary_start_end(self):
        tool = next(t for t in TOOL_DEFINITIONS if t.tool_id == "calendar.create_event")
        assert "summary" in tool.input_schema["required"]
        assert "start" in tool.input_schema["required"]
        assert "end" in tool.input_schema["required"]

    def test_update_event_schema_requires_uid(self):
        tool = next(t for t in TOOL_DEFINITIONS if t.tool_id == "calendar.update_event")
        assert "uid" in tool.input_schema["required"]

    def test_delete_event_schema_requires_uid(self):
        tool = next(t for t in TOOL_DEFINITIONS if t.tool_id == "calendar.delete_event")
        assert "uid" in tool.input_schema["required"]

    def test_all_schemas_have_connection_properties(self):
        for tool in TOOL_DEFINITIONS:
            props = tool.input_schema["properties"]
            assert "caldav_url" in props, f"{tool.tool_id} missing caldav_url"
            assert "user" in props, f"{tool.tool_id} missing user"
            assert "password" in props, f"{tool.tool_id} missing password"

    def test_all_have_permissions(self):
        for tool in TOOL_DEFINITIONS:
            assert len(tool.permissions) > 0, f"{tool.tool_id} has no permissions"

    def test_read_tools_have_read_permission(self):
        tool = next(t for t in TOOL_DEFINITIONS if t.tool_id == "calendar.list_events")
        assert "calendar.read" in tool.permissions

    def test_write_tools_have_write_permission(self):
        write_ids = {"calendar.create_event", "calendar.update_event", "calendar.delete_event"}
        for tool in TOOL_DEFINITIONS:
            if tool.tool_id in write_ids:
                assert "calendar.write" in tool.permissions, f"{tool.tool_id} missing calendar.write"


# ── Missing Dependency Tests ──────────────────────────────────────────


class TestMissingCaldav:
    @pytest.mark.asyncio
    async def test_list_events_no_caldav(self):
        with patch("max.tools.native.calendar_tools.HAS_CALDAV", False):
            result = await handle_calendar_list_events({**BASE_INPUTS, "start": "2025-01-01", "end": "2025-01-31"})
        assert "error" in result
        assert "caldav" in result["error"]

    @pytest.mark.asyncio
    async def test_create_event_no_caldav(self):
        with patch("max.tools.native.calendar_tools.HAS_CALDAV", False):
            result = await handle_calendar_create_event(
                {**BASE_INPUTS, "summary": "Test", "start": "2025-01-15T09:00:00", "end": "2025-01-15T10:00:00"}
            )
        assert "error" in result
        assert "caldav" in result["error"]

    @pytest.mark.asyncio
    async def test_update_event_no_caldav(self):
        with patch("max.tools.native.calendar_tools.HAS_CALDAV", False):
            result = await handle_calendar_update_event({**BASE_INPUTS, "uid": "test-uid"})
        assert "error" in result
        assert "caldav" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_event_no_caldav(self):
        with patch("max.tools.native.calendar_tools.HAS_CALDAV", False):
            result = await handle_calendar_delete_event({**BASE_INPUTS, "uid": "test-uid"})
        assert "error" in result
        assert "caldav" in result["error"]


class TestMissingIcalendar:
    @pytest.mark.asyncio
    async def test_list_events_no_icalendar(self):
        with patch("max.tools.native.calendar_tools.HAS_ICALENDAR", False):
            result = await handle_calendar_list_events({**BASE_INPUTS, "start": "2025-01-01", "end": "2025-01-31"})
        assert "error" in result
        assert "icalendar" in result["error"]

    @pytest.mark.asyncio
    async def test_create_event_no_icalendar(self):
        with patch("max.tools.native.calendar_tools.HAS_ICALENDAR", False):
            result = await handle_calendar_create_event(
                {**BASE_INPUTS, "summary": "Test", "start": "2025-01-15T09:00:00", "end": "2025-01-15T10:00:00"}
            )
        assert "error" in result
        assert "icalendar" in result["error"]


# ── List Events Tests ─────────────────────────────────────────────────


class TestListEvents:
    @pytest.mark.asyncio
    async def test_returns_events_list(self):
        mock_events = [_make_mock_event(SAMPLE_VCAL), _make_mock_event(SAMPLE_VCAL_MINIMAL)]
        mock_cal = _make_mock_calendar(mock_events)
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_list_events(
                {**BASE_INPUTS, "start": "2025-01-01T00:00:00", "end": "2025-01-31T23:59:59"}
            )

        assert "events" in result
        assert len(result["events"]) == 2
        assert result["events"][0]["uid"] == "test-uid-123"
        assert result["events"][0]["summary"] == "Team Standup"
        assert result["events"][1]["uid"] == "test-uid-456"
        assert result["events"][1]["summary"] == "Quick Chat"

    @pytest.mark.asyncio
    async def test_event_has_location_and_description(self):
        mock_events = [_make_mock_event(SAMPLE_VCAL)]
        mock_cal = _make_mock_calendar(mock_events)
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_list_events(
                {**BASE_INPUTS, "start": "2025-01-01T00:00:00", "end": "2025-01-31T23:59:59"}
            )

        event = result["events"][0]
        assert "location" in event
        assert event["location"] == "Conference Room A"
        assert "description" in event
        assert event["description"] == "Daily standup meeting"

    @pytest.mark.asyncio
    async def test_minimal_event_no_location_description(self):
        mock_events = [_make_mock_event(SAMPLE_VCAL_MINIMAL)]
        mock_cal = _make_mock_calendar(mock_events)
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_list_events(
                {**BASE_INPUTS, "start": "2025-01-01T00:00:00", "end": "2025-01-31T23:59:59"}
            )

        event = result["events"][0]
        assert "location" not in event
        assert "description" not in event

    @pytest.mark.asyncio
    async def test_empty_events_list(self):
        mock_cal = _make_mock_calendar([])
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_list_events(
                {**BASE_INPUTS, "start": "2025-01-01T00:00:00", "end": "2025-01-31T23:59:59"}
            )

        assert result["events"] == []

    @pytest.mark.asyncio
    async def test_calls_date_search_with_correct_dates(self):
        mock_cal = _make_mock_calendar([])
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            await handle_calendar_list_events(
                {**BASE_INPUTS, "start": "2025-01-15T09:00:00", "end": "2025-01-15T17:00:00"}
            )

        mock_cal.date_search.assert_called_once()
        args = mock_cal.date_search.call_args[0]
        assert args[0] == datetime.fromisoformat("2025-01-15T09:00:00")
        assert args[1] == datetime.fromisoformat("2025-01-15T17:00:00")


# ── Create Event Tests ────────────────────────────────────────────────


class TestCreateEvent:
    @pytest.mark.asyncio
    async def test_creates_event_returns_uid_and_summary(self):
        mock_cal = _make_mock_calendar()
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_create_event(
                {
                    **BASE_INPUTS,
                    "summary": "Sprint Planning",
                    "start": "2025-01-20T10:00:00",
                    "end": "2025-01-20T11:00:00",
                }
            )

        assert "uid" in result
        assert result["summary"] == "Sprint Planning"
        mock_cal.save_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_event_with_location_and_description(self):
        mock_cal = _make_mock_calendar()
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_create_event(
                {
                    **BASE_INPUTS,
                    "summary": "Team Lunch",
                    "start": "2025-01-20T12:00:00",
                    "end": "2025-01-20T13:00:00",
                    "location": "Cafe Downtown",
                    "description": "Team building lunch",
                }
            )

        assert result["summary"] == "Team Lunch"
        # Verify the vcal string passed to save_event contains location and description
        vcal_arg = mock_cal.save_event.call_args[0][0]
        assert "Cafe Downtown" in vcal_arg
        assert "Team building lunch" in vcal_arg

    @pytest.mark.asyncio
    async def test_save_event_called_with_vcal_string(self):
        mock_cal = _make_mock_calendar()
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            await handle_calendar_create_event(
                {
                    **BASE_INPUTS,
                    "summary": "Meeting",
                    "start": "2025-01-20T10:00:00",
                    "end": "2025-01-20T11:00:00",
                }
            )

        vcal_arg = mock_cal.save_event.call_args[0][0]
        assert "BEGIN:VCALENDAR" in vcal_arg
        assert "BEGIN:VEVENT" in vcal_arg
        assert "Meeting" in vcal_arg

    @pytest.mark.asyncio
    async def test_uid_is_unique_per_call(self):
        mock_cal = _make_mock_calendar()
        mock_client_cls = _make_mock_dav_client(mock_cal)

        uids = []
        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            for _ in range(3):
                result = await handle_calendar_create_event(
                    {
                        **BASE_INPUTS,
                        "summary": "Event",
                        "start": "2025-01-20T10:00:00",
                        "end": "2025-01-20T11:00:00",
                    }
                )
                uids.append(result["uid"])

        assert len(set(uids)) == 3  # All unique


# ── Update Event Tests ────────────────────────────────────────────────


class TestUpdateEvent:
    @pytest.mark.asyncio
    async def test_update_returns_uid_and_updated_true(self):
        mock_event = _make_mock_event(SAMPLE_VCAL)
        mock_cal = _make_mock_calendar()
        mock_cal.event_by_uid.return_value = mock_event
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_update_event(
                {**BASE_INPUTS, "uid": "test-uid-123", "summary": "Updated Standup"}
            )

        assert result["uid"] == "test-uid-123"
        assert result["updated"] is True

    @pytest.mark.asyncio
    async def test_update_calls_event_by_uid(self):
        mock_event = _make_mock_event(SAMPLE_VCAL)
        mock_cal = _make_mock_calendar()
        mock_cal.event_by_uid.return_value = mock_event
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            await handle_calendar_update_event(
                {**BASE_INPUTS, "uid": "test-uid-123", "summary": "Updated"}
            )

        mock_cal.event_by_uid.assert_called_once_with("test-uid-123")

    @pytest.mark.asyncio
    async def test_update_saves_modified_event(self):
        mock_event = _make_mock_event(SAMPLE_VCAL)
        mock_cal = _make_mock_calendar()
        mock_cal.event_by_uid.return_value = mock_event
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            await handle_calendar_update_event(
                {**BASE_INPUTS, "uid": "test-uid-123", "summary": "Updated Title"}
            )

        mock_event.save.assert_called_once()


# ── Delete Event Tests ────────────────────────────────────────────────


class TestDeleteEvent:
    @pytest.mark.asyncio
    async def test_delete_returns_uid_and_deleted_true(self):
        mock_event = _make_mock_event(SAMPLE_VCAL)
        mock_cal = _make_mock_calendar()
        mock_cal.event_by_uid.return_value = mock_event
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_delete_event(
                {**BASE_INPUTS, "uid": "test-uid-123"}
            )

        assert result["uid"] == "test-uid-123"
        assert result["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_calls_event_delete(self):
        mock_event = _make_mock_event(SAMPLE_VCAL)
        mock_cal = _make_mock_calendar()
        mock_cal.event_by_uid.return_value = mock_event
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            await handle_calendar_delete_event(
                {**BASE_INPUTS, "uid": "test-uid-123"}
            )

        mock_cal.event_by_uid.assert_called_once_with("test-uid-123")
        mock_event.delete.assert_called_once()


# ── Settings Fallback Tests ───────────────────────────────────────────


class TestSettingsFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_settings_env_vars(self, monkeypatch):
        """Connection params fall back to Settings when not in inputs."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("POSTGRES_PASSWORD", "testpass")
        monkeypatch.setenv("CALDAV_URL", "https://fallback.example.com/dav")
        monkeypatch.setenv("CALDAV_USER", "fallback_user")
        monkeypatch.setenv("CALDAV_PASSWORD", "fallback_pass")

        mock_cal = _make_mock_calendar([])
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_list_events(
                {"start": "2025-01-01T00:00:00", "end": "2025-01-31T23:59:59"}
            )

        assert "events" in result
        # Verify DAVClient was called with fallback values
        mock_client_cls.assert_called_once_with(
            url="https://fallback.example.com/dav",
            username="fallback_user",
            password="fallback_pass",
        )

    @pytest.mark.asyncio
    async def test_input_params_override_settings(self, monkeypatch):
        """Explicit input params should take precedence over env vars."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("POSTGRES_PASSWORD", "testpass")
        monkeypatch.setenv("CALDAV_URL", "https://fallback.example.com/dav")
        monkeypatch.setenv("CALDAV_USER", "fallback_user")
        monkeypatch.setenv("CALDAV_PASSWORD", "fallback_pass")

        mock_cal = _make_mock_calendar([])
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            result = await handle_calendar_list_events(
                {
                    **BASE_INPUTS,
                    "start": "2025-01-01T00:00:00",
                    "end": "2025-01-31T23:59:59",
                }
            )

        assert "events" in result
        # Verify DAVClient was called with input values, not fallback
        mock_client_cls.assert_called_once_with(
            url="https://caldav.example.com/dav",
            username="testuser",
            password="testpass",
        )

    @pytest.mark.asyncio
    async def test_no_url_returns_error(self):
        """When no URL is provided and Settings doesn't have one, return error."""
        with patch("max.tools.native.calendar_tools._get_connection_params", return_value=("", "user", "pass")):
            result = await handle_calendar_list_events(
                {"start": "2025-01-01", "end": "2025-01-31"}
            )
        assert "error" in result
        assert "CalDAV URL" in result["error"]

    @pytest.mark.asyncio
    async def test_no_url_create_returns_error(self):
        with patch("max.tools.native.calendar_tools._get_connection_params", return_value=("", "user", "pass")):
            result = await handle_calendar_create_event(
                {"summary": "Test", "start": "2025-01-15T09:00:00", "end": "2025-01-15T10:00:00"}
            )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_url_update_returns_error(self):
        with patch("max.tools.native.calendar_tools._get_connection_params", return_value=("", "user", "pass")):
            result = await handle_calendar_update_event({"uid": "test-uid"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_url_delete_returns_error(self):
        with patch("max.tools.native.calendar_tools._get_connection_params", return_value=("", "user", "pass")):
            result = await handle_calendar_delete_event({"uid": "test-uid"})
        assert "error" in result


# ── Connection and Calendar Resolution Tests ──────────────────────────


class TestConnectionHandling:
    @pytest.mark.asyncio
    async def test_connects_with_correct_credentials(self):
        mock_cal = _make_mock_calendar([])
        mock_client_cls = _make_mock_dav_client(mock_cal)

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            await handle_calendar_list_events(
                {
                    "caldav_url": "https://my.server.com/dav",
                    "user": "myuser",
                    "password": "mypass",
                    "start": "2025-01-01T00:00:00",
                    "end": "2025-01-31T23:59:59",
                }
            )

        mock_client_cls.assert_called_once_with(
            url="https://my.server.com/dav",
            username="myuser",
            password="mypass",
        )

    @pytest.mark.asyncio
    async def test_uses_first_calendar(self):
        """Should use the first calendar from principal.calendars()."""
        mock_cal1 = _make_mock_calendar([])
        mock_cal2 = _make_mock_calendar([])

        mock_client_cls = MagicMock()
        mock_client = MagicMock()
        mock_principal = MagicMock()
        mock_principal.calendars.return_value = [mock_cal1, mock_cal2]
        mock_client.principal.return_value = mock_principal
        mock_client_cls.return_value = mock_client

        with patch("max.tools.native.calendar_tools.caldav") as mock_caldav_mod:
            mock_caldav_mod.DAVClient = mock_client_cls
            await handle_calendar_list_events(
                {**BASE_INPUTS, "start": "2025-01-01T00:00:00", "end": "2025-01-31T23:59:59"}
            )

        mock_cal1.date_search.assert_called_once()
        mock_cal2.date_search.assert_not_called()
