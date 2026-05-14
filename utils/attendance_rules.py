# utils/attendance_rules.py — active class detection and 10-minute attendance window
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from config import Config


def _parse_time_hhmm(t: str) -> Tuple[int, int]:
    """Parse 'HH:MM' or 'HH:MM:SS' into hour, minute."""
    parts = str(t).strip().split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def _combine_date_time(class_date: str, time_str: str) -> datetime:
    """Build datetime from 'YYYY-MM-DD' and 'HH:MM' (server local time)."""
    d = datetime.strptime(class_date.strip(), "%Y-%m-%d").date()
    h, m = _parse_time_hhmm(time_str)
    return datetime.combine(d, datetime.min.time().replace(hour=h, minute=m, second=0, microsecond=0))


def window_for_class(class_date: str, start_time: str) -> Tuple[datetime, datetime]:
    """
    Attendance allowed from class start until start + ATTENDANCE_WINDOW_MINUTES.
    Returns (window_start, window_end).
    """
    start_dt = _combine_date_time(class_date, start_time)
    end_dt = start_dt + timedelta(minutes=Config.ATTENDANCE_WINDOW_MINUTES)
    return start_dt, end_dt


def is_within_class_duration(now: datetime, class_date: str, start_time: str, end_time: str) -> bool:
    """True if 'now' is between scheduled start and end (inclusive of start, exclusive of end+1min logic simplified)."""
    s = _combine_date_time(class_date, start_time)
    e = _combine_date_time(class_date, end_time)
    return s <= now < e


def is_within_attendance_window(now: datetime, class_date: str, start_time: str) -> bool:
    """True only during first ATTENDANCE_WINDOW_MINUTES after start."""
    w0, w1 = window_for_class(class_date, start_time)
    return w0 <= now < w1


def classify_attendance_state(
    now: datetime,
    class_row: Dict[str, Any],
) -> str:
    """
    Return one of:
    - 'no_window_yet' — before class start
    - 'open' — within first 10 minutes
    - 'closed' — class started but window over (or after window while class still running / ended)
    - 'outside_class' — not on class day or outside scheduled duration
    """
    class_date = class_row["class_date"]
    start_time = class_row["start_time"]
    end_time = class_row["end_time"]

    if not is_within_class_duration(now, class_date, start_time, end_time):
        return "outside_class"

    w0, w1 = window_for_class(class_date, start_time)
    if now < w0:
        return "no_window_yet"
    if w0 <= now < w1:
        return "open"
    return "closed"


def pick_active_class_for_student(
    now: datetime,
    department: str,
    semester: int,
    class_rows: list,
) -> Optional[Dict[str, Any]]:
    """
    From pre-filtered rows (same date as 'now'), pick the class that is currently
    in session for this department + semester. If multiple overlap (should not), first match wins.
    """
    today = now.strftime("%Y-%m-%d")
    for row in class_rows:
        r = dict(row)
        if r.get("class_date") != today:
            continue
        if str(r.get("department", "")).strip().lower() != str(department).strip().lower():
            continue
        if int(r.get("semester", -1)) != int(semester):
            continue
        if is_within_class_duration(now, r["class_date"], r["start_time"], r["end_time"]):
            return r
    return None


def classes_currently_in_session(now: datetime, class_rows: list) -> list:
    """
    Return all scheduled classes (as dicts) that are on today's date and
    currently between start_time and end_time (class is "in session").
    """
    today = now.strftime("%Y-%m-%d")
    out = []
    for row in class_rows:
        r = dict(row) if not isinstance(row, dict) else row.copy()
        if r.get("class_date") != today:
            continue
        if is_within_class_duration(now, r["class_date"], r["start_time"], r["end_time"]):
            out.append(r)
    return out
