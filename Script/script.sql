/*
    GA-PO UNIVERSITY TIMETABLING - DEVELOPMENT RESET SCRIPT

    Current scope:
    - Create a teaching timetable before student registration.
    - No Student/StudentGroup input.
    - A lecturer is assigned to each TeachingPart before optimization.
    - A locked PlanningScenario selects one approved TeachingPlan per TeachingPart.
    - Each ClassSession is one atomic session in one TermWeek.
    - The optimizer selects the actual date, start period and teaching location.
    - Room capacity is a SOFT criterion, never a hard filtering condition.

    WARNING: rerunning this file drops and recreates all project tables.
    This file intentionally refactors the existing database directly; it does
    not create a parallel v2 schema. Review before running.
*/

USE master;
GO

IF DB_ID(N'testkhoaluan') IS NULL
BEGIN
    EXEC(N'CREATE DATABASE testkhoaluan');
END;
GO

USE testkhoaluan;
GO

/* Drop both current and legacy tables in dependency-safe order. */
DROP TABLE IF EXISTS TimetableEntry;
DROP TABLE IF EXISTS OptimizationRun;
DROP TABLE IF EXISTS ConstraintSetting;
DROP TABLE IF EXISTS PlanningScenarioItem;
DROP TABLE IF EXISTS PlanningScenario;
DROP TABLE IF EXISTS LecturerAvailability;
DROP TABLE IF EXISTS RoomAvailability;
DROP TABLE IF EXISTS ClassSession;
DROP TABLE IF EXISTS TeachingPlan;
DROP TABLE IF EXISTS TeachingPartRequiredEquipment;
DROP TABLE IF EXISTS TeachingPart;
DROP TABLE IF EXISTS RoomEquipment;
DROP TABLE IF EXISTS Equipment;

-- Legacy child tables must be removed before their parent tables.
DROP TABLE IF EXISTS TeachingEvent;
DROP TABLE IF EXISTS SectionStudentGroup;
DROP TABLE IF EXISTS StudentGroup;

DROP TABLE IF EXISTS CourseSection;
DROP TABLE IF EXISTS Course;
DROP TABLE IF EXISTS Lecturer;
DROP TABLE IF EXISTS OnlineLocation;
DROP TABLE IF EXISTS Room;
DROP TABLE IF EXISTS TeachingLocation;
DROP TABLE IF EXISTS CampusTravelTime;
DROP TABLE IF EXISTS Campus;
DROP TABLE IF EXISTS AllowedPeriodBlock;
DROP TABLE IF EXISTS TeachingDurationRule;
DROP TABLE IF EXISTS TeachingDate;
DROP TABLE IF EXISTS TimePeriod;
DROP TABLE IF EXISTS TermWeek;
DROP TABLE IF EXISTS TimeSlot; -- legacy
DROP TABLE IF EXISTS AcademicTerm;
GO

/* Academic calendar. The core stores actual dates and ISO weekday 1..7. */
CREATE TABLE AcademicTerm
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

CREATE TABLE TermWeek
(
    term_code       VARCHAR(20) NOT NULL,
    week_number     INT         NOT NULL,
    start_date      DATE        NOT NULL,
    end_date        DATE        NOT NULL,
    CONSTRAINT PK_TermWeek PRIMARY KEY (term_code, week_number),
    CONSTRAINT FK_TermWeek_Term
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT CK_TermWeek_Number CHECK (week_number >= 1),
    CONSTRAINT CK_TermWeek_DateRange CHECK (start_date <= end_date),
    CONSTRAINT UQ_TermWeek_Term_StartDate UNIQUE (term_code, start_date)
);

CREATE TABLE TeachingDate
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
        REFERENCES TermWeek(term_code, week_number),
    CONSTRAINT CK_TeachingDate_Weekday CHECK (iso_weekday BETWEEN 1 AND 7),
    CONSTRAINT CK_TeachingDate_Status
        CHECK (date_status IN ('NORMAL', 'HOLIDAY', 'MAKEUP_ALLOWED'))
);

CREATE TABLE TimePeriod
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

CREATE TABLE TeachingDurationRule
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

-- Authoritative list of contiguous teaching blocks permitted by the school.
CREATE TABLE AllowedPeriodBlock
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

/* Teaching locations: physical room or online class. */
CREATE TABLE Campus
(
    campus_code VARCHAR(20)   NOT NULL PRIMARY KEY,
    campus_name NVARCHAR(150) NOT NULL,
    address      NVARCHAR(255) NULL,
    is_active    BIT           NOT NULL DEFAULT 1
);

CREATE TABLE CampusTravelTime
(
    from_campus_code VARCHAR(20) NOT NULL,
    to_campus_code   VARCHAR(20) NOT NULL,
    travel_minutes   INT         NOT NULL,
    CONSTRAINT PK_CampusTravelTime PRIMARY KEY (from_campus_code, to_campus_code),
    CONSTRAINT FK_CampusTravelTime_From
        FOREIGN KEY (from_campus_code) REFERENCES Campus(campus_code),
    CONSTRAINT FK_CampusTravelTime_To
        FOREIGN KEY (to_campus_code) REFERENCES Campus(campus_code),
    CONSTRAINT CK_CampusTravelTime_Different CHECK (from_campus_code <> to_campus_code),
    CONSTRAINT CK_CampusTravelTime_Minutes CHECK (travel_minutes >= 0)
);

CREATE TABLE TeachingLocation
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

CREATE TABLE Room
(
    location_id   BIGINT      NOT NULL PRIMARY KEY,
    location_type VARCHAR(20) NOT NULL DEFAULT 'PHYSICAL_ROOM',
    campus_code   VARCHAR(20) NOT NULL,
    room_type     VARCHAR(30) NOT NULL,
    capacity      INT         NULL,
    CONSTRAINT FK_Room_Location
        FOREIGN KEY (location_id, location_type)
        REFERENCES TeachingLocation(location_id, location_type),
    CONSTRAINT FK_Room_Campus
        FOREIGN KEY (campus_code) REFERENCES Campus(campus_code),
    CONSTRAINT CK_Room_LocationType CHECK (location_type = 'PHYSICAL_ROOM'),
    CONSTRAINT CK_Room_Capacity CHECK (capacity IS NULL OR capacity > 0)
);

