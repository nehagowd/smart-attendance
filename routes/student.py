# routes/student.py — Student-only portal (no admin privileges)
from datetime import datetime

from flask import Blueprint, redirect, render_template, session, url_for

from models.db import get_db
from routes.auth import student_required
from utils.attendance_rules import classify_attendance_state, pick_active_class_for_student

student_bp = Blueprint("student", __name__, url_prefix="/student")


def _current_student():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM students WHERE id = ?", (session["student_id"],)
    ).fetchone()
    conn.close()
    return row


def _todays_classes_for_student(stu):
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(
        """
        SELECT c.*, s.subject_name, s.subject_code
        FROM classes c
        JOIN subjects s ON s.id = c.subject_id
        WHERE c.class_date = ? AND c.department = ? AND c.semester = ?
        ORDER BY c.start_time
        """,
        (today, stu["department"], stu["semester"]),
    ).fetchall()
    conn.close()
    return rows


def _active_class_context(stu):
    """Return (active_row_dict or None, window_message_key)."""
    now = datetime.now()
    rows = _todays_classes_for_student(stu)
    active = pick_active_class_for_student(
        now, stu["department"], stu["semester"], [dict(r) for r in rows]
    )
    if not active:
        return None, "no_active"
    state = classify_attendance_state(now, active)
    return active, state


@student_bp.route("/")
@student_required
def student_home():
    return redirect(url_for("student.student_dashboard"))


@student_bp.route("/dashboard")
@student_required
def student_dashboard():
    stu = _current_student()
    if not stu:
        session.clear()
        return redirect(url_for("auth.student_login"))

    active, state = _active_class_context(stu)
    conn = get_db()
    attendance_note = None
    if not active:
        attendance_note = "No Active Class Right Now"
    else:
        ex = conn.execute(
            "SELECT * FROM attendance WHERE student_id=? AND class_id=?",
            (stu["id"], active["id"]),
        ).fetchone()
        if ex:
            attendance_note = "Attendance Already Marked"
        elif state == "closed":
            attendance_note = "Attendance Closed for This Class"
        elif state == "open":
            attendance_note = "Attendance window is OPEN — go to Mark Attendance"
        else:
            attendance_note = "No Active Class Right Now"

    # Overall attendance percentage (this student)
    stats = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) AS present_cnt
        FROM attendance WHERE student_id=?
        """,
        (stu["id"],),
    ).fetchone()
    conn.close()
    tot = stats["total"] or 0
    pr = stats["present_cnt"] or 0
    pct = round(100.0 * pr / tot, 1) if tot else 0.0

    subj_name = None
    if active:
        conn = get_db()
        sr = conn.execute(
            "SELECT subject_name FROM subjects WHERE id=?", (active["subject_id"],)
        ).fetchone()
        conn.close()
        subj_name = sr["subject_name"] if sr else ""

    return render_template(
        "student/dashboard.html",
        student=stu,
        active=active,
        state=state,
        attendance_note=attendance_note,
        overall_pct=pct,
        active_subject=subj_name,
    )


@student_bp.route("/today")
@student_required
def today_classes():
    stu = _current_student()
    rows = _todays_classes_for_student(stu)
    now = datetime.now()
    enriched = []
    for r in rows:
        d = dict(r)
        d["state"] = classify_attendance_state(now, d)
        enriched.append(d)
    return render_template("student/today.html", student=stu, classes=enriched)


@student_bp.route("/mark")
@student_required
def mark_attendance_page():
    stu = _current_student()
    active, state = _active_class_context(stu)
    subj = None
    if active:
        conn = get_db()
        subj = conn.execute(
            "SELECT * FROM subjects WHERE id=?", (active["subject_id"],)
        ).fetchone()
        conn.close()
    return render_template(
        "student/mark.html",
        student=stu,
        active=active,
        state=state,
        subject=subj,
    )


@student_bp.route("/history")
@student_required
def attendance_history():
    stu = _current_student()
    conn = get_db()
    rows = conn.execute(
        """
        SELECT a.*, s.subject_name, c.class_date, c.start_time, c.end_time
        FROM attendance a
        JOIN subjects s ON s.id = a.subject_id
        JOIN classes c ON c.id = a.class_id
        WHERE a.student_id = ?
        ORDER BY a.attendance_time DESC
        """,
        (stu["id"],),
    ).fetchall()
    conn.close()
    return render_template("student/history.html", student=stu, rows=rows)


@student_bp.route("/subjects")
@student_required
def subject_wise():
    stu = _current_student()
    conn = get_db()
    rows = conn.execute(
        """
        SELECT s.subject_name,
               COUNT(a.id) AS total,
               SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) AS present_cnt
        FROM attendance a
        JOIN subjects s ON s.id = a.subject_id
        WHERE a.student_id = ?
        GROUP BY s.id
        ORDER BY s.subject_name
        """,
        (stu["id"],),
    ).fetchall()
    conn.close()
    stats = []
    for r in rows:
        tot = r["total"] or 0
        pr = r["present_cnt"] or 0
        stats.append(
            {
                "name": r["subject_name"],
                "total": tot,
                "present": pr,
                "pct": round(100.0 * pr / tot, 1) if tot else 0.0,
            }
        )
    return render_template("student/subject_wise.html", student=stu, stats=stats)


@student_bp.route("/profile")
@student_required
def profile():
    stu = _current_student()
    return render_template("student/profile.html", student=stu)
