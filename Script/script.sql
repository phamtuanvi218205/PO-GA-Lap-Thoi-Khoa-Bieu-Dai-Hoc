/*
    University Timetabling Database for the GA-PO thesis project.

    DEVELOPMENT RESET SCRIPT
    ------------------------
    This script creates the database when it does not exist, then drops and
    recreates the project tables. Running it again deletes data in those tables.
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

-- Drop dependent tables first so the script can be rerun during development.
DROP TABLE IF EXISTS TimetableEntry;
DROP TABLE IF EXISTS OptimizationRun;
DROP TABLE IF EXISTS ConstraintSetting;
DROP TABLE IF EXISTS RoomAvailability;
DROP TABLE IF EXISTS LecturerAvailability;
DROP TABLE IF EXISTS TeachingEvent;
DROP TABLE IF EXISTS SectionStudentGroup;
DROP TABLE IF EXISTS CourseSection;
DROP TABLE IF EXISTS StudentGroup;
DROP TABLE IF EXISTS Course;
DROP TABLE IF EXISTS Lecturer;
DROP TABLE IF EXISTS Room;
DROP TABLE IF EXISTS TimeSlot;
DROP TABLE IF EXISTS AcademicTerm;
GO

-- =========================================================
-- MASTER DATA
-- =========================================================

CREATE TABLE AcademicTerm (
    term_code VARCHAR(20) PRIMARY KEY,
    term_name NVARCHAR(100) NOT NULL,
    academic_year VARCHAR(9) NOT NULL,
    semester INT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    is_active BIT NOT NULL CONSTRAINT DF_AcademicTerm_IsActive DEFAULT 0,
    CONSTRAINT CK_AcademicTerm_Semester CHECK (semester BETWEEN 1 AND 3),
    CONSTRAINT CK_AcademicTerm_DateRange CHECK (end_date >= start_date)
);

CREATE TABLE TimeSlot (
    time_slot_id INT IDENTITY(1,1) PRIMARY KEY,
    term_code VARCHAR(20) NOT NULL,
    day_of_week INT NOT NULL,
    period_number INT NOT NULL,
    start_time TIME(0) NOT NULL,
    end_time TIME(0) NOT NULL,
    session_type VARCHAR(20) NOT NULL,
    is_teaching_slot BIT NOT NULL CONSTRAINT DF_TimeSlot_IsTeachingSlot DEFAULT 1,
    CONSTRAINT FK_TimeSlot_AcademicTerm
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT UQ_TimeSlot_Term_Day_Period
        UNIQUE (term_code, day_of_week, period_number),
    CONSTRAINT CK_TimeSlot_Day CHECK (day_of_week BETWEEN 2 AND 7),
    CONSTRAINT CK_TimeSlot_Period CHECK (period_number BETWEEN 1 AND 15),
    CONSTRAINT CK_TimeSlot_TimeRange CHECK (end_time > start_time),
    CONSTRAINT CK_TimeSlot_Session
        CHECK (session_type IN ('MORNING', 'AFTERNOON', 'EVENING'))
);

CREATE TABLE Room (
    room_code VARCHAR(20) PRIMARY KEY,
    room_name NVARCHAR(100) NOT NULL,
    capacity INT NOT NULL,
    room_type VARCHAR(30) NOT NULL,
    building_name NVARCHAR(100) NOT NULL,
    campus_name NVARCHAR(100) NOT NULL,
    is_active BIT NOT NULL CONSTRAINT DF_Room_IsActive DEFAULT 1,
    CONSTRAINT CK_Room_Capacity CHECK (capacity > 0),
    CONSTRAINT CK_Room_Type
        CHECK (room_type IN ('LECTURE', 'COMPUTER_LAB'))
);

CREATE TABLE Lecturer (
    lecturer_code VARCHAR(20) PRIMARY KEY,
    lecturer_name NVARCHAR(100) NOT NULL,
    academic_title NVARCHAR(50),
    is_active BIT NOT NULL CONSTRAINT DF_Lecturer_IsActive DEFAULT 1
);

CREATE TABLE Course (
    course_code VARCHAR(20) PRIMARY KEY,
    course_name NVARCHAR(150) NOT NULL,
    credits INT NOT NULL,
    CONSTRAINT CK_Course_Credits CHECK (credits BETWEEN 1 AND 10)
);

CREATE TABLE StudentGroup (
    group_code VARCHAR(20) PRIMARY KEY,
    group_name NVARCHAR(100) NOT NULL,
    program_name NVARCHAR(100) NOT NULL,
    cohort_year INT NOT NULL,
    group_size INT NOT NULL,
    CONSTRAINT CK_StudentGroup_CohortYear CHECK (cohort_year BETWEEN 2000 AND 2100),
    CONSTRAINT CK_StudentGroup_Size CHECK (group_size > 0)
);

CREATE TABLE CourseSection (
    section_code VARCHAR(20) PRIMARY KEY,
    term_code VARCHAR(20) NOT NULL,
    course_code VARCHAR(20) NOT NULL,
    lecturer_code VARCHAR(20) NOT NULL,
    enrollment INT NOT NULL,
    CONSTRAINT FK_CourseSection_AcademicTerm
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT FK_CourseSection_Course
        FOREIGN KEY (course_code) REFERENCES Course(course_code),
    CONSTRAINT FK_CourseSection_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES Lecturer(lecturer_code),
    CONSTRAINT CK_CourseSection_Enrollment CHECK (enrollment > 0)
);

CREATE TABLE SectionStudentGroup (
    section_group_id INT IDENTITY(1,1) PRIMARY KEY,
    section_code VARCHAR(20) NOT NULL,
    group_code VARCHAR(20) NOT NULL,
    CONSTRAINT FK_SectionStudentGroup_CourseSection
        FOREIGN KEY (section_code) REFERENCES CourseSection(section_code),
    CONSTRAINT FK_SectionStudentGroup_StudentGroup
        FOREIGN KEY (group_code) REFERENCES StudentGroup(group_code),
    CONSTRAINT UQ_SectionStudentGroup UNIQUE (section_code, group_code)
);

/*
    A TeachingEvent is one meeting that must be placed in the timetable.
    One CourseSection can therefore produce multiple genes/chromosome dimensions.
*/
CREATE TABLE TeachingEvent (
    event_id INT IDENTITY(1,1) PRIMARY KEY,
    section_code VARCHAR(20) NOT NULL,
    event_number INT NOT NULL,
    duration_periods INT NOT NULL,
    required_room_type VARCHAR(30) NOT NULL,
    CONSTRAINT FK_TeachingEvent_CourseSection
        FOREIGN KEY (section_code) REFERENCES CourseSection(section_code),
    CONSTRAINT UQ_TeachingEvent_Section_Number
        UNIQUE (section_code, event_number),
    CONSTRAINT CK_TeachingEvent_Number CHECK (event_number > 0),
    CONSTRAINT CK_TeachingEvent_Duration CHECK (duration_periods BETWEEN 1 AND 5),
    CONSTRAINT CK_TeachingEvent_RoomType
        CHECK (required_room_type IN ('LECTURE', 'COMPUTER_LAB'))
);