CREATE TABLE OnlineLocation
(
    location_id   BIGINT        NOT NULL PRIMARY KEY,
    location_type VARCHAR(20)   NOT NULL DEFAULT 'ONLINE',
    platform_name NVARCHAR(100) NOT NULL,
    meeting_note  NVARCHAR(255) NULL,
    CONSTRAINT FK_OnlineLocation_Location
        FOREIGN KEY (location_id, location_type)
        REFERENCES TeachingLocation(location_id, location_type),
    CONSTRAINT CK_OnlineLocation_Type CHECK (location_type = 'ONLINE')
);
GO

/* Core teaching domain. There is deliberately no student/group table. */
CREATE TABLE Lecturer
(
    lecturer_code  VARCHAR(20)   NOT NULL PRIMARY KEY,
    full_name      NVARCHAR(150) NOT NULL,
    email           VARCHAR(150)  NULL,
    home_campus_code VARCHAR(20)  NULL,
    is_active      BIT           NOT NULL DEFAULT 1,
    CONSTRAINT FK_Lecturer_HomeCampus
        FOREIGN KEY (home_campus_code) REFERENCES Campus(campus_code)
);

CREATE TABLE Course
(
    course_code    VARCHAR(20)   NOT NULL PRIMARY KEY,
    course_name    NVARCHAR(200) NOT NULL,
    credits        DECIMAL(4,1)  NULL,
    is_active      BIT           NOT NULL DEFAULT 1,
    CONSTRAINT CK_Course_Credits CHECK (credits IS NULL OR credits > 0)
);

CREATE TABLE CourseSection
(
    section_code        VARCHAR(30) NOT NULL PRIMARY KEY,
    term_code           VARCHAR(20) NOT NULL,
    course_code         VARCHAR(20) NOT NULL,
    section_name        NVARCHAR(150) NULL,
    expected_enrollment INT         NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'PLANNING',
    CONSTRAINT FK_CourseSection_Term
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT FK_CourseSection_Course
        FOREIGN KEY (course_code) REFERENCES Course(course_code),
    CONSTRAINT CK_CourseSection_ExpectedEnrollment
        CHECK (expected_enrollment IS NULL OR expected_enrollment > 0),
    CONSTRAINT CK_CourseSection_Status
        CHECK (status IN ('PLANNING', 'APPROVED', 'CANCELLED'))
);

CREATE TABLE Equipment
(
    equipment_code VARCHAR(30)   NOT NULL PRIMARY KEY,
    equipment_name NVARCHAR(150) NOT NULL
);

CREATE TABLE RoomEquipment
(
    room_location_id BIGINT      NOT NULL,
    equipment_code   VARCHAR(30) NOT NULL,
    quantity         INT         NOT NULL DEFAULT 1,
    CONSTRAINT PK_RoomEquipment PRIMARY KEY (room_location_id, equipment_code),
    CONSTRAINT FK_RoomEquipment_Room
        FOREIGN KEY (room_location_id) REFERENCES Room(location_id),
    CONSTRAINT FK_RoomEquipment_Equipment
        FOREIGN KEY (equipment_code) REFERENCES Equipment(equipment_code),
    CONSTRAINT CK_RoomEquipment_Quantity CHECK (quantity >= 1)
);

-- A TeachingPart is lecture/practice work of one section and has one lecturer.
CREATE TABLE TeachingPart
(
    teaching_part_id      BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    section_code          VARCHAR(30) NOT NULL,
    part_code             VARCHAR(30) NOT NULL UNIQUE,
    part_type             VARCHAR(20) NOT NULL,
    lecturer_code         VARCHAR(20) NOT NULL,
    total_periods         INT         NOT NULL,
    required_room_type    VARCHAR(30) NULL,
    required_location_type VARCHAR(20) NOT NULL DEFAULT 'PHYSICAL_ROOM',
    note                  NVARCHAR(255) NULL,
    CONSTRAINT FK_TeachingPart_Section
        FOREIGN KEY (section_code) REFERENCES CourseSection(section_code),
    CONSTRAINT FK_TeachingPart_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES Lecturer(lecturer_code),
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

CREATE TABLE TeachingPartRequiredEquipment
(
    teaching_part_id BIGINT      NOT NULL,
    equipment_code   VARCHAR(30) NOT NULL,
    minimum_quantity INT         NOT NULL DEFAULT 1,
    CONSTRAINT PK_TeachingPartRequiredEquipment
        PRIMARY KEY (teaching_part_id, equipment_code),
    CONSTRAINT FK_TPRE_Part
        FOREIGN KEY (teaching_part_id) REFERENCES TeachingPart(teaching_part_id),
    CONSTRAINT FK_TPRE_Equipment
        FOREIGN KEY (equipment_code) REFERENCES Equipment(equipment_code),
    CONSTRAINT CK_TPRE_Quantity CHECK (minimum_quantity >= 1)
);

-- One part may have several approved alternative plans.
CREATE TABLE TeachingPlan
(
    teaching_plan_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    teaching_part_id BIGINT        NOT NULL,
    plan_code        VARCHAR(40)   NOT NULL UNIQUE,
    plan_name        NVARCHAR(180) NOT NULL,
    status           VARCHAR(20)   NOT NULL DEFAULT 'DRAFT',
    allows_intensive BIT           NOT NULL DEFAULT 0,
    approved_by      NVARCHAR(150) NULL,
    approved_at      DATETIME2     NULL,
    note              NVARCHAR(500) NULL,
    CONSTRAINT FK_TeachingPlan_Part
        FOREIGN KEY (teaching_part_id) REFERENCES TeachingPart(teaching_part_id),
    CONSTRAINT UQ_TeachingPlan_Id_Part UNIQUE (teaching_plan_id, teaching_part_id),
    CONSTRAINT CK_TeachingPlan_Status
        CHECK (status IN ('DRAFT', 'APPROVED', 'RETIRED')),
    CONSTRAINT CK_TeachingPlan_Approval
        CHECK (
            status <> 'APPROVED'
            OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)
        )
);

