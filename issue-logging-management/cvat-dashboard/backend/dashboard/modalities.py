from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

VALID_DIMENSIONS = ("3d", "2d")
VALID_FILTER_DIMENSIONS = ("all", "3d", "2d")


@dataclass(frozen=True)
class ModalityProfile:
    dimension: str
    label: str
    short_label: str
    unit_key: str
    unit_label: str
    speed_label: str
    iou_metric_label: str
    drift_hint: str
    default_annotation_type: str
    annotation_types: tuple[str, ...]
    category_labels: dict[str, str]
    geometry_metrics_schema: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILES: dict[str, ModalityProfile] = {
    "3d": ModalityProfile(
        dimension="3d",
        label="3D (LiDAR Cuboid)",
        short_label="3D",
        unit_key="cuboids",
        unit_label="Cuboids",
        speed_label="Cuboids/giờ",
        iou_metric_label="Mean 3D IoU",
        drift_hint="Dịch tâm (m) hoặc góc xoay Yaw (°) vượt ngưỡng",
        default_annotation_type="cuboid",
        annotation_types=("cuboid",),
        category_labels={
            "E1": "E1: Sai lệch Kích thước / Hướng xoay 3D (Geometry & Yaw)",
            "E2": "E2: Báo nhầm vật thể (False Positive / Phantom Box)",
            "E3": "E3: Bỏ sót vật thể (False Negative / Missed Object)",
            "E4": "E4: Thuộc tính sai lệch / Che khuất (Attributes & Occlusion)",
            "E5": "E5: Nhầm lẫn chuỗi di chuyển (Track ID Switch)",
            "E6": "E6: Nhầm phân lớp đối tượng (Classification)",
        },
        geometry_metrics_schema=(
            {"key": "mean_center_shift_m", "label": "Dịch tâm TB", "unit": "m"},
            {"key": "mean_abs_yaw_deg", "label": "Lệch Yaw TB", "unit": "°"},
            {"key": "mean_dl_m", "label": "Lệch dài (dL)", "unit": "m"},
            {"key": "mean_dw_m", "label": "Lệch rộng (dW)", "unit": "m"},
            {"key": "mean_dh_m", "label": "Lệch cao (dH)", "unit": "m"},
            {"key": "honeypot_mean_iou", "label": "Honeypot 3D IoU", "unit": ""},
        ),
    ),
    "2d": ModalityProfile(
        dimension="2d",
        label="2D (BBox / Landmark / Polygon)",
        short_label="2D",
        unit_key="objects",
        unit_label="Objects 2D",
        speed_label="Objects/giờ",
        iou_metric_label="Mean 2D IoU",
        drift_hint="Lệch khung bao (px), tỷ lệ box hoặc landmark vượt ngưỡng",
        default_annotation_type="bbox",
        annotation_types=("bbox", "polygon", "polyline", "skeleton", "points"),
        category_labels={
            "E1": "E1: Sai lệch Khung bao / Landmark / Polygon 2D (Geometry & Fit)",
            "E2": "E2: Dư đối tượng / Trùng khung (False Positive / Duplicate)",
            "E3": "E3: Bỏ sót đối tượng / Landmark (False Negative / Missed)",
            "E4": "E4: Thuộc tính / Trạng thái che khuất (Attributes & Occlusion)",
            "E5": "E5: Nhảy Track ID / Sai thứ tự điểm (Track / Landmark Order)",
            "E6": "E6: Nhầm phân lớp đối tượng (Classification)",
        },
        geometry_metrics_schema=(
            {"key": "mean_iou_2d", "label": "Mean 2D IoU", "unit": ""},
            {"key": "mean_center_shift_px", "label": "Dịch tâm TB", "unit": "px"},
            {"key": "mean_landmark_err_px", "label": "Lệch Landmark TB", "unit": "px"},
            {"key": "out_of_bounds_count", "label": "Vượt biên ảnh", "unit": "boxes"},
            {"key": "honeypot_mean_iou", "label": "Honeypot 2D IoU", "unit": ""},
        ),
    ),
    "all": ModalityProfile(
        dimension="all",
        label="Tất cả (2D & 3D)",
        short_label="All",
        unit_key="items",
        unit_label="Items (2D & 3D)",
        speed_label="Items/giờ",
        iou_metric_label="Mean IoU",
        drift_hint="Sai lệch hình học vượt ngưỡng (3D m/° hoặc 2D px/IoU)",
        default_annotation_type="mixed",
        annotation_types=("cuboid", "bbox", "polygon", "polyline", "skeleton", "points"),
        category_labels={
            "E1": "E1: Sai lệch Hình học (Geometry / Size / Yaw / Fit)",
            "E2": "E2: Báo nhầm / Dư đối tượng (False Positive / Duplicate)",
            "E3": "E3: Bỏ sót đối tượng (False Negative / Missed Object)",
            "E4": "E4: Thuộc tính / Che khuất (Attributes & Occlusion)",
            "E5": "E5: Nhầm chuỗi / Thứ tự (Track ID Switch / Order)",
            "E6": "E6: Nhầm phân lớp đối tượng (Classification)",
        },
        geometry_metrics_schema=(
            {"key": "honeypot_mean_iou", "label": "Honeypot IoU TB", "unit": ""},
        ),
    ),
}


