# models/db.py — SQLite schema, connection helpers, and seed sample data
import os
import sqlite3
from werkzeug.security import generate_password_hash

from config import Config


def get_db():
    """Return a new SQLite connection (row factory enabled for dict-like rows)."""
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(app=None):
    """
    Create all tables if they do not exist.
    Called on application startup.
    """
    os.makedirs(Config.DATASET_FOLDER, exist_ok=True)
    os.makedirs(Config.EXPORT_FOLDER, exist_ok=True)

    conn = get_db()
    cur = conn.cursor()

    # --- admins: system administrators ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        """
    )

    # --- subjects: master list of subjects ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_code TEXT NOT NULL,
            subject_name TEXT NOT NULL
        );
        """
    )

    # --- students: registered learners + optional averaged face encoding blob ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usn TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            password TEXT NOT NULL,
            department TEXT NOT NULL,
            semester INTEGER NOT NULL,
            face_encoding BLOB
        );
        """
    )

    # --- classes: dynamically scheduled sessions ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            department TEXT NOT NULL,
            semester INTEGER NOT NULL,
            class_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            created_by INTEGER,
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            FOREIGN KEY (created_by) REFERENCES admins(id)
        );
        """
    )

    # --- attendance: one row per student per class (UNIQUE prevents duplicates) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            attendance_time TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (class_id) REFERENCES classes(id),
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            UNIQUE(student_id, class_id)
        );
        """
    )

    conn.commit()

    # Seed default admin + sample subjects if empty (good for viva demo)
    cur.execute("SELECT COUNT(*) AS c FROM admins")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO admins (username, password) VALUES (?, ?)",
            ("admin", generate_password_hash("admin123")),
        )

    cur.execute("SELECT COUNT(*) AS c FROM subjects")
    if cur.fetchone()["c"] == 0:
        samples = [
            ("18CS51", "Programming Using Java"),
            ("18CS52", "Data Structures"),
            ("18CS53", "Database Management Systems"),
        ]
        cur.executemany(
            "INSERT INTO subjects (subject_code, subject_name) VALUES (?, ?)",
            samples,
        )

    conn.commit()
    conn.close()

    if app:
        app.logger.info("Database initialized at %s", Config.DATABASE_PATH)
