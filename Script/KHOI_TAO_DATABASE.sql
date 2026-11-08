/*
  KHOI TAO DATABASE UNG DUNG GA-PO - CHAY THU CONG MOT LAN TRONG SSMS.
  1. SQL Server + ODBC + Python duoc cai rieng.
  2. Mac dinh ten database la KhoaLuanDemo. Neu doi ten, thay TAT CA
     KhoaLuanDemo trong file nay, va dien databaseName tuong ung trong .env.
  3. Chi khoi tao database hoan toan trong. Neu da co bang thi dung,
     khong xoa bang, khong reset, khong thay ket qua lich da luu.
  4. Chi chen du lieu nen: tiet hoc, thoi luong, khoi tiet va rang buoc.
     Khong chen hoc ky, lop, mon, giang vien, phong hay ket qua demo.
  Khong dung Script/script.sql cu de cai dat: do la script RESET phat trien.
*/
USE master;
GO
IF DB_ID(N'KhoaLuanDemo') IS NULL
    EXEC(N'CREATE DATABASE [KhoaLuanDemo]');
GO
USE [KhoaLuanDemo];
GO

SET XACT_ABORT ON;
SET NOCOUNT ON;
BEGIN TRY
    IF DB_NAME() IN (N'master',N'model',N'msdb',N'tempdb')
        THROW 51000, N'Hay chon database rieng, khong khoi tao tren database he thong.', 1;

    BEGIN TRANSACTION;
    DECLARE @lock_result INT;
    EXEC @lock_result = sys.sp_getapplock
        @Resource=N'gapo:manual-schema-initialize',
        @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=30000;
    IF @lock_result < 0
        THROW 51001, N'Khong lay duoc khoa khoi tao. Hay thu lai.', 1;

    IF EXISTS (SELECT 1 FROM sys.tables WHERE is_ms_shipped=0)
        THROW 51002, N'Database da co bang. Script chi dung cho database trong; khong reset du lieu.', 1;

-- Fresh database only. No reset, migration, sample semester or optimizer result.
-- Table definitions copied from Script/script.sql; queue index included.

CREATE TABLE dbo.AcademicTerm
(
    term_code       VARCHAR(20)    NOT NULL PRIMARY KEY,
    term_name       NVARCHAR(150)  NOT NULL,
    start_date      DATE           NOT NULL,
    end_date        DATE           NOT NULL,
    status          VARCHAR(20)    NOT NULL DEFAULT 'PLANNING',
    created_at      DATETIME2      NOT NULL DEFAULT SYSDATETIME(),
    CONSTRAINT CK_AcademicTerm_DateRange CHECK (start_date <= end_date),
    CONSTRAINT CK_AcademicTerm_Status
        CHECK (status IN ('PLANNING', 'ACTIVE', 'CLOSED'))
);

CREATE TABLE dbo.TermWeek
(
    term_code       VARCHAR(20) NOT NULL,
    week_number     INT         NOT NULL,
    start_date      DATE        NOT NULL,
    end_date        DATE        NOT NULL,
    CONSTRAINT PK_TermWeek PRIMARY KEY (term_code, week_number),
    CONSTRAINT FK_TermWeek_Term
        FOREIGN KEY (term_code) REFERENCES dbo.AcademicTerm(term_code),
    CONSTRAINT CK_TermWeek_Number CHECK (week_number >= 1),
    CONSTRAINT CK_TermWeek_DateRange CHECK (start_date <= end_date),
    CONSTRAINT UQ_TermWeek_Term_StartDate UNIQUE (term_code, start_date)
);

CREATE TABLE dbo.TeachingDate
(
    term_code       VARCHAR(20)   NOT NULL,
    calendar_date   DATE          NOT NULL,
    week_number     INT           NOT NULL,
    iso_weekday     TINYINT       NOT NULL,
    date_status     VARCHAR(20)   NOT NULL DEFAULT 'NORMAL',
    note             NVARCHAR(255) NULL,
    CONSTRAINT PK_TeachingDate PRIMARY KEY (term_code, calendar_date),
    CONSTRAINT FK_TeachingDate_Week
        FOREIGN KEY (term_code, week_number)
        REFERENCES dbo.TermWeek(term_code, week_number),
    CONSTRAINT CK_TeachingDate_Weekday CHECK (iso_weekday BETWEEN 1 AND 7),
    CONSTRAINT CK_TeachingDate_Status
        CHECK (date_status IN ('NORMAL', 'HOLIDAY', 'MAKEUP_ALLOWED'))
);

CREATE TABLE dbo.TimePeriod
(
    period_number   TINYINT     NOT NULL PRIMARY KEY,
    start_time      TIME(0)     NOT NULL,
    end_time        TIME(0)     NOT NULL,
    session_name    VARCHAR(20) NOT NULL,
    CONSTRAINT CK_TimePeriod_Number CHECK (period_number BETWEEN 1 AND 16),
    CONSTRAINT CK_TimePeriod_Time CHECK (start_time < end_time),
    CONSTRAINT CK_TimePeriod_Session
        CHECK (session_name IN ('MORNING', 'AFTERNOON', 'EVENING'))
);

CREATE TABLE dbo.TeachingDurationRule
(
    part_type        VARCHAR(20)   NOT NULL,
    duration_periods TINYINT       NOT NULL,
    is_standard      BIT           NOT NULL DEFAULT 1,
    note              NVARCHAR(255) NULL,
    CONSTRAINT PK_TeachingDurationRule
        PRIMARY KEY (part_type, duration_periods),
    CONSTRAINT CK_TeachingDurationRule_PartType
        CHECK (part_type IN ('LECTURE', 'PRACTICE')),
    CONSTRAINT CK_TeachingDurationRule_Duration
        CHECK (duration_periods BETWEEN 1 AND 16)
);