-- =========================================================
-- AVAILABILITY AND FITNESS CONFIGURATION
-- =========================================================

CREATE TABLE LecturerAvailability (
    lecturer_availability_id INT IDENTITY(1,1) PRIMARY KEY,
    lecturer_code VARCHAR(20) NOT NULL,
    term_code VARCHAR(20) NOT NULL,
    day_of_week INT NOT NULL,
    start_period INT NOT NULL,
    end_period INT NOT NULL,
    availability_type VARCHAR(20) NOT NULL,
    preference_weight INT NOT NULL CONSTRAINT DF_LecturerAvailability_Weight DEFAULT 1,
    CONSTRAINT FK_LecturerAvailability_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES Lecturer(lecturer_code),
    CONSTRAINT FK_LecturerAvailability_AcademicTerm
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT CK_LecturerAvailability_Day CHECK (day_of_week BETWEEN 2 AND 7),
    CONSTRAINT CK_LecturerAvailability_Start CHECK (start_period BETWEEN 1 AND 15),
    CONSTRAINT CK_LecturerAvailability_End CHECK (end_period BETWEEN 1 AND 15),
    CONSTRAINT CK_LecturerAvailability_Range CHECK (end_period >= start_period),
    CONSTRAINT CK_LecturerAvailability_Type
        CHECK (availability_type IN ('UNAVAILABLE', 'DISCOURAGED', 'PREFERRED')),
    CONSTRAINT CK_LecturerAvailability_Weight CHECK (preference_weight BETWEEN 1 AND 100)
);

