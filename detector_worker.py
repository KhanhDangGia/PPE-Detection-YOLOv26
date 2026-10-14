"""
detector_worker.py
-------------------
Ket hop 2 model:
  1. Model COCO (yolo26n.pt goc, KHONG can train) -> Phat hien + Track "person"
     (dung ByteTrack de gan ID on dinh cho tung nguoi)
  2. Model custom (best_yolov26_new.pt) -> Phat hien head/helmet/vest/no-vest

Voi moi mu/ao tim duoc, xac dinh no thuoc VE NGUOI NAO bang cach kiem tra
diem trung tam co nam trong vung bounding box cua nguoi do khong.

Ca MU va AO deu duoc theo doi VI PHAM THEO TUNG NGUOI (person_id on dinh tu
ByteTrack). CHI CON 1 NGUONG DUY NHAT: neu vi pham LIEN TUC du
VIOLATION_DURATION giay -> gui canh bao ngay (khong con chia 3 chang nua).

Overlay (chu goc trai) duoc VE MOI FRAME dua tren DU LIEU GAN NHAT da tinh
duoc, khong phai chi ve vao dung luc quet AI -> khong bi nhap nhay giua cac
frame khong quet.
"""

import cv2
import re
import time
import os
import threading
from datetime import datetime
from ultralytics import YOLO
from dotenv import load_dotenv

load_dotenv()

PERSON_MODEL_PATH = os.getenv("PERSON_MODEL_PATH", "yolo26n.pt")
CUSTOM_MODEL_PATH = os.getenv("MODEL_PATH", "upgraded_no-vest.pt")

CAMERA_SOURCE_NAME = os.getenv("CAMERA_SOURCE", "Camera 01")
ADDRESS = os.getenv("ADDRESS", "Chua cau hinh dia chi")

BASE_CONF = 0.1
CONF_THRESHOLD_HELMET = 0.5
CONF_THRESHOLD_VEST = 0.12
CONF_THRESHOLD_PERSON = 0.4

VIOLATION_DURATION = 10.0

COCO_PERSON_CLASS_ID = 0

SCAN_EVERY_N_FRAMES = int(os.getenv("SCAN_EVERY_N_FRAMES", "4"))
MODEL_IMGSZ = int(os.getenv("MODEL_IMGSZ", "640"))
CAM_WIDTH = int(os.getenv("CAM_WIDTH", "1280"))
CAM_HEIGHT = int(os.getenv("CAM_HEIGHT", "720"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "90"))


def _normalize_class_name(name):
    return re.sub(r"[\s_\-]+", "", name.lower())


_lock = threading.Lock()
_latest_jpeg = None
_worker_thread = None
_state = {
    "running": False,
    "status_text": "Da tat",
    "source": None,
}


def _parse_source(src):
    src = src.strip()
    if src.isdigit():
        return int(src)
    return src


def get_status():
    with _lock:
        return dict(_state)


def get_latest_jpeg():
    with _lock:
        return _latest_jpeg


def start_detection(insert_detection_fn, source_input):
    global _worker_thread
    with _lock:
        if _state["running"]:
            return False, "Camera dang chay roi, hay tat truoc khi doi nguon."
        _state["running"] = True
        _state["status_text"] = "Dang khoi dong..."
        _state["source"] = source_input

    _worker_thread = threading.Thread(
        target=_run_loop, args=(insert_detection_fn, source_input), daemon=True
    )
    _worker_thread.start()
    return True, "Da bat dau khoi dong camera."


def stop_detection():
    with _lock:
        _state["running"] = False
        _state["status_text"] = "Da tat"
    return True


def _box_center(xyxy):
    x1, y1, x2, y2 = xyxy
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def _point_in_box(point, box_xyxy):
    px, py = point
    x1, y1, x2, y2 = box_xyxy
    return x1 <= px <= x2 and y1 <= py <= y2


class _FrameGrabber:
    """Doc frame tu VideoCapture o MOT THREAD RIENG, chay lien tuc doc khong
    ngung nghi, tranh bi tre don theo thoi gian ."""

    def __init__(self, cap):
        self.cap = cap
        self._lock = threading.Lock()
        self._frame = None
        self._ret = False
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _reader_loop(self):
        while self._running:
            ret, frame = self.cap.read()
            with self._lock:
                self._ret = ret
                self._frame = frame
            if not ret:
                time.sleep(0.05)

    def read(self):
        with self._lock:
            if self._frame is None:
                return self._ret, None
            return self._ret, self._frame.copy()

    def stop(self):
        self._running = False
        self._thread.join(timeout=2)