CREATE TABLE dbo.AllowedPeriodBlock
(
    start_period        TINYINT       NOT NULL,
    duration_periods    TINYINT       NOT NULL,
    end_period          AS (CONVERT(TINYINT, start_period + duration_periods - 1)) PERSISTED,
    block_name          NVARCHAR(100) NULL,
    is_active           BIT           NOT NULL DEFAULT 1,
    CONSTRAINT PK_AllowedPeriodBlock
        PRIMARY KEY (start_period, duration_periods),
    CONSTRAINT CK_AllowedPeriodBlock_Start CHECK (start_period BETWEEN 1 AND 16),
    CONSTRAINT CK_AllowedPeriodBlock_Duration CHECK (duration_periods BETWEEN 1 AND 16),
    CONSTRAINT CK_AllowedPeriodBlock_End
        CHECK (start_period + duration_periods - 1 <= 16)
);

CREATE TABLE dbo.Campus
(
    campus_code VARCHAR(20)   NOT NULL PRIMARY KEY,
    campus_name NVARCHAR(150) NOT NULL,
    address      NVARCHAR(255) NULL,
    is_active    BIT           NOT NULL DEFAULT 1
);

CREATE TABLE dbo.CampusTravelTime
(
    from_campus_code VARCHAR(20) NOT NULL,
    to_campus_code   VARCHAR(20) NOT NULL,
    travel_minutes   INT         NOT NULL,
    CONSTRAINT PK_CampusTravelTime PRIMARY KEY (from_campus_code, to_campus_code),
    CONSTRAINT FK_CampusTravelTime_From
        FOREIGN KEY (from_campus_code) REFERENCES dbo.Campus(campus_code),
    CONSTRAINT FK_CampusTravelTime_To
        FOREIGN KEY (to_campus_code) REFERENCES dbo.Campus(campus_code),
    CONSTRAINT CK_CampusTravelTime_Different CHECK (from_campus_code <> to_campus_code),
    CONSTRAINT CK_CampusTravelTime_Minutes CHECK (travel_minutes >= 0)
);

CREATE TABLE dbo.TeachingLocation
(
    location_id   BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    location_code VARCHAR(30)           NOT NULL UNIQUE,
    location_name NVARCHAR(150)         NOT NULL,
    location_type VARCHAR(20)           NOT NULL,
    is_active     BIT                   NOT NULL DEFAULT 1,
    CONSTRAINT UQ_TeachingLocation_Id_Type UNIQUE (location_id, location_type),
    CONSTRAINT CK_TeachingLocation_Type
        CHECK (location_type IN ('PHYSICAL_ROOM', 'ONLINE'))
);

CREATE TABLE dbo.Room
(
    location_id   BIGINT      NOT NULL PRIMARY KEY,
    location_type VARCHAR(20) NOT NULL DEFAULT 'PHYSICAL_ROOM',
    campus_code   VARCHAR(20) NOT NULL,
    room_type     VARCHAR(30) NOT NULL,
    capacity      INT         NULL,
    CONSTRAINT FK_Room_Location
        FOREIGN KEY (location_id, location_type)
        REFERENCES dbo.TeachingLocation(location_id, location_type),
    CONSTRAINT FK_Room_Campus
        FOREIGN KEY (campus_code) REFERENCES dbo.Campus(campus_code),
    CONSTRAINT CK_Room_LocationType CHECK (location_type = 'PHYSICAL_ROOM'),
    CONSTRAINT CK_Room_Capacity CHECK (capacity IS NULL OR capacity > 0)
);

CREATE TABLE dbo.OnlineLocation
(
    location_id   BIGINT        NOT NULL PRIMARY KEY,
    location_type VARCHAR(20)   NOT NULL DEFAULT 'ONLINE',
    platform_name NVARCHAR(100) NOT NULL,
    meeting_note  NVARCHAR(255) NULL,
    CONSTRAINT FK_OnlineLocation_Location
        FOREIGN KEY (location_id, location_type)
        REFERENCES dbo.TeachingLocation(location_id, location_type),
    CONSTRAINT CK_OnlineLocation_Type CHECK (location_type = 'ONLINE')
);

CREATE TABLE dbo.Lecturer
(
    lecturer_code  VARCHAR(20)   NOT NULL PRIMARY KEY,
    full_name      NVARCHAR(150) NOT NULL,
    email           VARCHAR(150)  NULL,
    home_campus_code VARCHAR(20)  NULL,
    is_active      BIT           NOT NULL DEFAULT 1,
    max_teaching_periods INT      NULL,
    CONSTRAINT FK_Lecturer_HomeCampus
        FOREIGN KEY (home_campus_code) REFERENCES dbo.Campus(campus_code),
    CONSTRAINT CK_Lecturer_MaxTeachingPeriods
        CHECK (max_teaching_periods IS NULL OR max_teaching_periods > 0)
);

CREATE TABLE dbo.Course
(
    course_code    VARCHAR(20)   NOT NULL PRIMARY KEY,
    course_name    NVARCHAR(200) NOT NULL,
    credits        DECIMAL(4,1)  NULL,
    is_active      BIT           NOT NULL DEFAULT 1,
    CONSTRAINT CK_Course_Credits CHECK (credits IS NULL OR credits > 0)
);