CREATE TABLE RoomAvailability (
    room_availability_id INT IDENTITY(1,1) PRIMARY KEY,
    room_code VARCHAR(20) NOT NULL,
    term_code VARCHAR(20) NOT NULL,
    day_of_week INT NOT NULL,
    start_period INT NOT NULL,
    end_period INT NOT NULL,
    availability_type VARCHAR(20) NOT NULL,
    preference_weight INT NOT NULL CONSTRAINT DF_RoomAvailability_Weight DEFAULT 1,
    CONSTRAINT FK_RoomAvailability_Room
        FOREIGN KEY (room_code) REFERENCES Room(room_code),
    CONSTRAINT FK_RoomAvailability_AcademicTerm
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT CK_RoomAvailability_Day CHECK (day_of_week BETWEEN 2 AND 7),
    CONSTRAINT CK_RoomAvailability_Start CHECK (start_period BETWEEN 1 AND 15),
    CONSTRAINT CK_RoomAvailability_End CHECK (end_period BETWEEN 1 AND 15),
    CONSTRAINT CK_RoomAvailability_Range CHECK (end_period >= start_period),
    CONSTRAINT CK_RoomAvailability_Type
        CHECK (availability_type IN ('UNAVAILABLE', 'DISCOURAGED', 'PREFERRED')),
    CONSTRAINT CK_RoomAvailability_Weight CHECK (preference_weight BETWEEN 1 AND 100)
);

CREATE TABLE ConstraintSetting (
    constraint_setting_id INT IDENTITY(1,1) PRIMARY KEY,
    term_code VARCHAR(20) NOT NULL,
    constraint_code VARCHAR(30) NOT NULL,
    constraint_name NVARCHAR(150) NOT NULL,
    constraint_type VARCHAR(10) NOT NULL,
    weight_value DECIMAL(12,4) NOT NULL,
    is_enabled BIT NOT NULL CONSTRAINT DF_ConstraintSetting_IsEnabled DEFAULT 1,
    description NVARCHAR(500),
    CONSTRAINT FK_ConstraintSetting_AcademicTerm
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT UQ_ConstraintSetting_Term_Code
        UNIQUE (term_code, constraint_code),
    CONSTRAINT CK_ConstraintSetting_Type CHECK (constraint_type IN ('HARD', 'SOFT')),
    CONSTRAINT CK_ConstraintSetting_Weight CHECK (weight_value >= 0)
);

-- =========================================================
-- OPTIMIZATION RUNS AND RESULTS
-- =========================================================

CREATE TABLE OptimizationRun (
    run_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    term_code VARCHAR(20) NOT NULL,
    algorithm VARCHAR(20) NOT NULL,
    population_size INT,
    max_iterations INT,
    ga_population_ratio DECIMAL(5,4),
    random_seed BIGINT,
    best_fitness FLOAT,
    hard_violation_count INT,
    soft_penalty FLOAT,
    execution_time_ms BIGINT,
    status VARCHAR(20) NOT NULL,
    algorithm_parameters NVARCHAR(MAX),
    created_at DATETIME2(0) NOT NULL CONSTRAINT DF_OptimizationRun_CreatedAt DEFAULT SYSDATETIME(),
    completed_at DATETIME2(0),
    CONSTRAINT FK_OptimizationRun_AcademicTerm
        FOREIGN KEY (term_code) REFERENCES AcademicTerm(term_code),
    CONSTRAINT CK_OptimizationRun_Algorithm CHECK (algorithm IN ('GA', 'PO', 'GA_PO')),
    CONSTRAINT CK_OptimizationRun_Population CHECK (population_size IS NULL OR population_size > 0),
    CONSTRAINT CK_OptimizationRun_Iterations CHECK (max_iterations IS NULL OR max_iterations > 0),
    CONSTRAINT CK_OptimizationRun_GaRatio
        CHECK (ga_population_ratio IS NULL OR ga_population_ratio BETWEEN 0 AND 1),
    CONSTRAINT CK_OptimizationRun_HardViolations
        CHECK (hard_violation_count IS NULL OR hard_violation_count >= 0),
    CONSTRAINT CK_OptimizationRun_Status
        CHECK (status IN ('DRAFT', 'RUNNING', 'COMPLETED', 'FAILED'))
);

