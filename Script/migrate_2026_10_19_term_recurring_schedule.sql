/*
    Migrate an existing development database to the term-recurring schedule.

    - ClassSession remains a weekly occurrence.
    - One optimizer gene is shared by (teaching_plan_id, stability_group_no).
    - Holidays and makeup dates no longer alter the optimization domain.
    - Lecturer/room UNAVAILABLE data remains effective, including DATE scope.
*/

USE testkhoaluan;
GO

BEGIN TRANSACTION;

/*
    Preserve HOLIDAY/MAKEUP_ALLOWED as source-data metadata.  D094 removes their
    effect from encoder/validator logic; it does not require overwriting history
    in an existing database.
*/

IF NOT EXISTS
(
    SELECT 1
    FROM sys.key_constraints
    WHERE name = 'UQ_ClassSession_Plan_Week_Group'
      AND parent_object_id = OBJECT_ID('dbo.ClassSession')
)
BEGIN
    ALTER TABLE ClassSession
    ADD CONSTRAINT UQ_ClassSession_Plan_Week_Group
        UNIQUE (teaching_plan_id, term_code, week_number, stability_group_no);
END;

DELETE FROM ConstraintSetting
WHERE constraint_code IN
(
    'SOFT_TIME_STABILITY',
    'SOFT_TIME_WEEKDAY_STABILITY',
    'SOFT_TIME_START_PERIOD_STABILITY',
    'SOFT_ROOM_STABILITY'
);

UPDATE ConstraintSetting SET weight = 0.4010
WHERE constraint_code = 'SOFT_CAPACITY';
UPDATE ConstraintSetting SET weight = 0.2228
WHERE constraint_code = 'SOFT_LECTURER_GAP';
UPDATE ConstraintSetting SET weight = 0.0891
WHERE constraint_code = 'SOFT_LECTURER_CONSECUTIVE';
UPDATE ConstraintSetting SET weight = 0.1782
WHERE constraint_code = 'SOFT_ROOM_DISCOURAGED';
UPDATE ConstraintSetting SET weight = 0.1089
WHERE constraint_code = 'SOFT_WORKLOAD_BALANCE';

UPDATE ConstraintSetting
SET constraint_name = N'Ngày học thuộc đúng tuần hoạt động',
    note = N'Ngày lễ/học bù không tham gia lọc; ngày thật dùng cho availability DATE'
WHERE constraint_code = 'HARD_VALID_DATE';

COMMIT TRANSACTION;
GO