CREATE TABLE dbo.CourseTeachingStructure
(
    course_structure_id      BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    course_code              VARCHAR(20) NOT NULL,
    part_type                VARCHAR(20) NOT NULL,
    total_periods            INT NOT NULL,
    required_location_type   VARCHAR(20) NOT NULL DEFAULT 'PHYSICAL_ROOM',
    required_room_type       VARCHAR(30) NULL,
    max_sessions_per_week    INT NOT NULL DEFAULT 1,
    allows_intensive         BIT NOT NULL DEFAULT 0,
    max_candidate_plans      INT NOT NULL DEFAULT 200,
    is_active                BIT NOT NULL DEFAULT 1,
    note                     NVARCHAR(255) NULL,
    CONSTRAINT UQ_CourseTeachingStructure UNIQUE(course_code, part_type),
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

CREATE TABLE dbo.LecturerCourseCapability
(
    lecturer_code       VARCHAR(20)  NOT NULL,
    course_code         VARCHAR(20)  NOT NULL,
    can_teach_lecture   BIT          NOT NULL DEFAULT 0,
    can_teach_practice  BIT          NOT NULL DEFAULT 0,
    suitability_score   DECIMAL(5,4) NOT NULL DEFAULT 1.0000,
    CONSTRAINT PK_LecturerCourseCapability
        PRIMARY KEY (lecturer_code, course_code),
    CONSTRAINT FK_LCC_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES dbo.Lecturer(lecturer_code),
    CONSTRAINT FK_LCC_Course
        FOREIGN KEY (course_code) REFERENCES dbo.Course(course_code),
    CONSTRAINT CK_LCC_AtLeastOnePartType
        CHECK (can_teach_lecture = 1 OR can_teach_practice = 1),
    CONSTRAINT CK_LCC_Suitability
        CHECK (suitability_score BETWEEN 0.0000 AND 1.0000)
);

CREATE TABLE dbo.CourseSection
(
    section_code        VARCHAR(30) NOT NULL PRIMARY KEY,
    term_code           VARCHAR(20) NOT NULL,
    course_code         VARCHAR(20) NOT NULL,
    section_name        NVARCHAR(150) NULL,
    expected_enrollment INT         NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'PLANNING',
    CONSTRAINT FK_CourseSection_Term
        FOREIGN KEY (term_code) REFERENCES dbo.AcademicTerm(term_code),
    CONSTRAINT FK_CourseSection_Course
        FOREIGN KEY (course_code) REFERENCES dbo.Course(course_code),
    CONSTRAINT CK_CourseSection_ExpectedEnrollment
        CHECK (expected_enrollment IS NULL OR expected_enrollment > 0),
    CONSTRAINT CK_CourseSection_Status
        CHECK (status IN ('PLANNING', 'APPROVED', 'CANCELLED'))
);

CREATE TABLE dbo.Equipment
(
    equipment_code VARCHAR(30)   NOT NULL PRIMARY KEY,
    equipment_name NVARCHAR(150) NOT NULL
);

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

CREATE TABLE dbo.RoomEquipment
(
    room_location_id BIGINT      NOT NULL,
    equipment_code   VARCHAR(30) NOT NULL,
    quantity         INT         NOT NULL DEFAULT 1,
    CONSTRAINT PK_RoomEquipment PRIMARY KEY (room_location_id, equipment_code),
    CONSTRAINT FK_RoomEquipment_Room
        FOREIGN KEY (room_location_id) REFERENCES dbo.Room(location_id),
    CONSTRAINT FK_RoomEquipment_Equipment
        FOREIGN KEY (equipment_code) REFERENCES dbo.Equipment(equipment_code),
    CONSTRAINT CK_RoomEquipment_Quantity CHECK (quantity >= 1)
);

CREATE TABLE dbo.TeachingPart
(
    teaching_part_id      BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    section_code          VARCHAR(30) NOT NULL,
    part_code             VARCHAR(30) NOT NULL UNIQUE,
    part_type             VARCHAR(20) NOT NULL,
    course_structure_id   BIGINT NULL,
    lecturer_code         VARCHAR(20) NULL,
    total_periods         INT         NOT NULL,
    required_room_type    VARCHAR(30) NULL,
    required_location_type VARCHAR(20) NOT NULL DEFAULT 'PHYSICAL_ROOM',
    note                  NVARCHAR(255) NULL,
    CONSTRAINT FK_TeachingPart_Section
        FOREIGN KEY (section_code) REFERENCES dbo.CourseSection(section_code),
    CONSTRAINT FK_TeachingPart_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES dbo.Lecturer(lecturer_code),
    CONSTRAINT FK_TeachingPart_Structure
        FOREIGN KEY (course_structure_id)
        REFERENCES dbo.CourseTeachingStructure(course_structure_id),
    CONSTRAINT UQ_TeachingPart_SectionType UNIQUE(section_code,part_type),
    CONSTRAINT CK_TeachingPart_Type CHECK (part_type IN ('LECTURE', 'PRACTICE')),
    CONSTRAINT CK_TeachingPart_TotalPeriods CHECK (total_periods > 0),
    CONSTRAINT CK_TeachingPart_LocationType
        CHECK (required_location_type IN ('PHYSICAL_ROOM', 'ONLINE')),
    CONSTRAINT CK_TeachingPart_RoomRequirement
        CHECK (
            (required_location_type = 'PHYSICAL_ROOM' AND required_room_type IS NOT NULL)
            OR
            (required_location_type = 'ONLINE' AND required_room_type IS NULL)
        )
);

CREATE TABLE dbo.TeachingPartRequiredEquipment
(
    teaching_part_id BIGINT      NOT NULL,
    equipment_code   VARCHAR(30) NOT NULL,
    minimum_quantity INT         NOT NULL DEFAULT 1,
    CONSTRAINT PK_TeachingPartRequiredEquipment
        PRIMARY KEY (teaching_part_id, equipment_code),
    CONSTRAINT FK_TPRE_Part
        FOREIGN KEY (teaching_part_id) REFERENCES dbo.TeachingPart(teaching_part_id),
    CONSTRAINT FK_TPRE_Equipment
        FOREIGN KEY (equipment_code) REFERENCES dbo.Equipment(equipment_code),
    CONSTRAINT CK_TPRE_Quantity CHECK (minimum_quantity >= 1)
);

CREATE TABLE dbo.TeachingPlanGenerationRule
(
    generation_rule_id     BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    teaching_part_id       BIGINT      NOT NULL,
    start_week_number      INT         NOT NULL,
    end_week_number        INT         NOT NULL,
    max_sessions_per_week  INT         NOT NULL,
    allows_intensive       BIT         NOT NULL DEFAULT 0,
    max_candidate_plans    INT         NOT NULL DEFAULT 200,
    is_active              BIT         NOT NULL DEFAULT 1,
    note                   NVARCHAR(500) NULL,
    CONSTRAINT FK_TeachingPlanGenerationRule_Part
        FOREIGN KEY (teaching_part_id) REFERENCES dbo.TeachingPart(teaching_part_id),
    CONSTRAINT UQ_TeachingPlanGenerationRule_Part UNIQUE (teaching_part_id),
    CONSTRAINT CK_TeachingPlanGenerationRule_WeekRange
        CHECK (start_week_number >= 1 AND end_week_number >= start_week_number),
    CONSTRAINT CK_TeachingPlanGenerationRule_MaxSessions
        CHECK (max_sessions_per_week >= 1),
    CONSTRAINT CK_TeachingPlanGenerationRule_MaxCandidates
        CHECK (max_candidate_plans >= 1)
);

CREATE TABLE dbo.TeachingPlan
(
    teaching_plan_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    teaching_part_id BIGINT        NOT NULL,
    plan_code        VARCHAR(40)   NOT NULL UNIQUE,
    plan_name        NVARCHAR(180) NOT NULL,
    status           VARCHAR(20)   NOT NULL DEFAULT 'VALID',
    allows_intensive BIT           NOT NULL DEFAULT 0,
    generation_no    INT           NOT NULL,
    candidate_rank   INT           NOT NULL,
    generation_key  CHAR(64)      NOT NULL,
    generated_at     DATETIME2     NOT NULL DEFAULT SYSDATETIME(),
    note              NVARCHAR(500) NULL,
    CONSTRAINT FK_TeachingPlan_Part
        FOREIGN KEY (teaching_part_id) REFERENCES dbo.TeachingPart(teaching_part_id),
    CONSTRAINT UQ_TeachingPlan_Id_Part UNIQUE (teaching_plan_id, teaching_part_id),
    CONSTRAINT UQ_TeachingPlan_GenerationRank
        UNIQUE (teaching_part_id, generation_no, candidate_rank),
    CONSTRAINT UQ_TeachingPlan_GenerationKeyRank
        UNIQUE (teaching_part_id, generation_key, candidate_rank),
    CONSTRAINT CK_TeachingPlan_Status
        CHECK (status IN ('VALID', 'RETIRED')),
    CONSTRAINT CK_TeachingPlan_GenerationNo CHECK (generation_no >= 1),
    CONSTRAINT CK_TeachingPlan_CandidateRank CHECK (candidate_rank >= 1),
    CONSTRAINT CK_TeachingPlan_GenerationKey
        CHECK (generation_key NOT LIKE '%[^0-9A-F]%')
);

CREATE TABLE dbo.TeachingPlanItem
(
    teaching_plan_item_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    teaching_plan_id      BIGINT      NOT NULL,
    item_number           INT         NOT NULL,
    term_code             VARCHAR(20) NOT NULL,
    week_number           INT         NOT NULL,
    session_order_in_week INT         NOT NULL,
    duration_periods      TINYINT     NOT NULL,
    stability_group_no    INT         NOT NULL DEFAULT 1,
    CONSTRAINT FK_TeachingPlanItem_Plan
        FOREIGN KEY (teaching_plan_id) REFERENCES dbo.TeachingPlan(teaching_plan_id),
    CONSTRAINT FK_TeachingPlanItem_Week
        FOREIGN KEY (term_code, week_number)
        REFERENCES dbo.TermWeek(term_code, week_number),
    CONSTRAINT UQ_TeachingPlanItem_Plan_Number
        UNIQUE (teaching_plan_id, item_number),
    CONSTRAINT UQ_TeachingPlanItem_Plan_Week_Order
        UNIQUE (teaching_plan_id, week_number, session_order_in_week),
    CONSTRAINT CK_TeachingPlanItem_Number CHECK (item_number >= 1),
    CONSTRAINT CK_TeachingPlanItem_Order CHECK (session_order_in_week >= 1),
    CONSTRAINT CK_TeachingPlanItem_Duration CHECK (duration_periods BETWEEN 1 AND 16),
    CONSTRAINT CK_TeachingPlanItem_StabilityGroup CHECK (stability_group_no >= 1)
);

CREATE TABLE dbo.ClassSession
(
    class_session_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    teaching_plan_id BIGINT      NOT NULL,
    session_number   INT         NOT NULL,
    stability_group_no INT       NOT NULL,
    term_code        VARCHAR(20) NOT NULL,
    week_number      INT         NOT NULL,
    duration_periods TINYINT     NOT NULL,
    required_location_type VARCHAR(20) NOT NULL,
    note              NVARCHAR(255) NULL,
    CONSTRAINT FK_ClassSession_Plan
        FOREIGN KEY (teaching_plan_id) REFERENCES dbo.TeachingPlan(teaching_plan_id),
    CONSTRAINT FK_ClassSession_Week
        FOREIGN KEY (term_code, week_number)
        REFERENCES dbo.TermWeek(term_code, week_number),
    CONSTRAINT UQ_ClassSession_Plan_Number
        UNIQUE (teaching_plan_id, session_number),
    CONSTRAINT UQ_ClassSession_Plan_Week_Group
        UNIQUE (teaching_plan_id, term_code, week_number, stability_group_no),
    CONSTRAINT UQ_ClassSession_Id_Term
        UNIQUE (class_session_id, term_code),
    CONSTRAINT UQ_ClassSession_Id_LocationType
        UNIQUE (class_session_id, required_location_type),
    CONSTRAINT CK_ClassSession_Number CHECK (session_number >= 1),
    CONSTRAINT CK_ClassSession_StabilityGroup CHECK (stability_group_no >= 1),
    CONSTRAINT CK_ClassSession_Duration CHECK (duration_periods BETWEEN 1 AND 16),
    CONSTRAINT CK_ClassSession_LocationType
        CHECK (required_location_type IN ('PHYSICAL_ROOM', 'ONLINE'))
);

CREATE TABLE dbo.LecturerAvailability
(
    availability_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    term_code       VARCHAR(20) NOT NULL,
    lecturer_code   VARCHAR(20) NOT NULL,
    scope_type      VARCHAR(20) NOT NULL,
    calendar_date   DATE        NULL,
    iso_weekday     TINYINT     NULL,
    start_period    TINYINT     NOT NULL,
    end_period      TINYINT     NOT NULL,
    availability_type VARCHAR(20) NOT NULL,
    preference_weight DECIMAL(8,3) NULL,
    note             NVARCHAR(255) NULL,
    CONSTRAINT FK_LecturerAvailability_Term
        FOREIGN KEY (term_code) REFERENCES dbo.AcademicTerm(term_code),
    CONSTRAINT FK_LecturerAvailability_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES dbo.Lecturer(lecturer_code),
    CONSTRAINT FK_LecturerAvailability_Date
        FOREIGN KEY (term_code, calendar_date)
        REFERENCES dbo.TeachingDate(term_code, calendar_date),
    CONSTRAINT CK_LecturerAvailability_Scope
        CHECK (
            (scope_type = 'DATE' AND calendar_date IS NOT NULL AND iso_weekday IS NULL)
            OR
            (scope_type = 'WEEKDAY' AND calendar_date IS NULL AND iso_weekday BETWEEN 1 AND 7)
        ),
    CONSTRAINT CK_LecturerAvailability_Period
        CHECK (start_period BETWEEN 1 AND 16 AND end_period BETWEEN start_period AND 16),
    CONSTRAINT CK_LecturerAvailability_Type
        CHECK (availability_type IN ('UNAVAILABLE', 'DISCOURAGED', 'PREFERRED')),
    CONSTRAINT CK_LecturerAvailability_Weight
        CHECK (
            (availability_type = 'UNAVAILABLE' AND preference_weight IS NULL)
            OR
            (availability_type IN ('DISCOURAGED', 'PREFERRED') AND preference_weight IS NOT NULL AND preference_weight >= 0)
        )
);

CREATE TABLE dbo.RoomAvailability
(
    availability_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    term_code       VARCHAR(20) NOT NULL,
    room_location_id BIGINT     NOT NULL,
    scope_type      VARCHAR(20) NOT NULL,
    calendar_date   DATE        NULL,
    iso_weekday     TINYINT     NULL,
    start_period    TINYINT     NOT NULL,
    end_period      TINYINT     NOT NULL,
    availability_type VARCHAR(20) NOT NULL,
    note             NVARCHAR(255) NULL,
    CONSTRAINT FK_RoomAvailability_Term
        FOREIGN KEY (term_code) REFERENCES dbo.AcademicTerm(term_code),
    CONSTRAINT FK_RoomAvailability_Room
        FOREIGN KEY (room_location_id) REFERENCES dbo.Room(location_id),
    CONSTRAINT FK_RoomAvailability_Date
        FOREIGN KEY (term_code, calendar_date)
        REFERENCES dbo.TeachingDate(term_code, calendar_date),
    CONSTRAINT CK_RoomAvailability_Scope
        CHECK (
            (scope_type = 'DATE' AND calendar_date IS NOT NULL AND iso_weekday IS NULL)
            OR
            (scope_type = 'WEEKDAY' AND calendar_date IS NULL AND iso_weekday BETWEEN 1 AND 7)
        ),
    CONSTRAINT CK_RoomAvailability_Period
        CHECK (start_period BETWEEN 1 AND 16 AND end_period BETWEEN start_period AND 16),
    CONSTRAINT CK_RoomAvailability_Type
        CHECK (availability_type IN ('UNAVAILABLE', 'DISCOURAGED'))
);

CREATE TABLE dbo.PlanningScenario
(
    scenario_id     BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scenario_code   VARCHAR(40)   NOT NULL UNIQUE,
    scenario_name   NVARCHAR(180) NOT NULL,
    term_code       VARCHAR(20)   NOT NULL,
    scope_type      VARCHAR(20)   NOT NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'DRAFT',
    scenario_batch_code VARCHAR(40) NOT NULL,
    candidate_rank  INT           NOT NULL,
    plan_rank_penalty INT         NOT NULL DEFAULT 0,
    created_by      NVARCHAR(150) NOT NULL,
    created_at      DATETIME2     NOT NULL DEFAULT SYSDATETIME(),
    locked_by       NVARCHAR(150) NULL,
    locked_at       DATETIME2     NULL,
    note             NVARCHAR(500) NULL,
    CONSTRAINT FK_PlanningScenario_Term
        FOREIGN KEY (term_code) REFERENCES dbo.AcademicTerm(term_code),
    CONSTRAINT CK_PlanningScenario_Scope
        CHECK (scope_type IN ('FULL_TERM', 'SUBSET')),
    CONSTRAINT CK_PlanningScenario_Status
        CHECK (status IN ('DRAFT', 'READY', 'LOCKED', 'ARCHIVED')),
    CONSTRAINT UQ_PlanningScenario_BatchRank
        UNIQUE (scenario_batch_code, candidate_rank),
    CONSTRAINT CK_PlanningScenario_CandidateRank CHECK (candidate_rank >= 1),
    CONSTRAINT CK_PlanningScenario_PlanRankPenalty CHECK (plan_rank_penalty >= 0),
    CONSTRAINT CK_PlanningScenario_Lock
        CHECK (
            status <> 'LOCKED'
            OR (locked_by IS NOT NULL AND locked_at IS NOT NULL)
        )
);

CREATE TABLE dbo.PlanningScenarioItem
(
    scenario_id      BIGINT NOT NULL,
    teaching_part_id BIGINT NOT NULL,
    teaching_plan_id BIGINT NOT NULL,
    CONSTRAINT PK_PlanningScenarioItem
        PRIMARY KEY (scenario_id, teaching_part_id),
    CONSTRAINT FK_PlanningScenarioItem_Scenario
        FOREIGN KEY (scenario_id) REFERENCES dbo.PlanningScenario(scenario_id),
    CONSTRAINT FK_PlanningScenarioItem_Part
        FOREIGN KEY (teaching_part_id) REFERENCES dbo.TeachingPart(teaching_part_id),
    CONSTRAINT FK_PlanningScenarioItem_PlanBelongsToPart
        FOREIGN KEY (teaching_plan_id, teaching_part_id)
        REFERENCES dbo.TeachingPlan(teaching_plan_id, teaching_part_id),
    CONSTRAINT UQ_PlanningScenarioItem_ScenarioPlan
        UNIQUE (scenario_id, teaching_plan_id)
);

CREATE TABLE dbo.ConstraintSetting
(
    constraint_code VARCHAR(50)   NOT NULL PRIMARY KEY,
    constraint_name NVARCHAR(200) NOT NULL,
    constraint_kind VARCHAR(20)   NOT NULL,
    priority_tier   TINYINT       NOT NULL,
    weight          DECIMAL(12,4) NULL,
    threshold_value DECIMAL(12,4) NULL,
    is_enabled      BIT           NOT NULL DEFAULT 1,
    note             NVARCHAR(500) NULL,
    CONSTRAINT CK_ConstraintSetting_Kind
        CHECK (constraint_kind IN ('HARD', 'SOFT')),
    CONSTRAINT CK_ConstraintSetting_Tier CHECK (priority_tier BETWEEN 1 AND 3),
    CONSTRAINT CK_ConstraintSetting_Weight
        CHECK (weight IS NULL OR weight >= 0),
    CONSTRAINT CK_ConstraintSetting_Threshold
        CHECK (threshold_value IS NULL OR threshold_value > 0),
    CONSTRAINT CK_ConstraintSetting_HardTier
        CHECK (constraint_kind <> 'HARD' OR priority_tier = 1),
    CONSTRAINT CK_ConstraintSetting_WeightUsage
        CHECK
        (
            (constraint_kind = 'HARD' AND weight IS NULL)
            OR
            (constraint_kind = 'SOFT' AND weight IS NOT NULL AND weight > 0)
        )
);

CREATE TABLE dbo.OptimizationRun
(
    run_id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scenario_id         BIGINT       NOT NULL,
    algorithm_name      VARCHAR(30)  NOT NULL,
    population_size     INT          NOT NULL,
    max_fitness_evaluations BIGINT   NOT NULL,
    random_seed         BIGINT       NOT NULL,
    algorithm_version   VARCHAR(50)  NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    current_fitness_evaluations BIGINT NOT NULL DEFAULT 0,
    completed_iterations INT         NOT NULL DEFAULT 0,
    progress_updated_at DATETIME2    NULL,
    cancel_requested    BIT          NOT NULL DEFAULT 0,
    timeout_seconds     INT          NULL,
    request_config_json NVARCHAR(MAX) NULL,
    queued_at           DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),
    worker_id           VARCHAR(64)  NULL,
    lease_expires_at    DATETIME2    NULL,
    hard_violation_count INT         NULL,
    general_quality_score DECIMAL(18,6) NULL,
    lecturer_preference_score DECIMAL(18,6) NULL,
    fitness_breakdown_json NVARCHAR(MAX) NULL,
    snapshot_json       NVARCHAR(MAX) NOT NULL,
    snapshot_checksum   CHAR(64)      NOT NULL,
    gene_option_mapping_json NVARCHAR(MAX) NOT NULL,
    started_at          DATETIME2    NULL,
    finished_at         DATETIME2    NULL,
    error_message       NVARCHAR(MAX) NULL,
    CONSTRAINT FK_OptimizationRun_Scenario
        FOREIGN KEY (scenario_id) REFERENCES dbo.PlanningScenario(scenario_id),
    CONSTRAINT CK_OptimizationRun_Algorithm
        CHECK (algorithm_name IN ('GA', 'PO', 'GA_PO')),
    CONSTRAINT CK_OptimizationRun_Population CHECK (population_size > 0),
    CONSTRAINT CK_OptimizationRun_FE CHECK (max_fitness_evaluations > 0),
    CONSTRAINT CK_OptimizationRun_Status
        CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT')),
    CONSTRAINT CK_OptimizationRun_CurrentFE
        CHECK (current_fitness_evaluations >= 0
               AND current_fitness_evaluations <= max_fitness_evaluations),
    CONSTRAINT CK_OptimizationRun_CompletedIterations
        CHECK (completed_iterations >= 0),
    CONSTRAINT CK_OptimizationRun_Timeout
        CHECK (timeout_seconds IS NULL OR timeout_seconds > 0),
    CONSTRAINT CK_OptimizationRun_HardViolations
        CHECK (hard_violation_count IS NULL OR hard_violation_count >= 0),
    CONSTRAINT CK_OptimizationRun_GeneralScore
        CHECK (general_quality_score IS NULL OR general_quality_score >= 0),
    CONSTRAINT CK_OptimizationRun_LecturerScore
        CHECK (lecturer_preference_score IS NULL OR lecturer_preference_score >= 0),
    CONSTRAINT CK_OptimizationRun_BreakdownJson
        CHECK (fitness_breakdown_json IS NULL OR ISJSON(fitness_breakdown_json) = 1),
    CONSTRAINT CK_OptimizationRun_RequestConfigJson
        CHECK (request_config_json IS NULL OR ISJSON(request_config_json) = 1),
    CONSTRAINT CK_OptimizationRun_SnapshotJson CHECK (ISJSON(snapshot_json) = 1),
    CONSTRAINT CK_OptimizationRun_SnapshotChecksum
        CHECK (LEN(snapshot_checksum) = 64
               AND LOWER(snapshot_checksum) NOT LIKE '%[^0-9a-f]%'),
    CONSTRAINT CK_OptimizationRun_MappingJson CHECK (ISJSON(gene_option_mapping_json) = 1)
);

