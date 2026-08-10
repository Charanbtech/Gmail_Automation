import json
import os
import re
import time

from dotenv import load_dotenv
from google.genai import Client
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel, Field

load_dotenv()

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 2
QUOTA_BLOCK_MINUTES = 30

API_ERROR_FALLBACK = {
    "is_meeting_related": True,
    "meeting_title": "API Error - Needs Review",
    "date": None,
    "time": None,
    "time_zone": None,
    "meet_link": None,
    "description": None,
    "confidence_score": 0,
}

MEETING_KEYWORDS = [
    "meeting", "meet", "join", "call", "sync", "sync up", "standup", "stand-up",
    "catch up", "catch-up", "1:1", "one-on-one", "one on one", "agenda", "review",
    "brainstorm", "webinar", "interview", "schedule", "huddle", "session", "demo",
    "planning", "discussion", "appointment", "briefing", "kickoff", "kick-off",
    "summit", "conference", "invite", "zoom", "teams", "hiring", "recruiter",
]

TZ_ABBREVS = [
    "UTC", "GMT", "BST", "CET", "CEST", "EET", "EEST",
    "IST", "EST", "EDT", "CST", "CDT", "MST", "MDT", "PST", "PDT",
    "AEST", "AEDT", "JST", "KST", "SGT", "HKT", "NZST", "NZDT", "AST", "ADT",
]

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

TIME_PATTERNS = [
    re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)", re.I),
    re.compile(r"(\d{1,2})[.:](\d{2})\s*(AM|PM)", re.I),
    re.compile(r"\b(\d{1,2})\s*(AM|PM)\b", re.I),
    re.compile(r"\b(\d{1,2}):(\d{2})\b"),
]

MEET_LINK_RE = re.compile(
    r"https?://(?:meet\.google\.com|[\w.-]*zoom\.us|teams\.microsoft\.com|[\w.-]*webex\.com)/[^\s)\]\"']+",
    re.I,
)
DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
MONTH_DAY_YEAR_RE = re.compile(
    r"\b([A-Z][a-z]{2,8})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b"
)
DAY_MONTH_YEAR_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Z][a-z]{2,8}),?\s+(\d{4})\b"
)
SLASH_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
TZ_LABEL_RE = re.compile(
    r"\b(?:time\s*zone|timezone|tz)\s*[:=]\s*([A-Za-z_/+-]+)", re.I
)

_quota_blocked_until = 0.0


class MeetingDetails(BaseModel):
    is_meeting_related: bool
    meeting_title: str | None = None
    date: str | None = Field(default=None, description="YYYY-MM-DD format")
    time: str | None = Field(default=None, description="HH:MM AM/PM format")
    time_zone: str | None = None
    meet_link: str | None = None
    description: str | None = None
    confidence_score: int = Field(ge=0, le=100)


def is_meeting_candidate(subject: str, body: str) -> bool:
    """Cheap local pre-filter: avoid calling the AI on obvious non-meeting mail."""
    text = f"{subject or ''}\n{body or ''}"
    low = text.lower()

    if MEET_LINK_RE.search(text):
        return True

    has_word_marker = any(
        marker in low
        for marker in ("we will meet", "we'll meet", "will have", "join us", "join me", "please join")
    )
    has_time = any(p.search(text) for p in TIME_PATTERNS)
    has_date = (
        DATE_RE.search(text)
        or MONTH_DAY_YEAR_RE.search(text)
        or DAY_MONTH_YEAR_RE.search(text)
        or SLASH_DATE_RE.search(text)
    )

    strong = any(kw in low for kw in MEETING_KEYWORDS)
    if not strong:
        return False
    if any(marker in low for marker in ("meet", "join", "call ", "sync", "1:1", "standup")):
        return True
    return has_word_marker or has_time or has_date


def _parse_date_value(value: str) -> str | None:
    value = value.strip().strip(".,:;")
    m = DATE_RE.search(value)
    if m:
        year, month, day = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    m = MONTH_DAY_YEAR_RE.search(value)
    if m:
        month_name, day, year = m.groups()
        return f"{year}-{MONTH_NAMES.get(month_name.lower(), 0):02d}-{int(day):02d}"
    m = DAY_MONTH_YEAR_RE.search(value)
    if m:
        day, month_name, year = m.groups()
        return f"{year}-{MONTH_NAMES.get(month_name.lower(), 0):02d}-{int(day):02d}"
    m = SLASH_DATE_RE.search(value)
    if m:
        month, day, year = m.groups()
        if len(year) == 2:
            year = f"20{year}"
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return None


def _parse_local_date(text: str) -> str | None:
    m = re.search(r"\bdate\s*[:=]\s*([^\r\n,;]+)", text, re.I)
    if m:
        parsed = _parse_date_value(m.group(1))
        if parsed:
            return parsed
    return _parse_date_value(text)


