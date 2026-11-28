"""Pure VanoHub comment-envelope parser and 3D position decoder for CVAT issues."""

from __future__ import annotations

import math
import re
from typing import Any

from accounts.datetime_utils import PG_INT32_MAX

NEW_ISSUE_PREFIX_RE = re.compile(
    r"^\[(?P<code>E[1-6]|[A-Z]{3}-[A-Z0-9]{2,8})\](?:\[(?P<severity>critical|major|minor)\])?"
    r"(?:\[REF:(?P<ref>[^\]\r\n]+)\])?\s*"
)
FRAMES_TAG_RE = re.compile(r"\[FRAMES:(\d+)-(\d+)\]")
PARAMS_TAG_RE = re.compile(r"\[PARAMS:([^\]\r\n]+)\]")
DISPUTE_WORD_RE = re.compile(r"\bdispute(?:d)?\b", re.IGNORECASE)

TAXONOMY_SEVERITY_FLOOR: dict[str, str] = {
    "CLS-UNK": "major",
    "CLS-UNCL": "major",
    "EXI-MISS": "major",
    "GEO-HDG": "major",
    "E1": "major",
    "E2": "major",
    "E3": "major",
    "E4": "minor",
    "E5": "major",
    "E6": "major",
}
SEV_RANK: dict[str, int] = {"minor": 1, "major": 2, "critical": 3}


def infer_primary_category(defect_code: str) -> str:
    """Infer primary category E1..E6 from a typed defect code, or '' when untyped/unknown."""
    c = (defect_code or "").strip().upper()
    if not c:
        return ""
    if len(c) >= 2 and c[0] == "E" and c[1] in "123456" and (len(c) == 2 or not c[2].isdigit()):
        return c[:2]
    if c.startswith(("EXI-MISS", "BDD_MISSED")):
        return "E1"
    if c.startswith(("CLS-ATTR", "ATR-", "OCC-", "DMS_OCC")):
        return "E5"
    if c.startswith(("CLS-", "BDD_INVALID_TAXONOMY")):
        return "E2"
    if c.startswith(("GEO-", "BDD_BOX", "DMS_003", "DMS_004", "DMS_005", "DMS_007", "DMS_008", "DMS_010")):
        return "E3"
    if c.startswith(("EXI-", "BDD_DUPLICATE")):
        return "E4"
    if c.startswith(("TRK-", "DMS_001", "DMS_002", "DMS_006")):
        return "E6"
    return ""


def parse_params(msg: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in PARAMS_TAG_RE.finditer(msg or ""):
        for token in re.split(r"[;&]", match.group(1).strip()):
            if "=" in token:
                key, val = token.split("=", 1)
                if key.strip() and val.strip():
                    out[key.strip()] = val.strip()
    return out


def parse_envelope(msg: str) -> dict[str, Any]:
    """Parse optional structured VanoHub comment envelope; degrade cleanly for plain CVAT issues."""
    s = (msg or "").strip()
    match = NEW_ISSUE_PREFIX_RE.match(s)
    params = parse_params(s)
    if not match:
        return {
            "typed": False,
            "code": "",
            "sub_code": "",
            "eff_code": "",
            "primary_category": "",
            "severity": "minor",
            "ref": "",
            "params": params,
            "clean_message": s,
            "frames_span": None,
        }
    code = match.group("code").upper()
    raw_sev = match.group("severity")
    ref = (match.group("ref") or "").strip()
    sub_code = params.get("sub_code", "").strip().upper()
    eff_code = sub_code or code
    primary_category = infer_primary_category(eff_code) or infer_primary_category(code)
    floor_sev = (
        TAXONOMY_SEVERITY_FLOOR.get(eff_code)
        or TAXONOMY_SEVERITY_FLOOR.get(code)
        or TAXONOMY_SEVERITY_FLOOR.get(primary_category)
        or "minor"
    )
    severity = raw_sev if raw_sev is not None and SEV_RANK[raw_sev] >= SEV_RANK[floor_sev] else floor_sev
    body = PARAMS_TAG_RE.sub("", FRAMES_TAG_RE.sub("", s[match.end() :])).strip()
    frames_match = FRAMES_TAG_RE.search(s)
    span: tuple[int, int] | None = None
    if frames_match:
        f_start = int(frames_match.group(1))
        f_end = int(frames_match.group(2))
        if 0 <= f_start <= f_end <= PG_INT32_MAX:
            span = (f_start, f_end)
    return {
        "typed": True,
        "code": code,
        "sub_code": sub_code,
        "eff_code": eff_code,
        "primary_category": primary_category,
        "severity": severity,
        "ref": ref,
        "params": params,
        "clean_message": body,
        "frames_span": span,
    }


def should_skip_preqc(env: dict[str, Any]) -> bool:
    """Return True if envelope denotes an automated pre-QC finding that must not enter JobIssue."""
    ref = str(env.get("ref") or "").lower()
    if ref.startswith(("preqc:", "preqc_external:", "auto:")):
        return True
    params = env.get("params")
    return bool(ref and isinstance(params, dict) and params.get("tool"))


def decode_3d_position(pos: Any) -> tuple[list[float], int | None, int | None]:
    """Validate finite numeric CVAT position and decode optional 3D (track_id, shape_id)."""
    if not isinstance(pos, list):
        raise ValueError("CVAT position must be a list")
    clean: list[float] = []
    for val in pos:
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            raise ValueError("Non-finite float in CVAT position")
        clean.append(float(val))
    if not clean:
        raise ValueError("Empty CVAT position")
    if len(clean) != 16 or any(clean[i] != 0.0 for i in range(12, 16)):
        return clean, None, None

    def _slot(val: float) -> int | None:
        if val <= 0 or not val.is_integer():
            return None
        iv = int(val) - 1
        if 1 <= iv <= PG_INT32_MAX:
            return iv
        return None

    tid = _slot(clean[10])
    sid = _slot(clean[11])
    if tid is not None and sid is not None:
        return clean, None, None
    return clean, tid, sid