CREATE TABLE dbo.TimetableEntry
(
    timetable_entry_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    run_id              BIGINT      NOT NULL,
    class_session_id    BIGINT      NOT NULL,
    lecturer_code       VARCHAR(20) NOT NULL,
    term_code           VARCHAR(20) NOT NULL,
    teaching_date       DATE        NOT NULL,
    location_id         BIGINT      NOT NULL,
    location_type       VARCHAR(20) NOT NULL,
    start_period        TINYINT     NOT NULL,
    end_period          TINYINT     NOT NULL,
    CONSTRAINT FK_TimetableEntry_Run
        FOREIGN KEY (run_id) REFERENCES dbo.OptimizationRun(run_id),
    CONSTRAINT FK_TimetableEntry_SessionTerm
        FOREIGN KEY (class_session_id, term_code)
        REFERENCES dbo.ClassSession(class_session_id, term_code),
    CONSTRAINT FK_TimetableEntry_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES dbo.Lecturer(lecturer_code),
    CONSTRAINT FK_TimetableEntry_SessionLocationType
        FOREIGN KEY (class_session_id, location_type)
        REFERENCES dbo.ClassSession(class_session_id, required_location_type),
    CONSTRAINT FK_TimetableEntry_Date
        FOREIGN KEY (term_code, teaching_date)
        REFERENCES dbo.TeachingDate(term_code, calendar_date),
    CONSTRAINT FK_TimetableEntry_Location
        FOREIGN KEY (location_id, location_type)
        REFERENCES dbo.TeachingLocation(location_id, location_type),
    CONSTRAINT UQ_TimetableEntry_Run_Session UNIQUE (run_id, class_session_id),
    CONSTRAINT CK_TimetableEntry_Period
        CHECK (start_period BETWEEN 1 AND 16 AND end_period BETWEEN start_period AND 16)
);