CREATE TABLE TimetableEntry (
    timetable_entry_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    run_id BIGINT NOT NULL,
    event_id INT NOT NULL,
    room_code VARCHAR(20) NOT NULL,
    day_of_week INT NOT NULL,
    start_period INT NOT NULL,
    end_period INT NOT NULL,
    is_locked BIT NOT NULL CONSTRAINT DF_TimetableEntry_IsLocked DEFAULT 0,
    CONSTRAINT FK_TimetableEntry_OptimizationRun
        FOREIGN KEY (run_id) REFERENCES OptimizationRun(run_id),
    CONSTRAINT FK_TimetableEntry_TeachingEvent
        FOREIGN KEY (event_id) REFERENCES TeachingEvent(event_id),
    CONSTRAINT FK_TimetableEntry_Room
        FOREIGN KEY (room_code) REFERENCES Room(room_code),
    CONSTRAINT UQ_TimetableEntry_Run_Event UNIQUE (run_id, event_id),
    CONSTRAINT CK_TimetableEntry_Day CHECK (day_of_week BETWEEN 2 AND 7),
    CONSTRAINT CK_TimetableEntry_Start CHECK (start_period BETWEEN 1 AND 15),
    CONSTRAINT CK_TimetableEntry_End CHECK (end_period BETWEEN 1 AND 15),
    CONSTRAINT CK_TimetableEntry_Range CHECK (end_period >= start_period)
);
GO

-- =========================================================
-- SAMPLE DATA
-- =========================================================

INSERT INTO AcademicTerm (
    term_code, term_name, academic_year, semester, start_date, end_date, is_active
) VALUES
('2026_HK1', N'Semester 1 - Academic year 2026-2027', '2026-2027', 1, '2026-08-17', '2026-12-20', 1);

-- Six teaching days, each with five morning, five afternoon and five evening periods.
INSERT INTO TimeSlot (
    term_code, day_of_week, period_number, start_time, end_time, session_type
)
SELECT
    '2026_HK1',
    d.day_of_week,
    p.period_number,
    p.start_time,
    p.end_time,
    p.session_type
FROM (VALUES (2), (3), (4), (5), (6), (7)) AS d(day_of_week)
CROSS JOIN (VALUES
    (1,  CAST('07:00' AS TIME), CAST('07:50' AS TIME), 'MORNING'),
    (2,  CAST('07:50' AS TIME), CAST('08:40' AS TIME), 'MORNING'),
    (3,  CAST('09:00' AS TIME), CAST('09:50' AS TIME), 'MORNING'),
    (4,  CAST('09:50' AS TIME), CAST('10:40' AS TIME), 'MORNING'),
    (5,  CAST('10:50' AS TIME), CAST('11:40' AS TIME), 'MORNING'),
    (6,  CAST('13:00' AS TIME), CAST('13:50' AS TIME), 'AFTERNOON'),
    (7,  CAST('13:50' AS TIME), CAST('14:40' AS TIME), 'AFTERNOON'),
    (8,  CAST('15:00' AS TIME), CAST('15:50' AS TIME), 'AFTERNOON'),
    (9,  CAST('15:50' AS TIME), CAST('16:40' AS TIME), 'AFTERNOON'),
    (10, CAST('16:50' AS TIME), CAST('17:40' AS TIME), 'AFTERNOON'),
    (11, CAST('18:00' AS TIME), CAST('18:50' AS TIME), 'EVENING'),
    (12, CAST('18:50' AS TIME), CAST('19:40' AS TIME), 'EVENING'),
    (13, CAST('19:50' AS TIME), CAST('20:40' AS TIME), 'EVENING'),
    (14, CAST('20:40' AS TIME), CAST('21:30' AS TIME), 'EVENING'),
    (15, CAST('21:30' AS TIME), CAST('22:20' AS TIME), 'EVENING')
) AS p(period_number, start_time, end_time, session_type);