-- Atomic unit scheduled by one gene. Duration and week are fixed by its plan.
CREATE TABLE ClassSession
(
    class_session_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    teaching_plan_id BIGINT      NOT NULL,
    session_number   INT         NOT NULL,
    term_code        VARCHAR(20) NOT NULL,
    week_number      INT         NOT NULL,
    duration_periods TINYINT     NOT NULL,
    required_location_type VARCHAR(20) NOT NULL,
    note              NVARCHAR(255) NULL,
    CONSTRAINT FK_ClassSession_Plan
        FOREIGN KEY (teaching_plan_id) REFERENCES TeachingPlan(teaching_plan_id),
    CONSTRAINT FK_ClassSession_Week
        FOREIGN KEY (term_code, week_number)
        REFERENCES TermWeek(term_code, week_number),
    CONSTRAINT UQ_ClassSession_Plan_Number
        UNIQUE (teaching_plan_id, session_number),
    CONSTRAINT UQ_ClassSession_Id_Term
        UNIQUE (class_session_id, term_code),
    CONSTRAINT UQ_ClassSession_Id_LocationType
        UNIQUE (class_session_id, required_location_type),
    CONSTRAINT CK_ClassSession_Number CHECK (session_number >= 1),
    CONSTRAINT CK_ClassSession_Duration CHECK (duration_periods BETWEEN 1 AND 16),
    CONSTRAINT CK_ClassSession_LocationType
        CHECK (required_location_type IN ('PHYSICAL_ROOM', 'ONLINE'))
);

/* Availability can target one date or recur on an ISO weekday. */
CREATE TABLE LecturerAvailability
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
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT FK_LecturerAvailability_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES Lecturer(lecturer_code),
    CONSTRAINT FK_LecturerAvailability_Date
        FOREIGN KEY (term_code, calendar_date)
        REFERENCES TeachingDate(term_code, calendar_date),
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

CREATE TABLE RoomAvailability
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
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT FK_RoomAvailability_Room
        FOREIGN KEY (room_location_id) REFERENCES Room(location_id),
    CONSTRAINT FK_RoomAvailability_Date
        FOREIGN KEY (term_code, calendar_date)
        REFERENCES TeachingDate(term_code, calendar_date),
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
GO

/* A run receives one locked scenario and one approved plan per selected part. */
CREATE TABLE PlanningScenario
(
    scenario_id     BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scenario_code   VARCHAR(40)   NOT NULL UNIQUE,
    scenario_name   NVARCHAR(180) NOT NULL,
    term_code       VARCHAR(20)   NOT NULL,
    scope_type      VARCHAR(20)   NOT NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'DRAFT',
    created_by      NVARCHAR(150) NOT NULL,
    created_at      DATETIME2     NOT NULL DEFAULT SYSDATETIME(),
    locked_by       NVARCHAR(150) NULL,
    locked_at       DATETIME2     NULL,
    note             NVARCHAR(500) NULL,
    CONSTRAINT FK_PlanningScenario_Term
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT CK_PlanningScenario_Scope
        CHECK (scope_type IN ('FULL_TERM', 'SUBSET')),
    CONSTRAINT CK_PlanningScenario_Status
        CHECK (status IN ('DRAFT', 'READY', 'LOCKED', 'ARCHIVED')),
    CONSTRAINT CK_PlanningScenario_Lock
        CHECK (
            status <> 'LOCKED'
            OR (locked_by IS NOT NULL AND locked_at IS NOT NULL)
        )
);

CREATE TABLE PlanningScenarioItem
(
    scenario_id      BIGINT NOT NULL,
    teaching_part_id BIGINT NOT NULL,
    teaching_plan_id BIGINT NOT NULL,
    CONSTRAINT PK_PlanningScenarioItem
        PRIMARY KEY (scenario_id, teaching_part_id),
    CONSTRAINT FK_PlanningScenarioItem_Scenario
        FOREIGN KEY (scenario_id) REFERENCES PlanningScenario(scenario_id),
    CONSTRAINT FK_PlanningScenarioItem_Part
        FOREIGN KEY (teaching_part_id) REFERENCES TeachingPart(teaching_part_id),
    CONSTRAINT FK_PlanningScenarioItem_PlanBelongsToPart
        FOREIGN KEY (teaching_plan_id, teaching_part_id)
        REFERENCES TeachingPlan(teaching_plan_id, teaching_part_id),
    CONSTRAINT UQ_PlanningScenarioItem_ScenarioPlan
        UNIQUE (scenario_id, teaching_plan_id)
);

-- Priority tier is already decided; final soft formulas/weights remain Gate F.
CREATE TABLE ConstraintSetting
(
    constraint_code VARCHAR(50)   NOT NULL PRIMARY KEY,
    constraint_name NVARCHAR(200) NOT NULL,
    constraint_kind VARCHAR(20)   NOT NULL,
    priority_tier   TINYINT       NOT NULL,
    weight          DECIMAL(12,4) NULL,
    is_enabled      BIT           NOT NULL DEFAULT 1,
    note             NVARCHAR(500) NULL,
    CONSTRAINT CK_ConstraintSetting_Kind
        CHECK (constraint_kind IN ('HARD', 'SOFT')),
    CONSTRAINT CK_ConstraintSetting_Tier CHECK (priority_tier BETWEEN 1 AND 3),
    CONSTRAINT CK_ConstraintSetting_Weight
        CHECK (weight IS NULL OR weight >= 0),
    CONSTRAINT CK_ConstraintSetting_HardTier
        CHECK (constraint_kind <> 'HARD' OR priority_tier = 1)
);

