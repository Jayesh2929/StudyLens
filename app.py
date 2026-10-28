"""StudyLens - Smart Notes and Study Assistant (BCA mini project)."""
import os, re, random, sqlite3, uuid, json, base64, hashlib, functools
from collections import Counter
from datetime import datetime
import fitz  # PyMuPDF, reads PDFs
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory, session

from markupsafe import Markup, escape
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
DB_PATH = os.path.join(BASE, "database.db")
ALLOWED = {"pdf", "txt"}

app = Flask(__name__)
app.secret_key = "studylens-dev-key"            # needed for flash messages
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024   # 10 MB upload limit
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------- Database ----------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    """Create the tables automatically on startup."""
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS notes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,       -- name shown to the student
        stored_name TEXT NOT NULL,    -- unique name on disk
        content TEXT NOT NULL,        -- extracted text
        uploaded_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS quiz_attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        taken_at TEXT NOT NULL);
    """)
    db.commit(); db.close()

# ---------------- Authentication helpers ----------------
def hash_password(password):
    """Hash a password with SHA-256 and a random salt."""
    salt = uuid.uuid4().hex
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return salt + ":" + hashed

def verify_password(stored, password):
    """Verify a password against a stored salt:hash string."""
    parts = stored.split(":", 1)
    if len(parts) != 2:
        return False
    salt, expected = parts
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return hashed == expected

def login_required(view):
    """Decorator to protect routes — redirects to login if not authenticated."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

# ---------------- Helpers ----------------
def extract_text(path, ext):
    """Return plain text from a PDF or TXT file."""
    if ext == "pdf":
        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc).strip()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().strip()

def all_notes():
    return get_db().execute("SELECT * FROM notes ORDER BY id DESC").fetchall()

def split_sentences(text):
    text = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 25]

def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())

STOP = set("the a an and or of to in is are was were be for on with as by it this that at from which can has have".split())

def highlight(snippet, query):
    """Escape HTML, then wrap the search words in <mark>."""
    safe = str(escape(snippet))
    for w in set(words(query)):
        safe = re.sub(f"({re.escape(w)})", r"<mark>\1</mark>", safe, flags=re.I)
    return Markup(safe)

# ---------------- Auth pages ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, go to dashboard
    if "user_id" in session:
        return redirect(url_for("index"))

    mode = "login"   # default tab

    if request.method == "POST":
        action = request.form.get("action", "login")

        if action == "register":
            mode = "register"
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")

            # ---- Server-side validation ----
            errors = []
            if not name or len(name) < 2 or len(name) > 50:
                errors.append("Name must be between 2 and 50 characters.")
            if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$", email):
                errors.append("Please enter a valid email address.")
            if len(password) < 8:
                errors.append("Password must be at least 8 characters.")
            if password != confirm:
                errors.append("Passwords do not match.")

            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("login.html", mode=mode)

            # Check if email already exists
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if existing:
                flash("An account with this email already exists. Please sign in.", "error")
                return render_template("login.html", mode=mode)

            # Create user
            db.execute("INSERT INTO users(name, email, password_hash, created_at) VALUES(?,?,?,?)",
                       (name, email, hash_password(password),
                        datetime.now().strftime("%d %b %Y, %H:%M")))
            db.commit()
            flash("Account created successfully! Please sign in.", "success")
            mode = "login"
            return render_template("login.html", mode=mode)

        else:  # action == "login"
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            # ---- Server-side validation ----
            errors = []
            if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$", email):
                errors.append("Please enter a valid email address.")
            if not password:
                errors.append("Password is required.")

            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("login.html", mode=mode)

            db = get_db()
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not user or not verify_password(user["password_hash"], password):
                flash("Invalid email or password.", "error")
                return render_template("login.html", mode=mode)

            # Login success
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("index"))

    return render_template("login.html", mode=mode)

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))