CREATE TABLE dbo.TimetableRevision(
 revision_id BIGINT IDENTITY(1,1) PRIMARY KEY,
 run_id BIGINT NOT NULL REFERENCES dbo.OptimizationRun(run_id),
 parent_revision_id BIGINT NULL REFERENCES dbo.TimetableRevision(revision_id),
 created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
 note NVARCHAR(500) NOT NULL,
 general_quality_score FLOAT NOT NULL,
 lecturer_preference_score FLOAT NOT NULL,
 fitness_breakdown_json NVARCHAR(MAX) NOT NULL CHECK(ISJSON(fitness_breakdown_json)=1),
 CONSTRAINT UQ_TimetableRevision_Id_Run UNIQUE(revision_id,run_id)
);

CREATE TABLE dbo.TimetableRevisionEntry(
 revision_id BIGINT NOT NULL,
 run_id BIGINT NOT NULL,
 class_session_id BIGINT NOT NULL REFERENCES dbo.ClassSession(class_session_id),
 lecturer_code VARCHAR(20) NOT NULL REFERENCES dbo.Lecturer(lecturer_code),
 term_code VARCHAR(20) NOT NULL,
 teaching_date DATE NOT NULL,
 location_id BIGINT NOT NULL,
 location_type VARCHAR(20) NOT NULL,
 start_period TINYINT NOT NULL,
 end_period TINYINT NOT NULL,
 PRIMARY KEY(revision_id,class_session_id),
 FOREIGN KEY(revision_id,run_id) REFERENCES dbo.TimetableRevision(revision_id,run_id),
 FOREIGN KEY(term_code,teaching_date) REFERENCES dbo.TeachingDate(term_code,calendar_date),
 FOREIGN KEY(location_id,location_type) REFERENCES dbo.TeachingLocation(location_id,location_type),
 CHECK(start_period BETWEEN 1 AND 16 AND end_period BETWEEN start_period AND 16)
);

