import base64
import html
import os
import re

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def get_gmail_service():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    return build("gmail", "v1", credentials=creds)


def _get_header(headers, name):
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _decode_body(data):
    if not data:
        return ""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def _html_to_text(raw_html):
    text = re.sub(r"<style.*?</style>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_plain_text(parts, depth=0):
    if depth > 10:
        return ""
    html = ""
    for part in parts:
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain":
            return _decode_body(part.get("body", {}).get("data", ""))
        if mime_type == "text/html" and not html:
            html = _decode_body(part.get("body", {}).get("data", ""))
        nested = part.get("parts")
        if nested:
            text = _extract_plain_text(nested, depth + 1)
            if text:
                return text
    return _html_to_text(html) if html else ""


def parse_email_content(message):
    """Convert a raw Gmail API message dict into a clean email dict."""
    headers = message.get("payload", {}).get("headers", [])
    subject = _get_header(headers, "Subject")
    from_addr = _get_header(headers, "From")
    date = _get_header(headers, "Date")

    payload = message.get("payload", {})
    mime_type = payload.get("mimeType", "")
    body = ""
    if mime_type == "text/plain":
        body = _decode_body(payload.get("body", {}).get("data", ""))
    else:
        parts = payload.get("parts", [])
        body = _extract_plain_text(parts)

    return {
        "id": message.get("id"),
        "subject": subject,
        "from": from_addr,
        "date": date,
        "body": body,
    }


def fetch_recent_emails(max_results=5):
    service = get_gmail_service()
    result = service.users().messages().list(userId="me", maxResults=max_results).execute()
    messages = result.get("messages", [])

    emails = []
    for msg in messages:
        full = service.users().messages().get(userId="me", id=msg["id"]).execute()
        emails.append(parse_email_content(full))
    return emails