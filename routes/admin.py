# routes/admin.py — Admin dashboard, CRUD for students/subjects/classes/attendance, reports, export
import csv
import os
import re
from datetime import datetime
from io import BytesIO, StringIO

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from config import Config
from models.db import get_db
from routes.auth import admin_required
from utils.face_utils import average_encoding_from_folder, encoding_to_blob

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _safe_usn_folder(usn: str) -> str:
    """Folder name under dataset/ — only alphanumeric and dash/underscore."""
    s = re.sub(r"[^\w\-]+", "_", (usn or "").strip(), flags=re.ASCII)
    return s or "unknown"


@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    conn = get_db()
    total_students = conn.execute("SELECT COUNT(*) AS c FROM students").fetchone()["c"]

    # Subject-wise attendance percentage (among recorded rows)
    subj_rows = conn.execute(
        """
        SELECT s.id, s.subject_name,
               COUNT(a.id) AS total_marks,
               SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) AS present_cnt
        FROM subjects s
        LEFT JOIN attendance a ON a.subject_id = s.id
        GROUP BY s.id
        ORDER BY s.subject_name
        """
    ).fetchall()

    present_absent = conn.execute(
        """
        SELECT status, COUNT(*) AS c FROM attendance GROUP BY status
        """
    ).fetchall()
    pa = {r["status"]: r["c"] for r in present_absent}

    # Today's summary
    today = datetime.now().strftime("%Y-%m-%d")
    today_rows = conn.execute(
        """
        SELECT COUNT(*) AS c FROM attendance
        WHERE substr(attendance_time,1,10) = ?
        """,
        (today,),
    ).fetchone()["c"]

    # Department-wise (join student for department)
    dept_rows = conn.execute(
        """
        SELECT st.department,
               COUNT(a.id) AS total_marks,
               SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) AS present_cnt
        FROM attendance a
        JOIN students st ON st.id = a.student_id
        GROUP BY st.department
        """
    ).fetchall()

    

    subj_stats = []
    for r in subj_rows:
        tot = r["total_marks"] or 0
        pr = r["present_cnt"] or 0
        pct = round(100.0 * pr / tot, 1) if tot else 0.0
        subj_stats.append(
            {"name": r["subject_name"], "total": tot, "present": pr, "pct": pct}
        )

    dept_stats = []
    for r in dept_rows:
        tot = r["total_marks"] or 0
        pr = r["present_cnt"] or 0
        pct = round(100.0 * pr / tot, 1) if tot else 0.0
        dept_stats.append({"dept": r["department"], "total": tot, "present": pr, "pct": pct})
    
    cur = conn.cursor()
    cur.execute("SELECT * FROM students")
   
    all_students = cur.fetchall()

    
    cur.execute("""
    SELECT DISTINCT s.*
    FROM students s
    JOIN attendance a ON s.id = a.student_id
    WHERE a.status='Present'
""")
    present_students = cur.fetchall()

    present_usns = [s["usn"] for s in present_students]

    absent_students = [
            s for s in all_students
            if s["usn"] not in present_usns
    ]
    conn.close()

    return render_template(
        "admin/dashboard.html",
        total_students=total_students,
        subj_stats=subj_stats,
        present_count=pa.get("Present", 0),
        absent_count=pa.get("Absent", 0),
        today_marks=today_rows,
        dept_stats=dept_stats,
           present_students=present_students,
        absent_students=absent_students,
    )