CREATE INDEX IX_TeachingDate_Week_Status
    ON dbo.TeachingDate(term_code, week_number, date_status, iso_weekday);

CREATE INDEX IX_CourseSection_Term
    ON dbo.CourseSection(term_code, status);

CREATE INDEX IX_TeachingPart_Section_Lecturer
    ON dbo.TeachingPart(section_code, lecturer_code);

CREATE INDEX IX_LecturerCourseCapability_Course
    ON dbo.LecturerCourseCapability(course_code, lecturer_code);

CREATE INDEX IX_TeachingPlanGenerationRule_Active
    ON dbo.TeachingPlanGenerationRule(is_active, teaching_part_id);

CREATE INDEX IX_TeachingPlanItem_Plan_Week
    ON dbo.TeachingPlanItem(teaching_plan_id, week_number, session_order_in_week);

CREATE INDEX IX_ClassSession_Plan_Week
    ON dbo.ClassSession(teaching_plan_id, term_code, week_number);

CREATE INDEX IX_LecturerAvailability_Lookup
    ON dbo.LecturerAvailability(term_code, lecturer_code, scope_type,
                            calendar_date, iso_weekday, start_period, end_period);

CREATE INDEX IX_RoomAvailability_Lookup
    ON dbo.RoomAvailability(term_code, room_location_id, scope_type,
                        calendar_date, iso_weekday, start_period, end_period);