CREATE TABLE OptimizationRun
(
    run_id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scenario_id         BIGINT       NOT NULL,
    algorithm_name      VARCHAR(30)  NOT NULL,
    population_size     INT          NOT NULL,
    max_fitness_evaluations BIGINT   NOT NULL,
    random_seed         BIGINT       NOT NULL,
    algorithm_version   VARCHAR(50)  NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    hard_violation_count INT         NULL,
    general_quality_score DECIMAL(18,6) NULL,
    lecturer_preference_score DECIMAL(18,6) NULL,
    snapshot_json       NVARCHAR(MAX) NOT NULL,
    gene_option_mapping_json NVARCHAR(MAX) NOT NULL,
    started_at          DATETIME2    NULL,
    finished_at         DATETIME2    NULL,
    error_message       NVARCHAR(MAX) NULL,
    CONSTRAINT FK_OptimizationRun_Scenario
        FOREIGN KEY (scenario_id) REFERENCES PlanningScenario(scenario_id),
    CONSTRAINT CK_OptimizationRun_Algorithm
        CHECK (algorithm_name IN ('GA', 'PO', 'GA_PO')),
    CONSTRAINT CK_OptimizationRun_Population CHECK (population_size > 0),
    CONSTRAINT CK_OptimizationRun_FE CHECK (max_fitness_evaluations > 0),
    CONSTRAINT CK_OptimizationRun_Status
        CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    CONSTRAINT CK_OptimizationRun_HardViolations
        CHECK (hard_violation_count IS NULL OR hard_violation_count >= 0),
    CONSTRAINT CK_OptimizationRun_SnapshotJson CHECK (ISJSON(snapshot_json) = 1),
    CONSTRAINT CK_OptimizationRun_MappingJson CHECK (ISJSON(gene_option_mapping_json) = 1)
);

CREATE TABLE TimetableEntry
(
    timetable_entry_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    run_id              BIGINT      NOT NULL,
    class_session_id    BIGINT      NOT NULL,
    term_code           VARCHAR(20) NOT NULL,
    teaching_date       DATE        NOT NULL,
    location_id         BIGINT      NOT NULL,
    location_type       VARCHAR(20) NOT NULL,
    start_period        TINYINT     NOT NULL,
    end_period          TINYINT     NOT NULL,
    CONSTRAINT FK_TimetableEntry_Run
        FOREIGN KEY (run_id) REFERENCES OptimizationRun(run_id),
    CONSTRAINT FK_TimetableEntry_SessionTerm
        FOREIGN KEY (class_session_id, term_code)
        REFERENCES ClassSession(class_session_id, term_code),
    CONSTRAINT FK_TimetableEntry_SessionLocationType
        FOREIGN KEY (class_session_id, location_type)
        REFERENCES ClassSession(class_session_id, required_location_type),
    CONSTRAINT FK_TimetableEntry_Date
        FOREIGN KEY (term_code, teaching_date)
        REFERENCES TeachingDate(term_code, calendar_date),
    CONSTRAINT FK_TimetableEntry_Location
        FOREIGN KEY (location_id, location_type)
        REFERENCES TeachingLocation(location_id, location_type),
    CONSTRAINT UQ_TimetableEntry_Run_Session UNIQUE (run_id, class_session_id),
    CONSTRAINT CK_TimetableEntry_Period
        CHECK (start_period BETWEEN 1 AND 16 AND end_period BETWEEN start_period AND 16)
);
GO

/* -------------------------------------------------------------------------
   SAMPLE DATA
   This small instance exercises weeks, holidays, physical/online locations,
   soft capacity, different teaching-plan structures and lecturer preferences.
   ------------------------------------------------------------------------- */
INSERT INTO AcademicTerm(term_code, term_name, start_date, end_date, status)
VALUES ('2026_HK1', N'Học kỳ 1 năm học 2026-2027', '2026-08-17', '2026-12-20', 'PLANNING');

DECLARE @week INT = 1;
WHILE @week <= 18
BEGIN
    DECLARE @weekStart DATE = DATEADD(DAY, (@week - 1) * 7, CONVERT(DATE, '2026-08-17'));
    INSERT INTO TermWeek(term_code, week_number, start_date, end_date)
    VALUES ('2026_HK1', @week, @weekStart, DATEADD(DAY, 6, @weekStart));
    SET @week += 1;
END;

DECLARE @d DATE = '2026-08-17';
WHILE @d <= '2026-12-20'
BEGIN
    DECLARE @dayOffset INT = DATEDIFF(DAY, CONVERT(DATE, '2026-08-17'), @d);
    INSERT INTO TeachingDate(term_code, calendar_date, week_number, iso_weekday)
    VALUES
    (
        '2026_HK1',
        @d,
        (@dayOffset / 7) + 1,
        (@dayOffset % 7) + 1
    );
    SET @d = DATEADD(DAY, 1, @d);
END;

-- Holiday is on an unused sample Monday; Saturday is explicitly allowed for makeup.
UPDATE TeachingDate
SET date_status = 'HOLIDAY', note = N'Ngày nghỉ minh họa'
WHERE term_code = '2026_HK1' AND calendar_date = '2026-09-07';

UPDATE TeachingDate
SET date_status = 'MAKEUP_ALLOWED', note = N'Ngày học bù minh họa'
WHERE term_code = '2026_HK1' AND calendar_date = '2026-09-05';

INSERT INTO TimePeriod(period_number, start_time, end_time, session_name) VALUES
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

INSERT INTO TeachingDurationRule(part_type, duration_periods, is_standard, note) VALUES
('LECTURE', 3, 1, N'Khung lý thuyết chuẩn'),
('LECTURE', 6, 1, N'Khung lý thuyết tăng cường được duyệt'),
('PRACTICE', 5, 1, N'Khung thực hành chuẩn'),
('PRACTICE', 6, 1, N'Khung thực hành tăng cường được duyệt');

