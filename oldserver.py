from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, abort
from werkzeug.security import check_password_hash
from functools import wraps
from pathlib import Path
from datetime import datetime
import os, re, secrets, sqlite3

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
SAVE_FOLDER = BASE_DIR / "received_images"
DB_PATH = BASE_DIR / "vehicles.db"
SAVE_FOLDER.mkdir(parents=True, exist_ok=True)

app.secret_key = os.environ.get("HSRP_SECRET_KEY") or secrets.token_hex(32)
if not os.environ.get("HSRP_SECRET_KEY"):
    print("WARNING: HSRP_SECRET_KEY is not set; sessions reset when the server restarts.")

ADMIN_USERNAME = os.environ.get("HSRP_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.environ.get("HSRP_ADMIN_PASSWORD_HASH")
PLATE_RE = re.compile(r"^[A-Z0-9 -]{4,15}$")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                plate TEXT PRIMARY KEY,
                owner_name TEXT NOT NULL,
                campus_id TEXT DEFAULT '',
                department TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                vehicle_type TEXT DEFAULT '',
                vehicle_model TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT DEFAULT NULL,
                reviewed_by TEXT DEFAULT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS parking (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                total_slots INTEGER NOT NULL DEFAULT 2 CHECK(total_slots >= 0),
                occupied_slots INTEGER NOT NULL DEFAULT 0
                    CHECK(occupied_slots >= 0 AND occupied_slots <= total_slots)
            )
        """)
        conn.execute("INSERT OR IGNORE INTO parking (id,total_slots,occupied_slots) VALUES (1,2,0)")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(vehicles)")}
        additions = {
            "campus_id": "TEXT DEFAULT ''", "department": "TEXT DEFAULT ''",
            "phone": "TEXT DEFAULT ''", "vehicle_type": "TEXT DEFAULT ''",
            "vehicle_model": "TEXT DEFAULT ''", "created_at": "TEXT",
            "reviewed_at": "TEXT", "reviewed_by": "TEXT"
        }
        for name, definition in additions.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE vehicles ADD COLUMN {name} {definition}")
        # Preserve older records and any existing approved demo row.


def normalize_plate(value):
    return re.sub(r"\s+", "", str(value or "").upper()).replace("-", "")


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    return "HSRP Parking Server is running. Open /dashboard for the dashboard."


@app.route("/dashboard")
def dashboard():
    with get_db() as conn:
        counts = {k: conn.execute("SELECT COUNT(*) FROM vehicles" + (" WHERE status=?" if k != "total" else ""),
                                  (k,) if k != "total" else ()).fetchone()[0]
                  for k in ("total", "pending", "approved", "rejected")}
        parking = conn.execute("SELECT * FROM parking WHERE id=1").fetchone()
        vehicles = conn.execute("""SELECT plate,owner_name,department,vehicle_type,status,created_at
            FROM vehicles ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
            created_at DESC LIMIT 200""").fetchall()
    return render_template("dashboard.html", counts=counts, parking=parking, vehicles=vehicles)


@app.route("/register", methods=["GET", "POST"])
def register_vehicle_page():
    if request.method == "POST":
        plate = normalize_plate(request.form.get("plate"))
        owner = request.form.get("owner_name", "").strip()
        fields = [request.form.get(k, "").strip() for k in
                  ("campus_id", "department", "phone", "vehicle_type", "vehicle_model")]
        if not PLATE_RE.fullmatch(plate):
            flash("Enter a valid plate using 4–15 letters or numbers.", "error")
            return render_template("register.html")
        if not owner:
            flash("Owner name is required.", "error")
            return render_template("register.html")
        try:
            with get_db() as conn:
                conn.execute("""INSERT INTO vehicles
                    (plate,owner_name,campus_id,department,phone,vehicle_type,vehicle_model,status,created_at)
                    VALUES (?,?,?,?,?,?,?,'approved',?)""",
                    (plate, owner, *fields, datetime.now().isoformat(timespec="seconds")))
            flash("Registration submitted. It remains PENDING until an administrator reviews it.", "success")
            return redirect(url_for("register_vehicle_page"))
        except sqlite3.IntegrityError:
            flash("This number plate is already registered.", "error")
    return render_template("register.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_PASSWORD_HASH:
        return render_template("admin_login.html", setup_required=True)
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if secrets.compare_digest(username, ADMIN_USERNAME) and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.clear()
            session["admin_logged_in"] = True
            session["admin_username"] = ADMIN_USERNAME
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("admin_login.html", setup_required=False)


@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/vehicles/<path:plate>/review", methods=["POST"])
@admin_required
def review_vehicle(plate):
    plate = normalize_plate(plate)
    action = request.form.get("action")
    if action not in ("approved", "rejected", "pending"):
        abort(400, "Invalid review action.")
    with get_db() as conn:
        cur = conn.execute("UPDATE vehicles SET status=?,reviewed_at=?,reviewed_by=? WHERE plate=?",
                           (action, datetime.now().isoformat(timespec="seconds"),
                            session.get("admin_username", ADMIN_USERNAME), plate))
        if cur.rowcount == 0:
            abort(404)
    flash(f"{plate} status changed to {action.upper()}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/parking", methods=["POST"])
@admin_required
def update_parking():
    try:
        total = int(request.form.get("total_slots", ""))
        occupied = int(request.form.get("occupied_slots", ""))
        if total < 0 or occupied < 0 or occupied > total:
            raise ValueError
    except ValueError:
        flash("Use whole numbers; occupied slots must be between zero and total slots.", "error")
        return redirect(url_for("dashboard"))
    with get_db() as conn:
        conn.execute("UPDATE parking SET total_slots=?,occupied_slots=? WHERE id=1", (total, occupied))
    flash("Parking occupancy updated.", "success")
    return redirect(url_for("dashboard"))


@app.route("/upload", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"status": "error", "message": "No image received"}), 400
    image = request.files["image"]
    filename = datetime.now().strftime("vehicle_%Y%m%d_%H%M%S_%f.jpg")
    filepath = SAVE_FOLDER / filename
    image.save(filepath)
    print(f"Image received: {filepath}")
    return jsonify({"status": "success", "filename": filename})


@app.route("/api/authorize", methods=["POST"])
def authorize():
    data = request.get_json(silent=True) or {}
    plate = normalize_plate(data.get("plate", ""))
    if not plate:
        return jsonify({"approved": False, "reason": "missing_plate"}), 400
    with get_db() as conn:
        vehicle = conn.execute("SELECT owner_name,status FROM vehicles WHERE plate=?", (plate,)).fetchone()
        parking = conn.execute("SELECT total_slots,occupied_slots FROM parking WHERE id=1").fetchone()
    if vehicle is None:
        return jsonify({"approved": False, "reason": "unregistered", "show_register_option": True})
    if vehicle["status"] != "approved":
        return jsonify({"approved": False, "reason": vehicle["status"], "show_register_option": False})
    if parking is None or parking["occupied_slots"] >= parking["total_slots"]:
        return jsonify({"approved": False, "reason": "parking_full"})
    return jsonify({"approved": True, "reason": "approved", "plate": plate,
                    "owner_name": vehicle["owner_name"],
                    "available_slots": parking["total_slots"] - parking["occupied_slots"]})


@app.route("/api/vehicles", methods=["POST"])
def register_vehicle_api():
    data = request.get_json(silent=True) or {}
    plate = normalize_plate(data.get("plate", ""))
    owner = str(data.get("owner_name", "")).strip()
    if not PLATE_RE.fullmatch(plate) or not owner:
        return jsonify({"status": "error", "message": "Valid plate and owner_name are required"}), 400
    fields = [str(data.get(k, "")).strip() for k in
              ("campus_id", "department", "phone", "vehicle_type", "vehicle_model")]
    try:
        with get_db() as conn:
            conn.execute("""INSERT INTO vehicles
                (plate,owner_name,campus_id,department,phone,vehicle_type,vehicle_model,status,created_at)
                VALUES (?,?,?,?,?,?,?,'pending',?)""",
                (plate, owner, *fields, datetime.now().isoformat(timespec="seconds")))
        return jsonify({"status": "approved", "message": "Vehicle registered and approved successfully"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "Vehicle already registered"}), 409


@app.route("/api/parking", methods=["GET"])
def parking_status():
    with get_db() as conn:
        p = conn.execute("SELECT total_slots,occupied_slots FROM parking WHERE id=1").fetchone()
    return jsonify({"total_slots": p["total_slots"], "occupied_slots": p["occupied_slots"],
                    "available_slots": p["total_slots"] - p["occupied_slots"]})


@app.route("/api/parking", methods=["POST"])
@admin_required
def update_parking_api():
    data = request.get_json(silent=True) or {}
    try:
        total, occupied = int(data["total_slots"]), int(data["occupied_slots"])
        if total < 0 or occupied < 0 or occupied > total:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid slot counts"}), 400
    with get_db() as conn:
        conn.execute("UPDATE parking SET total_slots=?,occupied_slots=? WHERE id=1", (total, occupied))
    return jsonify({"status": "success", "total_slots": total, "occupied_slots": occupied})


if __name__ == "__main__":
    init_db()
    print("HSRP Parking Server starting...")
    print("Dashboard: http://127.0.0.1:5000/dashboard")
    if not ADMIN_PASSWORD_HASH:
        print("ADMIN SETUP REQUIRED: configure HSRP_ADMIN_PASSWORD_HASH before logging in.")
    app.run(host="0.0.0.0", port=5000, debug=False)
