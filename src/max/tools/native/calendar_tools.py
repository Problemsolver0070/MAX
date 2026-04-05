"""Calendar tools — list, create, update, delete events via CalDAV.

Uses caldav + icalendar libraries for CalDAV server interaction.
All tools gracefully degrade if dependencies are not installed.
Connection parameters fall back to Settings env vars if not provided.
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from datetime import datetime, timezone
from typing import Any

from max.tools.registry import ToolDefinition

try:
    import caldav

    HAS_CALDAV = True
except ImportError:
    caldav = None  # type: ignore[assignment]
    HAS_CALDAV = False

try:
    from icalendar import Calendar, Event

    HAS_ICALENDAR = True
except ImportError:
    Calendar = None  # type: ignore[assignment,misc]
    Event = None  # type: ignore[assignment,misc]
    HAS_ICALENDAR = False


# ── Tool definitions ──────────────────────────────────────────────────

_CONNECTION_PROPERTIES = {
    "caldav_url": {
        "type": "string",
        "description": "CalDAV server URL (falls back to CALDAV_URL env var)",
    },
    "user": {
        "type": "string",
        "description": "CalDAV username (falls back to CALDAV_USER env var)",
    },
    "password": {
        "type": "string",
        "description": "CalDAV password (falls back to CALDAV_PASSWORD env var)",
    },
}

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="calendar.list_events",
        category="productivity",
        description="List calendar events in a date range from a CalDAV server.",
        permissions=["calendar.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "start": {
                    "type": "string",
                    "description": "Start date/time in ISO 8601 format",
                },
                "end": {
                    "type": "string",
                    "description": "End date/time in ISO 8601 format",
                },
                **_CONNECTION_PROPERTIES,
            },
            "required": ["start", "end"],
        },
    ),
    ToolDefinition(
        tool_id="calendar.create_event",
        category="productivity",
        description="Create a new calendar event on a CalDAV server.",
        permissions=["calendar.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Event title / summary",
                },
                "start": {
                    "type": "string",
                    "description": "Start date/time in ISO 8601 format",
                },
                "end": {
                    "type": "string",
                    "description": "End date/time in ISO 8601 format",
                },
                "location": {
                    "type": "string",
                    "description": "Event location (optional)",
                },
                "description": {
                    "type": "string",
                    "description": "Event description (optional)",
                },
                **_CONNECTION_PROPERTIES,
            },
            "required": ["summary", "start", "end"],
        },
    ),
    ToolDefinition(
        tool_id="calendar.update_event",
        category="productivity",
        description="Update an existing calendar event on a CalDAV server.",
        permissions=["calendar.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "uid": {
                    "type": "string",
                    "description": "Unique ID of the event to update",
                },
                "summary": {
                    "type": "string",
                    "description": "New event title (optional)",
                },
                "start": {
                    "type": "string",
                    "description": "New start date/time in ISO 8601 format (optional)",
                },
                "end": {
                    "type": "string",
                    "description": "New end date/time in ISO 8601 format (optional)",
                },
                "location": {
                    "type": "string",
                    "description": "New event location (optional)",
                },
                "description": {
                    "type": "string",
                    "description": "New event description (optional)",
                },
                **_CONNECTION_PROPERTIES,
            },
            "required": ["uid"],
        },
    ),
    ToolDefinition(
        tool_id="calendar.delete_event",
        category="productivity",
        description="Delete a calendar event from a CalDAV server.",
        permissions=["calendar.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "uid": {
                    "type": "string",
                    "description": "Unique ID of the event to delete",
                },
                **_CONNECTION_PROPERTIES,
            },
            "required": ["uid"],
        },
    ),
]


# ── Helpers ───────────────────────────────────────────────────────────


def _no_dep_error(lib: str) -> dict[str, Any]:
    """Return an error dict for a missing dependency."""
    return {"error": f"{lib} is not installed. Install with: pip install {lib}"}


def _check_deps() -> dict[str, Any] | None:
    """Check that caldav and icalendar are installed. Return error dict or None."""
    if not HAS_CALDAV:
        return _no_dep_error("caldav")
    if not HAS_ICALENDAR:
        return _no_dep_error("icalendar")
    return None


def _get_connection_params(inputs: dict[str, Any]) -> tuple[str, str, str]:
    """Extract connection params from inputs, falling back to Settings env vars.

    Returns (url, username, password).
    """
    url = inputs.get("caldav_url", "")
    user = inputs.get("user", "")
    password = inputs.get("password", "")

    if not url or not user or not password:
        try:
            from max.config import Settings

            settings = Settings()
            if not url:
                url = settings.caldav_url
            if not user:
                user = settings.caldav_user
            if not password:
                password = settings.caldav_password
        except Exception:
            pass  # Settings may fail if env vars not set; that's OK

    return url, user, password


def _get_calendar(url: str, username: str, password: str) -> Any:
    """Connect to CalDAV and return the first calendar."""
    client = caldav.DAVClient(url=url, username=username, password=password)
    principal = client.principal()
    calendars = principal.calendars()
    if not calendars:
        raise RuntimeError("No calendars found on the CalDAV server")
    return calendars[0]


def _parse_event(vevent: Any) -> dict[str, Any]:
    """Parse a caldav event object into a dict.

    Extracts uid, summary, start, end, location, and description
    from the vCalendar data using icalendar.
    """
    cal = Calendar.from_ical(vevent.data)
    for component in cal.walk():
        if component.name == "VEVENT":
            result: dict[str, Any] = {
                "uid": str(component.get("uid", "")),
                "summary": str(component.get("summary", "")),
            }

            dtstart = component.get("dtstart")
            if dtstart:
                dt = dtstart.dt
                result["start"] = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
            else:
                result["start"] = ""

            dtend = component.get("dtend")
            if dtend:
                dt = dtend.dt
                result["end"] = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
            else:
                result["end"] = ""

            location = component.get("location")
            if location:
                result["location"] = str(location)

            description = component.get("description")
            if description:
                result["description"] = str(description)

            return result

    return {"uid": "", "summary": ""}


def _build_vcal(
    uid: str,
    summary: str,
    start: str,
    end: str,
    location: str | None = None,
    description: str | None = None,
) -> str:
    """Build an iCalendar VCALENDAR string for a single event."""
    dtstart = datetime.fromisoformat(start)
    dtend = datetime.fromisoformat(end)

    cal = Calendar()
    cal.add("prodid", "-//Max AI Agent//EN")
    cal.add("version", "2.0")

    event = Event()
    event.add("uid", uid)
    event.add("summary", summary)
    event.add("dtstart", dtstart)
    event.add("dtend", dtend)
    if location:
        event.add("location", location)
    if description:
        event.add("description", description)
    event.add("dtstamp", datetime.now(timezone.utc))

    cal.add_component(event)
    return cal.to_ical().decode("utf-8")


async def _run_sync(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a synchronous function in the default executor."""
    loop = asyncio.get_event_loop()
    call = functools.partial(fn, *args, **kwargs)
    return await loop.run_in_executor(None, call)


