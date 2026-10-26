from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, Response, send_from_directory
from functools import wraps
from pathlib import Path
from datetime import datetime
import csv
import io
import os
import re
import secrets
import sqlite3
import threading

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
SAVE_FOLDER = BASE_DIR / "received_images"
DB_PATH = BASE_DIR / "vehicles.db"
SAVE_FOLDER.mkdir(parents=True, exist_ok=True)
app.secret_key = os.environ.get("HSRP_SECRET_KEY") or secrets.token_hex(32)
PLATE_RE = re.compile(r"^[A-Z0-9 -]{4,15}$")
SLOT_COUNT = 2
EVENT_LOCK = threading.Lock()

latest_camera_result = {
    "plate": "", "approved": False, "owner_name": "",
    "reason": "waiting_for_camera", "available_slots": None,
    "detection_confidence": None, "updated_at": None,
}

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS vehicles (
            plate TEXT PRIMARY KEY, owner_name TEXT NOT NULL,
            campus_id TEXT DEFAULT '', department TEXT DEFAULT '', phone TEXT DEFAULT '',
            vehicle_type TEXT DEFAULT '', vehicle_model TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'approved'
                CHECK(status IN ('pending', 'approved', 'rejected')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT DEFAULT NULL, reviewed_by TEXT DEFAULT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS parking (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            total_slots INTEGER NOT NULL DEFAULT 2 CHECK(total_slots >= 0),
            occupied_slots INTEGER NOT NULL DEFAULT 0
                CHECK(occupied_slots >= 0 AND occupied_slots <= total_slots)
        )""")
        conn.execute("INSERT OR IGNORE INTO parking (id,total_slots,occupied_slots) VALUES (1,2,0)")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(vehicles)")}
        additions = {
            "campus_id": "TEXT DEFAULT ''", "department": "TEXT DEFAULT ''",
            "phone": "TEXT DEFAULT ''", "vehicle_type": "TEXT DEFAULT ''",
            "vehicle_model": "TEXT DEFAULT ''", "created_at": "TEXT",
            "reviewed_at": "TEXT", "reviewed_by": "TEXT",
        }
        for name, definition in additions.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE vehicles ADD COLUMN {name} {definition}")
        conn.execute("""CREATE TABLE IF NOT EXISTS parking_activity (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT DEFAULT '', owner_name TEXT DEFAULT '',
            direction TEXT NOT NULL DEFAULT 'system',
            event_time TEXT NOT NULL,
            result TEXT NOT NULL DEFAULT 'info',
            note TEXT DEFAULT '',
            slot_id INTEGER DEFAULT NULL,
            image_filename TEXT DEFAULT ''
        )""")
        event_cols = {r["name"] for r in conn.execute("PRAGMA table_info(parking_activity)")}
        for name, definition in {
            "plate": "TEXT DEFAULT ''", "owner_name": "TEXT DEFAULT ''",
            "direction": "TEXT NOT NULL DEFAULT 'system'", "event_time": "TEXT",
            "result": "TEXT NOT NULL DEFAULT 'info'", "note": "TEXT DEFAULT ''",
            "slot_id": "INTEGER DEFAULT NULL", "image_filename": "TEXT DEFAULT ''"
        }.items():
            if name not in event_cols:
                conn.execute(f"ALTER TABLE parking_events ADD COLUMN {name} {definition}")
        conn.execute("""CREATE TABLE IF NOT EXISTS parking_slots (
            slot_id INTEGER PRIMARY KEY,
            occupied INTEGER NOT NULL DEFAULT 0 CHECK(occupied IN (0,1)),
            distance_cm REAL,
            sensor_status TEXT NOT NULL DEFAULT 'waiting',
            updated_at TEXT
        )""")
        for slot_id in range(1, SLOT_COUNT + 1):
            conn.execute("INSERT OR IGNORE INTO parking_slots(slot_id,occupied,sensor_status) VALUES (?,0,'waiting')", (slot_id,))
        # Backfill event_time for compatible older event rows.
        conn.execute("UPDATE parking_activity SET event_time=COALESCE(event_time, ?) WHERE event_time IS NULL", (now_iso(),))
        # Keep the count derived from the two slot records, not manually edited.
        occupied = conn.execute("SELECT COUNT(*) FROM parking_slots WHERE occupied=1").fetchone()[0]
        conn.execute("UPDATE parking SET total_slots=?, occupied_slots=? WHERE id=1", (SLOT_COUNT, occupied))

def normalize_plate(value):
    return re.sub(r"\s+", "", str(value or "").upper()).replace("-", "")

def log_event(plate="", owner_name="", direction="system", result="info", note="", slot_id=None, image_filename=""):
    with get_db() as conn:
        conn.execute("""INSERT INTO parking_activity
            (plate,owner_name,direction,event_time,result,note,slot_id,image_filename)
            VALUES (?,?,?,?,?,?,?,?)""",
            (normalize_plate(plate), owner_name or "", direction, now_iso(), result, note or "", slot_id, image_filename or ""))

# Local prototype: no login. Restrict access to a trusted LAN.
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper

@app.route("/")
def home():
    return redirect(url_for("dashboard"))

@app.route("/dashboard")
def dashboard():
    with get_db() as conn:
        counts = {key: conn.execute(
            "SELECT COUNT(*) FROM vehicles" + (" WHERE status=?" if key != "total" else ""),
            (key,) if key != "total" else ()
        ).fetchone()[0] for key in ("total", "pending", "approved", "rejected")}
        parking = conn.execute("SELECT * FROM parking WHERE id=1").fetchone()
        vehicles = conn.execute("""SELECT plate,owner_name,department,vehicle_type,status,created_at
            FROM vehicles ORDER BY created_at DESC LIMIT 100""").fetchall()
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
                    (plate, owner, *fields, now_iso()))
            flash("Vehicle registered and approved successfully.", "success")
            return redirect(url_for("register_vehicle_page"))
        except sqlite3.IntegrityError:
            flash("This number plate is already registered.", "error")
    return render_template("register.html")

@app.route("/admin/vehicles/<path:plate>/review", methods=["POST"])
@admin_required
def review_vehicle(plate):
    plate = normalize_plate(plate)
    action = request.form.get("action")
    if action not in ("approved", "rejected", "pending"):
        return "Invalid status", 400
    with get_db() as conn:
        row = conn.execute("SELECT owner_name FROM vehicles WHERE plate=?", (plate,)).fetchone()
        if not row:
            return "Vehicle not found", 404
        conn.execute("UPDATE vehicles SET status=?, reviewed_at=?, reviewed_by='local-dashboard' WHERE plate=?",
                     (action, now_iso(), plate))
    log_event(plate, row["owner_name"], "review", action, f"Vehicle status changed to {action}")
    flash(f"{plate} status changed to {action.upper()}.", "success")
    return redirect(url_for("dashboard"))

@app.route("/api/parking", methods=["GET"])
def parking_status():
    with get_db() as conn:
        p = conn.execute("SELECT total_slots,occupied_slots FROM parking WHERE id=1").fetchone()
        slots = conn.execute("SELECT slot_id,occupied,distance_cm,sensor_status,updated_at FROM parking_slots ORDER BY slot_id").fetchall()
    return jsonify({"total_slots": p["total_slots"], "occupied_slots": p["occupied_slots"],
                    "available_slots": p["total_slots"] - p["occupied_slots"],
                    "slots": [dict(s) for s in slots]})

@app.route("/api/slots/update", methods=["POST"])
def update_slots():
    data = request.get_json(silent=True) or {}
    readings = data.get("slots")
    if not isinstance(readings, list):
        return jsonify({"status":"error","message":"Expected slots list"}), 400
    timestamp = now_iso()
    changed = []
    with EVENT_LOCK:
        with get_db() as conn:
            for item in readings:
                try:
                    slot_id = int(item["slot_id"])
                    occupied = 1 if bool(item["occupied"]) else 0
                    distance = float(item["distance_cm"]) if item.get("distance_cm") is not None else None
                    sensor_status = str(item.get("sensor_status", "ok"))[:30]
                except (KeyError, TypeError, ValueError):
                    continue
                if slot_id not in (1, 2):
                    continue
                old = conn.execute("SELECT occupied FROM parking_slots WHERE slot_id=?", (slot_id,)).fetchone()
                conn.execute("""UPDATE parking_slots SET occupied=?,distance_cm=?,sensor_status=?,updated_at=?
                    WHERE slot_id=?""", (occupied, distance, sensor_status, timestamp, slot_id))
                if old is not None and int(old["occupied"]) != occupied:
                    changed.append((slot_id, occupied, distance))
                    state = "occupied" if occupied else "available"
                    conn.execute("""INSERT INTO parking_activity
                        (plate,owner_name,direction,event_time,result,note,slot_id,image_filename)
                        VALUES ('','','slot',?,?,?,?,'')""",
                        (timestamp, state, f"Slot {slot_id} changed to {state}", slot_id))
            occupied_count = conn.execute("SELECT COUNT(*) FROM parking_slots WHERE occupied=1").fetchone()[0]
            conn.execute("UPDATE parking SET total_slots=2,occupied_slots=? WHERE id=1", (occupied_count,))
    return jsonify({"status":"success","updated_at":timestamp,"changed_slots":len(changed)})

@app.route("/api/events")
def api_events():
    try:
        limit = max(1, min(200, int(request.args.get("limit", 30))))
    except ValueError:
        limit = 30
    plate_filter = normalize_plate(request.args.get("plate", ""))
    direction = request.args.get("direction", "")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    query = """SELECT event_id,plate,owner_name,direction,event_time,result,note,slot_id,image_filename
               FROM parking_activity WHERE 1=1"""
    args = []
    if plate_filter:
        query += " AND plate LIKE ?"; args.append(f"%{plate_filter}%")
    if direction in ("entry", "exit", "slot", "review", "system"):
        query += " AND direction=?"; args.append(direction)
    if start:
        query += " AND substr(event_time,1,10)>=?"; args.append(start)
    if end:
        query += " AND substr(event_time,1,10)<=?"; args.append(end)
    query += " ORDER BY event_id DESC LIMIT ?"; args.append(limit)
    with get_db() as conn:
        rows = conn.execute(query, args).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/dashboard-data")
def dashboard_data():
    with get_db() as conn:
        p = conn.execute("SELECT total_slots,occupied_slots FROM parking WHERE id=1").fetchone()
        slots = conn.execute("SELECT slot_id,occupied,distance_cm,sensor_status,updated_at FROM parking_slots ORDER BY slot_id").fetchall()
        entries = conn.execute("SELECT COUNT(*) FROM parking_activity WHERE direction='entry' AND substr(event_time,1,10)=?", (datetime.now().date().isoformat(),)).fetchone()[0]
        exits = conn.execute("SELECT COUNT(*) FROM parking_activity WHERE direction='exit' AND substr(event_time,1,10)=?", (datetime.now().date().isoformat(),)).fetchone()[0]
        latest = conn.execute("""SELECT * FROM parking_activity WHERE direction IN ('entry','exit')
            ORDER BY event_id DESC LIMIT 1""").fetchone()
        recent = conn.execute("""SELECT event_id,plate,owner_name,direction,event_time,result,note,slot_id
            FROM parking_activity ORDER BY event_id DESC LIMIT 15""").fetchall()
    return jsonify({
        "parking":{"total_slots":p["total_slots"],"occupied_slots":p["occupied_slots"],"available_slots":p["total_slots"]-p["occupied_slots"]},
        "slots":[dict(s) for s in slots], "today_entries":entries,"today_exits":exits,
        "latest_vehicle":dict(latest) if latest else None, "events":[dict(e) for e in recent],
        "server_time":now_iso()
    })

@app.route("/api/vehicle-event", methods=["POST"])
def vehicle_event():
    data = request.get_json(silent=True) or {}
    plate = normalize_plate(data.get("plate", ""))
    direction = str(data.get("direction", "entry")).lower()
    result = str(data.get("result", "unknown")).lower()
    note = str(data.get("note", ""))[:250]
    image_filename = str(data.get("image_filename", ""))[:200]
    if direction not in ("entry", "exit"):
        return jsonify({"status":"error","message":"direction must be entry or exit"}), 400
    owner = ""
    if plate:
        with get_db() as conn:
            vehicle = conn.execute("SELECT owner_name,status FROM vehicles WHERE plate=?", (plate,)).fetchone()
        if vehicle:
            owner = vehicle["owner_name"]
            if result == "unknown":
                result = vehicle["status"]
    log_event(plate, owner, direction, result, note, None, image_filename)
    with EVENT_LOCK:
        latest_camera_result.update({"plate":plate,"owner_name":owner,"approved":result=="approved",
                                     "reason":result,"updated_at":now_iso()})
    return jsonify({"status":"success","plate":plate,"owner_name":owner,"result":result}), 201

@app.route("/api/authorize", methods=["POST"])
def authorize():
    data = request.get_json(silent=True) or {}
    plate = normalize_plate(data.get("plate", ""))
    if not plate:
        return jsonify({"approved":False,"reason":"missing_plate"}), 400
    with get_db() as conn:
        vehicle = conn.execute("SELECT owner_name,status FROM vehicles WHERE plate=?", (plate,)).fetchone()
        parking = conn.execute("SELECT total_slots,occupied_slots FROM parking WHERE id=1").fetchone()
    if vehicle is None:
        log_event(plate, "", "entry", "unregistered", "Plate not registered")
        return jsonify({"approved":False,"reason":"unregistered","show_register_option":True})
    if vehicle["status"] != "approved":
        log_event(plate, vehicle["owner_name"], "entry", vehicle["status"], "Vehicle is not approved")
        return jsonify({"approved":False,"reason":vehicle["status"],"show_register_option":False})
    if parking is None or parking["occupied_slots"] >= parking["total_slots"]:
        log_event(plate, vehicle["owner_name"], "entry", "parking_full", "No free parking slots")
        return jsonify({"approved":False,"reason":"parking_full"})
    return jsonify({"approved":True,"reason":"approved","plate":plate,"owner_name":vehicle["owner_name"],
                    "available_slots":parking["total_slots"]-parking["occupied_slots"]})

@app.route("/api/parking-events.csv")
def download_csv():
    plate_filter = normalize_plate(request.args.get("plate", ""))
    direction = request.args.get("direction", "")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    query = """SELECT event_id,plate,owner_name,direction,event_time,result,note,slot_id,image_filename
               FROM parking_activity WHERE 1=1"""
    args = []
    if plate_filter:
        query += " AND plate LIKE ?"; args.append(f"%{plate_filter}%")
    if direction in ("entry", "exit", "slot", "review", "system"):
        query += " AND direction=?"; args.append(direction)
    if start:
        query += " AND substr(event_time,1,10)>=?"; args.append(start)
    if end:
        query += " AND substr(event_time,1,10)<=?"; args.append(end)
    query += " ORDER BY event_id DESC"
    with get_db() as conn:
        rows = conn.execute(query, args).fetchall()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Event ID","Plate","Owner","Direction","Timestamp","Result","Note","Slot","Image"])
    for row in rows:
        writer.writerow([row["event_id"],row["plate"],row["owner_name"],row["direction"],row["event_time"],
                         row["result"],row["note"],row["slot_id"],row["image_filename"]])
    response = Response("\ufeff" + out.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=hsrp_parking_logs.csv"
    return response

@app.route("/received_images/<path:filename>")
def received_image(filename):
    return send_from_directory(SAVE_FOLDER, filename)

@app.route("/upload", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"status":"error","message":"No image received"}), 400
    image = request.files["image"]
    filename = datetime.now().strftime("vehicle_%Y%m%d_%H%M%S_%f.jpg")
    image.save(SAVE_FOLDER / filename)
    return jsonify({"status":"success","filename":filename})

@app.route("/api/camera-status", methods=["POST"])
def camera_status():
    data = request.get_json(silent=True) or {}
    print("Camera status:", data)
    return jsonify({"status": "success"}), 200



if __name__ == "__main__":
    init_db()
    print("HSRP Smart Parking Server")
    print("Dashboard: http://127.0.0.1:5000/dashboard")
    print("Slot sensors post to /api/slots/update")
    app.run(host="0.0.0.0", port=5000, debug=False)