def normalize_dimension(raw: str | None, *, allow_all: bool = True) -> str:
    val = str(raw or "").strip().lower()
    if val in VALID_DIMENSIONS:
        return val
    if allow_all and (val in ("", "all")):
        return "all"
    return "all" if allow_all else "3d"


def default_annotation_type_for(dimension: str) -> str:
    dim = normalize_dimension(dimension, allow_all=False)
    return PROFILES[dim].default_annotation_type


def get_modality_profile(dimension: str | None) -> ModalityProfile:
    dim = normalize_dimension(dimension, allow_all=True)
    return PROFILES[dim]


def all_modality_profiles() -> dict[str, dict[str, Any]]:
    return {k: v.to_dict() for k, v in PROFILES.items()}


def summarize_geometry_metrics(snapshots: Iterable[Any], dimension: str) -> dict[str, Any]:
    """
    Aggregates modality-aware geometry metrics across JobQualitySnapshot rows.
    Reads both legacy 3D columns and flexible `geometry_metrics` JSONField.
    """
    snaps = list(snapshots)
    if not snaps:
        return {}

    dim = normalize_dimension(dimension, allow_all=True)

    def _avg(vals: list[float], digits: int = 3) -> float | None:
        return round(sum(vals) / len(vals), digits) if vals else None

    hp_ious: list[float] = []
    for s in snaps:
        v = s.honeypot_mean_iou if s.honeypot_mean_iou is not None else s.honeypot_mean_iou_3d
        if v is not None:
            hp_ious.append(float(v))

    if dim == "3d":
        return {
            "mean_center_shift_m": _avg([float(s.mean_center_shift_m) for s in snaps], 3),
            "mean_abs_yaw_deg": _avg([float(s.mean_abs_yaw_deg) for s in snaps], 2),
            "mean_dl_m": _avg([float(s.mean_dl_m) for s in snaps], 3),
            "mean_dw_m": _avg([float(s.mean_dw_m) for s in snaps], 3),
            "mean_dh_m": _avg([float(s.mean_dh_m) for s in snaps], 3),
            "honeypot_mean_iou": _avg(hp_ious, 3),
        }

    if dim == "2d":
        iou_2d: list[float] = []
        shift_px: list[float] = []
        lm_px: list[float] = []
        oob_total = 0
        for s in snaps:
            gm = s.geometry_metrics if isinstance(s.geometry_metrics, dict) else {}
            if gm.get("mean_iou_2d") is not None:
                iou_2d.append(float(gm["mean_iou_2d"]))
            if gm.get("mean_center_shift_px") is not None:
                shift_px.append(float(gm["mean_center_shift_px"]))
            if gm.get("mean_landmark_err_px") is not None:
                lm_px.append(float(gm["mean_landmark_err_px"]))
            if gm.get("out_of_bounds_count") is not None:
                oob_total += int(gm["out_of_bounds_count"])
        return {
            "mean_iou_2d": _avg(iou_2d, 3),
            "mean_center_shift_px": _avg(shift_px, 2),
            "mean_landmark_err_px": _avg(lm_px, 2),
            "out_of_bounds_count": oob_total,
            "honeypot_mean_iou": _avg(hp_ious, 3),
        }

    return {
        "honeypot_mean_iou": _avg(hp_ious, 3),
    }