# ── Handlers ──────────────────────────────────────────────────────────


async def handle_calendar_list_events(inputs: dict[str, Any]) -> dict[str, Any]:
    """List events in a date range from a CalDAV server."""
    dep_err = _check_deps()
    if dep_err:
        return dep_err

    url, user, password = _get_connection_params(inputs)
    if not url:
        return {"error": "No CalDAV URL provided and CALDAV_URL not set"}

    start_str = inputs["start"]
    end_str = inputs["end"]
    start_dt = datetime.fromisoformat(start_str)
    end_dt = datetime.fromisoformat(end_str)

    def _do_list() -> list[dict[str, Any]]:
        calendar = _get_calendar(url, user, password)
        results = calendar.date_search(start_dt, end_dt)
        return [_parse_event(ev) for ev in results]

    events = await _run_sync(_do_list)
    return {"events": events}


async def handle_calendar_create_event(inputs: dict[str, Any]) -> dict[str, Any]:
    """Create a new calendar event."""
    dep_err = _check_deps()
    if dep_err:
        return dep_err

    url, user, password = _get_connection_params(inputs)
    if not url:
        return {"error": "No CalDAV URL provided and CALDAV_URL not set"}

    summary = inputs["summary"]
    start = inputs["start"]
    end = inputs["end"]
    location = inputs.get("location")
    description = inputs.get("description")
    uid = str(uuid.uuid4())

    vcal = _build_vcal(uid, summary, start, end, location, description)

    def _do_create() -> None:
        calendar = _get_calendar(url, user, password)
        calendar.save_event(vcal)

    await _run_sync(_do_create)
    return {"uid": uid, "summary": summary}


async def handle_calendar_update_event(inputs: dict[str, Any]) -> dict[str, Any]:
    """Update an existing calendar event."""
    dep_err = _check_deps()
    if dep_err:
        return dep_err

    url, user, password = _get_connection_params(inputs)
    if not url:
        return {"error": "No CalDAV URL provided and CALDAV_URL not set"}

    uid = inputs["uid"]

    def _do_update() -> None:
        calendar = _get_calendar(url, user, password)
        event = calendar.event_by_uid(uid)
        cal = Calendar.from_ical(event.data)

        for component in cal.walk():
            if component.name == "VEVENT":
                if "summary" in inputs:
                    component["summary"] = inputs["summary"]
                if "start" in inputs:
                    component["dtstart"].dt = datetime.fromisoformat(inputs["start"])
                if "end" in inputs:
                    component["dtend"].dt = datetime.fromisoformat(inputs["end"])
                if "location" in inputs:
                    component["location"] = inputs["location"]
                if "description" in inputs:
                    component["description"] = inputs["description"]
                break

        event.data = cal.to_ical().decode("utf-8")
        event.save()

    await _run_sync(_do_update)
    return {"uid": uid, "updated": True}


async def handle_calendar_delete_event(inputs: dict[str, Any]) -> dict[str, Any]:
    """Delete a calendar event by UID."""
    dep_err = _check_deps()
    if dep_err:
        return dep_err

    url, user, password = _get_connection_params(inputs)
    if not url:
        return {"error": "No CalDAV URL provided and CALDAV_URL not set"}

    uid = inputs["uid"]

    def _do_delete() -> None:
        calendar = _get_calendar(url, user, password)
        event = calendar.event_by_uid(uid)
        event.delete()

    await _run_sync(_do_delete)
    return {"uid": uid, "deleted": True}
