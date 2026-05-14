# routes/api.py — JSON endpoints for webcam face capture and attendance marking
import base64
import re
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from models.db import get_db
from utils.attendance_rules import (
    classify_attendance_state,
    classes_currently_in_session,
    pick_active_class_for_student,
)
from utils.face_utils import (
    best_match_student,
    blob_to_encoding,
    compute_encoding_from_bytes,
    encodings_match,
    match_threshold_for_probe,
    parse_face_blob,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _require_admin():
    """Return (True, None, None) if admin is logged in."""
    if not session.get("admin_id"):
        return None, jsonify({"ok": False, "message": "Admin login required"}), 401
    return True, None, None


def _require_student():
    sid = session.get("student_id")
    if not sid:
        return None, jsonify({"ok": False, "message": "Not logged in"}), 401
    conn = get_db()
    stu = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not stu:
        return None, jsonify({"ok": False, "message": "Invalid session"}), 401
    return stu, None, None


@api_bp.route("/student/mark_attendance", methods=["POST"])
def student_mark_attendance():
    """
    Expect JSON: { "image": "<base64 data URL or raw base64>" }
    Marks attendance only if: active class, within 10-minute window, face matches logged-in student.
    """
    stu, err_resp, code = _require_student()
    if err_resp:
        return err_resp, code

    data = request.get_json(silent=True) or {}
    raw = data.get("image") or ""
    # Strip data URL prefix if present
    if "base64," in raw:
        raw = raw.split("base64,", 1)[1]
    raw = re.sub(r"\s+", "", raw)
    try:
        image_bytes = base64.b64decode(raw)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid image data"}), 400

    now = datetime.now()
    conn = get_db()
    today = now.strftime("%Y-%m-%d")
    class_rows = conn.execute(
        """
        SELECT c.* FROM classes c
        WHERE c.class_date = ? AND c.department = ? AND c.semester = ?
        """,
        (today, stu["department"], stu["semester"]),
    ).fetchall()

    active = pick_active_class_for_student(
        now, stu["department"], stu["semester"], [dict(r) for r in class_rows]
    )
    if not active:
        conn.close()
        return jsonify({"ok": False, "message": "No Active Class Right Now"})

    state = classify_attendance_state(now, active)
    if state == "closed":
        conn.close()
        return jsonify({"ok": False, "message": "Attendance Closed for This Class"})
    if state != "open":
        conn.close()
        return jsonify({"ok": False, "message": "No Active Class Right Now"})

    existing = conn.execute(
        "SELECT id FROM attendance WHERE student_id=? AND class_id=?",
        (stu["id"], active["id"]),
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"ok": False, "message": "Attendance Already Marked"})

    stored = blob_to_encoding(stu["face_encoding"])
    if stored is None:
        conn.close()
        return jsonify({"ok": False, "message": "Face not registered — contact admin."})

    try:
        probe = compute_encoding_from_bytes(image_bytes)
    except (RuntimeError, ValueError) as e:
        conn.close()
        return jsonify({"ok": False, "message": str(e)}), 400
    if probe is None:
        conn.close()
        return jsonify({"ok": False, "message": "Face Not Recognized"})

    sk, _ = parse_face_blob(stu["face_encoding"])
    probe_kind = "fr128" if probe.size == 128 else "ocv"
    if sk and sk != probe_kind:
        conn.close()
        return jsonify(
            {
                "ok": False,
                "message": "Re-register your face with admin (old dlib encoding vs OpenCV mode).",
            }
        )

    if not encodings_match(probe, stored):
        conn.close()
        return jsonify({"ok": False, "message": "Face Verification Failed"})

    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute(
            """
            INSERT INTO attendance (student_id, class_id, subject_id, attendance_time, status)
            VALUES (?, ?, ?, ?, 'Present')
            """,
            (stu["id"], active["id"], active["subject_id"], ts),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return jsonify({"ok": False, "message": "Attendance Already Marked"})
    conn.close()
    return jsonify({"ok": True, "message": "Attendance Marked Successfully"})


def _decode_image_from_json(data: dict) -> bytes:
    raw = data.get("image") or ""
    if "base64," in raw:
        raw = raw.split("base64,", 1)[1]
    raw = re.sub(r"\s+", "", raw)
    return base64.b64decode(raw)


@api_bp.route("/admin/live_mark", methods=["POST"])
def admin_live_mark():
    """
    Admin kiosk: JSON { "image": "<base64>", "class_id": <int> }
    Matches face against students in the same department/semester as the class,
    only during the 10-minute attendance window for that class.
    """
    _, err_resp, code = _require_admin()
    if err_resp:
        return err_resp, code

    data = request.get_json(silent=True) or {}
    try:
        class_id = int(data.get("class_id") or 0)
    except (TypeError, ValueError):
        class_id = 0
    if not class_id:
        return jsonify({"ok": False, "message": "Missing class_id"}), 400

    try:
        image_bytes = _decode_image_from_json(data)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid image data"}), 400

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    conn = get_db()
    crow = conn.execute(
        """
        SELECT c.*, s.subject_name FROM classes c
        JOIN subjects s ON s.id = c.subject_id WHERE c.id = ?
        """,
        (class_id,),
    ).fetchone()
    if not crow:
        conn.close()
        return jsonify({"ok": False, "message": "Class not found"})

    cdict = dict(crow)
    if cdict.get("class_date") != today:
        conn.close()
        return jsonify({"ok": False, "message": "No Active Class Right Now"})

    all_today = conn.execute(
        """
        SELECT c.* FROM classes c WHERE c.class_date = ?
        """,
        (today,),
    ).fetchall()
    in_session_ids = {r["id"] for r in classes_currently_in_session(now, [dict(r) for r in all_today])}
    if class_id not in in_session_ids:
        conn.close()
        return jsonify({"ok": False, "message": "This class is not in session right now"})

    state = classify_attendance_state(now, cdict)
    if state == "closed":
        conn.close()
        return jsonify({"ok": False, "message": "Attendance Closed for This Class"})
    if state != "open":
        conn.close()
        return jsonify({"ok": False, "message": "Attendance window is not open"})

    stu_rows = conn.execute(
        """
        SELECT id, usn, full_name, face_encoding FROM students
        WHERE lower(trim(department)) = lower(trim(?)) AND semester = ? AND face_encoding IS NOT NULL
        """,
        (cdict["department"], cdict["semester"]),
    ).fetchall()

    try:
        probe = compute_encoding_from_bytes(image_bytes)
    except (RuntimeError, ValueError) as e:
        conn.close()
        return jsonify({"ok": False, "message": str(e)}), 400
    if probe is None:
        conn.close()
        return jsonify({"ok": False, "message": "Face Not Recognized"})

    best_id, best_dist = best_match_student(probe, stu_rows)
    if best_id is None or best_dist > match_threshold_for_probe(probe):
        conn.close()
        return jsonify({"ok": False, "message": "Face Not Recognized"})

    stu = conn.execute("SELECT * FROM students WHERE id=?", (best_id,)).fetchone()
    if not stu:
        conn.close()
        return jsonify({"ok": False, "message": "Face Not Recognized"})

    existing = conn.execute(
        "SELECT id FROM attendance WHERE student_id=? AND class_id=?",
        (best_id, class_id),
    ).fetchone()
    if existing:
        conn.close()
        return jsonify(
            {
                "ok": False,
                "message": "Attendance Already Marked",
                "student": stu["full_name"],
                "usn": stu["usn"],
            }
        )

    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute(
            """
            INSERT INTO attendance (student_id, class_id, subject_id, attendance_time, status)
            VALUES (?, ?, ?, ?, 'Present')
            """,
            (best_id, class_id, cdict["subject_id"], ts),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return jsonify({"ok": False, "message": "Attendance Already Marked"})
    conn.close()
    return jsonify(
        {
            "ok": True,
            "message": "Attendance Marked Successfully",
            "student": stu["full_name"],
            "usn": stu["usn"],
        }
    )