INSERT INTO AllowedPeriodBlock(start_period, duration_periods, block_name) VALUES
(1, 3, N'Tiết 1-3'), (4, 3, N'Tiết 4-6'),
(7, 3, N'Tiết 7-9'), (10, 3, N'Tiết 10-12'),
(13, 3, N'Tiết 13-15'),
(1, 6, N'Tiết 1-6'), (7, 6, N'Tiết 7-12'),
(1, 5, N'Tiết 1-5'), (7, 5, N'Tiết 7-11');
GO

INSERT INTO Campus(campus_code, campus_name, address) VALUES
('CS1', N'Cơ sở chính', N'140 Lê Trọng Tấn'),
('CS2', N'Cơ sở phụ', N'Địa chỉ minh họa');

-- Travel time is explicit and directional; the optimizer must not guess it.
INSERT INTO CampusTravelTime(from_campus_code, to_campus_code, travel_minutes) VALUES
('CS1', 'CS2', 45),
('CS2', 'CS1', 45);

INSERT INTO TeachingLocation(location_code, location_name, location_type) VALUES
('F201',  N'Phòng F201', 'PHYSICAL_ROOM'),
('B304',  N'Phòng B304', 'PHYSICAL_ROOM'),
('LAB_A1', N'Phòng máy A1', 'PHYSICAL_ROOM'),
('LAB_B1', N'Phòng máy B1', 'PHYSICAL_ROOM'),
('ZOOM01', N'Lớp trực tuyến Zoom 01', 'ONLINE');

INSERT INTO Room(location_id, campus_code, room_type, capacity)
SELECT location_id, 'CS1', 'LECTURE_ROOM', 80
FROM TeachingLocation WHERE location_code = 'F201';

INSERT INTO Room(location_id, campus_code, room_type, capacity)
SELECT location_id, 'CS1', 'LECTURE_ROOM', 50
FROM TeachingLocation WHERE location_code = 'B304';

INSERT INTO Room(location_id, campus_code, room_type, capacity)
SELECT location_id, 'CS1', 'COMPUTER_LAB', 40
FROM TeachingLocation WHERE location_code = 'LAB_A1';

INSERT INTO Room(location_id, campus_code, room_type, capacity)
SELECT location_id, 'CS2', 'COMPUTER_LAB', 60
FROM TeachingLocation WHERE location_code = 'LAB_B1';

INSERT INTO OnlineLocation(location_id, platform_name, meeting_note)
SELECT location_id, N'Zoom', N'Liên kết được cấp sau khi lịch được duyệt'
FROM TeachingLocation WHERE location_code = 'ZOOM01';

INSERT INTO Lecturer(lecturer_code, full_name, email, home_campus_code) VALUES
('GV01', N'Đinh Nguyễn Trọng Nghĩa', 'nghia@example.edu.vn', 'CS1'),
('GV02', N'Nguyễn Văn An', 'an@example.edu.vn', 'CS1'),
('GV03', N'Trần Thị Bình', 'binh@example.edu.vn', 'CS2');

INSERT INTO Course(course_code, course_name, credits) VALUES
('KTDL', N'Khai thác dữ liệu', 3.0),
('LTWEB', N'Lập trình Web', 3.0),
('TTNT', N'Trí tuệ nhân tạo', 3.0);

-- expected_enrollment is planning data, not actual student registration.
INSERT INTO CourseSection
    (section_code, term_code, course_code, section_name, expected_enrollment, status)
VALUES
('KTDL01', '2026_HK1', 'KTDL', N'Khai thác dữ liệu 01', 60, 'APPROVED'),
('LTWEB01', '2026_HK1', 'LTWEB', N'Lập trình Web 01', 45, 'APPROVED'),
('TTNT01', '2026_HK1', 'TTNT', N'Trí tuệ nhân tạo 01', NULL, 'APPROVED');

INSERT INTO Equipment(equipment_code, equipment_name) VALUES
('PROJECTOR', N'Máy chiếu'),
('COMPUTER', N'Máy tính thực hành');

INSERT INTO RoomEquipment(room_location_id, equipment_code, quantity)
SELECT location_id, 'PROJECTOR', 1
FROM TeachingLocation WHERE location_code IN ('F201', 'B304');

INSERT INTO RoomEquipment(room_location_id, equipment_code, quantity)
SELECT location_id, 'COMPUTER', 40
FROM TeachingLocation WHERE location_code = 'LAB_A1';

INSERT INTO RoomEquipment(room_location_id, equipment_code, quantity)
SELECT location_id, 'COMPUTER', 60
FROM TeachingLocation WHERE location_code = 'LAB_B1';

INSERT INTO TeachingPart
    (section_code, part_code, part_type, lecturer_code, total_periods,
     required_room_type, required_location_type, note)
VALUES
('KTDL01', 'KTDL01_LT', 'LECTURE', 'GV01', 45,
 'LECTURE_ROOM', 'PHYSICAL_ROOM', N'Phần lý thuyết 45 tiết'),
('LTWEB01', 'LTWEB01_TH', 'PRACTICE', 'GV02', 30,
 'COMPUTER_LAB', 'PHYSICAL_ROOM', N'Phần thực hành 30 tiết'),
('TTNT01', 'TTNT01_LT', 'LECTURE', 'GV03', 45,
 NULL, 'ONLINE', N'Phần lý thuyết trực tuyến 45 tiết');

INSERT INTO TeachingPartRequiredEquipment(teaching_part_id, equipment_code, minimum_quantity)
SELECT teaching_part_id, 'PROJECTOR', 1
FROM TeachingPart WHERE part_code = 'KTDL01_LT';

INSERT INTO TeachingPartRequiredEquipment(teaching_part_id, equipment_code, minimum_quantity)
SELECT teaching_part_id, 'COMPUTER', 40
FROM TeachingPart WHERE part_code = 'LTWEB01_TH';

