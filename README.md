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
Dashboard, My Notes (upload/open/delete), Search Notes, EasyLearn, Quick Quiz (scores saved), My Progress.

## Limitation of EasyLearn
EasyLearn does not use AI. It ranks sentences from your uploaded notes by keyword matches, so the result is only as good as your notes. Scanned PDFs (images) cannot be read.

## Files
- app.py - all routes, database setup and logic
- templates/ - HTML pages (base.html is the shared layout)
- static/ - CSS and JavaScript
- uploads/ - uploaded files are stored here
