# Gmail to Google Calendar Automation

An intelligent, background-running automation pipeline that monitors your Gmail inbox in real-time, detects meeting-related emails, and automatically schedules them into your Google Calendar. It uses Google's Gemini AI for robust natural language extraction to parse unstructured email bodies and precisely extract meeting details like dates, times, and Google Meet links.

## Features

- **Live Inbox Monitoring**: A background daemon continuously polls the Gmail API for new emails.
- **Smart Pre-filtering**: Before querying the AI, emails are passed through a highly optimized local regex/keyword filter, guaranteeing 0 API quota waste on spam, newsletters, or irrelevant emails.
- **AI Meeting Extraction**: Uses Google's Gemini Flash model to seamlessly understand complex email threads, relative dates (e.g. "let's meet next Tuesday"), and timezone conversions.
- **Automatic Calendar Sync**: Instantly creates Google Calendar events using the extracted details. 
- **Two-way Sync (Deletions)**: The system monitors Google Calendar events in the background; if a user manually deletes the event from their calendar, the script detects this and updates its internal state.
- **Local Fallbacks & Rate Limiting**: If Gemini API limits are hit, the system temporarily backs off and relies on a local regex-based parsing fallback mechanism to ensure uninterrupted service.
- **Web UI Dashboard**: Built with FastAPI, providing a beautiful local dashboard to review processed emails, dismiss false positives, or manually approve low-confidence AI extractions.

## Tech Stack

- **Backend Framework:** FastAPI, Uvicorn
- **AI/LLM:** `google-genai` (Gemini Flash Model)
- **Google APIs:** Gmail API, Google Calendar API, Google Auth
- **Validation:** Pydantic

## Installation & Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/Charanbtech/Gmail_Automation.git
   cd Gmail_Automation
   ```

2. **Set up a Virtual Environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables**
   Create a `.env` file in the root directory and add your Gemini API Key:
   ```env
   GEMINI_API_KEY=your_api_key_here
   GEMINI_MODEL=gemini-3.6-flash
   ```

5. **Google OAuth Credentials**
   - Head to the [Google Cloud Console](https://console.cloud.google.com/).
   - Enable the **Gmail API** and **Google Calendar API**.
   - Create an OAuth 2.0 Client ID (Desktop App).
   - Download the JSON credentials file and rename it to `credentials.json`, placing it in the root of the project.

## Running the Application

Run the FastAPI application using Uvicorn:

```bash
uvicorn main:app --reload
```

1. Navigate to `http://localhost:8000/auth` to complete the initial Google OAuth login (this generates a local `token.json`).
2. Visit `http://localhost:8000/ui/` to view the live dashboard and see emails being processed in real-time.

## Architecture & Logic Flow

1. **Daemon Polling**: `watcher.py` runs a background thread that polls Gmail every 8 seconds.
2. **Pre-Filter Check**: Emails are checked against `is_meeting_candidate` to weed out non-meeting emails instantly.
3. **LLM Extraction**: Valid candidates are sent to Gemini to extract a structured JSON object (`MeetingDetails`).
4. **Calendar Scheduling**: If confidence is high (>80%), a Calendar Event is generated immediately. If not, it enters a "Pending Review" queue in the UI.
5. **State Management**: All email tracking is handled in `live_state.json` allowing the script to safely resume after restarts.