def _parse_local_time(text: str) -> str | None:
    for pattern in TIME_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        groups = m.groups()
        hour, minute = int(groups[0]), int(groups[1] or 0)
        meridiem = groups[2].upper() if len(groups) > 2 and groups[2] else None
        if meridiem == "PM" and hour < 12:
            hour += 12
        elif meridiem == "AM" and hour == 12:
            hour = 0
        if not meridiem:
            meridiem = "AM" if hour < 12 else "PM"
            hour12 = hour % 12
            if hour12 == 0:
                hour12 = 12
            return f"{hour12:02d}:{minute:02d} {meridiem}"
        return f"{hour % 12 or 12:02d}:{minute:02d} {meridiem}"
    return None


def _parse_local_tz(text: str) -> str | None:
    m = TZ_LABEL_RE.search(text)
    if m:
        value = m.group(1).strip().upper()
        if value in TZ_ABBREVS:
            return value
    for tz in TZ_ABBREVS:
        if re.search(rf"\b{tz}\b", text):
            return tz
    return None


def _local_title(subject: str, text: str) -> str:
    clean_subject = re.sub(
        r"^(re|fw|fwd|aw):\s*", "", subject or "", flags=re.I
    ).strip()
    for line in text.splitlines():
        line = line.strip()
        low = line.lower()
        if len(line.split()) < 2 or not any(kw in low for kw in MEETING_KEYWORDS):
            continue
        sentence = re.split(r"[.!?]", line)[0].strip()
        sentence = re.sub(
            r"^(?:please\s+)?(?:join|attend|come to)\s+(?:us|me|the team)?\s*(?:for|in|at)?\s*(?:the\s+)?",
            "", sentence, flags=re.I,
        ).strip()
        if len(sentence) >= 2:
            return sentence[:120]
    return clean_subject[:120] or "Meeting"


def _local_extract(subject: str, body: str) -> dict | None:
    """Extract meeting details from explicitly-labelled or clearly formatted emails."""
    text = f"{subject or ''}\n{body or ''}"
    date = _parse_local_date(text)
    time = _parse_local_time(text)
    if not date or not time:
        return None
    link = None
    m = MEET_LINK_RE.search(text)
    if m:
        link = m.group(0)
    return {
        "is_meeting_related": True,
        "meeting_title": _local_title(subject, text),
        "date": date,
        "time": time,
        "time_zone": _parse_local_tz(text),
        "meet_link": link,
        "description": None,
        "confidence_score": 85,
    }


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "code", None)
    if status is None:
        return True
    return status in (429, 500, 503)


def _is_quota_exhausted(exc: Exception) -> bool:
    low = (getattr(exc, "message", None) or str(exc)).lower()
    return "quota" in low or "resource_exhausted" in low


def _retry_delay_seconds(exc: Exception) -> float:
    details = getattr(exc, "details", None) or {}
    for item in details.get("error", {}).get("details", []):
        if item.get("@type", "").endswith("google.rpc.RetryInfo"):
            delay = item.get("retryDelay", "")
            if delay.endswith("s"):
                try:
                    return min(float(delay[:-1]), 60.0)
                except ValueError:
                    pass
    return 0.0


def _error_fallback(exc: Exception) -> dict:
    fallback = dict(API_ERROR_FALLBACK)
    reason = getattr(exc, "message", None) or str(exc)
    fallback["description"] = f"Gemini API error: {reason}"[:500]
    return fallback


def extract_meeting_info(email_text: str, email_date: str, subject: str | None = None) -> dict:
    global _quota_blocked_until
    if time.time() < _quota_blocked_until:
        local = _local_extract(subject, email_text)
        if local:
            return local
        fallback = dict(API_ERROR_FALLBACK)
        fallback["description"] = (
            "AI temporarily unavailable (quota exceeded). "
            "Could not parse meeting details from the email locally."
        )
        return fallback

    client = Client(api_key=os.getenv("GEMINI_API_KEY"))
    config = GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=MeetingDetails,
        system_instruction=(
            "You are an AI that extracts meeting details from emails. "
            f"The email was received on {email_date}. Parse relative dates based on this timestamp. "
            "If no meeting exists, set is_meeting_related to false and confidence_score to 100."
        ),
    )

    last_error = None
    waited_for_delay = False
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=email_text,
                config=config,
            )
            return json.loads(response.text)
        except Exception as exc:
            last_error = exc
            print(f"Gemini API error (attempt {attempt}/{MAX_RETRIES}): {exc}")
            if _is_quota_exhausted(exc):
                _quota_blocked_until = time.time() + QUOTA_BLOCK_MINUTES * 60
                print(f"Quota exhausted - blocking Gemini calls for {QUOTA_BLOCK_MINUTES} min")
                break
            if attempt >= MAX_RETRIES or not _is_retryable(exc):
                break
            delay = _retry_delay_seconds(exc)
            if delay > 0 and not waited_for_delay:
                waited_for_delay = True
                print(f"Waiting {delay:.0f}s for quota/rate-limit reset...")
                time.sleep(delay)
            elif delay > 0:
                break
            else:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    local = _local_extract(subject, email_text)
    if local:
        print("Gemini failed, using local extraction fallback")
        return local

    print(f"Gemini extraction failed after {MAX_RETRIES} attempts: {last_error}")
    return _error_fallback(last_error)