INSERT INTO Room (
    room_code, room_name, capacity, room_type, building_name, campus_name
) VALUES
('F_201', N'Room F.201', 50, 'LECTURE', N'Building F', N'Main Campus'),
('F_202', N'Room F.202', 50, 'LECTURE', N'Building F', N'Main Campus'),
('F_203', N'Room F.203', 60, 'LECTURE', N'Building F', N'Main Campus'),
('F_204', N'Room F.204', 60, 'LECTURE', N'Building F', N'Main Campus'),
('F_301', N'Room F.301', 80, 'LECTURE', N'Building F', N'Main Campus'),
('F_302', N'Room F.302', 80, 'LECTURE', N'Building F', N'Main Campus'),
('F_303', N'Room F.303', 100, 'LECTURE', N'Building F', N'Main Campus'),
('F_304', N'Room F.304', 100, 'LECTURE', N'Building F', N'Main Campus'),
('F_401', N'Room F.401', 40, 'LECTURE', N'Building F', N'Main Campus'),
('F_402', N'Room F.402', 40, 'LECTURE', N'Building F', N'Main Campus'),
('PM_101', N'Computer Lab 101', 45, 'COMPUTER_LAB', N'Practice Building', N'Main Campus'),
('PM_102', N'Computer Lab 102', 45, 'COMPUTER_LAB', N'Practice Building', N'Main Campus'),
('PM_201', N'Computer Lab 201', 45, 'COMPUTER_LAB', N'Practice Building', N'Main Campus'),
('PM_202', N'Computer Lab 202', 45, 'COMPUTER_LAB', N'Practice Building', N'Main Campus'),
('PM_301', N'Computer Lab 301', 60, 'COMPUTER_LAB', N'Practice Building', N'Main Campus');

INSERT INTO Lecturer (lecturer_code, lecturer_name, academic_title) VALUES
('GV01', N'Nguyen Van Tri', N'PhD'),
('GV02', N'Tran Thi Minh', N'MSc'),
('GV03', N'Le Tuan Anh', N'Assoc. Prof., PhD'),
('GV04', N'Pham Hoang Hai', N'MSc'),
('GV05', N'Hoang Thanh Ngoc', N'PhD'),
('GV06', N'Do Quang Huy', N'MSc'),
('GV07', N'Vu Thi Lan', N'MSc'),
('GV08', N'Ngo Tan Phat', N'PhD'),
('GV09', N'Dinh Xuan Bach', N'MSc'),
('GV10', N'Bui Kim Yen', N'MSc'),
('GV11', N'Ly Cong Bang', N'PhD'),
('GV12', N'Phan Thanh Tuan', N'MSc');

INSERT INTO Course (course_code, course_name, credits) VALUES
('INT_AI', N'Artificial Intelligence', 3),
('INT_DM', N'Data Mining', 3),
('SE_JAVA', N'Java Backend Programming', 3),
('SE_MOB', N'Cross-platform Mobile Programming', 3),
('DB_SQL', N'Database Management Systems', 3),
('CS_DSA', N'Data Structures and Algorithms', 3),
('CS_OS', N'Operating Systems', 3),
('SE_SAD', N'Systems Analysis and Design', 3),
('INT_ML', N'Machine Learning Fundamentals', 3),
('CS_NW', N'Computer Networks', 3);

INSERT INTO StudentGroup (
    group_code, group_name, program_name, cohort_year, group_size
) VALUES
('CNTT16A', N'Information Technology 16A', N'Information Technology', 2024, 40),
('CNTT16B', N'Information Technology 16B', N'Information Technology', 2024, 40),
('KTPM16A', N'Software Engineering 16A', N'Software Engineering', 2024, 40),
('KTPM16B', N'Software Engineering 16B', N'Software Engineering', 2024, 40),
('HTTT16A', N'Information Systems 16A', N'Information Systems', 2024, 40),
('KHMT16A', N'Computer Science 16A', N'Computer Science', 2024, 40);