CREATE INDEX IX_OptimizationRun_Scenario_Status
    ON dbo.OptimizationRun(scenario_id, status);

CREATE INDEX IX_TimetableEntry_Run_Date
    ON dbo.TimetableEntry(run_id, teaching_date, start_period, end_period);

CREATE INDEX IX_TimetableEntry_Run_Location_Date
    ON dbo.TimetableEntry(run_id, location_id, teaching_date, start_period, end_period);

CREATE INDEX IX_OptimizationRun_Queue ON dbo.OptimizationRun(status, cancel_requested, lease_expires_at, queued_at, run_id);

-- Executed only while creating a completely empty application database.
INSERT INTO dbo.TimePeriod(period_number, start_time, end_time, session_name) VALUES
(1,  '06:45', '07:35', 'MORNING'),
(2,  '07:35', '08:25', 'MORNING'),
(3,  '08:35', '09:25', 'MORNING'),
(4,  '09:25', '10:15', 'MORNING'),
(5,  '10:25', '11:15', 'MORNING'),
(6,  '11:15', '12:05', 'MORNING'),
(7,  '12:30', '13:20', 'AFTERNOON'),
(8,  '13:20', '14:10', 'AFTERNOON'),
(9,  '14:20', '15:10', 'AFTERNOON'),
(10, '15:10', '16:00', 'AFTERNOON'),
(11, '16:10', '17:00', 'AFTERNOON'),
(12, '17:00', '17:50', 'AFTERNOON'),
(13, '18:00', '18:50', 'EVENING'),
(14, '18:50', '19:40', 'EVENING'),
(15, '19:50', '20:40', 'EVENING'),
(16, '20:40', '21:30', 'EVENING');