INSERT INTO TeachingPlan
    (teaching_part_id, plan_code, plan_name, status, allows_intensive,
     approved_by, approved_at, note)
SELECT teaching_part_id, 'KTDL01_STANDARD', N'15 buổi x 3 tiết',
       'APPROVED', 0, N'Phòng Đào tạo', SYSDATETIME(),
       N'Kế hoạch chuẩn kéo dài 15 tuần'
FROM TeachingPart WHERE part_code = 'KTDL01_LT';

INSERT INTO TeachingPlan
    (teaching_part_id, plan_code, plan_name, status, allows_intensive,
     approved_by, approved_at, note)
SELECT teaching_part_id, 'KTDL01_ACCELERATED', N'5 buổi x 3 tiết và 5 buổi x 6 tiết',
       'APPROVED', 1, N'Phòng Đào tạo', SYSDATETIME(),
       N'Kế hoạch tăng tốc đã được duyệt, vẫn đủ 45 tiết'
FROM TeachingPart WHERE part_code = 'KTDL01_LT';

INSERT INTO TeachingPlan
    (teaching_part_id, plan_code, plan_name, status, allows_intensive,
     approved_by, approved_at, note)
SELECT teaching_part_id, 'LTWEB01_STANDARD', N'6 buổi x 5 tiết',
       'APPROVED', 0, N'Phòng Đào tạo', SYSDATETIME(),
       N'Kế hoạch thực hành 30 tiết'
FROM TeachingPart WHERE part_code = 'LTWEB01_TH';

INSERT INTO TeachingPlan
    (teaching_part_id, plan_code, plan_name, status, allows_intensive,
     approved_by, approved_at, note)
SELECT teaching_part_id, 'TTNT01_ONLINE', N'15 buổi trực tuyến x 3 tiết',
       'APPROVED', 0, N'Phòng Đào tạo', SYSDATETIME(),
       N'Kế hoạch học trực tuyến'
FROM TeachingPart WHERE part_code = 'TTNT01_LT';
GO

-- Expand every approved plan into atomic week-specific ClassSession rows.
DECLARE @standardPlan BIGINT =
    (SELECT teaching_plan_id FROM TeachingPlan WHERE plan_code = 'KTDL01_STANDARD');
DECLARE @acceleratedPlan BIGINT =
    (SELECT teaching_plan_id FROM TeachingPlan WHERE plan_code = 'KTDL01_ACCELERATED');
DECLARE @practicePlan BIGINT =
    (SELECT teaching_plan_id FROM TeachingPlan WHERE plan_code = 'LTWEB01_STANDARD');
DECLARE @onlinePlan BIGINT =
    (SELECT teaching_plan_id FROM TeachingPlan WHERE plan_code = 'TTNT01_ONLINE');

DECLARE @n INT = 1;
WHILE @n <= 15
BEGIN
    INSERT INTO ClassSession
        (teaching_plan_id, session_number, term_code, week_number,
         duration_periods, required_location_type)
    VALUES (@standardPlan, @n, '2026_HK1', @n, 3, 'PHYSICAL_ROOM');
    SET @n += 1;
END;

SET @n = 1;
WHILE @n <= 10
BEGIN
    INSERT INTO ClassSession
        (teaching_plan_id, session_number, term_code, week_number,
         duration_periods, required_location_type)
    VALUES
    (
        @acceleratedPlan, @n, '2026_HK1', @n,
        CASE WHEN @n <= 5 THEN 3 ELSE 6 END,
        'PHYSICAL_ROOM'
    );
    SET @n += 1;
END;

SET @n = 1;
WHILE @n <= 6
BEGIN
    INSERT INTO ClassSession
        (teaching_plan_id, session_number, term_code, week_number,
         duration_periods, required_location_type)
    VALUES (@practicePlan, @n, '2026_HK1', @n, 5, 'PHYSICAL_ROOM');
    SET @n += 1;
END;

SET @n = 1;
WHILE @n <= 15
BEGIN
    INSERT INTO ClassSession
        (teaching_plan_id, session_number, term_code, week_number,
         duration_periods, required_location_type)
    VALUES (@onlinePlan, @n, '2026_HK1', @n, 3, 'ONLINE');
    SET @n += 1;
END;
GO

/* Availability samples. UNAVAILABLE is hard; preferences are soft. */
INSERT INTO LecturerAvailability
    (term_code, lecturer_code, scope_type, iso_weekday,
     start_period, end_period, availability_type, preference_weight, note)
VALUES
('2026_HK1', 'GV01', 'WEEKDAY', 1, 1, 16, 'UNAVAILABLE', NULL,
 N'Giảng viên không thể dạy thứ Hai'),
('2026_HK1', 'GV01', 'WEEKDAY', 2, 1, 6, 'PREFERRED', 1.0,
 N'Giảng viên ưu tiên sáng thứ Ba'),
('2026_HK1', 'GV03', 'WEEKDAY', 3, 1, 6, 'PREFERRED', 1.0,
 N'Giảng viên ưu tiên sáng thứ Tư');

-- Exact-date example intentionally does not collide with the sample timetable.
INSERT INTO LecturerAvailability
    (term_code, lecturer_code, scope_type, calendar_date,
     start_period, end_period, availability_type, preference_weight, note)
VALUES
('2026_HK1', 'GV02', 'DATE', '2026-09-04', 1, 16,
 'UNAVAILABLE', NULL, N'Bận công tác vào thứ Sáu');

INSERT INTO RoomAvailability
    (term_code, room_location_id, scope_type, calendar_date,
     start_period, end_period, availability_type, note)
SELECT '2026_HK1', location_id, 'DATE', '2026-09-08',
       1, 16, 'UNAVAILABLE', N'Bảo trì phòng minh họa'
FROM TeachingLocation
WHERE location_code = 'B304';

INSERT INTO PlanningScenario
    (scenario_code, scenario_name, term_code, scope_type, status,
     created_by, locked_by, locked_at, note)