# ---------------- Pages ----------------
@app.route("/")
@login_required
def index():
    db = get_db()
    notes = db.execute("SELECT COUNT(*) c FROM notes").fetchone()["c"]
    quizzes = db.execute("SELECT COUNT(*) c FROM quiz_attempts").fetchone()["c"]
    recent = db.execute("SELECT * FROM notes ORDER BY id DESC LIMIT 3").fetchall()
    last = db.execute("SELECT * FROM quiz_attempts ORDER BY id DESC LIMIT 1").fetchone()
    return render_template("index.html", notes=notes, quizzes=quizzes, recent=recent, last=last, page="home")

@app.route("/notes")
@login_required
def notes():
    return render_template("notes.html", notes=all_notes(), page="notes")

@app.route("/notes/upload", methods=["POST"])
@login_required
def upload():
    f = request.files.get("file")
    if not f or f.filename == "":
        flash("Please choose a file first.", "error"); return redirect(url_for("notes"))
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED:
        flash("Only PDF and TXT files are allowed.", "error"); return redirect(url_for("notes"))
    stored = uuid.uuid4().hex + "." + ext
    path = os.path.join(UPLOAD_DIR, stored)
    f.save(path)
    try:
        text = extract_text(path, ext)
    except Exception:
        os.remove(path)
        flash("This file could not be read. It may be damaged.", "error"); return redirect(url_for("notes"))
    if not text:
        os.remove(path)
        flash("No text found in this file. Scanned PDFs (images) are not supported.", "error")
        return redirect(url_for("notes"))
    db = get_db()
    db.execute("INSERT INTO notes(filename,stored_name,content,uploaded_at) VALUES(?,?,?,?)",
               (secure_filename(f.filename) or "notes." + ext, stored, text,
                datetime.now().strftime("%d %b %Y, %H:%M")))
    db.commit()
    flash(f"'{f.filename}' uploaded successfully.", "success")
    return redirect(url_for("notes"))

@app.route("/notes/<int:nid>")
@login_required
def open_note(nid):
    note = get_db().execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    if not note:
        flash("That note does not exist.", "error"); return redirect(url_for("notes"))
    return render_template("note_view.html", note=note, page="notes")

@app.route("/notes/<int:nid>/file")
@login_required
def note_file(nid):
    note = get_db().execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    if not note: return redirect(url_for("notes"))
    return send_from_directory(UPLOAD_DIR, note["stored_name"], as_attachment=True,
                               download_name=note["filename"])

@app.route("/notes/<int:nid>/delete", methods=["POST"])
@login_required
def delete_note(nid):
    db = get_db()
    note = db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    if note:
        p = os.path.join(UPLOAD_DIR, note["stored_name"])
        if os.path.exists(p): os.remove(p)
        db.execute("DELETE FROM notes WHERE id=?", (nid,)); db.commit()
        flash(f"'{note['filename']}' deleted.", "success")
    return redirect(url_for("notes"))

@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    selected_ids = request.args.getlist("note_ids", type=int)
    results = []
    if q:
        notes_pool = all_notes()
        if selected_ids:
            notes_pool = [n for n in notes_pool if n["id"] in selected_ids]
        for n in notes_pool:
            text = re.sub(r"\s+", " ", n["content"])
            hits = [m.start() for m in re.finditer(re.escape(q), text, re.I)]
            for pos in hits[:3]:   # at most 3 snippets per file
                s = text[max(0, pos - 100): pos + len(q) + 150]
                results.append({"file": n["filename"], "id": n["id"], "snippet": highlight("..." + s + "...", q)})
    return render_template("search.html", q=q, results=results,
                           all_notes=all_notes(), selected_ids=selected_ids, page="search")