INSERT INTO CourseSection (
    section_code, term_code, course_code, lecturer_code, enrollment
) VALUES
('INT_AI_01', '2026_HK1', 'INT_AI', 'GV01', 80),
('INT_AI_02', '2026_HK1', 'INT_AI', 'GV03', 80),
('INT_AI_03', '2026_HK1', 'INT_AI', 'GV03', 40),
('INT_DM_01', '2026_HK1', 'INT_DM', 'GV08', 40),
('INT_DM_02', '2026_HK1', 'INT_DM', 'GV11', 40),
('SE_JAVA_01', '2026_HK1', 'SE_JAVA', 'GV04', 40),
('SE_JAVA_02', '2026_HK1', 'SE_JAVA', 'GV06', 40),
('SE_MOB_01', '2026_HK1', 'SE_MOB', 'GV09', 40),
('SE_MOB_02', '2026_HK1', 'SE_MOB', 'GV12', 40),
('DB_SQL_01', '2026_HK1', 'DB_SQL', 'GV07', 40),
('DB_SQL_02', '2026_HK1', 'DB_SQL', 'GV10', 40),
('CS_DSA_01', '2026_HK1', 'CS_DSA', 'GV02', 80),
('CS_DSA_02', '2026_HK1', 'CS_DSA', 'GV05', 80),
('CS_OS_01', '2026_HK1', 'CS_OS', 'GV05', 80),
('CS_OS_02', '2026_HK1', 'CS_OS', 'GV11', 40),
('SE_SAD_01', '2026_HK1', 'SE_SAD', 'GV02', 80),
('SE_SAD_02', '2026_HK1', 'SE_SAD', 'GV06', 40),
('INT_ML_01', '2026_HK1', 'INT_ML', 'GV01', 40),
('INT_ML_02', '2026_HK1', 'INT_ML', 'GV08', 40),
('CS_NW_01', '2026_HK1', 'CS_NW', 'GV10', 80),
('CS_NW_02', '2026_HK1', 'CS_NW', 'GV10', 40);

INSERT INTO SectionStudentGroup (section_code, group_code) VALUES
('INT_AI_01', 'CNTT16A'), ('INT_AI_01', 'CNTT16B'),
('INT_AI_02', 'KTPM16A'), ('INT_AI_02', 'KTPM16B'),
('INT_AI_03', 'KHMT16A'),
('INT_DM_01', 'CNTT16A'), ('INT_DM_02', 'KHMT16A'),
('SE_JAVA_01', 'KTPM16A'), ('SE_JAVA_02', 'KTPM16B'),
('SE_MOB_01', 'KTPM16A'), ('SE_MOB_02', 'KTPM16B'),
('DB_SQL_01', 'HTTT16A'), ('DB_SQL_02', 'CNTT16B'),
('CS_DSA_01', 'CNTT16A'), ('CS_DSA_01', 'CNTT16B'),
('CS_DSA_02', 'KTPM16A'), ('CS_DSA_02', 'KTPM16B'),
('CS_OS_01', 'CNTT16A'), ('CS_OS_01', 'CNTT16B'),
('CS_OS_02', 'KHMT16A'),
('SE_SAD_01', 'HTTT16A'), ('SE_SAD_01', 'KHMT16A'),
('SE_SAD_02', 'KTPM16B'),
('INT_ML_01', 'KHMT16A'), ('INT_ML_02', 'CNTT16A'),
('CS_NW_01', 'CNTT16A'), ('CS_NW_01', 'CNTT16B'),
('CS_NW_02', 'HTTT16A');

-- Most sections have one weekly event. Java sections have a lecture and a lab event.
INSERT INTO TeachingEvent (
    section_code, event_number, duration_periods, required_room_type
)
SELECT
    cs.section_code,
    1,
    CASE
        WHEN cs.course_code IN ('INT_DM', 'SE_MOB', 'DB_SQL', 'INT_ML') THEN 4
        ELSE 3
    END,
    CASE
        WHEN cs.course_code IN ('INT_DM', 'SE_MOB', 'DB_SQL', 'INT_ML')
            THEN 'COMPUTER_LAB'
        ELSE 'LECTURE'
    END
FROM CourseSection cs
WHERE cs.course_code <> 'SE_JAVA';

