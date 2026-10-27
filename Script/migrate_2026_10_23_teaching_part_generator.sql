USE testkhoaluan;
GO

IF OBJECT_ID('dbo.CourseTeachingStructure', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.CourseTeachingStructure
    (
        course_structure_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        course_code VARCHAR(20) NOT NULL,
        part_type VARCHAR(20) NOT NULL,
        total_periods INT NOT NULL,
        required_location_type VARCHAR(20) NOT NULL DEFAULT 'PHYSICAL_ROOM',
        required_room_type VARCHAR(30) NULL,
        max_sessions_per_week INT NOT NULL DEFAULT 1,
        allows_intensive BIT NOT NULL DEFAULT 0,
        max_candidate_plans INT NOT NULL DEFAULT 200,
        is_active BIT NOT NULL DEFAULT 1,
        note NVARCHAR(255) NULL,
        CONSTRAINT UQ_CourseTeachingStructure UNIQUE(course_code,part_type),
        CONSTRAINT FK_CTS_Course FOREIGN KEY(course_code) REFERENCES dbo.Course(course_code),
        CONSTRAINT CK_CTS_PartType CHECK(part_type IN ('LECTURE','PRACTICE')),
        CONSTRAINT CK_CTS_TotalPeriods CHECK(total_periods > 0),
        CONSTRAINT CK_CTS_MaxSessions CHECK(max_sessions_per_week BETWEEN 1 AND 7),
        CONSTRAINT CK_CTS_MaxPlans CHECK(max_candidate_plans BETWEEN 1 AND 200),
        CONSTRAINT CK_CTS_LocationType
            CHECK(required_location_type IN ('PHYSICAL_ROOM','ONLINE')),
        CONSTRAINT CK_CTS_RoomRequirement CHECK(
            (required_location_type='PHYSICAL_ROOM' AND required_room_type IS NOT NULL)
            OR (required_location_type='ONLINE' AND required_room_type IS NULL)
        )
    );
END;
GO

IF OBJECT_ID('dbo.CourseTeachingStructureRequiredEquipment', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.CourseTeachingStructureRequiredEquipment
    (
        course_structure_id BIGINT NOT NULL,
        equipment_code VARCHAR(30) NOT NULL,
        minimum_quantity INT NOT NULL DEFAULT 1,
        CONSTRAINT PK_CTSRE PRIMARY KEY(course_structure_id,equipment_code),
        CONSTRAINT FK_CTSRE_Structure FOREIGN KEY(course_structure_id)
            REFERENCES dbo.CourseTeachingStructure(course_structure_id),
        CONSTRAINT FK_CTSRE_Equipment FOREIGN KEY(equipment_code)
            REFERENCES dbo.Equipment(equipment_code),
        CONSTRAINT CK_CTSRE_Quantity CHECK(minimum_quantity >= 1)
    );
END;
GO

IF COL_LENGTH('dbo.TeachingPart', 'course_structure_id') IS NULL
    ALTER TABLE dbo.TeachingPart ADD course_structure_id BIGINT NULL;
GO

IF OBJECT_ID('dbo.FK_TeachingPart_Structure', 'F') IS NULL
    ALTER TABLE dbo.TeachingPart ADD CONSTRAINT FK_TeachingPart_Structure
        FOREIGN KEY(course_structure_id)
        REFERENCES dbo.CourseTeachingStructure(course_structure_id);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id=OBJECT_ID('dbo.TeachingPart')
      AND name='UQ_TeachingPart_SectionType'
)
    CREATE UNIQUE INDEX UQ_TeachingPart_SectionType
        ON dbo.TeachingPart(section_code,part_type);
GO

/*
   Preserve current projects by deriving reusable structures from existing
   TeachingPart rows. When rows disagree, the most recently materialized
   teaching part (highest identity) supplies the initial default.
*/
;WITH RankedStructure AS
(
    SELECT section.course_code,part.part_type,part.total_periods,
           part.required_location_type,part.required_room_type,part.note,
           generation_rule.max_sessions_per_week,generation_rule.allows_intensive,
           generation_rule.max_candidate_plans,
           ROW_NUMBER() OVER(
               PARTITION BY section.course_code,part.part_type
               ORDER BY part.teaching_part_id DESC
           ) AS row_rank
    FROM dbo.TeachingPart AS part
    JOIN dbo.CourseSection AS section ON section.section_code=part.section_code
    LEFT JOIN dbo.TeachingPlanGenerationRule AS generation_rule
      ON generation_rule.teaching_part_id=part.teaching_part_id
     AND generation_rule.is_active=1
)
INSERT INTO dbo.CourseTeachingStructure(
    course_code,part_type,total_periods,required_location_type,
    required_room_type,max_sessions_per_week,allows_intensive,
    max_candidate_plans,is_active,note
)
SELECT source.course_code,source.part_type,source.total_periods,
       source.required_location_type,source.required_room_type,
       ISNULL(source.max_sessions_per_week,1),ISNULL(source.allows_intensive,0),
       ISNULL(source.max_candidate_plans,200),1,source.note
FROM RankedStructure AS source
WHERE source.row_rank=1
  AND NOT EXISTS(
      SELECT 1 FROM dbo.CourseTeachingStructure AS target
      WHERE target.course_code=source.course_code
        AND target.part_type=source.part_type
  );
GO

UPDATE part
SET course_structure_id=structure.course_structure_id
FROM dbo.TeachingPart AS part
JOIN dbo.CourseSection AS section ON section.section_code=part.section_code
JOIN dbo.CourseTeachingStructure AS structure
  ON structure.course_code=section.course_code
 AND structure.part_type=part.part_type
WHERE part.course_structure_id IS NULL;
GO

INSERT INTO dbo.CourseTeachingStructureRequiredEquipment(
    course_structure_id,equipment_code,minimum_quantity
)
SELECT part.course_structure_id,requirement.equipment_code,
       MAX(requirement.minimum_quantity)
FROM dbo.TeachingPartRequiredEquipment AS requirement
JOIN dbo.TeachingPart AS part
  ON part.teaching_part_id=requirement.teaching_part_id
WHERE part.course_structure_id IS NOT NULL
  AND NOT EXISTS(
      SELECT 1
      FROM dbo.CourseTeachingStructureRequiredEquipment AS target
      WHERE target.course_structure_id=part.course_structure_id
        AND target.equipment_code=requirement.equipment_code
  )
GROUP BY part.course_structure_id,requirement.equipment_code;
GO