VALUES
('SCN_2026_HK1_FULL_01', N'Kịch bản toàn học kỳ minh họa',
 '2026_HK1', 'FULL_TERM', 'LOCKED',
 N'Phòng Đào tạo', N'Phòng Đào tạo', SYSDATETIME(),
 N'Chọn đúng một kế hoạch đã duyệt cho mỗi phần giảng dạy trong phạm vi');

DECLARE @scenarioId BIGINT =
    (SELECT scenario_id FROM PlanningScenario WHERE scenario_code = 'SCN_2026_HK1_FULL_01');

INSERT INTO PlanningScenarioItem(scenario_id, teaching_part_id, teaching_plan_id)
SELECT @scenarioId, p.teaching_part_id, pl.teaching_plan_id
FROM TeachingPart p
JOIN TeachingPlan pl ON pl.teaching_part_id = p.teaching_part_id
WHERE pl.plan_code IN ('KTDL01_STANDARD', 'LTWEB01_STANDARD', 'TTNT01_ONLINE');

-- Final soft weights are intentionally NULL until Gate F is approved.
INSERT INTO ConstraintSetting
    (constraint_code, constraint_name, constraint_kind, priority_tier, weight, note)
VALUES
('HARD_VALID_DATE', N'Ngày học được phép trong đúng tuần', 'HARD', 1, NULL,
 N'Không xếp vào ngày nghỉ và không ra ngoài tuần của buổi'),
('HARD_LECTURER_OVERLAP', N'Không trùng lịch giảng viên', 'HARD', 1, NULL,
 N'Áp dụng cả phòng vật lý và lớp trực tuyến'),
('HARD_ROOM_OVERLAP', N'Không trùng phòng vật lý', 'HARD', 1, NULL,
 N'Không áp dụng cho lớp trực tuyến'),
('HARD_AVAILABILITY', N'Tuân thủ khoảng không thể dạy/sử dụng', 'HARD', 1, NULL,
 N'UNAVAILABLE là bắt buộc'),
('HARD_LOCATION_MATCH', N'Đúng loại địa điểm, loại phòng và thiết bị', 'HARD', 1, NULL,
 N'Không dùng capacity như điều kiện cứng'),
('HARD_TRAVEL_TIME', N'Đủ thời gian di chuyển giữa các cơ sở', 'HARD', 1, NULL,
 N'Chỉ áp dụng khi phạm vi có nhiều cơ sở và đã cấu hình thời gian'),
('SOFT_GENERAL_QUALITY', N'Chất lượng chung của lịch', 'SOFT', 2, NULL,
 N'Công thức và trọng số chi tiết sẽ chốt tại Gate F'),
('SOFT_CAPACITY', N'Mức thiếu sức chứa phòng vật lý', 'SOFT', 2, NULL,
 N'Bỏ qua khi expected_enrollment hoặc capacity là NULL; không áp dụng ONLINE'),
('SOFT_LECTURER_PREFERENCE', N'Mong muốn thời gian của giảng viên', 'SOFT', 3, NULL,
 N'Không được lấn át chất lượng chung; công thức chi tiết chốt tại Gate F');
GO

/* One manually constructed sample result for query/UI development.
   It is not claimed to be an optimizer benchmark result. */
DECLARE @scenarioId BIGINT =
    (SELECT scenario_id FROM PlanningScenario WHERE scenario_code = 'SCN_2026_HK1_FULL_01');

INSERT INTO OptimizationRun
    (scenario_id, algorithm_name, population_size, max_fitness_evaluations,
     random_seed, algorithm_version, status, hard_violation_count,
     general_quality_score, lecturer_preference_score,
     snapshot_json, gene_option_mapping_json, started_at, finished_at)
VALUES
(@scenarioId, 'GA_PO', 30, 10000, 20260917, 'sample-manual-1', 'COMPLETED', 0,
 NULL, NULL,
 N'{"purpose":"sample database output; not an optimizer benchmark"}',
 N'{"mapping":"generated from selected scenario sessions"}',
 SYSDATETIME(), SYSDATETIME());

DECLARE @runId BIGINT = SCOPE_IDENTITY();

-- KTDL: Tuesday, periods 1-3, F201, weeks 1-15.
INSERT INTO TimetableEntry
    (run_id, class_session_id, term_code, teaching_date,
     location_id, location_type, start_period, end_period)
SELECT
    @runId,
    cs.class_session_id,
    cs.term_code,
    DATEADD(DAY, 1, tw.start_date),
    tl.location_id,
    tl.location_type,
    1,
    3
FROM ClassSession cs
JOIN TeachingPlan pl ON pl.teaching_plan_id = cs.teaching_plan_id
JOIN TermWeek tw
    ON tw.term_code = cs.term_code AND tw.week_number = cs.week_number
CROSS JOIN TeachingLocation tl
WHERE pl.plan_code = 'KTDL01_STANDARD'
  AND tl.location_code = 'F201';

-- LTWEB: Thursday, periods 7-11, LAB_A1, weeks 1-6.
-- Capacity is 40 while expected enrollment is 45: still valid, but penalized softly.
INSERT INTO TimetableEntry
    (run_id, class_session_id, term_code, teaching_date,
     location_id, location_type, start_period, end_period)
SELECT
    @runId,
    cs.class_session_id,
    cs.term_code,
    DATEADD(DAY, 3, tw.start_date),
    tl.location_id,
    tl.location_type,
    7,
    11
FROM ClassSession cs
JOIN TeachingPlan pl ON pl.teaching_plan_id = cs.teaching_plan_id
JOIN TermWeek tw
    ON tw.term_code = cs.term_code AND tw.week_number = cs.week_number
CROSS JOIN TeachingLocation tl
WHERE pl.plan_code = 'LTWEB01_STANDARD'
  AND tl.location_code = 'LAB_A1';

-- TTNT: Wednesday, periods 1-3, online, weeks 1-15.
INSERT INTO TimetableEntry
    (run_id, class_session_id, term_code, teaching_date,
     location_id, location_type, start_period, end_period)
