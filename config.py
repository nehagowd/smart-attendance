# config.py — Application configuration (paths, secret key, database URI)
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Flask configuration for Smart Attendance System."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-this-in-production-mini-project")
    DATABASE_PATH = os.path.join(BASE_DIR, "smart_attendance.db")
    DATASET_FOLDER = os.path.join(BASE_DIR, "dataset")
    EXPORT_FOLDER = os.path.join(BASE_DIR, "attendance", "exports")

    # face_recognition tolerance: lower = stricter match (typical 0.5–0.6)
    FACE_MATCH_TOLERANCE = 0.55
    # OpenCV fallback (no dlib): max L2 on normalized 64×64 face vectors
    OPENCV_FACE_MAX_L2 = 32.0
    # First N minutes after class start when attendance is allowed
    ATTENDANCE_WINDOW_MINUTES = 10
