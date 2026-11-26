"""Strict Pydantic v2 data contracts for external CVAT REST payloads and sync outputs."""

from __future__ import annotations

import math
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

_FRAME_STEP_RE = re.compile(r"step\s*=\s*([1-9]\d*)")


class CvatAboutPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    version: str | None = None


class CvatAssigneePayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    username: str = Field(min_length=1)


class CvatTaskPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    id: int = Field(gt=0)
    name: str = ""
    project_id: int | None = Field(default=None, gt=0)
    status: str = ""
    size: int = Field(default=0, ge=0)
    subset: str = ""


class CvatJobPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    id: int = Field(gt=0)
    type: str = "annotation"
    stage: str = ""
    state: str = ""
    assignee: CvatAssigneePayload | None = None
    frame_count: int | None = Field(default=None, ge=0)
    start_frame: int | None = Field(default=None, ge=0)
    stop_frame: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_frame_bounds(self) -> CvatJobPayload:
        if self.start_frame is not None and self.stop_frame is not None and self.stop_frame < self.start_frame:
            raise ValueError("stop_frame must be greater than or equal to start_frame")
        return self

    @property
    def resolved_frame_count(self) -> int:
        if self.frame_count is not None:
            return self.frame_count
        if self.start_frame is not None and self.stop_frame is not None:
            return self.stop_frame - self.start_frame + 1
        return 0


class CvatJobMetaPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    size: int = Field(default=0, ge=0)
    start_frame: int | None = Field(default=None, ge=0)
    stop_frame: int | None = Field(default=None, ge=0)
    frame_filter: str = ""
    deleted_frames: list[int] = Field(default_factory=list)
    included_frames: list[int] | None = None

    @property
    def frame_step(self) -> int:
        match = _FRAME_STEP_RE.search(self.frame_filter or "")
        return int(match.group(1)) if match else 1

    @property
    def resolved_stop_frame(self) -> int | None:
        if self.stop_frame is not None:
            return self.stop_frame
        if self.size > 0:
            base = self.start_frame or 0
            return base + (self.size - 1) * self.frame_step
        return None


class CvatAnnotationsPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    shapes: list[dict[str, object]] = Field(default_factory=list)
    tracks: list[dict[str, object]] = Field(default_factory=list)

    def count_object_frames(
        self,
        *,
        start_frame: int | None = None,
        stop_frame: int | None = None,
        frame_step: int = 1,
        deleted_frames: list[int] | None = None,
        included_frames: list[int] | None = None,
    ) -> int:
        """Đếm tổng số cuboid/object-frame hợp lệ theo đúng ngữ nghĩa CVAT gốc.

        - Shape đơn lẻ: tính 1 nếu không `outside` và frame nằm trong miền hoạt động.
        - Track: bung khoảng frame từ keyframe không `outside` đến keyframe kế tiếp (hoặc `stop_frame`),
          xét `frame_step` (từ `frame_filter="step=N"`), trừ `deleted_frames` và giao với `included_frames` (nếu có).
        - Nếu track chỉ có fixture tối giản không chứa danh sách `shapes` (keyframe): giữ tương thích đếm 1.
        """
        step = max(1, frame_step)
        base_frame = start_frame or 0
        deleted_set = set(deleted_frames or ())
        included_set = set(included_frames) if included_frames is not None else None

        def _count_range(lo: int, hi: int) -> int:
            if start_frame is not None:
                lo = max(lo, start_frame)
            if stop_frame is not None:
                hi = min(hi, stop_frame)
            if hi < lo:
                return 0
            if included_set is not None:
                return sum(1 for f in included_set if lo <= f <= hi and f not in deleted_set)
            if step == 1:
                deleted_in_range = sum(1 for f in deleted_set if lo <= f <= hi)
                return (hi - lo + 1) - deleted_in_range
            first_valid = base_frame + math.ceil((lo - base_frame) / step) * step
            if first_valid > hi:
                return 0
            total_stepped = ((hi - first_valid) // step) + 1
            deleted_in_range = sum(
                1 for f in deleted_set if first_valid <= f <= hi and (f - base_frame) % step == 0
            )
            return total_stepped - deleted_in_range

        total = 0
        for shape in self.shapes:
            if shape.get("outside") is True:
                continue
            frame = shape.get("frame")
            if isinstance(frame, int) and not isinstance(frame, bool):
                total += _count_range(frame, frame)
            else:
                total += 1

        for track in self.tracks:
            raw_kfs = track.get("shapes")
            if not isinstance(raw_kfs, list):
                total += 1
                continue
            by_frame: dict[int, dict[str, object]] = {}
            for kf in raw_kfs:
                if not isinstance(kf, dict):
                    continue
                frame = kf.get("frame")
                if isinstance(frame, int) and not isinstance(frame, bool):
                    by_frame[frame] = kf
            if not by_frame:
                continue
            ordered_frames = sorted(by_frame)
            for idx, f_start in enumerate(ordered_frames):
                kf = by_frame[f_start]
                if kf.get("outside") is True:
                    continue
                if idx + 1 < len(ordered_frames):
                    f_end = ordered_frames[idx + 1] - 1
                else:
                    f_end = stop_frame if stop_frame is not None else f_start
                total += _count_range(f_start, f_end)
        return total

    @property
    def object_count(self) -> int:
        return self.count_object_frames()


class CvatImportResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    task_name: str | None
    created: int = Field(ge=0)
    updated: int = Field(ge=0)
    total: int = Field(ge=0)


class CvatSyncResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    updated: int = Field(ge=0)
    total: int = Field(ge=0)
