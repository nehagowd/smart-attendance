# routes/auth.py — Admin and student login/logout (separate sessions)
from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from models.db import get_db

auth_bp = Blueprint("auth", __name__)


def admin_required(f):
    """Decorator: only logged-in admin may access the view."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("auth.admin_login"))
        return f(*args, **kwargs)

    return decorated


def student_required(f):
    """Decorator: only logged-in student may access the view."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("student_id"):
            return redirect(url_for("auth.student_login"))
        return f(*args, **kwargs)

    return decorated


@auth_bp.route("/")
def home():
    """Landing page with links to admin and student portals."""
    return render_template("index.html")


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin.dashboard"))
    err = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM admins WHERE username = ?", (username,)
        ).fetchone()
        conn.close()
        if row and check_password_hash(row["password"], password):
            session.clear()
            session["admin_id"] = row["id"]
            session["admin_username"] = row["username"]
            return redirect(url_for("admin.dashboard"))
        err = "Invalid username or password"
    return render_template("admin/login.html", error=err)


@auth_bp.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_username", None)
    return redirect(url_for("auth.admin_login"))


@auth_bp.route("/student/login", methods=["GET", "POST"])
def student_login():
    if session.get("student_id"):
        return redirect(url_for("student.student_dashboard"))
    err = None
    if request.method == "POST":
        usn = (request.form.get("usn") or "").strip()
        password = request.form.get("password") or ""
        conn = get_db()
        row = conn.execute("SELECT * FROM students WHERE usn = ?", (usn,)).fetchone()
        conn.close()
        if row and check_password_hash(row["password"], password):
            session.clear()
            session["student_id"] = row["id"]
            session["student_usn"] = row["usn"]
            return redirect(url_for("student.student_dashboard"))
        err = "Invalid USN or Password"
    return render_template("student/login.html", error=err)


@auth_bp.route("/student/logout")
def student_logout():
    session.pop("student_id", None)
    session.pop("student_usn", None)
    return redirect(url_for("auth.student_login"))