SELECT
    @runId,
    cs.class_session_id,
    cs.term_code,
    DATEADD(DAY, 2, tw.start_date),
    tl.location_id,
    tl.location_type,
    1,
    3
FROM ClassSession cs
JOIN TeachingPlan pl ON pl.teaching_plan_id = cs.teaching_plan_id
JOIN TermWeek tw
    ON tw.term_code = cs.term_code AND tw.week_number = cs.week_number
CROSS JOIN TeachingLocation tl
WHERE pl.plan_code = 'TTNT01_ONLINE'
  AND tl.location_code = 'ZOOM01';
GO

/* Indexes for option generation, validation and lecturer timetable views. */
CREATE INDEX IX_TeachingDate_Week_Status
    ON TeachingDate(term_code, week_number, date_status, iso_weekday);

CREATE INDEX IX_CourseSection_Term
    ON CourseSection(term_code, status);

CREATE INDEX IX_TeachingPart_Section_Lecturer
    ON TeachingPart(section_code, lecturer_code);

CREATE INDEX IX_ClassSession_Plan_Week
    ON ClassSession(teaching_plan_id, term_code, week_number);

CREATE INDEX IX_LecturerAvailability_Lookup
    ON LecturerAvailability(term_code, lecturer_code, scope_type,
                            calendar_date, iso_weekday, start_period, end_period);

CREATE INDEX IX_RoomAvailability_Lookup
    ON RoomAvailability(term_code, room_location_id, scope_type,
                        calendar_date, iso_weekday, start_period, end_period);

CREATE INDEX IX_OptimizationRun_Scenario_Status
    ON OptimizationRun(scenario_id, status);

CREATE INDEX IX_TimetableEntry_Run_Date
    ON TimetableEntry(run_id, teaching_date, start_period, end_period);

CREATE INDEX IX_TimetableEntry_Run_Location_Date
    ON TimetableEntry(run_id, location_id, teaching_date, start_period, end_period);
GO

/* -------------------------------------------------------------------------
   READ-ONLY VERIFICATION QUERIES
   These queries do not prove every business rule, but expose common data
   errors immediately after a manual execution of this script.
   ------------------------------------------------------------------------- */
SELECT 'AcademicTerm' AS table_name, COUNT(*) AS row_count FROM AcademicTerm
UNION ALL SELECT 'TermWeek', COUNT(*) FROM TermWeek
UNION ALL SELECT 'TeachingDate', COUNT(*) FROM TeachingDate
UNION ALL SELECT 'TimePeriod', COUNT(*) FROM TimePeriod
UNION ALL SELECT 'TeachingLocation', COUNT(*) FROM TeachingLocation
UNION ALL SELECT 'CourseSection', COUNT(*) FROM CourseSection
UNION ALL SELECT 'TeachingPart', COUNT(*) FROM TeachingPart
UNION ALL SELECT 'TeachingPlan', COUNT(*) FROM TeachingPlan
UNION ALL SELECT 'ClassSession', COUNT(*) FROM ClassSession
UNION ALL SELECT 'PlanningScenario', COUNT(*) FROM PlanningScenario
UNION ALL SELECT 'PlanningScenarioItem', COUNT(*) FROM PlanningScenarioItem
UNION ALL SELECT 'OptimizationRun', COUNT(*) FROM OptimizationRun
UNION ALL SELECT 'TimetableEntry', COUNT(*) FROM TimetableEntry;

-- Every plan must exactly match the total periods required by its TeachingPart.
SELECT
    pl.plan_code,
    p.total_periods AS required_periods,
    SUM(cs.duration_periods) AS planned_periods,
    CASE WHEN SUM(cs.duration_periods) = p.total_periods THEN 'OK' ELSE 'MISMATCH' END AS validation_result
FROM TeachingPlan pl
JOIN TeachingPart p ON p.teaching_part_id = pl.teaching_part_id
LEFT JOIN ClassSession cs ON cs.teaching_plan_id = pl.teaching_plan_id
GROUP BY pl.plan_code, p.total_periods
ORDER BY pl.plan_code;

-- A complete run should contain exactly one timetable entry per selected session.
SELECT
    r.run_id,
    expected.expected_sessions,
    actual.actual_entries,
    CASE WHEN expected.expected_sessions = actual.actual_entries THEN 'OK' ELSE 'MISMATCH' END AS validation_result
FROM OptimizationRun r
CROSS APPLY
(
    SELECT COUNT(*) AS expected_sessions
    FROM PlanningScenarioItem psi
    JOIN ClassSession cs ON cs.teaching_plan_id = psi.teaching_plan_id
    WHERE psi.scenario_id = r.scenario_id
) expected
CROSS APPLY
(
    SELECT COUNT(*) AS actual_entries
    FROM TimetableEntry te
    WHERE te.run_id = r.run_id
) actual;

-- Lecturer timetable view: suitable for the requested lecturer-based demo.
SELECT
    l.full_name AS lecturer_name,
    c.course_name,
    csn.section_code,
    p.part_type,
    te.teaching_date,
    td.week_number,
    td.iso_weekday,
    te.start_period,
    te.end_period,
    loc.location_name,
    loc.location_type
FROM TimetableEntry te
JOIN ClassSession ses ON ses.class_session_id = te.class_session_id
JOIN TeachingPlan pl ON pl.teaching_plan_id = ses.teaching_plan_id
JOIN TeachingPart p ON p.teaching_part_id = pl.teaching_part_id
JOIN CourseSection csn ON csn.section_code = p.section_code
JOIN Course c ON c.course_code = csn.course_code
JOIN Lecturer l ON l.lecturer_code = p.lecturer_code
JOIN TeachingDate td
    ON td.term_code = te.term_code AND td.calendar_date = te.teaching_date
JOIN TeachingLocation loc ON loc.location_id = te.location_id
ORDER BY l.full_name, te.teaching_date, te.start_period;
GO
