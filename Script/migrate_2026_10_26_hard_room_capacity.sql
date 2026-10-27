SET XACT_ABORT ON;
BEGIN TRANSACTION;

/* D109: sức chứa phòng vật lý là điều kiện bắt buộc. */
DELETE FROM ConstraintSetting
WHERE constraint_code = 'SOFT_CAPACITY';

IF EXISTS (
    SELECT 1 FROM ConstraintSetting
    WHERE constraint_code = 'HARD_ROOM_CAPACITY'
)
BEGIN
    UPDATE ConstraintSetting
    SET constraint_name = N'Phòng đủ sức chứa lớp học phần',
        constraint_kind = 'HARD',
        priority_tier = 1,
        weight = NULL,
        threshold_value = NULL,
        is_enabled = 1,
        note = N'Buổi vật lý yêu cầu capacity >= expected_enrollment; dữ liệu thiếu bị chặn ở readiness'
    WHERE constraint_code = 'HARD_ROOM_CAPACITY';
END
ELSE
BEGIN
    INSERT INTO ConstraintSetting
        (constraint_code, constraint_name, constraint_kind, priority_tier,
         weight, threshold_value, is_enabled, note)
    VALUES
        ('HARD_ROOM_CAPACITY', N'Phòng đủ sức chứa lớp học phần', 'HARD', 1,
         NULL, NULL, 1,
         N'Buổi vật lý yêu cầu capacity >= expected_enrollment; dữ liệu thiếu bị chặn ở readiness');
END;

UPDATE ConstraintSetting
SET weight = CASE constraint_code
    WHEN 'SOFT_LECTURER_GAP' THEN 0.3720
    WHEN 'SOFT_LECTURER_CONSECUTIVE' THEN 0.1487
    WHEN 'SOFT_ROOM_DISCOURAGED' THEN 0.2975
    WHEN 'SOFT_WORKLOAD_BALANCE' THEN 0.1818
    ELSE weight
END
WHERE constraint_code IN (
    'SOFT_LECTURER_GAP',
    'SOFT_LECTURER_CONSECUTIVE',
    'SOFT_ROOM_DISCOURAGED',
    'SOFT_WORKLOAD_BALANCE'
);

COMMIT TRANSACTION;
