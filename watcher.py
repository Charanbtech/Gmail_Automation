import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from ai_extractor import (
    API_ERROR_FALLBACK,
    extract_meeting_info,
    is_meeting_candidate,
)
from calendar_service import create_or_update_event, get_calendar_service
from gmail_service import get_gmail_service, parse_email_content

load_dotenv()

PENDING_FILE = "pending_meetings.json"
STATE_FILE = "live_state.json"

GMAIL_POLL_SECONDS = float(os.getenv("GMAIL_POLL_SECONDS", "8"))
BASELINE_MAX = 50
MAX_NEW_PER_TICK = 5
API_ERROR_RETRY_MINUTES = 5

_state_lock = threading.Lock()
_pending_lock = threading.Lock()
_stop_event = threading.Event()
_watcher_thread = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_pending() -> list[dict]:
    with _pending_lock:
        if not os.path.exists(PENDING_FILE):
            return []
        with open(PENDING_FILE, "r", encoding="utf-8") as pending_file:
            return json.load(pending_file)


def write_pending(entries: list[dict]) -> None:
    with _pending_lock:
        with open(PENDING_FILE, "w", encoding="utf-8") as pending_file:
            json.dump(entries, pending_file, indent=2)


def add_pending(email_id: str, subject: str, extracted_data: dict) -> None:
    entries = [e for e in read_pending() if e["email_id"] != email_id]
    entries.append(
        {
            "email_id": email_id,
            "subject": subject,
            "extracted_data": extracted_data,
        }
    )
    write_pending(entries)


def read_state() -> dict:
    with _state_lock:
        if not os.path.exists(STATE_FILE):
            return {"baseline_done": False, "last_scan": None, "emails": {}}
        with open(STATE_FILE, "r", encoding="utf-8") as state_file:
            return json.load(state_file)


def write_state(state: dict) -> None:
    with _state_lock:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as state_file:
            json.dump(state, state_file, indent=2)
        os.replace(tmp, STATE_FILE)


def update_email_state(email_id: str, **patch) -> None:
    state = read_state()
    entry = state["emails"].get(email_id)
    if entry is None:
        return
    entry.update(patch)
    entry["updated_at"] = _now_iso()
    write_state(state)


def _find_event(calendar_service, email_id: str):
    result = (
        calendar_service.events()
        .list(calendarId="primary", privateExtendedProperty=f"email_id={email_id}")
        .execute()
    )
    items = result.get("items", [])
    if items:
        return items[0].get("id"), items[0].get("htmlLink")
    return None, None



def _process_email(gmail_service, calendar_service, email_id: str) -> dict:
    full = gmail_service.users().messages().get(userId="me", id=email_id).execute()
    email = parse_email_content(full)

    entry = {
        "email_id": email_id,
        "subject": email["subject"],
        "from": email["from"],
        "meeting": None,
        "reason": None,
        "link": None,
        "status": None,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "deleted_at": None,
    }

    if not is_meeting_candidate(email["subject"], email["body"]):
        entry["status"] = "skipped"
        entry["reason"] = "Not meeting related"
        return entry

    extracted = extract_meeting_info(email["body"], email["date"], email["subject"])
    entry["meeting"] = extracted

    if not extracted.get("is_meeting_related"):
        entry["status"] = "skipped"
        entry["reason"] = "Not meeting related"
        return entry

    if extracted.get("confidence_score", 0) < 80 or not extracted.get("date") or not extracted.get("time"):
        add_pending(email_id, email["subject"], extracted)
        entry["status"] = "pending"
        entry["reason"] = "Low confidence or missing date/time"
        return entry

    try:
        event_id, link = create_or_update_event(email_id, extracted)
        entry["status"] = "created"
        entry["link"] = link
        entry["event_id"] = event_id
    except Exception as exc:
        entry["status"] = "error"
        entry["reason"] = str(exc)

    return entry


