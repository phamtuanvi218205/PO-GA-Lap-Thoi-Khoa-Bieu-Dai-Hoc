/*
   Non-destructive migration for the local development database.

   It synchronizes changes that already exist in Script/script.sql without
   dropping project tables or sample data:
   - OptimizationRun.snapshot_checksum and its validation constraint;
   - D088 trigger: one lecturer per CourseSection;
   - D092 normalized Q_general weights.

   The checksum backfill uses UTF-8 bytes so it follows the Java/Python
   snapshot checksum contract instead of SQL Server's UTF-16 NVARCHAR bytes.
*/

USE testkhoaluan;
GO

IF COL_LENGTH('dbo.OptimizationRun', 'snapshot_checksum') IS NULL
BEGIN
    ALTER TABLE dbo.OptimizationRun
        ADD snapshot_checksum CHAR(64) NULL;
END;
GO

/*
   SQL Server compiles column references for a batch before executing its IF.
   Keeping the ADD COLUMN in the previous batch makes this migration work both
   before and after the column already exists.
*/
SET XACT_ABORT ON;
BEGIN TRANSACTION;

UPDATE dbo.OptimizationRun
SET snapshot_checksum = LOWER(
    CONVERT(
        VARCHAR(64),
        HASHBYTES(
            'SHA2_256',
            CONVERT(
                VARBINARY(MAX),
                CONVERT(
                    VARCHAR(MAX),
                    snapshot_json COLLATE Latin1_General_100_BIN2_UTF8
                )
            )
        ),
        2
    )
)
WHERE snapshot_checksum IS NULL;

IF EXISTS
(
    SELECT 1
    FROM sys.columns
    WHERE object_id = OBJECT_ID('dbo.OptimizationRun')
      AND name = 'snapshot_checksum'
      AND is_nullable = 1
)
BEGIN
    ALTER TABLE dbo.OptimizationRun
        ALTER COLUMN snapshot_checksum CHAR(64) NOT NULL;
END;

IF OBJECT_ID('dbo.CK_OptimizationRun_SnapshotChecksum', 'C') IS NULL
BEGIN
    ALTER TABLE dbo.OptimizationRun
        ADD CONSTRAINT CK_OptimizationRun_SnapshotChecksum
        CHECK
        (
            LEN(snapshot_checksum) = 64
            AND LOWER(snapshot_checksum) NOT LIKE '%[^0-9a-f]%'
        );
END;

UPDATE dbo.ConstraintSetting
SET weight = CASE constraint_code
        WHEN 'SOFT_CAPACITY' THEN 0.4091
        WHEN 'SOFT_LECTURER_GAP' THEN 0.2273
        WHEN 'SOFT_LECTURER_CONSECUTIVE' THEN 0.0909
        WHEN 'SOFT_ROOM_DISCOURAGED' THEN 0.1818
        WHEN 'SOFT_ROOM_STABILITY' THEN 0.0909
        ELSE weight
    END,
    note = CASE constraint_code
        WHEN 'SOFT_LECTURER_GAP'
            THEN N'Chuẩn hóa bằng gap/(gap+teaching); không tính trước buổi đầu, sau buổi cuối hoặc ngày không dạy'
        ELSE note
    END
WHERE constraint_code IN
(
    'SOFT_CAPACITY',
    'SOFT_LECTURER_GAP',
    'SOFT_LECTURER_CONSECUTIVE',
    'SOFT_ROOM_DISCOURAGED',
    'SOFT_ROOM_STABILITY'
);

COMMIT TRANSACTION;
GO

CREATE OR ALTER TRIGGER dbo.TR_TeachingPart_OneLecturerPerCourseSection
ON dbo.TeachingPart
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF EXISTS
    (
        SELECT 1
        FROM inserted AS changed_part
        JOIN dbo.TeachingPart AS existing_part
          ON existing_part.section_code = changed_part.section_code
         AND existing_part.teaching_part_id <> changed_part.teaching_part_id
         AND existing_part.lecturer_code <> changed_part.lecturer_code
    )
    BEGIN
        THROW 51001,
              'All TeachingPart rows of one CourseSection must use the same lecturer.',
              1;
    END;
END;
GO

-- Verification queries: all scalar flags must be 1, the conflict query empty,
-- and the five tier-2 weights must sum to 1.0000.
SELECT CASE
    WHEN COL_LENGTH('dbo.OptimizationRun', 'snapshot_checksum') IS NULL
    THEN 0 ELSE 1
END AS has_snapshot_checksum;

SELECT CASE
    WHEN OBJECT_ID('dbo.TR_TeachingPart_OneLecturerPerCourseSection', 'TR') IS NULL
    THEN 0 ELSE 1
END AS has_one_lecturer_trigger;

SELECT SUM(weight) AS q_general_weight_sum
FROM dbo.ConstraintSetting
WHERE constraint_code IN
(
    'SOFT_CAPACITY',
    'SOFT_LECTURER_GAP',
    'SOFT_LECTURER_CONSECUTIVE',
    'SOFT_ROOM_DISCOURAGED',
    'SOFT_ROOM_STABILITY'
);

SELECT section_code
FROM dbo.TeachingPart
GROUP BY section_code
HAVING COUNT(DISTINCT lecturer_code) > 1;
GO