INSERT INTO dbo.TeachingDurationRule(part_type, duration_periods, is_standard, note) VALUES
('LECTURE', 3, 1, N'Khung lý thuyết chuẩn'),
('LECTURE', 6, 1, N'Khung lý thuyết tăng cường được cấu hình cho phép'),
('PRACTICE', 5, 1, N'Khung thực hành chuẩn'),
('PRACTICE', 6, 1, N'Khung thực hành tăng cường được cấu hình cho phép');

INSERT INTO dbo.AllowedPeriodBlock(start_period, duration_periods, block_name) VALUES
(1, 3, N'Tiết 1-3'), (4, 3, N'Tiết 4-6'),
(7, 3, N'Tiết 7-9'), (10, 3, N'Tiết 10-12'),
(13, 3, N'Tiết 13-15'),
(1, 6, N'Tiết 1-6'), (7, 6, N'Tiết 7-12'),
(1, 5, N'Tiết 1-5'), (7, 5, N'Tiết 7-11');

INSERT INTO dbo.ConstraintSetting
    (constraint_code, constraint_name, constraint_kind, priority_tier, weight,
     threshold_value, note)
VALUES
('HARD_VALID_DATE', N'Ngày học thuộc đúng tuần hoạt động', 'HARD', 1, NULL, NULL,
 N'Ngày lễ/học bù không tham gia lọc; ngày thật dùng để kiểm tra availability DATE'),
('HARD_LECTURER_OVERLAP', N'Không trùng lịch giảng viên', 'HARD', 1, NULL, NULL,
 N'Áp dụng cả phòng vật lý và lớp trực tuyến'),
('HARD_ROOM_OVERLAP', N'Không trùng phòng vật lý', 'HARD', 1, NULL, NULL,
 N'Không áp dụng cho lớp trực tuyến'),
('HARD_AVAILABILITY', N'Tuân thủ khoảng không thể dạy/sử dụng', 'HARD', 1, NULL, NULL,
 N'UNAVAILABLE là bắt buộc'),
('HARD_LOCATION_MATCH', N'Đúng loại địa điểm, loại phòng và thiết bị', 'HARD', 1, NULL, NULL,
 N'Kiểm tra loại địa điểm, loại phòng và thiết bị bắt buộc'),
('HARD_ROOM_CAPACITY', N'Phòng đủ sức chứa lớp học phần', 'HARD', 1, NULL, NULL,
 N'Buổi vật lý yêu cầu capacity >= expected_enrollment; dữ liệu thiếu bị chặn ở readiness'),
('HARD_TRAVEL_TIME', N'Đủ thời gian di chuyển giữa các cơ sở', 'HARD', 1, NULL, NULL,
 N'Chỉ áp dụng khi phạm vi có nhiều cơ sở và đã cấu hình thời gian'),
('SOFT_LECTURER_GAP', N'Khoảng trống trong ngày của giảng viên', 'SOFT', 2, 0.3720, NULL,
 N'Chuẩn hóa bằng gap/(gap+teaching); không tính trước buổi đầu, sau buổi cuối hoặc ngày không dạy'),
('SOFT_LECTURER_CONSECUTIVE', N'Hạn chế giảng viên dạy quá nhiều tiết liên tục', 'SOFT', 2, 0.1487, 6.0000,
 N'Chỉ phạt số tiết vượt ngưỡng; ngưỡng mặc định là 6 tiết liên tục'),
('SOFT_ROOM_DISCOURAGED', N'Hạn chế dùng phòng trong khoảng DISCOURAGED', 'SOFT', 2, 0.2975, NULL,
 N'Tính theo tỷ lệ tiết vật lý chồng lên khoảng DISCOURAGED'),
('SOFT_WORKLOAD_BALANCE', N'Cân bằng khối lượng giảng dạy', 'SOFT', 2, 0.1818, NULL,
 N'Tính trên tổng số tiết được phân cho các giảng viên đủ năng lực'),
('SOFT_LECTURER_TIME_PREFERENCE', N'Mong muốn thời gian của giảng viên', 'SOFT', 3, 0.5000, NULL,
 N'Một nửa Q_lecturer; đứng sau Q_general'),
('SOFT_COURSE_SUITABILITY', N'Mức phù hợp môn và giảng viên', 'SOFT', 3, 0.5000, NULL,
 N'Một nửa Q_lecturer; 1-suitability_score là mức phạt');

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO

-- Ket qua ky vong: 34 bang, 16 tiet, 4 quy tac thoi luong, 9 khoi tiet,
-- 13 rang buoc (7 cung + 6 mem); cac bang hoc ky/giang vien/lop/run con trong.
SELECT
    (SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped=0) AS application_table_count,
    (SELECT COUNT(*) FROM dbo.TimePeriod) AS time_period_count,
    (SELECT COUNT(*) FROM dbo.TeachingDurationRule) AS duration_rule_count,
    (SELECT COUNT(*) FROM dbo.AllowedPeriodBlock) AS allowed_block_count,
    (SELECT COUNT(*) FROM dbo.ConstraintSetting) AS constraint_setting_count,
    (SELECT COUNT(*) FROM dbo.AcademicTerm) AS term_count,
    (SELECT COUNT(*) FROM dbo.OptimizationRun) AS optimization_run_count;
GO