@admin_bp.route("/live-scan")
@admin_required
def live_scan():
    """
    Classroom kiosk: webcam + pick active scheduled class, mark any matching student
    (same rules: 10-minute window, one mark per student per class).
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    conn = get_db()
    all_today = conn.execute(
        """
        SELECT c.*, s.subject_name, s.subject_code
        FROM classes c
        JOIN subjects s ON s.id = c.subject_id
        WHERE c.class_date = ?
        ORDER BY c.start_time
        """,
        (today,),
    ).fetchall()
    conn.close()

    from utils.attendance_rules import classify_attendance_state, classes_currently_in_session

    in_session = classes_currently_in_session(now, [dict(r) for r in all_today])
    for row in in_session:
        row["window_state"] = classify_attendance_state(now, row)

    default_class_id = None
    for row in in_session:
        if row.get("window_state") == "open":
            default_class_id = row["id"]
            break
    if default_class_id is None and in_session:
        default_class_id = in_session[0]["id"]

    return render_template(
        "admin/live_scan.html", sessions=in_session, default_class_id=default_class_id
    )


@admin_bp.route("/students")
@admin_required
def students_list():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, usn, full_name, department, semester FROM students ORDER BY usn"
    ).fetchall()
    conn.close()
    return render_template("admin/students.html", students=rows)


@admin_bp.route("/students/add", methods=["GET", "POST"])
@admin_required
def students_add():
    if request.method == "GET":
        return render_template("admin/student_form.html", student=None, edit=False)

    usn = (request.form.get("usn") or "").strip()
    full_name = (request.form.get("full_name") or "").strip()
    department = (request.form.get("department") or "").strip()
    semester = int(request.form.get("semester") or 0)

    if not usn or not full_name or not department or not semester:
        flash("Please fill all required fields.", "error")
        return redirect(url_for("admin.students_add"))

    files = [f for f in request.files.getlist("face_images") if f and f.filename]
    if not files:
        flash("Please capture at least one face photo using the webcam before saving.", "error")
        return redirect(url_for("admin.students_add"))

    folder = os.path.join(Config.DATASET_FOLDER, _safe_usn_folder(usn))
    os.makedirs(folder, exist_ok=True)
    saved_paths = []
    for i, f in enumerate(files):
        ext = os.path.splitext(secure_filename(f.filename))[1].lower() or ".jpg"
        dest = os.path.join(folder, f"capture_{len(saved_paths)+1}{ext}")
        f.save(dest)
        saved_paths.append(dest)

    enc_blob = None
    if saved_paths:
        avg = average_encoding_from_folder(saved_paths)
        if avg is not None:
            enc_blob = encoding_to_blob(avg)

    pwd_hash = generate_password_hash(full_name)

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO students (usn, full_name, password, department, semester, face_encoding)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (usn, full_name, pwd_hash, department, semester, enc_blob),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        flash(f"Could not save student (USN duplicate?): {e}", "error")
        return redirect(url_for("admin.students_add"))
    conn.close()

    if not enc_blob:
        flash(
            "Student saved but no face encoding could be built — use clearer webcam captures (frontal, good light).",
            "warning",
        )
    else:
        flash("Student registered successfully.", "success")
    return redirect(url_for("admin.students_list"))


@admin_bp.route("/students/edit/<int:sid>", methods=["GET", "POST"])
@admin_required
def students_edit(sid):
    conn = get_db()
    row = conn.execute("SELECT * FROM students WHERE id = ?", (sid,)).fetchone()
    if not row:
        conn.close()
        flash("Student not found.", "error")
        return redirect(url_for("admin.students_list"))

    if request.method == "GET":
        conn.close()
        return render_template("admin/student_form.html", student=row, edit=True)

    full_name = (request.form.get("full_name") or "").strip()
    department = (request.form.get("department") or "").strip()
    semester = int(request.form.get("semester") or 0)
    new_password = (request.form.get("password") or "").strip()
    files = request.files.getlist("face_images")

    folder = os.path.join(Config.DATASET_FOLDER, _safe_usn_folder(row["usn"]))
    os.makedirs(folder, exist_ok=True)
    for f in files:
        if f and f.filename:
            ext = os.path.splitext(secure_filename(f.filename))[1].lower() or ".jpg"
            dest = os.path.join(folder, f"capture_{datetime.now().strftime('%H%M%S')}_{len(os.listdir(folder))}{ext}")
            f.save(dest)

    # Recompute encoding from all images in folder
    all_imgs = [
        os.path.join(folder, x)
        for x in os.listdir(folder)
        if x.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    ]
    enc_blob = row["face_encoding"]
    if all_imgs:
        avg = average_encoding_from_folder(all_imgs)
        if avg is not None:
            enc_blob = encoding_to_blob(avg)

    if new_password:
        conn.execute(
            """
            UPDATE students SET full_name=?, department=?, semester=?, password=?, face_encoding=?
            WHERE id=?
            """,
            (full_name, department, semester, generate_password_hash(new_password), enc_blob, sid),
        )
    else:
        conn.execute(
            """
            UPDATE students SET full_name=?, department=?, semester=?, face_encoding=?
            WHERE id=?
            """,
            (full_name, department, semester, enc_blob, sid),
        )
    conn.commit()
    conn.close()
    flash("Student updated.", "success")
    return redirect(url_for("admin.students_list"))


@admin_bp.route("/students/delete/<int:sid>", methods=["POST"])
@admin_required
def students_delete(sid):
    conn = get_db()
    row = conn.execute("SELECT usn FROM students WHERE id=?", (sid,)).fetchone()
    if row:
        conn.execute("DELETE FROM students WHERE id=?", (sid,))
        conn.commit()
    conn.close()
    if row:
        folder = os.path.join(Config.DATASET_FOLDER, _safe_usn_folder(row["usn"]))
        if os.path.isdir(folder):
            for fn in os.listdir(folder):
                try:
                    os.remove(os.path.join(folder, fn))
                except OSError:
                    pass
            try:
                os.rmdir(folder)
            except OSError:
                pass
    flash("Student removed.", "success")
    return redirect(url_for("admin.students_list"))


@admin_bp.route("/subjects", methods=["GET", "POST"])
@admin_required
def subjects():
    conn = get_db()
    if request.method == "POST":
        code = (request.form.get("subject_code") or "").strip()
        name = (request.form.get("subject_name") or "").strip()
        if code and name:
            conn.execute(
                "INSERT INTO subjects (subject_code, subject_name) VALUES (?, ?)",
                (code, name),
            )
            conn.commit()
            flash("Subject added.", "success")
    rows = conn.execute("SELECT * FROM subjects ORDER BY subject_code").fetchall()
    conn.close()
    return render_template("admin/subjects.html", subjects=rows)


@admin_bp.route("/subjects/delete/<int:sid>", methods=["POST"])
@admin_required
def subjects_delete(sid):
    conn = get_db()
    conn.execute("DELETE FROM subjects WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    flash("Subject deleted.", "warning")
    return redirect(url_for("admin.subjects"))


@admin_bp.route("/schedule")
@admin_required
def schedule_list():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT c.*, s.subject_name, s.subject_code
        FROM classes c
        JOIN subjects s ON s.id = c.subject_id
        ORDER BY c.class_date DESC, c.start_time
        """
    ).fetchall()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY subject_name").fetchall()
    conn.close()
    return render_template("admin/schedule.html", classes=rows, subjects=subjects, edit_row=None)


