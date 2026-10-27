/*
    NON-DESTRUCTIVE MIGRATION: dynamic lecturer assignment

    This migration upgrades an existing development database created by the
    former schema. It preserves runs and timetable entries, converts each old
    fixed assignment into an initial course capability, and makes the actual
    lecturer explicit in TimetableEntry.
*/

USE testkhoaluan;
GO

DROP TRIGGER IF EXISTS TR_TeachingPart_OneLecturerPerCourseSection;
GO

IF COL_LENGTH('Lecturer', 'max_teaching_periods') IS NULL
BEGIN
    ALTER TABLE Lecturer ADD max_teaching_periods INT NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_Lecturer_MaxTeachingPeriods'
)
BEGIN
    ALTER TABLE Lecturer ADD CONSTRAINT CK_Lecturer_MaxTeachingPeriods
        CHECK (max_teaching_periods IS NULL OR max_teaching_periods > 0);
END;
GO

IF OBJECT_ID('LecturerCourseCapability', 'U') IS NULL
BEGIN
    CREATE TABLE LecturerCourseCapability
    (
        lecturer_code       VARCHAR(20)  NOT NULL,
        course_code         VARCHAR(20)  NOT NULL,
        can_teach_lecture   BIT          NOT NULL DEFAULT 0,
        can_teach_practice  BIT          NOT NULL DEFAULT 0,
        suitability_score   DECIMAL(5,4) NOT NULL DEFAULT 1.0000,
        CONSTRAINT PK_LecturerCourseCapability
            PRIMARY KEY (lecturer_code, course_code),
        CONSTRAINT FK_LCC_Lecturer
            FOREIGN KEY (lecturer_code) REFERENCES Lecturer(lecturer_code),
        CONSTRAINT FK_LCC_Course
            FOREIGN KEY (course_code) REFERENCES Course(course_code),
        CONSTRAINT CK_LCC_AtLeastOnePartType
            CHECK (can_teach_lecture = 1 OR can_teach_practice = 1),
        CONSTRAINT CK_LCC_Suitability
            CHECK (suitability_score BETWEEN 0.0000 AND 1.0000)
    );
END;
GO

MERGE LecturerCourseCapability AS target
USING
(
    SELECT
        p.lecturer_code,
        cs.course_code,
        CONVERT(BIT, MAX(CASE WHEN p.part_type = 'LECTURE' THEN 1 ELSE 0 END))
            AS can_teach_lecture,
        CONVERT(BIT, MAX(CASE WHEN p.part_type = 'PRACTICE' THEN 1 ELSE 0 END))
            AS can_teach_practice
    FROM TeachingPart p
    JOIN CourseSection cs ON cs.section_code = p.section_code
    WHERE p.lecturer_code IS NOT NULL
    GROUP BY p.lecturer_code, cs.course_code
) AS source
ON target.lecturer_code = source.lecturer_code
AND target.course_code = source.course_code
WHEN MATCHED THEN UPDATE SET
    can_teach_lecture = source.can_teach_lecture,
    can_teach_practice = source.can_teach_practice
WHEN NOT MATCHED THEN INSERT
    (lecturer_code, course_code, can_teach_lecture, can_teach_practice,
     suitability_score)
VALUES
    (source.lecturer_code, source.course_code, source.can_teach_lecture,
     source.can_teach_practice, 1.0000);
GO

ALTER TABLE TeachingPart ALTER COLUMN lecturer_code VARCHAR(20) NULL;
GO

IF COL_LENGTH('TimetableEntry', 'lecturer_code') IS NULL
BEGIN
    ALTER TABLE TimetableEntry ADD lecturer_code VARCHAR(20) NULL;
END;
GO

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('TimetableEntry')
      AND name = 'lecturer_code'
      AND is_nullable = 1
)
BEGIN
    UPDATE te
    SET lecturer_code = p.lecturer_code
    FROM TimetableEntry te
    JOIN ClassSession ses ON ses.class_session_id = te.class_session_id
    JOIN TeachingPlan pl ON pl.teaching_plan_id = ses.teaching_plan_id
    JOIN TeachingPart p ON p.teaching_part_id = pl.teaching_part_id;

    IF EXISTS (SELECT 1 FROM TimetableEntry WHERE lecturer_code IS NULL)
        THROW 51020, 'Cannot infer lecturer for one or more legacy timetable entries.', 1;

    ALTER TABLE TimetableEntry ALTER COLUMN lecturer_code VARCHAR(20) NOT NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = 'FK_TimetableEntry_Lecturer'
)
BEGIN
    ALTER TABLE TimetableEntry ADD CONSTRAINT FK_TimetableEntry_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES Lecturer(lecturer_code);
END;
GO

MERGE ConstraintSetting AS target
USING (VALUES
    ('SOFT_CAPACITY', N'Mức thiếu sức chứa phòng vật lý', 2, 0.3682),
    ('SOFT_LECTURER_GAP', N'Khoảng trống trong ngày của giảng viên', 2, 0.2046),
    ('SOFT_LECTURER_CONSECUTIVE', N'Hạn chế dạy quá nhiều tiết liên tục', 2, 0.0818),
    ('SOFT_ROOM_DISCOURAGED', N'Hạn chế dùng phòng trong khoảng DISCOURAGED', 2, 0.1636),
    ('SOFT_ROOM_STABILITY', N'Ổn định phòng giữa các tuần', 2, 0.0818),
    ('SOFT_WORKLOAD_BALANCE', N'Cân bằng khối lượng giảng dạy', 2, 0.1000),
    ('SOFT_LECTURER_TIME_PREFERENCE', N'Mong muốn thời gian của giảng viên', 3, 0.5000),
    ('SOFT_COURSE_SUITABILITY', N'Mức phù hợp môn và giảng viên', 3, 0.5000)
) AS source(constraint_code, constraint_name, priority_tier, weight)
ON target.constraint_code = source.constraint_code
WHEN MATCHED THEN UPDATE SET
    constraint_name = source.constraint_name,
    constraint_kind = 'SOFT',
    priority_tier = source.priority_tier,
    weight = source.weight,
    is_enabled = 1
WHEN NOT MATCHED THEN INSERT
    (constraint_code, constraint_name, constraint_kind, priority_tier,
     weight, is_enabled)
VALUES
    (source.constraint_code, source.constraint_name, 'SOFT',
     source.priority_tier, source.weight, 1);
GO

-- Mã cũ gộp toàn bộ preference vào một thành phần duy nhất. Giữ bản ghi để
-- truy nguyên dữ liệu lịch sử nhưng không cho snapshot mới dùng đồng thời với
-- hai thành phần đã tách rõ ở trên.
UPDATE ConstraintSetting
SET is_enabled = 0,
    note = N'Đã thay thế bởi SOFT_LECTURER_TIME_PREFERENCE và SOFT_COURSE_SUITABILITY'
WHERE constraint_code = 'SOFT_LECTURER_PREFERENCE';
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_LecturerCourseCapability_Course'
      AND object_id = OBJECT_ID('LecturerCourseCapability')
)
    CREATE INDEX IX_LecturerCourseCapability_Course
        ON LecturerCourseCapability(course_code, lecturer_code);
GO