def _wait_for_first_frame(grabber, timeout=15.0):
    wait_start = time.time()
    ret, frame = grabber.read()
    while (not ret or frame is None) and (time.time() - wait_start) < timeout:
        time.sleep(0.1)
        ret, frame = grabber.read()
    return ret, frame


def _draw_snapshot_with_highlight(frame, persons, highlight_pid, highlight_label):
    snap = frame.copy()

    for pid, pbox in persons.items():
        if pid == highlight_pid:
            continue
        x1, y1, x2, y2 = [int(v) for v in pbox]
        cv2.rectangle(snap, (x1, y1), (x2, y2), (160, 160, 160), 1)
        cv2.putText(snap, f"ID:{pid}", (x1, max(y1 - 6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)

    if highlight_pid in persons:
        x1, y1, x2, y2 = [int(v) for v in persons[highlight_pid]]
        cv2.rectangle(snap, (x1, y1), (x2, y2), (0, 0, 255), 4)

        label = f"VI PHAM: {highlight_label} (ID:{highlight_pid})"
        (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        label_y = max(y1 - 12, text_h + 10)
        cv2.rectangle(snap, (x1, label_y - text_h - 8), (x1 + text_w + 10, label_y + 4), (0, 0, 255), -1)
        cv2.putText(snap, label, (x1 + 5, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    return snap


def _draw_overlay(base_frame, persons, custom_boxes_info, helmet_states, vest_states):
    """Ve toan bo overlay (khung nguoi, khung mu/ao, chu tong quan goc trai)
    LEN TREN 1 frame nen (base_frame). Duoc goi o MOI FRAME (khong chi luc
    quet AI)."""
    annotated = base_frame.copy()

    # Khung nguoi + mau theo trang thai
    for pid, pbox in persons.items():
        x1, y1, x2, y2 = [int(v) for v in pbox]
        helmet_violating = pid in helmet_states
        vest_violating = pid in vest_states
        is_violating = helmet_violating or vest_violating
        color = (0, 0, 255) if is_violating else (0, 200, 0)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"ID:{pid}"
        if helmet_violating:
            label += " KHONG MU"
        if vest_violating:
            label += " KHONG AO"
        cv2.putText(annotated, label, (x1, max(y1 - 8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    # Khung mu/ao (mau vang nhat, mong) tu model custom
    for (x1, y1, x2, y2, cname, conf) in custom_boxes_info:
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 200, 0), 1)
        cv2.putText(annotated, f"{cname} {conf:.2f}", (x1, max(y1 - 4, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 200, 0), 1)

    # Thong tin tong quan goc tren trai
    total_people_now = len(persons)
    helmet_violation_count_now = len(helmet_states)
    vest_violation_count_now = len(vest_states)
    info_lines = [
        f"Dang quet: {total_people_now} nguoi",
        f"Vi pham MU: {helmet_violation_count_now} nguoi",
        f"Vi pham AO: {vest_violation_count_now} nguoi",
    ]
    y_pos = 30
    for line in info_lines:
        cv2.putText(annotated, line, (15, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
        cv2.putText(annotated, line, (15, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        y_pos += 30

    return annotated


def _run_loop(insert_detection_fn, source_input):
    global _latest_jpeg

    print("Loading PERSON model (COCO)...")
    person_model = YOLO(PERSON_MODEL_PATH)
    print(f"Person model classes (chi dung class 'person' id={COCO_PERSON_CLASS_ID}): OK")

    print("Loading CUSTOM model (helmet/vest)...")
    custom_model = YOLO(CUSTOM_MODEL_PATH)
    print(f"Custom model classes: {custom_model.names}")

    source = _parse_source(source_input)
    cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print(f"[AI Detector] Khong the mo nguon video: {source}")
        with _lock:
            _state["running"] = False
            _state["status_text"] = f"Loi: khong mo duoc nguon '{source_input}'"
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    grabber = _FrameGrabber(cap)

    ret0, _ = _wait_for_first_frame(grabber, timeout=15.0)
    if not ret0:
        print(f"[AI Detector] Khong nhan duoc frame nao tu nguon '{source}' sau 15s.")
        grabber.stop()
        cap.release()
        with _lock:
            _state["running"] = False
            _state["status_text"] = f"Loi: khong nhan duoc hinh anh tu nguon '{source_input}'"
        return

    with _lock:
        _state["status_text"] = "Dang chay"
    print(f"[AI Detector] Da ket noi nguon video: {source}")
    os.makedirs("violations", exist_ok=True)

    frame_count = 0

    # track_states[person_id] = {"violation_start", "already_alerted"}
    helmet_track_states = {}
    vest_track_states = {}

    # ============ BO NHO OVERLAY GAN NHAT (chong nhap nhay) ============
    # Duoc CAP NHAT moi lan quet AI, nhung duoc SU DUNG DE VE o MOI FRAME
    # (ke ca frame khong quet), giup chu/khung luon hien thi lien tuc on dinh.
    last_persons = {}
    last_custom_boxes_info = []   # list of (x1,y1,x2,y2,name,conf)

    while True:
        with _lock:
            if not _state["running"]:
                break

        ret, frame = grabber.read()
        if not ret or frame is None:
            print("[AI Detector] Mat ket noi, thu lai sau 3s...")
            grabber.stop()
            cap.release()
            time.sleep(3)
            cap = cv2.VideoCapture(source)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            grabber = _FrameGrabber(cap)
            _wait_for_first_frame(grabber, timeout=15.0)
            with _lock:
                if not _state["running"]:
                    break
            continue

        frame_count += 1

        if frame_count % SCAN_EVERY_N_FRAMES == 0:
            current_time = time.time()

            # ============ BƯỚC 1: PHÁT HIỆN + TRACK NGƯỜI (Model COCO) ============
            person_results = person_model.track(
                source=frame, conf=CONF_THRESHOLD_PERSON, persist=True,
                tracker="bytetrack.yaml", classes=[COCO_PERSON_CLASS_ID],
                imgsz=MODEL_IMGSZ, verbose=False
            )
            person_result = person_results[0]

            persons = {}
            for box in person_result.boxes:
                pid = int(box.id) if box.id is not None else None
                if pid is None:
                    continue
                xyxy = box.xyxy[0].tolist()
                persons[pid] = xyxy

            # ============ BƯỚC 2: PHÁT HIỆN MŨ/ÁO (Model Custom) ============
            custom_results = custom_model.predict(
                source=frame, conf=BASE_CONF, imgsz=MODEL_IMGSZ, verbose=False
            )
            custom_result = custom_results[0]

            # ============ BƯỚC 3: GHÉP CẶP - MỖI MŨ/ÁO THUỘC VỀ NGƯỜI NÀO ============
            person_has_head = set()
            person_has_helmet = set()
            person_has_vest = set()
            person_no_vest = set()

            custom_boxes_info = []

            for box in custom_result.boxes:
                cid = int(box.cls)
                cname_raw = custom_model.names[cid]
                cname = _normalize_class_name(cname_raw)
                conf = float(box.conf)
                xyxy = box.xyxy[0].tolist()
                center = _box_center(xyxy)

                if conf >= 0.15:
                    x1, y1, x2, y2 = [int(v) for v in xyxy]
                    custom_boxes_info.append((x1, y1, x2, y2, cname_raw, conf))

                matched_pid = None
                for pid, pbox in persons.items():
                    if _point_in_box(center, pbox):
                        matched_pid = pid
                        break

                is_novest_class = cname in ("novest", "novests", "nvest")

                if cname == "head" and conf >= CONF_THRESHOLD_HELMET:
                    if matched_pid is not None:
                        person_has_head.add(matched_pid)
                elif cname == "helmet" and conf >= CONF_THRESHOLD_HELMET:
                    if matched_pid is not None:
                        person_has_helmet.add(matched_pid)
                elif is_novest_class:
                    if conf >= CONF_THRESHOLD_VEST:
                        if matched_pid is not None:
                            person_no_vest.add(matched_pid)
                elif cname == "vest":
                    if conf >= CONF_THRESHOLD_VEST:
                        if matched_pid is not None:
                            person_has_vest.add(matched_pid)

            # ============ CẬP NHẬT TRẠNG THÁI TỪNG NGƯỜI - MŨ ============
            for pid in person_has_head:
                if pid in person_has_helmet:
                    continue

                if pid not in helmet_track_states:
                    helmet_track_states[pid] = {"violation_start": current_time, "already_alerted": False}
                    print(f"[Nguoi #{pid}] Bat dau khong doi mu, dang tinh {VIOLATION_DURATION:.0f}s...")
                else:
                    st = helmet_track_states[pid]
                    elapsed = current_time - st["violation_start"]
                    if elapsed >= VIOLATION_DURATION and not st["already_alerted"]:
                        print(f"[CANH BAO] Nguoi #{pid} khong doi mu lien tuc {VIOLATION_DURATION:.0f}s!")
                        snapshot_path = f"violations/no_helmet_{datetime.now().strftime('%Y%m%d_%H%M%S')}_id{pid}.jpg"
                        snap_img = _draw_snapshot_with_highlight(frame, persons, pid, "KHONG DOI MU")
                        cv2.imwrite(snapshot_path, snap_img)
                        insert_detection_fn(
                            address=ADDRESS, camera_source=CAMERA_SOURCE_NAME,
                            person_count=1, confidence=90.0,
                            image_path=snapshot_path,
                            notes=f"Nguoi #{pid} - Vi pham MU sau {VIOLATION_DURATION:.0f}s lien tuc",
                        )
                        st["already_alerted"] = True

            for pid in person_has_helmet:
                if pid in helmet_track_states:
                    del helmet_track_states[pid]

            stale_helmet_ids = [
                pid for pid, st in helmet_track_states.items()
                if pid not in persons and (current_time - st["violation_start"]) > 30
            ]
            for pid in stale_helmet_ids:
                del helmet_track_states[pid]

            # ============ CẬP NHẬT TRẠNG THÁI TỪNG NGƯỜI - ÁO ============
            for pid in person_no_vest:
                if pid in person_has_vest:
                    continue

                if pid not in vest_track_states:
                    vest_track_states[pid] = {"violation_start": current_time, "already_alerted": False}
                    print(f"[Nguoi #{pid}] Bat dau khong mac ao, dang tinh {VIOLATION_DURATION:.0f}s...")
                else:
                    st = vest_track_states[pid]
                    elapsed = current_time - st["violation_start"]
                    if elapsed >= VIOLATION_DURATION and not st["already_alerted"]:
                        print(f"[CANH BAO] Nguoi #{pid} khong mac ao lien tuc {VIOLATION_DURATION:.0f}s!")
                        snapshot_path = f"violations/no_vest_{datetime.now().strftime('%Y%m%d_%H%M%S')}_id{pid}.jpg"
                        snap_img = _draw_snapshot_with_highlight(frame, persons, pid, "KHONG MAC AO PHAN QUANG")
                        cv2.imwrite(snapshot_path, snap_img)
                        insert_detection_fn(
                            address=ADDRESS, camera_source=CAMERA_SOURCE_NAME,
                            person_count=1, confidence=90.0,
                            image_path=snapshot_path,
                            notes=f"Nguoi #{pid} - Vi pham AO sau {VIOLATION_DURATION:.0f}s lien tuc",
                        )
                        st["already_alerted"] = True

            for pid in person_has_vest:
                if pid in vest_track_states:
                    del vest_track_states[pid]

            stale_vest_ids = [
                pid for pid, st in vest_track_states.items()
                if pid not in persons and (current_time - st["violation_start"]) > 30
            ]
            for pid in stale_vest_ids:
                del vest_track_states[pid]

            # ============ LƯU LẠI KẾT QUẢ ĐỂ VẼ ỔN ĐỊNH Ở MỌI FRAME ============
            last_persons = persons
            last_custom_boxes_info = custom_boxes_info

        # ============ VẼ OVERLAY Ở MỌI FRAME (KHÔNG CHỈ LÚC QUÉT) ============
        annotated_frame = _draw_overlay(
            frame, last_persons, last_custom_boxes_info,
            helmet_track_states, vest_track_states
        )

        ok, buffer = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if ok:
            with _lock:
                _latest_jpeg = buffer.tobytes()

    grabber.stop()
    cap.release()
    with _lock:
        _state["status_text"] = "Da tat"
    print("[AI Detector] Da dung luong detect.")