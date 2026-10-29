"""Cấu hình các tiêu chí mềm cho những snapshot được tạo sau thời điểm lưu.

Các hard constraint và thứ tự ưu tiên hai tầng không thể tắt qua API. Cấu
hình trong snapshot/run cũ là bất biến; chỉnh cấu hình không sửa kết quả cũ.
"""

from __future__ import annotations

from hashlib import sha256
from math import isclose

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .database import ConnectionProtocol, fetch_all_dicts
from ..core.snapshot import canonical_json

SOFT_CRITERIA = {
    "SOFT_LECTURER_GAP": ("Khoảng trống giảng viên", 2, 0.3720),
    "SOFT_LECTURER_CONSECUTIVE": ("Dạy liên tục vượt ngưỡng", 2, 0.1487),
    "SOFT_ROOM_DISCOURAGED": ("Khung giờ phòng hạn chế sử dụng", 2, 0.2975),
    "SOFT_WORKLOAD_BALANCE": ("Cân bằng tải giảng dạy", 2, 0.1818),
    "SOFT_LECTURER_TIME_PREFERENCE": ("Mong muốn thời gian giảng viên", 3, 0.5),
    "SOFT_COURSE_SUITABILITY": ("Mức phù hợp môn và giảng viên", 3, 0.5),
}


class SoftCriterionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    constraint_code: str
    weight: float = Field(gt=0, le=1, multiple_of=0.0001)
    threshold_value: int | None = Field(default=None, ge=1, le=16)

    @model_validator(mode="after")
    def validate_supported_criterion(self) -> "SoftCriterionInput":
        if self.constraint_code not in SOFT_CRITERIA:
            raise ValueError(
                "Chỉ được sửa sáu tiêu chí mềm đang sử dụng; không được sửa hard constraint."
            )
        needs_threshold = self.constraint_code == "SOFT_LECTURER_CONSECUTIVE"
        if needs_threshold != (self.threshold_value is not None):
            raise ValueError(
                "Chỉ tiêu chí dạy liên tục nhận ngưỡng nguyên từ 1 đến 16."
            )
        return self


class ConstraintSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    settings: list[SoftCriterionInput]

    @model_validator(mode="after")
    def validate_complete_tiers(self) -> "ConstraintSettingsUpdate":
        codes = [item.constraint_code for item in self.settings]
        if len(codes) != len(set(codes)) or set(codes) != set(SOFT_CRITERIA):
            raise ValueError("Phải cung cấp đúng sáu tiêu chí mềm, không trùng mã.")
        for tier in (2, 3):
            total = sum(
                item.weight
                for item in self.settings
                if SOFT_CRITERIA[item.constraint_code][1] == tier
            )
            if not isclose(total, 1.0, rel_tol=0, abs_tol=0.000001):
                raise ValueError(
                    f"Tổng trọng số tầng {tier} phải bằng 1; hiện là {total:.4f}."
                )
        return self


class ConstraintSettingsConflictError(RuntimeError):
    """Cấu hình đã bị sửa bởi một yêu cầu khác hoặc database chưa migration."""


class ConstraintSettingsService:
    def __init__(self, connection: ConnectionProtocol) -> None:
        self.connection = connection

    def get(self, *, for_update: bool = False) -> dict:
        lock = " WITH (UPDLOCK,HOLDLOCK)" if for_update else ""
        rows = fetch_all_dicts(
            self.connection.cursor().execute(
                f"SELECT constraint_code,weight,threshold_value,is_enabled FROM ConstraintSetting{lock} ORDER BY constraint_code"
            )
        )
        indexed = {row["constraint_code"]: row for row in rows}
        settings = []
        for code, (name, tier, _) in SOFT_CRITERIA.items():
            row = indexed.get(code)
            if row is None or not row["is_enabled"]:
                raise ConstraintSettingsConflictError(
                    "Database chưa đồng bộ cấu hình tiêu chí mềm; cần chạy migration 28/10."
                )
            settings.append(
                {
                    "constraint_code": code,
                    "name": name,
                    "priority_tier": tier,
                    "weight": float(row["weight"]),
                    "threshold_value": (
                        None
                        if row["threshold_value"] is None
                        else float(row["threshold_value"])
                    ),
                }
            )
        checksum = sha256(canonical_json(settings).encode("utf-8")).hexdigest()
        return {"settings": settings, "checksum": checksum}

    def update(self, request: ConstraintSettingsUpdate) -> dict:
        try:
            current = self.get(for_update=True)
            if request.expected_checksum != current["checksum"]:
                raise ConstraintSettingsConflictError(
                    "Cấu hình đã thay đổi. Hãy tải lại trước khi lưu."
                )
            for item in request.settings:
                self.connection.cursor().execute(
                    "UPDATE ConstraintSetting SET weight=?,threshold_value=? WHERE constraint_code=? AND constraint_kind='SOFT'",
                    item.weight,
                    item.threshold_value,
                    item.constraint_code,
                )
            result = self.get()
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise
