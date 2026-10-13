import os, sqlite3, secrets, string
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-deployment")
DB = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "hostelfix.db"))

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'STUDENT', room TEXT, parent_phone TEXT,
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS complaints(
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES users(id),
          category TEXT NOT NULL, description TEXT NOT NULL, room TEXT NOT NULL,
          priority TEXT NOT NULL DEFAULT 'NORMAL', status TEXT NOT NULL DEFAULT 'PENDING',
          created_at TEXT NOT NULL, resolved_at TEXT);
        CREATE TABLE IF NOT EXISTS laundry(
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES users(id),
          item_count INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'PICKED_UP',
          picked_up_at TEXT NOT NULL, ready_at TEXT, returned_at TEXT);
        CREATE TABLE IF NOT EXISTS outpasses(
          id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES users(id),
          reason TEXT NOT NULL, otp TEXT NOT NULL, otp_verified INTEGER NOT NULL DEFAULT 0,
          parent_approved INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'PENDING_OTP',
          qr_token TEXT UNIQUE NOT NULL, expected_return TEXT NOT NULL, exit_time TEXT, entry_time TEXT,
          is_late INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        """)
        count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            demos = [
                ("Demo Student","student@hostelfix.test","STUDENT","A-101"),
                ("Demo Warden","warden@hostelfix.test","WARDEN",None),
                ("Demo Gatekeeper","gatekeeper@hostelfix.test","GATEKEEPER",None)]
            for name,email,role,room in demos:
                db.execute("INSERT INTO users(name,email,password,role,room,created_at) VALUES(?,?,?,?,?,?)",
                           (name,email,generate_password_hash("password123"),role,room,now()))

def now():
    return datetime.now().isoformat(timespec="seconds")

def current_user():
    if "user_id" not in session: return None
    return connect().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user=current_user()
            if not user:
                return redirect(url_for("login"))
            if roles and user["role"] not in roles:
                abort(403)
            g.user=user
            return fn(*args, **kwargs)
        return wrapped
    return deco

@app.context_processor
def inject_user():
    u = current_user()
    return {"user": u, "base_template": "base.html" if u else "base_public.html"}

@app.template_filter("dt")
def format_dt(value):
    if not value:
        return "\u2014"
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return value

def count(db, sql, params=()):
    return db.execute(sql, params).fetchone()[0]

def repeat_rooms(db):
    since = (datetime.now() - timedelta(days=30)).isoformat()
    return db.execute("SELECT room,COUNT(*) AS total FROM complaints WHERE created_at>=? GROUP BY room HAVING COUNT(*)>=3", (since,)).fetchall()

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form.get("name","").strip()
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        room=request.form.get("room","").strip()
        phone=request.form.get("parent_phone","").strip()
        if not name or not email or len(password)<8:
            flash("Enter your name and email, and use a password of at least 8 characters.","error")
        else:
            try:
                with connect() as db:
                    db.execute("INSERT INTO users(name,email,password,role,room,parent_phone,created_at) VALUES(?,?,?,?,?,?,?)",
                               (name,email,generate_password_hash(password),"STUDENT",room,phone,now()))
                flash("Account created. Please log in.")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That email is already registered.","error")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        with connect() as db: u=db.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if u and check_password_hash(u["password"],password):
            session.clear(); session["user_id"]=u["id"]
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.","error")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/dashboard")
@login_required()
def dashboard():
    role=g.user["role"]
    if role=="STUDENT": return redirect(url_for("student_dashboard"))
    if role=="WARDEN": return redirect(url_for("warden_dashboard"))
    return redirect(url_for("gatekeeper_dashboard"))

@app.route("/student")
@login_required("STUDENT")
def student_dashboard():
    uid = g.user["id"]
    with connect() as db:
        stats = {
            "open_complaints": count(db, "SELECT COUNT(*) FROM complaints WHERE student_id=? AND status!='RESOLVED'", (uid,)),
            "laundry_active": count(db, "SELECT COUNT(*) FROM laundry WHERE student_id=? AND status!='RETURNED'", (uid,)),
            "active_outpasses": count(db, "SELECT COUNT(*) FROM outpasses WHERE student_id=? AND status IN ('PENDING_OTP','PENDING_PARENT','APPROVED','OUT')", (uid,)),
        }
    return render_template("student_dashboard.html", stats=stats)

@app.route("/student/maintenance")
@login_required("STUDENT")
def student_maintenance():
    with connect() as db:
        complaints = db.execute("SELECT * FROM complaints WHERE student_id=? ORDER BY created_at DESC", (g.user["id"],)).fetchall()
    return render_template("student_maintenance.html", complaints=complaints)

@app.route("/student/laundry")
@login_required("STUDENT")
def student_laundry():
    with connect() as db:
        laundry = db.execute("SELECT * FROM laundry WHERE student_id=? ORDER BY picked_up_at DESC", (g.user["id"],)).fetchall()
    return render_template("student_laundry.html", laundry=laundry)

@app.route("/student/outpass")
@login_required("STUDENT")
def student_outpass():
    with connect() as db:
        outpasses = db.execute("SELECT * FROM outpasses WHERE student_id=? ORDER BY created_at DESC", (g.user["id"],)).fetchall()
    return render_template("student_outpass.html", outpasses=outpasses)

@app.route("/complaints", methods=["POST"])
@login_required("STUDENT")
def add_complaint():
    category=request.form.get("category","").strip(); description=request.form.get("description","").strip()
    room=request.form.get("room","").strip() or g.user["room"] or ""
    priority="URGENT" if request.form.get("priority")=="URGENT" else "NORMAL"
    if not category or not description or not room:
        flash("Category, description, and room are required.","error")
    else:
        with connect() as db:
            db.execute("INSERT INTO complaints(student_id,category,description,room,priority,status,created_at) VALUES(?,?,?,?,?,'PENDING',?)",
                       (g.user["id"],category,description,room,priority,now()))
        flash("Maintenance complaint submitted.")
    return redirect(url_for("student_maintenance"))

@app.route("/laundry", methods=["POST"])
@login_required("STUDENT")
def add_laundry():
    try: count=max(1,min(100,int(request.form.get("item_count","1"))))
    except ValueError: count=1
    with connect() as db:
        db.execute("INSERT INTO laundry(student_id,item_count,status,picked_up_at) VALUES(?,?,'PICKED_UP',?)",(g.user["id"],count,now()))
    flash("Laundry pickup recorded.")
    return redirect(url_for("student_laundry"))

@app.route("/laundry/<int:item_id>/confirm", methods=["POST"])
@login_required("STUDENT")
def confirm_laundry(item_id):
    with connect() as db:
        db.execute("UPDATE laundry SET status='RETURNED', returned_at=? WHERE id=? AND student_id=? AND status='READY'",(now(),item_id,g.user["id"]))
    flash("Laundry receipt confirmed.")
    return redirect(url_for("student_laundry"))

@app.route("/outpass", methods=["POST"])
@login_required("STUDENT")
def add_outpass():
    reason=request.form.get("reason","").strip()
    try: expected=datetime.fromisoformat(request.form.get("expected_return",""))
    except ValueError: expected=None
    if not reason or not expected:
        flash("Enter a reason and expected return date/time.","error")
    else:
        otp=''.join(secrets.choice(string.digits) for _ in range(6))
        token=secrets.token_urlsafe(24)
        with connect() as db:
            db.execute("INSERT INTO outpasses(student_id,reason,otp,qr_token,expected_return,status,created_at) VALUES(?,?,?,?,?,'PENDING_OTP',?)",
                       (g.user["id"],reason,otp,token,expected.isoformat(timespec="seconds"),now()))
            oid=db.execute("SELECT last_insert_rowid()").fetchone()[0]
        flash(f"Demo OTP for outpass #{oid}: {otp} (demo only; not sent to a parent).")
    return redirect(url_for("student_outpass"))

@app.route("/outpass/<int:oid>/verify", methods=["POST"])
@login_required("STUDENT")
def verify_otp(oid):
    code=request.form.get("otp","").strip()
    with connect() as db:
        row=db.execute("SELECT * FROM outpasses WHERE id=? AND student_id=?",(oid,g.user["id"])).fetchone()
        if row and row["otp"]==code and row["status"]=="PENDING_OTP":
            db.execute("UPDATE outpasses SET otp_verified=1,status='PENDING_PARENT' WHERE id=?",(oid,))
            flash("OTP verified. Waiting for warden approval.")
        else: flash("Invalid OTP or outpass state.","error")
    return redirect(url_for("student_outpass"))

@app.route("/warden")
@login_required("WARDEN")
def warden_dashboard():
    with connect() as db:
        stats = {
            "open_complaints": count(db, "SELECT COUNT(*) FROM complaints WHERE status!='RESOLVED'"),
            "laundry_active": count(db, "SELECT COUNT(*) FROM laundry WHERE status!='RETURNED'"),
            "pending_outpasses": count(db, "SELECT COUNT(*) FROM outpasses WHERE status='PENDING_PARENT'"),
            "students": count(db, "SELECT COUNT(*) FROM users WHERE role='STUDENT'"),
        }
        repeats = repeat_rooms(db)
    return render_template("warden_dashboard.html", stats=stats, repeats=repeats)

@app.route("/warden/maintenance")
@login_required("WARDEN")
def warden_maintenance():
    with connect() as db:
        complaints = db.execute("SELECT c.*,u.name AS student_name FROM complaints c JOIN users u ON u.id=c.student_id ORDER BY CASE c.priority WHEN 'URGENT' THEN 0 ELSE 1 END,c.created_at DESC").fetchall()
        repeats = repeat_rooms(db)
    return render_template("warden_maintenance.html", complaints=complaints, repeats=repeats)

@app.route("/warden/laundry")
@login_required("WARDEN")
def warden_laundry():
    with connect() as db:
        laundry = db.execute("SELECT l.*,u.name AS student_name,u.room FROM laundry l JOIN users u ON u.id=l.student_id ORDER BY l.picked_up_at DESC").fetchall()
    return render_template("warden_laundry.html", laundry=laundry)

@app.route("/warden/outpass")
@login_required("WARDEN")
def warden_outpass():
    with connect() as db:
        outpasses = db.execute("SELECT o.*,u.name AS student_name,u.room FROM outpasses o JOIN users u ON u.id=o.student_id ORDER BY o.created_at DESC").fetchall()
    return render_template("warden_outpass.html", outpasses=outpasses)

@app.route("/complaints/<int:cid>/status", methods=["POST"])
@login_required("WARDEN")
def complaint_status(cid):
    status=request.form.get("status")
    if status not in ("PENDING","ASSIGNED","IN_PROGRESS","RESOLVED"): abort(400)
    with connect() as db:
        db.execute("UPDATE complaints SET status=?,resolved_at=? WHERE id=?",(status,now() if status=="RESOLVED" else None,cid))
    flash("Complaint status updated.")
    return redirect(url_for("warden_maintenance"))

@app.route("/laundry/<int:item_id>/status", methods=["POST"])
@login_required("WARDEN")
def laundry_status(item_id):
    status=request.form.get("status")
    if status not in ("PICKED_UP","IN_PROGRESS","READY","RETURNED"): abort(400)
    with connect() as db:
        db.execute("UPDATE laundry SET status=?,ready_at=CASE WHEN ?='READY' THEN ? ELSE ready_at END,returned_at=CASE WHEN ?='RETURNED' THEN ? ELSE returned_at END WHERE id=?",
                   (status,status,now(),status,now(),item_id))
    flash("Laundry status updated.")
    return redirect(url_for("warden_laundry"))

@app.route("/outpass/<int:oid>/approve", methods=["POST"])
@login_required("WARDEN")
def approve_outpass(oid):
    action=request.form.get("action")
    with connect() as db:
        row=db.execute("SELECT * FROM outpasses WHERE id=?",(oid,)).fetchone()
        if not row: abort(404)
        if action=="approve" and row["otp_verified"]:
            db.execute("UPDATE outpasses SET parent_approved=1,status='APPROVED' WHERE id=?",(oid,))
            flash("Outpass approved.")
        elif action=="reject":
            db.execute("UPDATE outpasses SET status='REJECTED' WHERE id=?",(oid,))
            flash("Outpass rejected.")
        else: flash("OTP must be verified before approval.","error")
    return redirect(url_for("warden_outpass"))

@app.route("/gatekeeper", methods=["GET","POST"])
@login_required("GATEKEEPER")
def gatekeeper_dashboard():
    if request.method=="POST":
        token=request.form.get("qr_token","").strip()
        with connect() as db:
            row=db.execute("SELECT * FROM outpasses WHERE qr_token=?",(token,)).fetchone()
            if not row: flash("QR token not found.","error")
            elif row["status"]=="APPROVED":
                db.execute("UPDATE outpasses SET status='OUT',exit_time=? WHERE id=?",(now(),row["id"]))
                flash("Exit recorded.")
            elif row["status"]=="OUT":
                late=datetime.fromisoformat(now())>datetime.fromisoformat(row["expected_return"])
                db.execute("UPDATE outpasses SET status=?,entry_time=?,is_late=? WHERE id=?",("LATE" if late else "RETURNED",now(),int(late),row["id"]))
                flash("Entry recorded. "+("Late return flagged." if late else "Returned on time."))
            else: flash("This outpass is not ready for exit or has already been used.","error")
        return redirect(url_for("gatekeeper_dashboard"))
    with connect() as db:
        logs=db.execute("SELECT o.*,u.name AS student_name,u.room FROM outpasses o JOIN users u ON u.id=o.student_id ORDER BY o.created_at DESC").fetchall()
        stats = {
            "out_now": count(db, "SELECT COUNT(*) FROM outpasses WHERE status='OUT'"),
            "awaiting_exit": count(db, "SELECT COUNT(*) FROM outpasses WHERE status='APPROVED'"),
            "late_returns": count(db, "SELECT COUNT(*) FROM outpasses WHERE is_late=1"),
            "returned": count(db, "SELECT COUNT(*) FROM outpasses WHERE status IN ('RETURNED','LATE')"),
        }
    return render_template("gatekeeper.html",logs=logs,stats=stats)

@app.errorhandler(403)
def forbidden(_): return render_template("error.html",message="You do not have permission to view this page."),403
@app.errorhandler(404)
def not_found(_): return render_template("error.html",message="Page not found."),404

init_db()
if __name__=="__main__":
    app.run(debug=True)
