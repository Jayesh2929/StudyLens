"""StudyLens - Smart Notes and Study Assistant (BCA mini project)."""
import os, re, random, sqlite3, uuid
from collections import Counter
from datetime import datetime, timedelta
import secrets, time
from functools import wraps
from urllib.parse import urlparse
from werkzeug.security import generate_password_hash, check_password_hash
from textwrap import shorten
import fitz  # PyMuPDF, reads PDFs
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory, session
from markupsafe import Markup, escape
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
DB_PATH = os.path.join(BASE, "database.db")
ALLOWED = {"pdf", "txt", "md", "docx", "pptx"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "studylens-dev-key")   # set SECRET_KEY env var in production
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=timedelta(days=14))
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
    """Create the two tables automatically on startup."""
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
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
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL);
    """)
    # add user_id to older databases (existing rows stay with user_id NULL = unowned)
    for table in ("notes", "quiz_attempts"):
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
        if "user_id" not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")
    db.commit(); db.close()

# ---------------- Helpers ----------------
BULLETS = "[•▪●◦‣⁃∙\uf0b7\uf0a7]"

def clean_text(text):
    """Tidy raw extracted text: bullets and wrapped lines become proper lines/paragraphs."""
    text = text.replace("\r", "\n").replace("\u00a0", " ")
    text = re.sub(BULLETS + r"\s*", "\n", text)        # every bullet starts a new line
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)        # re-join words hyphenated at a line end
    out = []
    for line in (re.sub(r"[ \t]+", " ", l).strip() for l in text.split("\n")):
        if not line:
            out.append(""); continue
        if re.fullmatch(r"\d{1,3}", line):              # lone page number
            continue
        j = len(out) - 1
        while j >= 0 and out[j] == "": j -= 1           # last non-empty line
        if j >= 0 and len(out[j]) >= 50 and out[j][-1] not in ".!?:;" and line[0].islower():
            out[j] += " " + line                        # wrapped line of the same paragraph
            del out[j + 1:]
        else:
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()

def extract_text(path, ext):
    """Return clean text from PDF, DOCX, PPTX, TXT or MD files."""
    if ext == "pdf":
        pages = []
        with fitz.open(path) as doc:
            for page in doc:
                lines = []
                for b in page.get_text("blocks", sort=True):   # blocks come in reading order
                    if b[6] == 0:                               # 0 = text block
                        lines += b[4].split("\n") + [""]
                pages.append(lines)
        if len(pages) >= 4:   # remove headers/footers that repeat on most pages
            seen = Counter(l.strip() for p in pages for l in set(p) if l.strip())
            pages = [[l for l in p if not (len(l.strip()) < 80 and seen[l.strip()] > 0.6 * len(pages))] for p in pages]
        text = "\n\n".join("\n".join(p) for p in pages)
    elif ext == "docx":
        import docx
        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            parts += [" | ".join(c.text.strip() for c in row.cells) for row in t.rows]
        text = "\n".join(parts)
    elif ext == "pptx":
        from pptx import Presentation
        parts = []
        for slide in Presentation(path).slides:
            for sh in slide.shapes:
                if sh.has_text_frame:
                    parts.append(sh.text_frame.text)
                if getattr(sh, "has_table", False) and sh.has_table:
                    parts += [" | ".join(c.text.strip() for c in row.cells) for row in sh.table.rows]
            parts.append("")
        text = "\n".join(parts)
    else:   # txt / md
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        if ext == "md":
            text = re.sub(r"[#*_`>]+", "", text)
    return clean_text(text)

def all_notes():
    return get_db().execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall()

def selection(key):
    """Return (all notes, set of picked ids, picked notes).
    First visit (no `key` in the URL) = every note is ticked."""
    notes = all_notes()
    ids = {int(i) for i in request.args.getlist("note") if i.isdigit()}
    # `picked=1` is sent by the picker form, so "nothing ticked" is different from "no choice made"
    picked = ids if (ids or "picked" in request.args) else {n["id"] for n in notes}
    return notes, picked, [n for n in notes if n["id"] in picked]

def split_sentences(text):
    """Split cleaned notes into readable sentences (one per line/sentence, sensible length)."""
    units = []
    for para in clean_text(text).split("\n"):
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", para):
            sent = sent.strip()
            if 30 <= len(sent) <= 320 and len(sent.split()) >= 5:
                units.append(sent)
    return units

def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())

STOP = set("the a an and or of to in is are was were be for on with as by it this that at from which can has have".split())

def highlight(snippet, query, word_start=False):
    """Escape HTML, then wrap the search words in <mark>."""
    safe = str(escape(snippet))
    for w in set(words(query)):
        if len(w) < 3: continue
        safe = re.sub(("\\b" if word_start else "") + f"({re.escape(w)})", r"<mark>\1</mark>", safe, flags=re.I)
    return Markup(safe)

# ---------------- Authentication ----------------
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
PUBLIC_ENDPOINTS = {"login", "register", "static"}
MAX_ATTEMPTS, LOCK_SECONDS = 5, 300
FAILED = {}   # (ip, email) -> [count, first_failure_time]   (in memory, resets on restart)

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]

app.jinja_env.globals["csrf_token"] = csrf_token

def uid():
    return session.get("uid")

@app.before_request
def protect():
    # CSRF: every POST must carry the token from the session
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            flash("Your session expired. Please try again.", "error")
            return redirect(request.referrer or url_for("login"))
    # Login wall: everything except login/register/static needs a signed-in user
    if request.endpoint not in PUBLIC_ENDPOINTS and not uid():
        if request.endpoint:
            flash("Please log in to continue.", "error")
        return redirect(url_for("login", next=request.full_path.rstrip("?")) if request.method == "GET" else url_for("login"))

@app.after_request
def no_cache_private(resp):
    if uid():
        resp.headers["Cache-Control"] = "no-store"   # back button won't show pages after logout
    return resp

def safe_next(target):
    """Only allow redirects to paths inside this site (blocks open-redirect attacks)."""
    if not target: return url_for("index")
    p = urlparse(target)
    if p.scheme or p.netloc or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return url_for("index")
    return target

def validate_password(pw, email="", name=""):
    errs = []
    if len(pw) < 8: errs.append("at least 8 characters")
    if len(pw) > 72: errs.append("no more than 72 characters")
    if not re.search(r"[a-z]", pw): errs.append("a lowercase letter")
    if not re.search(r"[A-Z]", pw): errs.append("an uppercase letter")
    if not re.search(r"\d", pw): errs.append("a number")
    if not re.search(r"[^A-Za-z0-9]", pw): errs.append("a special character")
    if re.search(r"\s", pw): errs.append("no spaces")
    if pw.lower() in {"password1!", "password@123", "qwerty123!", "welcome@123", "admin@123"}:
        errs.append("a less common password")
    if email and pw.lower() == email.split("@")[0].lower(): errs.append("a password different from your email")
    return errs

def start_session(user, remember):
    session.clear()
    session["uid"] = user["id"]
    session["uname"] = user["name"]
    session["_csrf"] = secrets.token_hex(16)
    session.permanent = bool(remember)

@app.route("/login", methods=["GET", "POST"])
def login():
    if uid(): return redirect(url_for("index"))
    nxt = request.args.get("next", "")
    errors, email = {}, ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        nxt = request.form.get("next", "")
        key = (request.remote_addr, email)
        rec = FAILED.get(key)
        if rec and time.time() - rec[1] > LOCK_SECONDS:
            FAILED.pop(key, None); rec = None
        if not email: errors["email"] = "Please enter your email."
        elif len(email) > 254 or not EMAIL_RE.match(email): errors["email"] = "Enter a valid email address."
        if not pw: errors["password"] = "Please enter your password."
        elif len(pw) > 128: errors["password"] = "Password is too long."
        if rec and rec[0] >= MAX_ATTEMPTS:
            wait = int(LOCK_SECONDS - (time.time() - rec[1])) // 60 + 1
            errors["form"] = f"Too many failed attempts. Try again in about {wait} minute(s)."
        elif not errors:
            user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            # same message for unknown email and wrong password, so emails can't be guessed
            if user and check_password_hash(user["password_hash"], pw):
                FAILED.pop(key, None)
                start_session(user, request.form.get("remember"))
                flash(f"Welcome back, {user['name'].split()[0]}!", "success")
                return redirect(safe_next(nxt))
            FAILED[key] = [(rec[0] + 1) if rec else 1, rec[1] if rec else time.time()]
            left = MAX_ATTEMPTS - FAILED[key][0]
            errors["form"] = "Incorrect email or password." + (f" {left} attempt(s) left." if 0 < left <= 2 else "")
        if errors: return render_template("login.html", errors=errors, email=email, next=nxt), 400 if "form" not in errors else 401
    return render_template("login.html", errors=errors, email=email, next=nxt)

@app.route("/register", methods=["GET", "POST"])
def register():
    if uid(): return redirect(url_for("index"))
    errors, form = {}, {"name": "", "email": ""}
    if request.method == "POST":
        name = re.sub(r"\s+", " ", request.form.get("name", "")).strip()
        email = request.form.get("email", "").strip().lower()
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
        form = {"name": name, "email": email}
        if len(name) < 2: errors["name"] = "Name must be at least 2 characters."
        elif len(name) > 60: errors["name"] = "Name must be 60 characters or fewer."
        elif not re.fullmatch(r"[A-Za-z][A-Za-z .'\-]*", name): errors["name"] = "Name can only contain letters, spaces, . ' and -."
        if not email: errors["email"] = "Please enter your email."
        elif len(email) > 254 or not EMAIL_RE.match(email): errors["email"] = "Enter a valid email address."
        pe = validate_password(pw, email, name)
        if pe: errors["password"] = "Password needs " + ", ".join(pe) + "."
        if not errors.get("password") and pw != pw2: errors["confirm"] = "Passwords do not match."
        elif not pw2 and "confirm" not in errors: errors["confirm"] = "Please confirm your password."
        if not errors:
            db = get_db()
            try:
                db.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                           (name, email, generate_password_hash(pw), datetime.now().strftime("%d %b %Y, %H:%M")))
                db.commit()
            except sqlite3.IntegrityError:
                errors["email"] = "An account with this email already exists. Try logging in."
            else:
                user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
                start_session(user, False)
                flash(f"Account created. Welcome to StudyLens, {name.split()[0]}!", "success")
                return redirect(url_for("index"))
        return render_template("register.html", errors=errors, form=form), 400
    return render_template("register.html", errors=errors, form=form)

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))

# ---------------- Pages ----------------
@app.route("/")
def index():
    db = get_db()
    notes = db.execute("SELECT COUNT(*) c FROM notes WHERE user_id=?", (uid(),)).fetchone()["c"]
    quizzes = db.execute("SELECT COUNT(*) c FROM quiz_attempts WHERE user_id=?", (uid(),)).fetchone()["c"]
    recent = db.execute("SELECT * FROM notes WHERE user_id=? ORDER BY id DESC LIMIT 3", (uid(),)).fetchall()
    last = db.execute("SELECT * FROM quiz_attempts WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid(),)).fetchone()
    return render_template("index.html", notes=notes, quizzes=quizzes, recent=recent, last=last, page="home")

@app.route("/notes")
def notes():
    return render_template("notes.html", notes=all_notes(), page="notes")

@app.route("/notes/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f or f.filename == "":
        flash("Please choose a file first.", "error"); return redirect(url_for("notes"))
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED:
        flash("Allowed file types: PDF, DOCX, PPTX, TXT and MD.", "error"); return redirect(url_for("notes"))
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
    db.execute("INSERT INTO notes(filename,stored_name,content,uploaded_at,user_id) VALUES(?,?,?,?,?)",
               (secure_filename(f.filename) or "notes." + ext, stored, text,
                datetime.now().strftime("%d %b %Y, %H:%M"), uid()))
    db.commit()
    flash(f"'{f.filename}' uploaded successfully.", "success")
    return redirect(url_for("notes"))

@app.route("/notes/<int:nid>")
def open_note(nid):
    note = get_db().execute("SELECT * FROM notes WHERE id=? AND user_id=?", (nid, uid())).fetchone()
    if not note:
        flash("That note does not exist.", "error"); return redirect(url_for("notes"))
    return render_template("note_view.html", note=note, page="notes")

@app.route("/notes/<int:nid>/file")
def note_file(nid):
    note = get_db().execute("SELECT * FROM notes WHERE id=? AND user_id=?", (nid, uid())).fetchone()
    if not note: return redirect(url_for("notes"))
    return send_from_directory(UPLOAD_DIR, note["stored_name"], as_attachment=True,
                               download_name=note["filename"])

@app.route("/notes/<int:nid>/delete", methods=["POST"])
def delete_note(nid):
    db = get_db()
    note = db.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (nid, uid())).fetchone()
    if note:
        p = os.path.join(UPLOAD_DIR, note["stored_name"])
        if os.path.exists(p): os.remove(p)
        db.execute("DELETE FROM notes WHERE id=?", (nid,)); db.commit()
        flash(f"'{note['filename']}' deleted.", "success")
    return redirect(url_for("notes"))

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    notes, picked, chosen = selection("q")
    results = []
    if q:
        for n in chosen:
            text = re.sub(r"\s+", " ", n["content"])
            hits = [m.start() for m in re.finditer(re.escape(q), text, re.I)]
            for pos in hits[:3]:   # at most 3 snippets per file
                s = text[max(0, pos - 100): pos + len(q) + 150]
                results.append({"file": n["filename"], "id": n["id"], "snippet": highlight("..." + s + "...", q)})
    return render_template("search.html", q=q, results=results, all_notes=notes, picked=picked,
                           no_selection=bool(q and notes and not chosen), page="search")

@app.route("/easylearn")
def easylearn():
    topic = request.args.get("topic", "").strip()
    notes, picked, chosen = selection("topic")
    out = None
    if topic and chosen:
        t_words = [w for w in words(topic) if w not in STOP] or words(topic)
        cands, seen, order = [], set(), 0     # candidate = (score, position, sentence, file)
        for n in chosen:
            for sent in split_sentences(n["content"]):
                order += 1
                stems = [x[:6] for x in words(sent)]   # first 6 letters: "normal" matches "normalization"
                score = sum(stems.count(w[:6]) for w in t_words)
                if not score or sent[:60].lower() in seen: continue
                seen.add(sent[:60].lower())
                if topic.lower() in sent.lower(): score += 3     # exact phrase bonus
                if sent[-1] in ".!?": score += 1                  # real sentences beat fragments
                cands.append((score, order, sent, n["filename"]))
        if cands:
            best = sorted(cands, key=lambda c: -c[0])
            h = lambda t: highlight(t, topic, word_start=True)
            short = lambda t: shorten(t, 230, placeholder="...")
            in_order = lambda items: " ".join(c[2] for c in sorted(items, key=lambda c: c[1]))
            out = {"found": True, "count": len(cands),
                   "explanation": h(in_order(best[:3])),
                   "summary": h(shorten(in_order(best[:2]), 300, placeholder="...")),
                   "points": [h(short(c[2])) for c in best[:6]],
                   "answer": {"intro": h(best[0][2]), "body": [h(short(c[2])) for c in best[1:5]],
                              "conclusion": f"Thus, {topic} is an important concept and is best remembered through the points above."},
                   "sources": sorted({c[3] for c in cands})}
        else:
            out = {"found": False}
    return render_template("easylearn.html", topic=topic, out=out, all_notes=notes, picked=picked,
                           no_selection=bool(topic and notes and not chosen), page="easylearn")

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

def make_note_quiz(chosen, n=5):
    """Fill-in-the-blank MCQs from the selected notes (no AI needed):
    hide a key term in a sentence; other key terms from the same note become the wrong options."""
    keyterms = lambda t: Counter(w for w in words(t) if len(w) >= 5 and w.isalpha() and w not in STOP)
    freqs = [keyterms(x["content"]) for x in chosen]       # key terms per note
    freq = sum(freqs, Counter())
    global_pool = [w for w, _ in freq.most_common(80)]
    tagged = [(sent, i) for i, x in enumerate(chosen) for sent in split_sentences(x["content"])]
    good = [t for t in tagged if 45 <= len(t[0]) <= 240 and t[0][-1] in ".!?" and len(t[0].split()) >= 8]
    rest = [t for t in tagged if t not in good and len(t[0]) <= 240]
    random.shuffle(good); random.shuffle(rest)
    qs, used = [], set()
    for sent, i in good + rest:              # full sentences first, fragments only if needed
        cands = sorted({w for w in words(sent) if w in freq and w not in used}, key=lambda w: -freq[w])
        if not cands: continue
        ans = cands[0]
        local = [w for w, _ in freqs[i].most_common(40) if w[:5] != ans[:5]]
        source = local if len(local) >= 6 else [w for w in global_pool if w[:5] != ans[:5]]
        wrong = sorted(source, key=lambda w: abs(len(w) - len(ans)))[:10]
        m = re.search(rf"\b{re.escape(ans)}\b", sent, re.I)
        if len(wrong) < 3 or not m: continue
        cap = m.group(0)[0].isupper()
        opts = random.sample(wrong, 3) + [ans]
        if cap: opts = [o.capitalize() for o in opts]
        random.shuffle(opts)
        qs.append({"q": sent[:m.start()] + "_____" + sent[m.end():], "opts": opts,
                   "correct": opts.index(ans.capitalize() if cap else ans), "f": 1})
        used.add(ans)
        if len(qs) == n: break
    return qs if len(qs) >= 3 else []

@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if request.method == "POST":
        qs = session.pop("quiz", None)   # the quiz we generated for this student
        if not qs:
            flash("Quiz expired. Please start again.", "error"); return redirect(url_for("quiz"))
        review, score = [], 0
        for i, q in enumerate(qs):
            chosen = request.form.get(f"q{i}")
            chosen = int(chosen) if chosen and chosen.isdigit() else None
            ok = chosen == q["correct"]
            score += ok
            review.append({"fill": q.get("f"), "q": q["q"], "opts": q["opts"], "correct": q["correct"], "chosen": chosen, "ok": ok})
        db = get_db()
        db.execute("INSERT INTO quiz_attempts(score,total,taken_at,user_id) VALUES(?,?,?,?)",
                   (score, len(qs), datetime.now().strftime("%d %b %Y, %H:%M"), uid()))
        db.commit()
        flash(f"Quiz submitted. You scored {score}/{len(qs)}.", "success")
        return render_template("quiz.html", review=review, score=score, total=len(qs), page="quiz")

    notes, picked, chosen = selection("source")
    source = request.args.get("source")
    if source not in ("notes", "general"):       # step 1: let the student choose
        return render_template("quiz.html", chooser=True, all_notes=notes, picked=picked, page="quiz")
    if source == "notes":
        if not chosen:
            flash("Select at least one note to make a quiz from.", "error"); return redirect(url_for("quiz"))
        qs = make_note_quiz(chosen)
        if not qs:
            flash("Not enough text in the selected notes to make a quiz. Try more or longer notes.", "error")
            return redirect(url_for("quiz"))
    else:
        qs = [{"q": QUESTIONS[i][0], "opts": QUESTIONS[i][1], "correct": QUESTIONS[i][2]}
              for i in random.sample(range(len(QUESTIONS)), 5)]
    session["quiz"] = qs
    return render_template("quiz.html", questions=[(i, q["q"], q["opts"]) for i, q in enumerate(qs)],
                           from_notes=(source == "notes"), page="quiz")

@app.route("/progress")
def progress():
    db = get_db()
    notes = db.execute("SELECT COUNT(*) c FROM notes WHERE user_id=?", (uid(),)).fetchone()["c"]
    attempts = db.execute("SELECT * FROM quiz_attempts WHERE user_id=? ORDER BY id DESC LIMIT 8", (uid(),)).fetchall()
    count = db.execute("SELECT COUNT(*) c FROM quiz_attempts WHERE user_id=?", (uid(),)).fetchone()["c"]
    best = db.execute("SELECT MAX(ROUND(score*100.0/total)) b, ROUND(AVG(score*100.0/total)) a FROM quiz_attempts WHERE user_id=?", (uid(),)).fetchone()
    return render_template("progress.html", notes=notes, count=count, attempts=attempts,
                           best=best["b"], avg=best["a"], page="progress")

@app.errorhandler(413)
def too_big(e):
    flash("File is too large. Maximum size is 10 MB.", "error")
    return redirect(url_for("notes"))

init_db()
if __name__ == "__main__":
    app.run(debug=True)
