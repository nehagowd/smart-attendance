"""
sample_data.py — Optional demo rows for viva (run once from project root).

Creates:
- One class for TODAY: CSE, Semester 5, Java (18CS51), 14:00–15:00
- Demo student: USN 1MS21CS000, password = full name \"Demo Student\" (add face via admin)

Usage (from project folder):
    python sample_data.py
"""
from datetime import datetime

from werkzeug.security import generate_password_hash

from models.db import get_db, init_db


def main():
    init_db()
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    sub = conn.execute(
        "SELECT id FROM subjects WHERE subject_code = ?", ("18CS51",)
    ).fetchone()
    if not sub:
        print("No subject 18CS51 — start the app once to create default subjects.")
        conn.close()
        return
    sid = sub["id"]
    admin = conn.execute("SELECT id FROM admins LIMIT 1").fetchone()
    aid = admin["id"] if admin else None

    exists = conn.execute(
        """
        SELECT id FROM classes WHERE class_date = ? AND department = ? AND semester = ?
        AND start_time = ? AND subject_id = ?
        """,
        (today, "CSE", 5, "14:00", sid),
    ).fetchone()
    if not exists:
        conn.execute(
            """
            INSERT INTO classes (subject_id, department, semester, class_date, start_time, end_time, created_by)
            VALUES (?, 'CSE', 5, ?, '14:00', '15:00', ?)
            """,
            (sid, today, aid),
        )
        conn.commit()
        print(f"Inserted demo class: {today} 14:00–15:00 CSE Sem 5 (Java).")
    else:
        print("Demo class for today already exists — skipped.")

    try:
        conn.execute(
            """
            INSERT INTO students (usn, full_name, password, department, semester, face_encoding)
            VALUES (?, ?, ?, 'CSE', 5, NULL)
            """,
            ("1MS21CS000", "Demo Student", generate_password_hash("Demo Student")),
        )
        conn.commit()
        print("Added demo student USN=1MS21CS000, password=Demo Student (add face photos in admin).")
    except Exception as e:
        print("Demo student:", e)

    conn.close()


if __name__ == "__main__":
    main()