@app.route("/easylearn")
@login_required
def easylearn():
    topic = request.args.get("topic", "").strip()
    selected_ids = request.args.getlist("note_ids", type=int)
    out = None
    if topic:
        t_words = [w for w in words(topic) if w not in STOP] or words(topic)
        matches = []   # (score, sentence, filename)
        notes_pool = all_notes()
        if selected_ids:
            notes_pool = [n for n in notes_pool if n["id"] in selected_ids]
        for n in notes_pool:
            for s in split_sentences(n["content"]):
                # compare the first 6 letters so "normal" also matches "normalization"
                stems = [x[:6] for x in words(s)]
                score = sum(stems.count(w[:6]) for w in t_words)
                if score: matches.append((score, s, n["filename"]))
        matches.sort(key=lambda m: -m[0])
        if matches:
            top = matches[:8]
            freq = Counter(w for _, s, _ in top for w in words(s) if w not in STOP)
            ranked = sorted(top, key=lambda m: -sum(freq[w] for w in words(m[1])) / (len(words(m[1])) ** 0.5))
            explanation = " ".join(m[1] for m in top[:3])
            summary = " ".join(m[1] for m in ranked[:2])
            points = [m[1] for m in ranked[:5]]
            answer = {"intro": f"{topic.title()} is an important topic. " + top[0][1],
                      "body": [m[1] for m in ranked[:4]],
                      "conclusion": f"In conclusion, {topic} is best understood through the points above."}
            out = {"found": True, "explanation": explanation, "summary": summary, "points": points,
                   "answer": answer, "sources": sorted({m[2] for m in top})}
        else:
            out = {"found": False}
    return render_template("easylearn.html", topic=topic, out=out,
                           all_notes=all_notes(), selected_ids=selected_ids, page="easylearn")

# ---------------- Quiz ----------------
QUESTIONS = [
 ("Which language is Flask written in?", ["Java", "Python", "C#", "PHP"], 1),
 ("What does SQL stand for?", ["Structured Query Language", "Simple Question List", "Server Query Logic", "Stored Query Language"], 0),
 ("Which HTML tag creates a hyperlink?", ["<link>", "<a>", "<href>", "<url>"], 1),
 ("Which CSS property changes text colour?", ["font-color", "text-style", "color", "background"], 2),
 ("Which data structure works on FIFO?", ["Stack", "Queue", "Tree", "Graph"], 1),
 ("Which keyword defines a function in Python?", ["func", "define", "function", "def"], 3),
 ("What is the brain of the computer?", ["RAM", "CPU", "Hard disk", "Monitor"], 1),
 ("SQLite is which type of database?", ["Server-based", "File-based", "Cloud-only", "Graph"], 1),
 ("Which symbol starts a comment in Python?", ["//", "#", "--", "/*"], 1),
 ("1 byte equals how many bits?", ["4", "8", "16", "2"], 1),
]

def generate_quiz(text, num_questions=5):
    """Generate fill-in-the-blank MCQ questions from note content."""
    sents = split_sentences(text)
    if not sents:
        return []
    important = [w for w in words(text) if w not in STOP and len(w) > 3]
    freq = Counter(important)
    pool = [w for w, _ in freq.most_common(80)]
    if len(pool) < 4:
        return []
    questions = []
    used = set()
    random.shuffle(sents)
    for sent in sents:
        if len(questions) >= num_questions:
            break
        if len(sent) < 30 or len(sent) > 300:
            continue
        cands = [w for w in set(words(sent))
                 if w in pool and len(w) > 3 and w not in STOP and w not in used]
        if not cands:
            continue
        cands.sort(key=lambda w: -freq[w])
        answer = cands[0]
        blanked = re.sub(r'\b' + re.escape(answer) + r'\b', '________', sent, count=1, flags=re.I)
        if blanked == sent:
            continue
        dists = [w for w in pool if w != answer]
        random.shuffle(dists)
        dists = dists[:3]
        if len(dists) < 3:
            continue
        used.add(answer)
        opts = [answer] + dists
        random.shuffle(opts)
        correct = opts.index(answer)
        questions.append(("Complete: " + blanked, opts, correct))
    return questions

@app.route("/quiz", methods=["GET", "POST"])
@login_required
def quiz():
    if request.method == "POST":
        action = request.form.get("action", "submit")

        if action == "generate":
            note_ids = request.form.getlist("note_ids", type=int)
            pool = all_notes()
            if note_ids:
                pool = [n for n in pool if n["id"] in note_ids]
            if not pool:
                flash("Please select at least one note.", "error")
                return redirect(url_for("quiz"))
            combined = " ".join(n["content"] for n in pool)
            gen = generate_quiz(combined)
            if len(gen) < 2:
                flash("Not enough content to generate a quiz. Try selecting notes with more text.", "error")
                return redirect(url_for("quiz"))
            quiz_data = base64.b64encode(json.dumps(gen).encode()).decode()
            display = [(i, q, opts) for i, (q, opts, _) in enumerate(gen)]
            return render_template("quiz.html", questions=display, quiz_data=quiz_data,
                                   quiz_type="generated", page="quiz")

        if action == "general":
            picked = random.sample(range(len(QUESTIONS)), 5)
            return render_template("quiz.html",
                                   questions=[(i, *QUESTIONS[i][:2]) for i in picked],
                                   quiz_type="general", page="quiz")

        # action == "submit" — grade the quiz
        quiz_type = request.form.get("quiz_type", "general")

        if quiz_type == "generated":
            raw = request.form.get("quiz_data", "")
            try:
                q_list = json.loads(base64.b64decode(raw))
            except Exception:
                flash("Quiz data was corrupted. Please try again.", "error")
                return redirect(url_for("quiz"))
            review, score = [], 0
            for i, (q_text, opts, correct) in enumerate(q_list):
                chosen = request.form.get(f"q{i}")
                chosen = int(chosen) if chosen and chosen.isdigit() else None
                ok = chosen == correct
                score += ok
                review.append({"q": q_text, "opts": opts, "correct": correct, "chosen": chosen, "ok": ok})
            db = get_db()
            db.execute("INSERT INTO quiz_attempts(score,total,taken_at) VALUES(?,?,?)",
                       (score, len(q_list), datetime.now().strftime("%d %b %Y, %H:%M")))
            db.commit()
            flash(f"Quiz submitted. You scored {score}/{len(q_list)}.", "success")
            return render_template("quiz.html", review=review, score=score,
                                   total=len(q_list), page="quiz")
        else:
            # General quiz grading (original logic)
            ids = [int(i) for i in request.form.getlist("qid") if i.isdigit() and int(i) < len(QUESTIONS)]
            if not ids:
                flash("Quiz expired. Please start again.", "error"); return redirect(url_for("quiz"))
            review, score = [], 0
            for i in ids:
                q, opts, correct = QUESTIONS[i]
                chosen = request.form.get(f"q{i}")
                chosen = int(chosen) if chosen and chosen.isdigit() else None
                ok = chosen == correct
                score += ok
                review.append({"q": q, "opts": opts, "correct": correct, "chosen": chosen, "ok": ok})
            db = get_db()
            db.execute("INSERT INTO quiz_attempts(score,total,taken_at) VALUES(?,?,?)",
                       (score, len(ids), datetime.now().strftime("%d %b %Y, %H:%M")))
            db.commit()
            flash(f"Quiz submitted. You scored {score}/{len(ids)}.", "success")
            return render_template("quiz.html", review=review, score=score, total=len(ids), page="quiz")

    # GET — show setup page
    return render_template("quiz.html", all_notes=all_notes(), setup=True, page="quiz")

@app.route("/progress")
@login_required
def progress():
    db = get_db()
    notes = db.execute("SELECT COUNT(*) c FROM notes").fetchone()["c"]
    attempts = db.execute("SELECT * FROM quiz_attempts ORDER BY id DESC LIMIT 8").fetchall()
    count = db.execute("SELECT COUNT(*) c FROM quiz_attempts").fetchone()["c"]
    best = db.execute("SELECT MAX(ROUND(score*100.0/total)) b, ROUND(AVG(score*100.0/total)) a FROM quiz_attempts").fetchone()
    return render_template("progress.html", notes=notes, count=count, attempts=attempts,
                           best=best["b"], avg=best["a"], page="progress")

@app.errorhandler(413)
def too_big(e):
    flash("File is too large. Maximum size is 10 MB.", "error")
    return redirect(url_for("notes"))

init_db()
if __name__ == "__main__":
    app.run(debug=True)
