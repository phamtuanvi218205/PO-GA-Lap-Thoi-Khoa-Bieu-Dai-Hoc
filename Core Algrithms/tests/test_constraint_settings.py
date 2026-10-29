"""Cấu hình mềm có tổng bằng 1 ở mỗi tầng và không thay đổi hard constraints."""

from copy import deepcopy

from pydantic import ValidationError
import pytest

from gapo_timetabling.application.constraint_settings import (
    SOFT_CRITERIA,
    ConstraintSettingsService,
    ConstraintSettingsUpdate,
    ConstraintSettingsConflictError,
)


class SettingsConnection:
    def __init__(self):
        self.rows = [
            {
                "constraint_code": code,
                "weight": default,
                "threshold_value": 6 if code == "SOFT_LECTURER_CONSECUTIVE" else None,
                "is_enabled": True,
            }
            for code, (_, _, default) in SOFT_CRITERIA.items()
        ]
        self.committed = self.rolled_back = False
        self.executions = []
        self.description = []

    def cursor(self):
        return self

    def execute(self, sql, *parameters):
        self.executions.append((sql, parameters))
        if sql.startswith("UPDATE"):
            row = next(
                row for row in self.rows if row["constraint_code"] == parameters[2]
            )
            row.update(weight=parameters[0], threshold_value=parameters[1])
        else:
            self.description = [(key,) for key in self.rows[0]]
        return self

    def fetchall(self):
        return [tuple(row.values()) for row in self.rows]

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def update_payload(service):
    result = service.get()
    return {
        "expected_checksum": result["checksum"],
        "settings": [
            {key: item[key] for key in ("constraint_code", "weight", "threshold_value")}
            for item in result["settings"]
        ],
    }


def test_updates_settings_with_optimistic_lock_and_keeps_tier_order():
    connection = SettingsConnection()
    service = ConstraintSettingsService(connection)
    payload = update_payload(service)
    original = payload["expected_checksum"]
    payload["settings"][1]["threshold_value"] = 7
    result = service.update(ConstraintSettingsUpdate.model_validate(payload))
    assert connection.committed
    assert result["checksum"] != original
    assert any("UPDLOCK,HOLDLOCK" in sql for sql, _ in connection.executions)
    assert all(
        "priority_tier" not in sql
        for sql, _ in connection.executions
        if sql.startswith("UPDATE")
    )


def test_rejects_stale_update_before_any_write():
    connection = SettingsConnection()
    service = ConstraintSettingsService(connection)
    payload = update_payload(service)
    payload["expected_checksum"] = "0" * 64
    with pytest.raises(ConstraintSettingsConflictError):
        service.update(ConstraintSettingsUpdate.model_validate(payload))
    assert connection.rolled_back and not connection.committed
    assert not any(sql.startswith("UPDATE") for sql, _ in connection.executions)


@pytest.mark.parametrize(
    "mutation",
    ["hard", "sum", "duplicate", "missing", "threshold", "nan", "zero", "extra"],
)
def test_rejects_unsupported_or_invalid_settings(mutation):
    payload = deepcopy(update_payload(ConstraintSettingsService(SettingsConnection())))
    if mutation == "hard":
        payload["settings"][0]["constraint_code"] = "HARD_ROOM_CAPACITY"
    if mutation == "sum":
        payload["settings"][0]["weight"] = 0.1
    if mutation == "duplicate":
        payload["settings"][1] = payload["settings"][0]
    if mutation == "missing":
        payload["settings"].pop()
    if mutation == "threshold":
        payload["settings"][1]["threshold_value"] = 6.5
    if mutation == "nan":
        payload["settings"][0]["weight"] = float("nan")
    if mutation == "zero":
        payload["settings"][0]["weight"] = 0
    if mutation == "extra":
        payload["settings"][0]["enabled"] = False
    with pytest.raises(ValidationError):
        ConstraintSettingsUpdate.model_validate(payload)
