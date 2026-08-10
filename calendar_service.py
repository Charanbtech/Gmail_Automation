import datetime as dt
import os
import re
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
LOCAL_TIMEZONE = os.getenv("LOCAL_TIMEZONE", "").strip()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

TZ_ABBREVIATIONS = {
    "UTC": "UTC",
    "GMT": "UTC",
    "BST": "Europe/London",
    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",
    "IST": "Asia/Kolkata",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    "NZST": "Pacific/Auckland",
    "NZDT": "Pacific/Auckland",
    "JST": "Asia/Tokyo",
    "KST": "Asia/Seoul",
    "SGT": "Asia/Singapore",
    "HKT": "Asia/Hong_Kong",
    "CST_CN": "Asia/Shanghai",
}


def get_calendar_service():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    return build("calendar", "v3", credentials=creds)


def _resolve_timezone(time_zone):
    """Convert a timezone string (IANA name, abbreviation, or offset) to a tzinfo."""
    if time_zone:
        tz = time_zone.strip()
        if tz in TZ_ABBREVIATIONS:
            return ZoneInfo(TZ_ABBREVIATIONS[tz])
        offset_match = re.fullmatch(r"([+-])(\d{1,2}):?(\d{2})", tz)
        if offset_match:
            sign, hours, minutes = offset_match.groups()
            delta = dt.timedelta(hours=int(hours), minutes=int(minutes))
            if sign == "-":
                delta = -delta
            return dt.timezone(delta)
        try:
            return ZoneInfo(tz)
        except Exception:
            pass
    if LOCAL_TIMEZONE:
        try:
            return ZoneInfo(LOCAL_TIMEZONE)
        except Exception:
            pass
    return dt.datetime.now().astimezone().tzinfo


def _parse_date_time(date_str, time_str, time_zone):
    """Parse extracted date/time strings into a timezone-aware RFC3339 datetime string."""
    tzinfo = _resolve_timezone(time_zone)

    date = None
    if date_str:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                date = dt.datetime.strptime(date_str.strip(), fmt).date()
                break
            except ValueError:
                continue
    if date is None:
        date = dt.date.today()

    time = None
    if time_str:
        t = time_str.strip().upper()
        match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", t)
        if match:
            hour, minute, meridiem = match.groups()
            hour = int(hour)
            minute = int(minute)
            if meridiem == "PM" and hour < 12:
                hour += 12
            elif meridiem == "AM" and hour == 12:
                hour = 0
            time = dt.time(hour, minute)
        else:
            match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", t)
            if match:
                hour, minute, meridiem = match.groups()
                hour = int(hour)
                minute = int(minute or 0)
                if meridiem == "PM" and hour < 12:
                    hour += 12
                elif meridiem == "AM" and hour == 12:
                    hour = 0
                time = dt.time(hour, minute)
    if time is None:
        time = dt.time(9, 0)

    start = dt.datetime.combine(date, time, tzinfo=tzinfo)
    return start.isoformat()


def _parse_rfc3339(start_iso, end_iso):
    """Ensure both datetimes carry an explicit UTC offset for the Calendar API."""
    parsed_start = dt.datetime.fromisoformat(start_iso)
    parsed_end = dt.datetime.fromisoformat(end_iso)
    if parsed_start.tzinfo is None:
        parsed_start = parsed_start.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
        parsed_end = parsed_end.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed_start.isoformat(), parsed_end.isoformat()


def create_or_update_event(email_id, extracted_data: dict):
    """Create or update a calendar event for the given email, deduped by email_id."""
    service = get_calendar_service()

    existing = (
        service.events()
        .list(
            calendarId="primary",
            privateExtendedProperty=f"email_id={email_id}",
        )
        .execute()
    )
    existing_items = existing.get("items", [])

    start_iso = _parse_date_time(
        extracted_data.get("date"),
        extracted_data.get("time"),
        extracted_data.get("time_zone"),
    )
    end_iso = dt.datetime.fromisoformat(start_iso) + dt.timedelta(hours=1)
    start_iso, end_iso = _parse_rfc3339(start_iso, end_iso.isoformat())

    description = extracted_data.get("description") or ""
    meet_link = extracted_data.get("meet_link")
    if meet_link:
        description = f"{description}\nMeet link: {meet_link}".strip()

    event_body = {
        "summary": extracted_data.get("meeting_title") or "Meeting",
        "description": description,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
        "extendedProperties": {"private": {"email_id": email_id}},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 5}],
        },
    }

    if existing_items:
        event = (
            service.events()
            .update(
                calendarId="primary",
                eventId=existing_items[0]["id"],
                body=event_body,
            )
            .execute()
        )
    else:
        event = service.events().insert(calendarId="primary", body=event_body).execute()

    return event.get("id"), event.get("htmlLink")