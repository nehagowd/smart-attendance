# Smart Attendance System (B.Tech mini project)

Face recognition attendance with **dynamic class scheduling**, a **10-minute marking window** after each class starts, separate **admin** and **student** portals, and **SQLite** storage.

## Features (summary)

- Admin login, dashboard, CRUD for students, subjects, and scheduled classes  
- Student login (USN + password = full name as stored by admin)  
- Face encodings from webcam photos (`dataset/<USN>/`): uses **`face_recognition` (dlib)** when installed; otherwise an **OpenCV Haar + patch vector** fallback so Windows works without compiling `dlib`  
- Attendance only for the student’s **department + semester**, only when a class is **live**, only in the **first 10 minutes** (student self-scan)  
- **Admin Live Scan** (`/admin/live-scan`): webcam + choose which class is in session; matches any registered student in that class’s department/semester and marks present during the 10-minute window (same duplicate rules).  
- Duplicate prevention (`UNIQUE(student_id, class_id)`), manual attendance, filters, CSV/Excel export, reports  

## Tech stack

- Python 3.10+ (recommended), Flask, SQLite  
- **OpenCV** (required) + optional **`face_recognition`** (dlib) for higher-quality 128-D embeddings  
- HTML / CSS / JavaScript  

## Quick start

1. **Create a virtual environment (recommended)**

   ```powershell
   cd "path\to\Smart attendance"
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. **Install dependencies**

   ```powershell
   pip install -r requirements.txt
   ```

   Optional (better face accuracy, needs working **dlib**):

   ```powershell
   pip install -r requirements-optional-face.txt
   ```

   **Windows / `dlib`:** If `pip install face_recognition` fails, you can **skip it** — the app uses an **OpenCV-only** face model automatically. For better accuracy in demos, install `dlib` via **Conda** (`conda install -c conda-forge dlib`) then `pip install face_recognition`, or use a trusted **pre-built dlib wheel** for your Python version.

   If students were registered with dlib embeddings and you later run **without** `face_recognition`, they must be **re-captured** once in admin so embeddings match the OpenCV backend.

3. **Run the application**

   ```powershell
   python app.py
   ```

   Open **http://127.0.0.1:5000/** in your browser.

4. **Default admin**

   - Username: `admin`  
   - Password: `admin123`  

   Change the password in production (replace hash in DB or add a change-password screen).

## Optional demo data

Creates a **Java** class for **today** (14:00–15:00) for **CSE**, semester **5**, and a demo student **1MS21CS000** / password **`Demo Student`** (no face encoding until you add photos in admin):

```powershell
python sample_data.py
```

Adjust department/semester/time in **Admin → Schedule Class** to match your test student.

## Folder layout

| Path | Purpose |
|------|--------|
| `app.py` | Flask entry |
| `config.py` | Paths, secret key, tolerance, 10-minute window |
| `models/db.py` | SQLite schema + default admin/subjects |
| `routes/` | `auth`, `admin`, `student`, `api` blueprints |
| `utils/face_utils.py` | Encodings, matching |
| `utils/attendance_rules.py` | Active class + 10-minute window |
| `templates/` | HTML (admin + student) |
| `static/` | CSS / JS |
| `dataset/` | Per-student face images |
| `attendance/exports/` | (Reserved) exports are generated in memory |

## Database (SQLite file: `smart_attendance.db`)

Tables: `admins`, `subjects`, `students`, `classes`, `attendance` — relationships match your specification (`subject_id`, `class_id`, `student_id`, `UNIQUE(student_id, class_id)`).

## Security notes (viva talking points)

- Passwords hashed with Werkzeug (`generate_password_hash` / `check_password_hash`).  
- Admin and student areas use separate session keys (`admin_id` vs `student_id`).  
- Students have **no** admin routes; all admin URLs use `@admin_required`.  
- For a real deployment: HTTPS, strong `SECRET_KEY`, CSRF tokens, rate limiting, and audited admin actions.

## MySQL (optional)

The project uses SQLite by default. To use MySQL, you would replace `get_db()` with a connection pool (for example Flask–MySQLdb or SQLAlchemy), translate `?` placeholders to `%s`, and run the same schema as in `models/db.py`.

## Viva tips

1. Show **scheduling** a class for today and how the UI shows **window open vs closed**.  
2. Register a student with **3–5 frontal photos** under good light.  
3. Demo **student login → Mark Attendance** within the first 10 minutes.  
4. Show **duplicate** prevention by scanning twice.  
5. Show **export CSV** and **reports** on the admin side.
