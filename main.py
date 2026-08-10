import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ai_extractor import extract_meeting_info, is_meeting_candidate
from auth import get_google_credentials
from calendar_service import create_or_update_event
from gmail_service import fetch_recent_emails, get_gmail_service, parse_email_content
from watcher import (
    read_pending,
    read_state,
    start_watcher,
    stop_watcher,
    update_email_state,
    write_pending,
)

TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")


@asynccontextmanager
async def lifespan(_: FastAPI):
    start_watcher()
    yield
    stop_watcher()


app = FastAPI(title="Gmail to Google Calendar Automation", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health_check() -> dict:
    return {"status": "ok", "service": "gmail-calendar-automation"}


@app.get("/auth")
def authenticate() -> dict:
    try:
        get_google_credentials()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Authentication failed: {exc}") from exc

    if not os.path.exists(TOKEN_FILE):
        raise HTTPException(status_code=500, detail="Authentication failed: token.json missing")

    return {"status": "success", "authenticated": True, "token_file": TOKEN_FILE}


@app.get("/live-status")
def live_status() -> dict:
    state = read_state()
    emails = [
        entry
        for entry in state.get("emails", {}).values()
        if entry.get("status") not in ("existing",)
    ]
    emails.sort(key=lambda e: e.get("processed_at") or "", reverse=True)
    return {
        "watching": True,
        "last_scan": state.get("last_scan"),
        "pending_count": len(read_pending()),
        "emails": emails,
    }


@app.get("/emails")
def list_recent_emails(max_results: int = 5) -> list[dict]:
    if not os.path.exists(TOKEN_FILE):
        raise HTTPException(status_code=401, detail="Not authenticated. Visit /auth first.")

    try:
        return fetch_recent_emails(max_results=max_results)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch emails: {exc}") from exc


@app.get("/extract-meetings")
def extract_meetings() -> list[dict]:
    if not os.path.exists(TOKEN_FILE):
        raise HTTPException(status_code=401, detail="Not authenticated. Visit /auth first.")

    try:
        emails = fetch_recent_emails(max_results=3)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch emails: {exc}") from exc

    results = []
    for email in emails:
        extracted = extract_meeting_info(email["body"], email["date"], email["subject"])
        results.append(
            {
                "id": email["id"],
                "subject": email["subject"],
                "extracted_data": extracted,
            }
        )
    return results


@app.get("/pending-meetings")
def pending_meetings() -> list[dict]:
    return read_pending()


@app.delete("/pending-meetings/{email_id}")
def remove_pending_meeting(email_id: str) -> dict:
    entries = read_pending()
    remaining = [e for e in entries if e["email_id"] != email_id]
    if len(remaining) == len(entries):
        raise HTTPException(status_code=404, detail=f"No pending meeting for email_id: {email_id}")
    write_pending(remaining)
    update_email_state(email_id, status="dismissed", reason="Dismissed by user")
    return {"email_id": email_id, "action": "dismissed"}


@app.post("/pending-meetings/{email_id}/retry")
def retry_pending_meeting(email_id: str) -> dict:
    entries = read_pending()
    entry = next((e for e in entries if e["email_id"] == email_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No pending meeting for email_id: {email_id}")

    try:
        full_message = get_gmail_service().users().messages().get(userId="me", id=email_id).execute()
        email = parse_email_content(full_message)
        if not is_meeting_candidate(email["subject"], email["body"]):
            remaining = [e for e in entries if e["email_id"] != email_id]
            write_pending(remaining)
            update_email_state(email_id, status="skipped", meeting=None, reason="Not meeting related")
            return {"email_id": email_id, "action": "skipped", "extracted_data": None}
        extracted = extract_meeting_info(email["body"], email["date"], email["subject"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to re-extract email: {exc}") from exc

    if (
        extracted.get("is_meeting_related")
        and extracted.get("confidence_score", 0) >= 80
        and extracted.get("date")
        and extracted.get("time")
    ):
        try:
            event_id, event_link = create_or_update_event(email_id, extracted)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to create calendar event: {exc}") from exc

        write_pending([e for e in entries if e["email_id"] != email_id])
        update_email_state(email_id, status="created", link=event_link, event_id=event_id, meeting=extracted, reason=None)
        return {"email_id": email_id, "action": "created", "link": event_link, "extracted_data": extracted}

    remaining = [e for e in entries if e["email_id"] != email_id]
    entry["extracted_data"] = extracted
    remaining.append(entry)
    write_pending(remaining)
    update_email_state(email_id, status="pending", meeting=extracted, reason="Low confidence or missing date/time")
    return {"email_id": email_id, "action": "still_pending", "extracted_data": extracted}


@app.post("/approve-meeting/{email_id}")
def approve_meeting(email_id: str, payload: dict) -> dict:
    entries = read_pending()
    entry = next((e for e in entries if e["email_id"] == email_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No pending meeting for email_id: {email_id}")

    corrected = {
        "is_meeting_related": True,
        "meeting_title": payload.get("meeting_title") or entry["extracted_data"].get("meeting_title") or "Meeting",
        "date": payload.get("date") or entry["extracted_data"].get("date"),
        "time": payload.get("time") or entry["extracted_data"].get("time"),
        "time_zone": payload.get("time_zone") or entry["extracted_data"].get("time_zone"),
        "meet_link": payload.get("meet_link") or entry["extracted_data"].get("meet_link"),
        "description": entry["extracted_data"].get("description"),
        "confidence_score": 100,
    }

    if not corrected["date"] or not corrected["time"]:
        raise HTTPException(status_code=422, detail="Date and time are required to approve.")

    try:
        event_id, event_link = create_or_update_event(email_id, corrected)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create calendar event: {exc}") from exc

    write_pending([e for e in entries if e["email_id"] != email_id])
    update_email_state(email_id, status="approved", link=event_link, event_id=event_id, reason=None, deleted_at=None)

    return {
        "email_id": email_id,
        "action": "approved",
        "link": event_link,
        "event": corrected,
    }