def _tick() -> None:
    gmail = get_gmail_service()
    calendar = get_calendar_service()

    result = gmail.users().messages().list(userId="me", maxResults=BASELINE_MAX).execute()
    inbox_ids = [m["id"] for m in result.get("messages", [])]

    state = read_state()
    changed = False

    if not state.get("baseline_done"):
        for mid in inbox_ids:
            eid, link = _find_event(calendar, mid)
            state["emails"][mid] = {
                "email_id": mid,
                "subject": "",
                "from": "",
                "meeting": None,
                "reason": None,
                "link": link,
                "event_id": eid,
                "status": "created" if link else "existing",
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "deleted_at": None,
            }
        state["baseline_done"] = True
        changed = True
    else:
        new_ids = [mid for mid in inbox_ids if mid not in state["emails"]][:MAX_NEW_PER_TICK]
        for mid in new_ids:
            state["emails"][mid] = _process_email(gmail, calendar, mid)
            changed = True

    last_cal_scan = state.get("last_calendar_scan")
    if not last_cal_scan:
        last_cal_scan = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    try:
        events_result = calendar.events().list(
            calendarId="primary", 
            updatedMin=last_cal_scan, 
            showDeleted=True, 
            maxResults=2500
        ).execute()
        updated_events = events_result.get("items", [])

        event_id_to_mid = {}
        for mid, entry in list(state["emails"].items()):
            if entry.get("status") in ("created", "approved"):
                eid = entry.get("event_id")
                if not eid:
                    eid, _ = _find_event(calendar, mid)
                    if eid:
                        entry["event_id"] = eid
                        changed = True
                    else:
                        entry["status"] = "deleted"
                        entry["deleted_at"] = _now_iso()
                        entry["updated_at"] = _now_iso()
                        changed = True
                        continue
                if eid:
                    event_id_to_mid[eid] = mid

        for item in updated_events:
            eid = item["id"]
            if eid in event_id_to_mid and item.get("status") == "cancelled":
                mid = event_id_to_mid[eid]
                entry = state["emails"][mid]
                entry["status"] = "deleted"
                entry["deleted_at"] = _now_iso()
                entry["updated_at"] = _now_iso()
                changed = True

        state["last_calendar_scan"] = _now_iso()
        changed = True
    except Exception as exc:
        print(f"[watcher] calendar sync failed: {exc}")

    state["last_scan"] = datetime.now(timezone.utc).isoformat()
    if changed:
        write_state(state)

    _retry_failed_pending(gmail, state, changed)


def _retry_failed_pending(gmail, state: dict, changed_already: bool) -> None:
    now = datetime.now(timezone.utc)
    changed = changed_already

    for mid, entry in list(state["emails"].items()):
        meeting = entry.get("meeting") or {}
        if entry.get("status") != "pending" or meeting.get("meeting_title") != API_ERROR_FALLBACK["meeting_title"]:
            continue

        last_retry = entry.get("retried_at")
        if last_retry:
            try:
                last = datetime.fromisoformat(last_retry)
                if (now - last).total_seconds() < API_ERROR_RETRY_MINUTES * 60:
                    continue
            except ValueError:
                pass

        full_message = gmail.users().messages().get(userId="me", id=mid).execute()
        email = parse_email_content(full_message)

        if not is_meeting_candidate(email["subject"], email["body"]):
            entry["status"] = "skipped"
            entry["reason"] = "Not meeting related"
            entry["meeting"] = None
            pending = [p for p in read_pending() if p["email_id"] != mid]
            write_pending(pending)
            changed = True
            continue

        extracted = extract_meeting_info(email["body"], email["date"], email["subject"])
        entry["retried_at"] = datetime.now(timezone.utc).isoformat()
        entry["meeting"] = extracted
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        changed = True

        pending_entries = [p for p in read_pending()]
        for pending_entry in pending_entries:
            if pending_entry["email_id"] == mid:
                pending_entry["extracted_data"] = extracted
        write_pending(pending_entries)

        if (
            extracted.get("is_meeting_related")
            and extracted.get("confidence_score", 0) >= 80
            and extracted.get("date")
            and extracted.get("time")
        ):
            try:
                event_id, link = create_or_update_event(mid, extracted)
                entry["status"] = "created"
                entry["link"] = link
                entry["event_id"] = event_id
                entry["reason"] = None
                pending = [p for p in read_pending() if p["email_id"] != mid]
                write_pending(pending)
            except Exception as exc:
                entry["reason"] = str(exc)

    if changed:
        state["last_scan"] = datetime.now(timezone.utc).isoformat()
        write_state(state)


def _run() -> None:
    while not _stop_event.is_set():
        try:
            _tick()
        except Exception as exc:
            print(f"[watcher] scan failed: {exc}")
        _stop_event.wait(GMAIL_POLL_SECONDS)


def start_watcher() -> None:
    global _watcher_thread
    if _watcher_thread and _watcher_thread.is_alive():
        return
    _stop_event.clear()
    _watcher_thread = threading.Thread(target=_run, name="gmail-watcher", daemon=True)
    _watcher_thread.start()


def stop_watcher() -> None:
    _stop_event.set()