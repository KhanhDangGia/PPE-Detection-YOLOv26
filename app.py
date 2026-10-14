#!/usr/bin/env python3
"""
He thong Giam sat Phat hien Nguoi (Person Detection Monitoring System)
------------------------------------------------------------------------
Backend server. Chay:  python3 app.py [port]
Mac dinh: http://localhost:8000
"""

import json
import sqlite3
import base64
import os
import re
import uuid
import sys
import shutil
import time
import mimetypes
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import detector_worker
from telegram_notifier import send_telegram_photo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "detections.db")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DEFAULT_PORT = 8000

os.makedirs(UPLOADS_DIR, exist_ok=True)

DETAIL_RE = re.compile(r"^/api/detections/(\d+)(?:/(status))?$")
UPLOAD_RE = re.compile(r"^/uploads/([a-zA-Z0-9_\-.]+)$")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            address TEXT NOT NULL,
            camera_source TEXT,
            person_count INTEGER DEFAULT 1,
            confidence REAL,
            image_path TEXT,
            notes TEXT,
            status TEXT DEFAULT 'unreviewed',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def row_to_dict(row):
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "address": row["address"],
        "camera_source": row["camera_source"],
        "person_count": row["person_count"],
        "confidence": row["confidence"],
        "image_path": row["image_path"],
        "image_url": f"/{row['image_path']}" if row["image_path"] else None,
        "notes": row["notes"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def insert_detection_direct(address, camera_source, person_count, confidence, image_path, notes):
    final_image_path = None
    if image_path and os.path.exists(image_path):
        ext = os.path.splitext(image_path)[1].lstrip(".").lower() or "jpg"
        filename = f"{uuid.uuid4().hex}.{ext}"
        dest = os.path.join(UPLOADS_DIR, filename)
        shutil.copy2(image_path, dest)
        final_image_path = f"uploads/{filename}"

    conn = get_db()
    conn.execute(
        """INSERT INTO detections
           (timestamp, address, camera_source, person_count, confidence,
            image_path, notes, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'unreviewed', ?)""",
        (
            datetime.now().astimezone().isoformat(timespec="seconds"),
            address, camera_source, person_count, confidence,
            final_image_path, notes,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()

    # Gui canh bao qua Telegram
    # con ton tai tren dia ngay tai thoi diem nay; final_image_path la duong
    # dan tuong doi trong uploads/ dung de hien thi tren web).
    caption = (
        f"CANH BAO VI PHAM AN TOAN LAO DONG\n"
        f"Dia chi: {address}\n"
        f"Camera: {camera_source or 'Khong ro'}\n"
        f"So nguoi: {person_count}\n"
        f"Ghi chu: {notes or ''}"
    )
    send_telegram_photo(image_path, caption)


class Handler(BaseHTTPRequestHandler):
    server_version = "PersonDetectionServer/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status, message):
        self._send_json(status, {"error": message})

    def _send_file(self, path, content_type=None):
        if not os.path.isfile(path):
            self._send_error_json(404, "Khong tim thay tep")
            return
        if content_type is None:
            content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            return self._send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        if path == "/style.css":
            return self._send_file(os.path.join(STATIC_DIR, "style.css"), "text/css; charset=utf-8")
        if path == "/script.js":
            return self._send_file(os.path.join(STATIC_DIR, "script.js"), "application/javascript; charset=utf-8")

        m = UPLOAD_RE.match(path)
        if m:
            return self._send_file(os.path.join(UPLOADS_DIR, m.group(1)))

        if path == "/api/detections":
            return self._list_detections(query)

        if path == "/api/stats":
            return self._stats()

        if path == "/video_feed":
            return self._stream_video()

        if path == "/api/camera/status":
            return self._send_json(200, detector_worker.get_status())

        m = DETAIL_RE.match(path)
        if m and m.group(2) is None:
            return self._get_detection(int(m.group(1)))

        self._send_error_json(404, "Khong tim thay duong dan")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/detections":
            return self._create_detection()

        if parsed.path == "/api/camera/start":
            data = self._read_json_body()
            source_input = (data or {}).get("source", "0")
            started, msg = detector_worker.start_detection(insert_detection_direct, source_input)
            return self._send_json(200, {"started": started, "message": msg, **detector_worker.get_status()})

        if parsed.path == "/api/camera/stop":
            detector_worker.stop_detection()
            return self._send_json(200, {"stopped": True, **detector_worker.get_status()})

        self._send_error_json(404, "Khong tim thay duong dan")

    def do_PATCH(self):
        parsed = urlparse(self.path)
        m = DETAIL_RE.match(parsed.path)
        if m and m.group(2) == "status":
            return self._update_status(int(m.group(1)))
        self._send_error_json(404, "Khong tim thay duong dan")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        m = DETAIL_RE.match(parsed.path)
        if m and m.group(2) is None:
            return self._delete_detection(int(m.group(1)))
        self._send_error_json(404, "Khong tim thay duong dan")

    def _stream_video(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self._cors()
        self.end_headers()
        try:
            while True:
                frame_bytes = detector_worker.get_latest_jpeg()
                if frame_bytes is None:
                    time.sleep(0.1)
                    continue
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame_bytes)}\r\n\r\n".encode())
                self.wfile.write(frame_bytes)
                self.wfile.write(b"\r\n")
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _create_detection(self):
        data = self._read_json_body()
        if data is None:
            return self._send_error_json(400, "JSON khong hop le")

        address = (data.get("address") or "").strip()
        if not address:
            return self._send_error_json(400, "Thieu truong bat buoc: 'address' (dia chi / vi tri)")

        timestamp = data.get("timestamp") or datetime.now().astimezone().isoformat(timespec="seconds")
        camera_source = data.get("camera_source")
        person_count = data.get("person_count", 1)
        confidence = data.get("confidence")
        notes = data.get("notes")

        try:
            person_count = int(person_count)
        except (TypeError, ValueError):
            person_count = 1
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = None

        image_path = None
        image_b64 = data.get("image_base64")
        if image_b64:
            if "," in image_b64[:60] and image_b64.strip().lower().startswith("data:"):
                image_b64 = image_b64.split(",", 1)[1]
            ext = data.get("image_format", "jpg").lstrip(".").lower()
            if ext not in ("jpg", "jpeg", "png", "webp"):
                ext = "jpg"
            filename = f"{uuid.uuid4().hex}.{ext}"
            try:
                raw = base64.b64decode(image_b64, validate=False)
            except Exception:
                return self._send_error_json(400, "image_base64 khong hop le")
            with open(os.path.join(UPLOADS_DIR, filename), "wb") as f:
                f.write(raw)
            image_path = f"uploads/{filename}"

        conn = get_db()
        cur = conn.execute(
            """INSERT INTO detections
               (timestamp, address, camera_source, person_count, confidence,
                image_path, notes, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'unreviewed', ?)""",
            (
                timestamp, address, camera_source, person_count, confidence,
                image_path, notes,
                datetime.now().astimezone().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
        row = conn.execute("SELECT * FROM detections WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        self._send_json(201, row_to_dict(row))

    def _list_detections(self, query):
        conn = get_db()
        clauses = []
        params = []

        address = query.get("address", [None])[0]
        if address:
            clauses.append("address LIKE ?")
            params.append(f"%{address}%")

        status = query.get("status", [None])[0]
        if status in ("reviewed", "unreviewed"):
            clauses.append("status = ?")
            params.append(status)

        date_from = query.get("from", [None])[0]
        if date_from:
            clauses.append("timestamp >= ?")
            params.append(date_from)

        date_to = query.get("to", [None])[0]
        if date_to:
            clauses.append("timestamp <= ?")
            params.append(date_to)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        try:
            limit = min(int(query.get("limit", [200])[0]), 500)
        except ValueError:
            limit = 200
        try:
            offset = int(query.get("offset", [0])[0])
        except ValueError:
            offset = 0

        rows = conn.execute(
            f"SELECT * FROM detections {where} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) AS c FROM detections {where}", params).fetchone()["c"]
        conn.close()
        self._send_json(200, {"total": total, "items": [row_to_dict(r) for r in rows]})

    def _get_detection(self, detection_id):
        conn = get_db()
        row = conn.execute("SELECT * FROM detections WHERE id = ?", (detection_id,)).fetchone()
        conn.close()
        if not row:
            return self._send_error_json(404, "Khong tim thay ban ghi")
        self._send_json(200, row_to_dict(row))

    def _update_status(self, detection_id):
        data = self._read_json_body()
        if data is None or data.get("status") not in ("reviewed", "unreviewed"):
            return self._send_error_json(400, "Can truong 'status' la 'reviewed' hoac 'unreviewed'")
        conn = get_db()
        row = conn.execute("SELECT * FROM detections WHERE id = ?", (detection_id,)).fetchone()
        if not row:
            conn.close()
            return self._send_error_json(404, "Khong tim thay ban ghi")
        conn.execute("UPDATE detections SET status = ? WHERE id = ?", (data["status"], detection_id))
        conn.commit()
        row = conn.execute("SELECT * FROM detections WHERE id = ?", (detection_id,)).fetchone()
        conn.close()
        self._send_json(200, row_to_dict(row))

    def _delete_detection(self, detection_id):
        conn = get_db()
        row = conn.execute("SELECT * FROM detections WHERE id = ?", (detection_id,)).fetchone()
        if not row:
            conn.close()
            return self._send_error_json(404, "Khong tim thay ban ghi")
        if row["image_path"]:
            img_file = os.path.join(BASE_DIR, row["image_path"])
            if os.path.isfile(img_file):
                try:
                    os.remove(img_file)
                except OSError:
                    pass
        conn.execute("DELETE FROM detections WHERE id = ?", (detection_id,))
        conn.commit()
        conn.close()
        self._send_json(200, {"deleted": detection_id})

    def _stats(self):
        conn = get_db()
        total = conn.execute("SELECT COUNT(*) AS c FROM detections").fetchone()["c"]

        today_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        today = conn.execute(
            "SELECT COUNT(*) AS c FROM detections WHERE timestamp >= ?",
            (today_start.isoformat(timespec="seconds"),),
        ).fetchone()["c"]

        week_start = today_start - timedelta(days=today_start.weekday())
        this_week = conn.execute(
            "SELECT COUNT(*) AS c FROM detections WHERE timestamp >= ?",
            (week_start.isoformat(timespec="seconds"),),
        ).fetchone()["c"]

        unique_addresses = conn.execute(
            "SELECT COUNT(DISTINCT address) AS c FROM detections"
        ).fetchone()["c"]

        unreviewed = conn.execute(
            "SELECT COUNT(*) AS c FROM detections WHERE status = 'unreviewed'"
        ).fetchone()["c"]

        conn.close()
        self._send_json(200, {
            "total": total,
            "today": today,
            "this_week": this_week,
            "unique_addresses": unique_addresses,
            "unreviewed": unreviewed,
        })


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"He thong Giam sat Phat hien Nguoi dang chay tai: http://localhost:{port}")
    print("Nhan Ctrl+C de dung server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDang dung server...")
        server.shutdown()


if __name__ == "__main__":
    main()