INSERT INTO TeachingEvent (
    section_code, event_number, duration_periods, required_room_type
) VALUES
('SE_JAVA_01', 1, 2, 'LECTURE'),
('SE_JAVA_01', 2, 2, 'COMPUTER_LAB'),
('SE_JAVA_02', 1, 2, 'LECTURE'),
('SE_JAVA_02', 2, 2, 'COMPUTER_LAB');

INSERT INTO LecturerAvailability (
    lecturer_code, term_code, day_of_week, start_period, end_period,
    availability_type, preference_weight
) VALUES
('GV01', '2026_HK1', 2, 1, 5, 'UNAVAILABLE', 100),
('GV01', '2026_HK1', 4, 1, 5, 'PREFERRED', 8),
('GV02', '2026_HK1', 6, 11, 15, 'DISCOURAGED', 5),
('GV03', '2026_HK1', 3, 6, 10, 'UNAVAILABLE', 100),
('GV04', '2026_HK1', 5, 1, 5, 'PREFERRED', 6),
('GV05', '2026_HK1', 7, 1, 15, 'UNAVAILABLE', 100),
('GV08', '2026_HK1', 2, 6, 10, 'PREFERRED', 7),
('GV10', '2026_HK1', 4, 11, 15, 'DISCOURAGED', 4);

INSERT INTO RoomAvailability (
    room_code, term_code, day_of_week, start_period, end_period,
    availability_type, preference_weight
) VALUES
('PM_101', '2026_HK1', 4, 1, 5, 'UNAVAILABLE', 100),
('PM_201', '2026_HK1', 6, 11, 15, 'UNAVAILABLE', 100),
('F_303', '2026_HK1', 7, 11, 15, 'DISCOURAGED', 3),
('F_301', '2026_HK1', 2, 1, 5, 'PREFERRED', 2);

INSERT INTO ConstraintSetting (
    term_code, constraint_code, constraint_name, constraint_type,
    weight_value, description
) VALUES
('2026_HK1', 'H01_EVENT_ONCE', N'Each event is scheduled exactly once', 'HARD', 1000000, N'Every TeachingEvent must have exactly one assignment.'),
('2026_HK1', 'H02_ROOM_CONFLICT', N'No room conflict', 'HARD', 1000000, N'A room cannot host overlapping events.'),
('2026_HK1', 'H03_LECTURER_CONFLICT', N'No lecturer conflict', 'HARD', 1000000, N'A lecturer cannot teach overlapping events.'),
('2026_HK1', 'H04_GROUP_CONFLICT', N'No student-group conflict', 'HARD', 1000000, N'A student group cannot attend overlapping events.'),
('2026_HK1', 'H05_ROOM_CAPACITY', N'Room capacity is sufficient', 'HARD', 1000000, N'Room capacity must cover section enrollment.'),
('2026_HK1', 'H06_ROOM_TYPE', N'Room type is suitable', 'HARD', 1000000, N'The room type must match the event requirement.'),
('2026_HK1', 'H07_AVAILABILITY', N'Respect unavailable periods', 'HARD', 1000000, N'Do not use unavailable lecturer, room or time periods.'),
('2026_HK1', 'H08_CONTIGUOUS_DURATION', N'Valid contiguous duration', 'HARD', 1000000, N'All periods of an event must be active and in one session.'),
('2026_HK1', 'S01_LECTURER_PREFERENCE', N'Lecturer time preference', 'SOFT', 8, N'Reward preferred periods and penalize discouraged periods.'),
('2026_HK1', 'S02_STUDENT_GAPS', N'Minimize student gaps', 'SOFT', 7, N'Reduce idle periods between events for a student group.'),
('2026_HK1', 'S03_LECTURER_GAPS', N'Minimize lecturer gaps', 'SOFT', 5, N'Reduce idle periods between events for a lecturer.'),
('2026_HK1', 'S04_DAILY_BALANCE', N'Balance daily workload', 'SOFT', 4, N'Distribute events across teaching days.'),
('2026_HK1', 'S05_CONSECUTIVE_LOAD', N'Limit consecutive load', 'SOFT', 5, N'Avoid excessively long consecutive teaching or study blocks.'),
('2026_HK1', 'S06_EVENT_SPREAD', N'Spread section events', 'SOFT', 6, N'Place multiple events of one section on different days.'),
('2026_HK1', 'S07_ROOM_WASTE', N'Minimize unused room capacity', 'SOFT', 2, N'Prefer the smallest suitable room.');

