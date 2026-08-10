# SyncFlow: Gmail to Google Calendar Automation 📅

Welcome to **SyncFlow**! This is a smart automation tool that reads your Gmail inbox and automatically schedules meeting invitations right onto your Google Calendar. 

It uses Artificial Intelligence (AI) to read the emails and figure out the exact date, time, and meeting link. If it gets confused by a messy email, it puts it in a "Manual Review" queue so you can fix it yourself!

---

## 🛠️ Step 1: Getting Started

You only need to install two things to run this on your computer:
1. **Python** (Downloads the backend).
2. **Node.js** (Downloads the frontend dashboard).

Open your terminal or command prompt inside this folder and run these exact commands:

### Install the Backend (Python)
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Install the Frontend (Dashboard)
```bash
cd frontend
npm install
cd ..
```

---

## 🔑 Step 2: Setup Your Secret Keys

This app needs to connect to your Google Account and the Gemini AI. We keep these secrets safe inside a `.env` file.

1. Find the file named `.env.example` in this folder.
2. Rename it to just `.env`.
3. Open the `.env` file in a text editor (like Notepad). You will see this:

```text
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json
GEMINI_API_KEY=your_gemini_api_key
LOCAL_TIMEZONE=Asia/Kolkata
```

### How to get your Gemini API Key:
1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Click **Create API Key**.
3. Copy the key and paste it into your `.env` file next to `GEMINI_API_KEY=`.

### How to get your Google Credentials:
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project and enable the **Gmail API** and **Google Calendar API**.
3. Go to "Credentials" and create an **OAuth 2.0 Client ID** (choose "Desktop App").
4. Download the JSON file, rename it to exactly `credentials.json`, and put it inside this folder!

---

## 🚀 Step 3: Run the App!

You will need to open **two** terminal windows (one for the backend, one for the dashboard).

### Terminal 1: Start the Backend Server
Make sure you are in the main folder and run:
```bash
.venv\Scripts\activate
python -m uvicorn main:app --reload
```
*Note: The very first time you run this, a web page will pop up asking you to log into your Google Account. Just click "Allow" so the app can read your emails and calendar!*

### Terminal 2: Start the Beautiful Dashboard
Open a new terminal, go into the frontend folder, and run:
```bash
cd frontend
npm run dev
```

### 🎉 You're Done!
Open your web browser and go to **`http://localhost:5173`**. You will see your live dashboard tracking your emails and adding meetings to your calendar automatically!

---

## ❓ FAQ (Frequently Asked Questions)

**What if the AI misses an email?**
If the AI isn't 100% sure about the time or date, it won't guess. Instead, it places the email into the **Manual Review Queue** on your dashboard. You can type in the correct time yourself and click "Approve".

**How often does it check my email?**
It securely checks your inbox every 8 seconds while the backend terminal is running. 

**Is my data safe?**
Yes! This script runs 100% locally on your own computer. Your emails are never sent anywhere except directly to Google's official Gemini AI for quick reading. 
