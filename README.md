# StudyLens - Smart Notes and Study Assistant

A simple Flask web app for students: upload notes (PDF/TXT), search them, get topic summaries, and practise MCQ quizzes.

## Run on Windows
1. Install Python 3.9+ from python.org (tick "Add Python to PATH").
2. Open the StudyLens folder in Command Prompt (or VS Code terminal).
3. Run: `pip install -r requirements.txt`
4. Run: `python app.py`
5. Open http://127.0.0.1:5000 in your browser.

`database.db` is created automatically on first run.

## Features
Login / Register (hashed passwords, CSRF protection, login lockout, per-user notes and scores), Dashboard, My Notes (upload/open/delete), Search Notes, EasyLearn, Quick Quiz (scores saved), My Progress.

Supported note types: PDF, DOCX, PPTX, TXT, MD (not scanned PDFs or images).

## Limitation of EasyLearn
EasyLearn does not use AI. It ranks sentences from your uploaded notes by keyword matches, so the result is only as good as your notes. Scanned PDFs (images) cannot be read.

## Files
- app.py - all routes, database setup, login/register and logic
- templates/ - HTML pages (base.html is the shared layout)
- static/ - CSS and JavaScript
- uploads/ - uploaded files are stored here

## Login notes
- Pages: /login, /register. Every other page requires login; each user only sees their own notes and quiz scores.
- Passwords need 8+ chars with upper, lower, number and special character.
- 5 wrong logins for one email lock that email for 5 minutes (in memory, resets on restart).
- Notes uploaded before this update have no owner and will not show up; re-upload them after logging in.
- For real deployment set a secret: `set SECRET_KEY=some-long-random-text` (Windows) before `python app.py`.