-- A small draft result demonstrates the result tables; real runs are produced by Python.
INSERT INTO OptimizationRun (
    term_code, algorithm, population_size, max_iterations,
    ga_population_ratio, random_seed, status, algorithm_parameters
) VALUES (
    '2026_HK1', 'GA_PO', 50, 200, 0.5000, 42, 'DRAFT',
    N'{"source":"sample-data","note":"Replace with a real Python optimization run"}'
);

DECLARE @sample_run_id BIGINT = SCOPE_IDENTITY();

INSERT INTO TimetableEntry (
    run_id, event_id, room_code, day_of_week, start_period, end_period, is_locked
)
SELECT @sample_run_id, event_id, 'F_301', 3, 1, 3, 0
FROM TeachingEvent
WHERE section_code = 'INT_AI_01' AND event_number = 1;

INSERT INTO TimetableEntry (
    run_id, event_id, room_code, day_of_week, start_period, end_period, is_locked
)
SELECT @sample_run_id, event_id, 'PM_101', 3, 6, 9, 0
FROM TeachingEvent
WHERE section_code = 'INT_DM_01' AND event_number = 1;
GO

-- =========================================================
-- INDEXES USED BY ENCODING, FITNESS AND RESULT QUERIES
-- =========================================================

CREATE INDEX IX_TimeSlot_Term_Day
    ON TimeSlot(term_code, day_of_week, period_number);

CREATE INDEX IX_CourseSection_Term
    ON CourseSection(term_code);

CREATE INDEX IX_CourseSection_Lecturer
    ON CourseSection(lecturer_code);

CREATE INDEX IX_SectionStudentGroup_Group
    ON SectionStudentGroup(group_code, section_code);

CREATE INDEX IX_TeachingEvent_Section
    ON TeachingEvent(section_code);

CREATE INDEX IX_LecturerAvailability_Lookup
    ON LecturerAvailability(term_code, lecturer_code, day_of_week, start_period, end_period);

CREATE INDEX IX_RoomAvailability_Lookup
    ON RoomAvailability(term_code, room_code, day_of_week, start_period, end_period);

CREATE INDEX IX_OptimizationRun_Term_CreatedAt
    ON OptimizationRun(term_code, created_at DESC);

CREATE INDEX IX_TimetableEntry_Run_Day
    ON TimetableEntry(run_id, day_of_week, start_period);

CREATE INDEX IX_TimetableEntry_Room_Day
    ON TimetableEntry(run_id, room_code, day_of_week, start_period, end_period);
GO

-- Quick verification after execution.
SELECT 'AcademicTerm' AS table_name, COUNT(*) AS row_count FROM AcademicTerm
UNION ALL SELECT 'TimeSlot', COUNT(*) FROM TimeSlot
UNION ALL SELECT 'Room', COUNT(*) FROM Room
UNION ALL SELECT 'Lecturer', COUNT(*) FROM Lecturer
UNION ALL SELECT 'Course', COUNT(*) FROM Course
UNION ALL SELECT 'StudentGroup', COUNT(*) FROM StudentGroup
UNION ALL SELECT 'CourseSection', COUNT(*) FROM CourseSection
UNION ALL SELECT 'SectionStudentGroup', COUNT(*) FROM SectionStudentGroup
UNION ALL SELECT 'TeachingEvent', COUNT(*) FROM TeachingEvent
UNION ALL SELECT 'LecturerAvailability', COUNT(*) FROM LecturerAvailability
UNION ALL SELECT 'RoomAvailability', COUNT(*) FROM RoomAvailability
UNION ALL SELECT 'ConstraintSetting', COUNT(*) FROM ConstraintSetting
UNION ALL SELECT 'OptimizationRun', COUNT(*) FROM OptimizationRun
UNION ALL SELECT 'TimetableEntry', COUNT(*) FROM TimetableEntry;
GO
