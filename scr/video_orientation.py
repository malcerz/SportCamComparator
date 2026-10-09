"""Explicitly interpret FFprobe stream rotation and choose pixel filters."""
from __future__ import annotations

import math
import re


def _angle(value):
    try:
        angle = float(value)
        return angle if math.isfinite(angle) else None
    except (TypeError, ValueError):
        return None


def _matrix_angle(displaymatrix):
    """Recover FFmpeg's display rotation from its printed 3x3 16.16 matrix."""
    if not displaymatrix:
        return None
    rows = []
    for line in str(displaymatrix).splitlines():
        match = re.search(r":\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)", line)
        if match:
            rows.append(tuple(int(match.group(i)) for i in range(1, 4)))
    if len(rows) < 2:
        return None
    a, b = rows[0][0], rows[0][1]
    c, d = rows[1][0], rows[1][1]
    norm_a, norm_b = math.hypot(a, c), math.hypot(b, d)
    dot = a * b + c * d
    determinant = a * d - b * c
    # A reflection, shear, or degenerate matrix is not a pure quarter-turn.
    if determinant <= 0 or norm_a == 0 or norm_b == 0:
        return None
    if abs(dot) > max(norm_a * norm_b * 1e-4, 1):
        return None
    return -math.degrees(math.atan2(b, a))


def inspect_orientation(video_stream: dict) -> dict:
    """Return metadata values, a deterministic correction filter, and a reason.

    FFprobe's Display Matrix rotation is preferred over the legacy rotate tag.
    FFmpeg reports this as the display rotation; the explicit transpose is
    counter-clockwise for +90 and clockwise for +270.
    """
    tags = video_stream.get("tags") or {}
    tag_value = tags.get("rotate")
    tag_angle = _angle(tag_value)
    side_data = video_stream.get("side_data_list") or []
    matrix_data = next((item for item in side_data if "displaymatrix" in item.get("side_data_type", "").lower()
                        or "displaymatrix" in item), None)
    matrix_rotation = None
    matrix_present = bool(matrix_data)
    if matrix_data:
        matrix_rotation = _angle(matrix_data.get("rotation"))
        if matrix_rotation is None:
            matrix_rotation = _matrix_angle(matrix_data.get("displaymatrix"))

    if matrix_present and matrix_rotation is None:
        return {
            "rotate_tag": tag_value,
            "displaymatrix_rotation": "UNKNOWN",
            "filter": "",
            "correction": 0,
            "d3d_rotation": 0,
            "normalized": False,
            "decision": "WARN_DISPLAYMATRIX_UNSUPPORTED; no pixel rotation applied",
            "warning": True,
        }

    source = "DISPLAYMATRIX" if matrix_rotation is not None else "ROTATE_TAG" if tag_angle is not None else "NONE"
    angle = matrix_rotation if matrix_rotation is not None else tag_angle
    if angle is None:
        return {
            "rotate_tag": tag_value if tag_value is not None else "NONE",
            "displaymatrix_rotation": "NONE" if not matrix_present else "UNKNOWN",
            "filter": "",
            "correction": 0,
            "d3d_rotation": 0,
            "normalized": True,
            "decision": "NO_ROTATION_METADATA; no pixel rotation applied",
            "warning": False,
        }

    quarter = round(angle / 90.0) * 90
    if abs(angle - quarter) > 0.1:
        return {
            "rotate_tag": tag_value if tag_value is not None else "NONE",
            "displaymatrix_rotation": matrix_rotation if matrix_rotation is not None else "NONE",
            "filter": "",
            "correction": 0,
            "d3d_rotation": 0,
            "normalized": False,
            "decision": f"WARN_UNSUPPORTED_ROTATION_{angle:g}; no pixel rotation applied",
            "warning": True,
        }

    normalized = int(quarter) % 360
    if normalized == 0:
        filter_name = ""
    elif normalized == 180:
        filter_name = "hflip,vflip"
    elif normalized == 90:
        filter_name = "transpose=cclock"
    else:  # 270
        filter_name = "transpose=clock"

    conflicts = tag_angle is not None and matrix_rotation is not None and abs(
        ((tag_angle - matrix_rotation + 180) % 360) - 180
    ) > 0.1
    if conflicts:
        reason = f"WARN_TAG_MATRIX_CONFLICT; using DISPLAYMATRIX_{normalized}"
    elif normalized:
        reason = f"NORMALIZE_{source}_{normalized}; filter={filter_name}"
    else:
        reason = f"NO_ROTATION_{source}; no pixel rotation applied"
    return {
        "rotate_tag": tag_value if tag_value is not None else "NONE",
        "displaymatrix_rotation": matrix_rotation if matrix_rotation is not None else "NONE",
        "filter": filter_name,
        "correction": normalized,
        "d3d_rotation": (-normalized) % 360,
        "normalized": True,
        "decision": reason,
        "warning": conflicts,
    }
