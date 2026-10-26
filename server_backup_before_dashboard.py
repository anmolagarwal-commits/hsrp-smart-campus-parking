
from flask import Flask, request, jsonify
import os
import sqlite3
from datetime import datetime

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_FOLDER = os.path.join(BASE_DIR, "received_images")
DB_PATH = os.path.join(BASE_DIR, "vehicles.db")

os.makedirs(SAVE_FOLDER, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                plate TEXT PRIMARY KEY,
                owner_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS parking (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                total_slots INTEGER NOT NULL,
                occupied_slots INTEGER NOT NULL
            )
        """)

        conn.execute("""
            INSERT OR IGNORE INTO parking
            (id, total_slots, occupied_slots)
            VALUES (1, 2, 0)
        """)

        conn.execute("""
            INSERT OR IGNORE INTO vehicles
            (plate, owner_name, status)
            VALUES (?, ?, ?)
        """, ("UP16AB1234", "Demo Vehicle", "approved"))


@app.route("/")
def home():
    return "HSRP Parking Server is running"


@app.route("/upload", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({
            "status": "error",
            "message": "No image received"
        }), 400

    image = request.files["image"]
    filename = datetime.now().strftime(
        "vehicle_%Y%m%d_%H%M%S_%f.jpg"
    )
    filepath = os.path.join(SAVE_FOLDER, filename)
    image.save(filepath)

    print(f"Image received: {filepath}")

    return jsonify({
        "status": "success",
        "filename": filename
    })


@app.route("/api/authorize", methods=["POST"])
def authorize():
    data = request.get_json(silent=True) or {}
    plate = str(data.get("plate", "")).strip().upper()

    if not plate:
        return jsonify({
            "approved": False,
            "reason": "missing_plate"
        }), 400

    with get_db() as conn:
        vehicle = conn.execute(
            "SELECT owner_name, status FROM vehicles WHERE plate = ?",
            (plate,)
        ).fetchone()

        parking = conn.execute(
            "SELECT total_slots, occupied_slots FROM parking WHERE id = 1"
        ).fetchone()

    if vehicle is None:
        return jsonify({
            "approved": False,
            "reason": "unregistered",
            "show_register_option": True
        })

    if vehicle["status"] != "approved":
        return jsonify({
            "approved": False,
            "reason": vehicle["status"],
            "show_register_option": False
        })

    if parking["occupied_slots"] >= parking["total_slots"]:
        return jsonify({
            "approved": False,
            "reason": "parking_full"
        })

    return jsonify({
        "approved": True,
        "reason": "approved",
        "plate": plate,
        "owner_name": vehicle["owner_name"]
    })


@app.route("/api/vehicles", methods=["POST"])
def register_vehicle():
    data = request.get_json(silent=True) or {}
    plate = str(data.get("plate", "")).strip().upper()
    owner = str(data.get("owner_name", "")).strip()

    if not plate or not owner:
        return jsonify({
            "status": "error",
            "message": "plate and owner_name are required"
        }), 400

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO vehicles (plate, owner_name, status) "
                "VALUES (?, ?, 'pending')",
                (plate, owner)
            )

        return jsonify({
            "status": "pending",
            "message": "Vehicle submitted for admin approval"
        }), 201

    except sqlite3.IntegrityError:
        return jsonify({
            "status": "error",
            "message": "Vehicle already registered"
        }), 409


if __name__ == "__main__":
    init_db()
    print("HSRP Parking Server starting...")
    app.run(host="0.0.0.0", port=5000)
