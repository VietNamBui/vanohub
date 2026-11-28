"""Strict Pydantic v2 data contracts for external CVAT REST payloads and sync outputs."""

from __future__ import annotations

import math
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_FRAME_STEP_RE = re.compile(r"step\s*=\s*([1-9]\d*)")


def _none_to_empty_str(value: object) -> object:
    return "" if value is None else value


def _none_to_empty_list(value: object) -> object:
    return [] if value is None else value


def _none_to_zero(value: object) -> object:
    return 0 if value is None else value


class CvatAboutPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    version: str | None = None


class CvatAssigneePayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    id: int = Field(gt=0)
    username: str = ""

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        return _none_to_empty_str(value)


class CvatTaskPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    id: int = Field(gt=0)
    name: str = ""
    project_id: int | None = Field(default=None, gt=0)
    status: str = ""
    size: int = Field(default=0, ge=0)
    subset: str = ""

    @field_validator("name", "status", "subset", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> object:
        return _none_to_empty_str(value)

    @field_validator("size", mode="before")
    @classmethod
    def normalize_size(cls, value: object) -> object:
        return _none_to_zero(value)


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

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: object) -> object:
        return "annotation" if value is None else value

    @field_validator("stage", "state", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> object:
        return _none_to_empty_str(value)

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

    @field_validator("size", mode="before")
    @classmethod
    def normalize_size(cls, value: object) -> object:
        return _none_to_zero(value)

    @field_validator("frame_filter", mode="before")
    @classmethod
    def normalize_frame_filter(cls, value: object) -> object:
        return _none_to_empty_str(value)

    @field_validator("deleted_frames", mode="before")
    @classmethod
    def normalize_deleted_frames(cls, value: object) -> object:
        return _none_to_empty_list(value)

    @model_validator(mode="after")
    def validate_frame_bounds(self) -> CvatJobMetaPayload:
        if self.start_frame is not None and self.stop_frame is not None and self.stop_frame < self.start_frame:
            raise ValueError("stop_frame must be greater than or equal to start_frame")
        return self

    @property
    def frame_step(self) -> int:
        match = _FRAME_STEP_RE.search(self.frame_filter or "")
        return int(match.group(1)) if match else 1

    def resolve_stop_frame(self, job_stop_frame: int | None = None) -> int | None:
        if self.stop_frame is not None:
            return self.stop_frame
        if self.included_frames is not None:
            return max(self.included_frames) if self.included_frames else None
        if job_stop_frame is not None:
            return job_stop_frame
        if self.size > 0:
            base = self.start_frame or 0
            return base + (self.size - 1) * self.frame_step
        return None

    @property
    def resolved_stop_frame(self) -> int | None:
        return self.resolve_stop_frame()


class CvatAnnotationsPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    shapes: list[dict[str, object]] = Field(default_factory=list)
    tracks: list[dict[str, object]] = Field(default_factory=list)

    @field_validator("shapes", "tracks", mode="before")
    @classmethod
    def normalize_lists(cls, value: object) -> object:
        return _none_to_empty_list(value)

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
        - `included_frames is None`: không lọc theo danh sách tường minh; `included_frames == []`: khớp 0 frame.
        - Nếu track chỉ có fixture tối giản không chứa danh sách `shapes` (keyframe): giữ tương thích đếm 1
          khi không bị lọc rỗng (`included_frames != []`).
        """
        step = max(1, frame_step)
        base_frame = start_frame or 0
        deleted_set = {f for f in (deleted_frames or ()) if isinstance(f, int) and not isinstance(f, bool)}
        included_set = (
            {f for f in included_frames if isinstance(f, int) and not isinstance(f, bool)}
            if included_frames is not None
            else None
        )
        if included_set is not None and not included_set:
            return 0

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

        has_frame_constraints = (
            start_frame is not None
            or stop_frame is not None
            or included_set is not None
            or step > 1
            or bool(deleted_set)
        )

        total = 0
        for shape in self.shapes:
            if shape.get("outside") is True:
                continue
            frame = shape.get("frame")
            if isinstance(frame, int) and not isinstance(frame, bool):
                total += _count_range(frame, frame)
            elif not has_frame_constraints:
                total += 1

        max_included = max(included_set) if included_set else None
        for track in self.tracks:
            raw_kfs = track.get("shapes")
            if not isinstance(raw_kfs, list):
                if not has_frame_constraints:
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
                elif stop_frame is not None:
                    f_end = stop_frame
                elif max_included is not None:
                    f_end = max(max_included, f_start)
                else:
                    f_end = f_start
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