@admin_bp.route("/schedule/edit/<int:cid>")
@admin_required
def schedule_edit(cid):
    conn = get_db()
    edit_row = conn.execute(
        """
        SELECT c.*, s.subject_name FROM classes c
        JOIN subjects s ON s.id = c.subject_id WHERE c.id = ?
        """,
        (cid,),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT c.*, s.subject_name, s.subject_code
        FROM classes c JOIN subjects s ON s.id = c.subject_id
        ORDER BY c.class_date DESC, c.start_time
        """
    ).fetchall()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY subject_name").fetchall()
    conn.close()
    if not edit_row:
        flash("Class not found.", "error")
        return redirect(url_for("admin.schedule_list"))
    return render_template(
        "admin/schedule.html", classes=rows, subjects=subjects, edit_row=edit_row
    )


@admin_bp.route("/schedule/add", methods=["POST"])
@admin_required
def schedule_add():
    subject_id = int(request.form.get("subject_id") or 0)
    department = (request.form.get("department") or "").strip()
    semester = int(request.form.get("semester") or 0)
    class_date = (request.form.get("class_date") or "").strip()
    start_time = (request.form.get("start_time") or "").strip()
    end_time = (request.form.get("end_time") or "").strip()
    admin_id = session.get("admin_id")
    conn = get_db()
    conn.execute(
        """
        INSERT INTO classes (subject_id, department, semester, class_date, start_time, end_time, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (subject_id, department, semester, class_date, start_time, end_time, admin_id),
    )
    conn.commit()
    conn.close()
    flash("Class scheduled.", "success")
    return redirect(url_for("admin.schedule_list"))


@admin_bp.route("/schedule/update/<int:cid>", methods=["POST"])
@admin_required
def schedule_update(cid):
    subject_id = int(request.form.get("subject_id") or 0)
    department = (request.form.get("department") or "").strip()
    semester = int(request.form.get("semester") or 0)
    class_date = (request.form.get("class_date") or "").strip()
    start_time = (request.form.get("start_time") or "").strip()
    end_time = (request.form.get("end_time") or "").strip()
    conn = get_db()
    conn.execute(
        """
        UPDATE classes SET subject_id=?, department=?, semester=?, class_date=?, start_time=?, end_time=?
        WHERE id=?
        """,
        (subject_id, department, semester, class_date, start_time, end_time, cid),
    )
    conn.commit()
    conn.close()
    flash("Class updated.", "success")
    return redirect(url_for("admin.schedule_list"))


@admin_bp.route("/schedule/delete/<int:cid>", methods=["POST"])
@admin_required
def schedule_delete(cid):
    conn = get_db()
    conn.execute("DELETE FROM attendance WHERE class_id=?", (cid,))
    conn.execute("DELETE FROM classes WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    flash("Class and related attendance removed.", "warning")
    return redirect(url_for("admin.schedule_list"))


@admin_bp.route("/")
@admin_required
def admin_index():
    return redirect(url_for("admin.dashboard"))


def _attendance_query(conn, filters):
    """
    Build filtered attendance list joined with student, subject, class.
    filters: dict with optional keys subject_id, student_id, date, department, semester, class_id
    """
    sql = """
        SELECT a.*,
               st.usn, st.full_name, st.department, st.semester,
               s.subject_name, s.subject_code,
               c.class_date, c.start_time, c.end_time
        FROM attendance a
        JOIN students st ON st.id = a.student_id
        JOIN subjects s ON s.id = a.subject_id
        JOIN classes c ON c.id = a.class_id
        WHERE 1=1
    """
    params = []
    if filters.get("subject_id"):
        sql += " AND a.subject_id = ?"
        params.append(int(filters["subject_id"]))
    if filters.get("student_id"):
        sql += " AND a.student_id = ?"
        params.append(int(filters["student_id"]))
    if filters.get("date"):
        sql += " AND c.class_date = ?"
        params.append(filters["date"])
    if filters.get("department"):
        sql += " AND st.department = ?"
        params.append(filters["department"])
    if filters.get("semester"):
        sql += " AND st.semester = ?"
        params.append(int(filters["semester"]))
    if filters.get("class_id"):
        sql += " AND a.class_id = ?"
        params.append(int(filters["class_id"]))
    sql += " ORDER BY a.attendance_time DESC"
    return conn.execute(sql, params).fetchall()


@admin_bp.route("/attendance")
@admin_required
def attendance_records():
    conn = get_db()
    f = {
        "subject_id": request.args.get("subject_id") or None,
        "student_id": request.args.get("student_id") or None,
        "date": request.args.get("date") or None,
        "department": request.args.get("department") or None,
        "semester": request.args.get("semester") or None,
        "class_id": request.args.get("class_id") or None,
    }
    rows = _attendance_query(conn, f)
    subjects = conn.execute("SELECT * FROM subjects ORDER BY subject_name").fetchall()
    students = conn.execute(
        "SELECT id, usn, full_name FROM students ORDER BY usn"
    ).fetchall()
    classes = conn.execute(
        """
        SELECT c.id, c.class_date, c.start_time, c.end_time, s.subject_name
        FROM classes c JOIN subjects s ON s.id = c.subject_id
        ORDER BY c.class_date DESC, c.start_time DESC
        LIMIT 200
        """
    ).fetchall()
    conn.close()
    return render_template(
        "admin/attendance.html",
        rows=rows,
        subjects=subjects,
        students=students,
        classes=classes,
        filters=f,
    )


@admin_bp.route("/attendance/edit/<int:aid>", methods=["POST"])
@admin_required
def attendance_edit(aid):
    status = (request.form.get("status") or "Present").strip()
    when = (request.form.get("attendance_time") or "").strip()
    if when:
        when = when.replace("T", " ")
        if len(when) == 16:
            when += ":00"
    else:
        when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    conn.execute(
        "UPDATE attendance SET status=?, attendance_time=? WHERE id=?",
        (status, when, aid),
    )
    conn.commit()
    conn.close()
    flash("Attendance record updated.", "success")
    return redirect(url_for("admin.attendance_records"))


@admin_bp.route("/attendance/delete/<int:aid>", methods=["POST"])
@admin_required
def attendance_delete(aid):
    conn = get_db()
    conn.execute("DELETE FROM attendance WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    flash("Attendance record deleted.", "warning")
    return redirect(url_for("admin.attendance_records"))


@admin_bp.route("/attendance/manual", methods=["POST"])
@admin_required
def attendance_manual():
    student_id = int(request.form.get("student_id") or 0)
    class_id = int(request.form.get("class_id") or 0)
    status = (request.form.get("status") or "Present").strip()
    conn = get_db()
    crow = conn.execute(
        "SELECT subject_id FROM classes WHERE id=?", (class_id,)
    ).fetchone()
    if not crow:
        conn.close()
        flash("Invalid class.", "error")
        return redirect(url_for("admin.attendance_records"))
    subject_id = crow["subject_id"]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute(
            """
            INSERT INTO attendance (student_id, class_id, subject_id, attendance_time, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (student_id, class_id, subject_id, ts, status),
        )
        conn.commit()
        flash("Manual attendance saved.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Could not add (duplicate for this class?): {e}", "error")
    conn.close()
    return redirect(url_for("admin.attendance_records"))


@admin_bp.route("/reports")
@admin_required
def reports():
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    daily = conn.execute(
        """
        SELECT substr(a.attendance_time,1,10) AS d,
               COUNT(*) AS total,
               SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) AS present_cnt
        FROM attendance a
        GROUP BY substr(a.attendance_time,1,10)
        ORDER BY d DESC
        LIMIT 30
        """
    ).fetchall()

    by_subject = conn.execute(
        """
        SELECT s.subject_name,
               COUNT(a.id) AS total,
               SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) AS present_cnt
        FROM subjects s
        LEFT JOIN attendance a ON a.subject_id = s.id
        GROUP BY s.id
        ORDER BY s.subject_name
        """
    ).fetchall()

    by_dept = conn.execute(
        """
        SELECT st.department,
               COUNT(a.id) AS total,
               SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) AS present_cnt
        FROM students st
        LEFT JOIN attendance a ON a.student_id = st.id
        GROUP BY st.department
        """
    ).fetchall()

    conn.close()
    return render_template(
        "admin/reports.html",
        daily=daily,
        by_subject=by_subject,
        by_dept=by_dept,
        today=today,
    )


@admin_bp.route("/export")
@admin_required
def export_data():
    fmt = request.args.get("format")
    if not fmt:
        return render_template("admin/export.html")
    fmt = fmt.lower()
    conn = get_db()
    rows = conn.execute(
        """
        SELECT st.full_name, st.usn, s.subject_name, st.department, st.semester,
               c.class_date, c.start_time, c.end_time, a.attendance_time, a.status
        FROM attendance a
        JOIN students st ON st.id = a.student_id
        JOIN subjects s ON s.id = a.subject_id
        JOIN classes c ON c.id = a.class_id
        ORDER BY a.attendance_time
        """
    ).fetchall()
    conn.close()

    headers = [
        "Student Name",
        "Roll Number",
        "Subject",
        "Department",
        "Semester",
        "Class Date",
        "Start Time",
        "End Time",
        "Attendance Time",
        "Status",
    ]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "xlsx":
        try:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = "Attendance"
            ws.append(headers)
            for r in rows:
                ws.append(
                    [
                        r["full_name"],
                        r["usn"],
                        r["subject_name"],
                        r["department"],
                        r["semester"],
                        r["class_date"],
                        r["start_time"],
                        r["end_time"],
                        r["attendance_time"],
                        r["status"],
                    ]
                )
            bio = BytesIO()
            wb.save(bio)
            bio.seek(0)
            return send_file(
                bio,
                as_attachment=True,
                download_name=f"attendance_{stamp}.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except ImportError:
            flash("openpyxl not installed — downloaded CSV instead.", "warning")
            fmt = "csv"

    si = StringIO()
    w = csv.writer(si)
    w.writerow(headers)
    for r in rows:
        w.writerow(
            [
                r["full_name"],
                r["usn"],
                r["subject_name"],
                r["department"],
                r["semester"],
                r["class_date"],
                r["start_time"],
                r["end_time"],
                r["attendance_time"],
                r["status"],
            ]
        )
    mem = BytesIO(si.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(
        mem,
        as_attachment=True,
        download_name=f"attendance_{stamp}.csv",
        mimetype="text/csv",
    )
