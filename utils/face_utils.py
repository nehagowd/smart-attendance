# utils/face_utils.py — Face embeddings: prefer face_recognition (dlib), else OpenCV fallback (Windows-friendly)
import pickle
from typing import List, Optional, Tuple

import numpy as np

from config import Config


def _face_recognition_module():
    """Return face_recognition module if installed, else None (no hard dependency on dlib)."""
    try:
        import face_recognition

        return face_recognition
    except ImportError:
        return None


def _get_cv2():
    """Lazy import so Flask can start even if OpenCV is not installed yet."""
    try:
        import cv2

        return cv2
    except ImportError as e:
        raise RuntimeError(
            "opencv-python is not installed. Run: pip install opencv-python"
        ) from e


def _bytes_to_numpy_rgb(image_bytes: bytes) -> np.ndarray:
    """Decode image bytes to RGB (numpy)."""
    cv2 = _get_cv2()
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Could not decode image")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _opencv_face_vector_from_rgb(cv2, rgb: np.ndarray) -> Optional[np.ndarray]:
    """
    Haar face detection + 64×64 grayscale patch, L2-normalized (4096-D).
    Used when face_recognition / dlib is not installed (typical on Windows without a wheel).
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
    )
    if faces is None or len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    roi = gray[y : y + h, x : x + w]
    roi = cv2.resize(roi, (64, 64))
    v = roi.astype(np.float64).reshape(-1) / 255.0
    n = np.linalg.norm(v) + 1e-8
    return v / n


def parse_face_blob(blob: bytes) -> Tuple[Optional[str], Optional[np.ndarray]]:
    """
    Decode stored BLOB into (kind, vector).
    kind is 'fr128' (dlib 128-D) or 'ocv' (OpenCV 4096-D). Legacy: raw pickled 128-D array → fr128.
    """
    if not blob:
        return None, None
    obj = pickle.loads(blob)
    if isinstance(obj, dict) and "k" in obj and "v" in obj:
        return str(obj["k"]), np.asarray(obj["v"], dtype=np.float64).reshape(-1)
    if isinstance(obj, np.ndarray):
        flat = obj.astype(np.float64).reshape(-1)
        if flat.size == 128:
            return "fr128", flat
        return "ocv", flat
    return None, None


def encoding_to_blob(enc: np.ndarray) -> bytes:
    """Serialize embedding with a type tag so OpenCV and dlib encodings can coexist."""
    enc = np.asarray(enc, dtype=np.float64).reshape(-1)
    kind = "fr128" if enc.size == 128 else "ocv"
    return pickle.dumps({"k": kind, "v": enc}, protocol=pickle.HIGHEST_PROTOCOL)


def blob_to_encoding(blob: bytes) -> Optional[np.ndarray]:
    """Return raw vector only (backward compatible for callers that only need the array)."""
    _, v = parse_face_blob(blob)
    return v


def compute_encoding_from_bytes(image_bytes: bytes) -> Optional[np.ndarray]:
    """
    Single-face embedding from JPEG/PNG bytes.
    Uses face_recognition when available; otherwise OpenCV Haar + normalized patch vector.
    """
    rgb = _bytes_to_numpy_rgb(image_bytes)
    fr = _face_recognition_module()
    if fr is not None:
        boxes = fr.face_locations(rgb, model="hog")
        if not boxes:
            return None
        encs = fr.face_encodings(rgb, boxes)
        if not encs:
            return None
        return encs[0]

    cv2 = _get_cv2()
    return _opencv_face_vector_from_rgb(cv2, rgb)


def average_encoding_from_folder(image_paths: List[str]) -> Optional[np.ndarray]:
    """Average multiple face embeddings from image files (same backend as compute_encoding_from_bytes)."""
    fr = _face_recognition_module()
    if fr is not None:
        encodings = []
        for path in image_paths:
            try:
                img = fr.load_image_file(path)
                locs = fr.face_locations(img, model="hog")
                if not locs:
                    continue
                enc = fr.face_encodings(img, locs)
                if enc:
                    encodings.append(enc[0])
            except OSError:
                continue
        if not encodings:
            return None
        return np.mean(np.stack(encodings, axis=0), axis=0)

    cv2 = _get_cv2()
    vecs = []
    for path in image_paths:
        try:
            bgr = cv2.imread(path)
            if bgr is None:
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            v = _opencv_face_vector_from_rgb(cv2, rgb)
            if v is not None:
                vecs.append(v)
        except OSError:
            continue
    if not vecs:
        return None
    return np.mean(np.stack(vecs, axis=0), axis=0)


def distance_between(enc_a: np.ndarray, enc_b: np.ndarray) -> float:
    """Euclidean distance (lower = more similar)."""
    return float(np.linalg.norm(enc_a - enc_b))


def encodings_match(enc_a: np.ndarray, enc_b: np.ndarray, tolerance: float = None) -> bool:
    """Same person if distance under tolerance (depends on embedding length)."""
    if enc_a.shape != enc_b.shape:
        return False
    if enc_a.size == 128:
        tol = tolerance if tolerance is not None else Config.FACE_MATCH_TOLERANCE
    else:
        tol = tolerance if tolerance is not None else Config.OPENCV_FACE_MAX_L2
    return distance_between(enc_a, enc_b) <= tol


def best_match_student(
    probe_encoding: np.ndarray,
    students_rows: list,
) -> Tuple[Optional[int], float]:
    """
    Nearest stored embedding among students (only compares same backend: fr128↔fr128, ocv↔ocv).
    """
    probe_kind = "fr128" if probe_encoding.size == 128 else "ocv"
    best_id = None
    best_dist = float("inf")
    for row in students_rows:
        kind, vec = parse_face_blob(row["face_encoding"])
        if kind is None or vec is None or kind != probe_kind:
            continue
        d = distance_between(probe_encoding, vec)
        if d < best_dist:
            best_dist = d
            best_id = row["id"]
    return best_id, best_dist


def match_threshold_for_probe(probe: np.ndarray) -> float:
    """Distance cutoff for live matching (admin kiosk) — same rule as encodings_match."""
    if probe.size == 128:
        return Config.FACE_MATCH_TOLERANCE
    return Config.OPENCV_FACE_MAX_L2
