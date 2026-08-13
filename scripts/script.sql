-- =========================================================
-- DATABASE SCHEMA
-- =========================================================

CREATE TABLE Room (
    room_code VARCHAR(20) PRIMARY KEY,
    room_name NVARCHAR(50) NOT NULL,
    capacity INT NOT NULL,
    room_type VARCHAR(20) NOT NULL,
    CONSTRAINT CK_Room_Capacity CHECK (capacity > 0),
    CONSTRAINT CK_Room_Type CHECK (room_type IN ('LECTURE', 'LAB'))
);

CREATE TABLE Lecturer (
    lecturer_code VARCHAR(20) PRIMARY KEY,
    lecturer_name NVARCHAR(100) NOT NULL,
    academic_title NVARCHAR(50)
);

CREATE TABLE Course (
    course_code VARCHAR(20) PRIMARY KEY,
    course_name NVARCHAR(100) NOT NULL,
    credits INT NOT NULL,
    required_room_type VARCHAR(20) NOT NULL,
    CONSTRAINT CK_Course_Credits CHECK (credits > 0),
    CONSTRAINT CK_Course_RoomType
        CHECK (required_room_type IN ('LECTURE', 'LAB'))
);

CREATE TABLE CourseSection (
    section_code VARCHAR(20) PRIMARY KEY,
    course_code VARCHAR(20) NOT NULL,
    lecturer_code VARCHAR(20) NOT NULL,
    enrollment INT NOT NULL,
    duration_periods INT NOT NULL,
    CONSTRAINT FK_CourseSection_Course
        FOREIGN KEY (course_code) REFERENCES Course(course_code),
    CONSTRAINT FK_CourseSection_Lecturer
        FOREIGN KEY (lecturer_code) REFERENCES Lecturer(lecturer_code),
    CONSTRAINT CK_CourseSection_Enrollment CHECK (enrollment > 0),
    CONSTRAINT CK_CourseSection_Duration CHECK (duration_periods > 0)
);

CREATE TABLE TimetableEntry (
    id INT IDENTITY(1,1) PRIMARY KEY,
    section_code VARCHAR(20) NOT NULL,
    room_code VARCHAR(20) NOT NULL,
    day_of_week INT NOT NULL,
    start_period INT NOT NULL,
    end_period INT NOT NULL,
    CONSTRAINT FK_TimetableEntry_CourseSection
        FOREIGN KEY (section_code) REFERENCES CourseSection(section_code),
    CONSTRAINT FK_TimetableEntry_Room
        FOREIGN KEY (room_code) REFERENCES Room(room_code),
    CONSTRAINT CK_TimetableEntry_Day CHECK (day_of_week BETWEEN 2 AND 7),
    CONSTRAINT CK_TimetableEntry_StartPeriod CHECK (start_period BETWEEN 1 AND 15),
    CONSTRAINT CK_TimetableEntry_EndPeriod CHECK (end_period BETWEEN 1 AND 15),
    CONSTRAINT CK_TimetableEntry_PeriodOrder CHECK (end_period >= start_period)
);

GO

-- =========================================================
-- MOCK DATA
-- =========================================================

INSERT INTO Room (room_code, room_name, capacity, room_type) VALUES
('F_201', N'Room F.201', 50, 'LECTURE'),
('F_202', N'Room F.202', 50, 'LECTURE'),
('F_203', N'Room F.203', 60, 'LECTURE'),
('F_204', N'Room F.204', 60, 'LECTURE'),
('F_301', N'Room F.301', 80, 'LECTURE'),
('F_302', N'Room F.302', 80, 'LECTURE'),
('F_303', N'Room F.303', 100, 'LECTURE'),
('F_304', N'Room F.304', 100, 'LECTURE'),
('F_401', N'Room F.401', 40, 'LECTURE'),
('F_402', N'Room F.402', 40, 'LECTURE'),
('PM_101', N'Computer Lab 101', 45, 'LAB'),
('PM_102', N'Computer Lab 102', 45, 'LAB'),
('PM_201', N'Computer Lab 201', 40, 'LAB'),
('PM_202', N'Computer Lab 202', 40, 'LAB'),
('PM_301', N'Computer Lab 301', 60, 'LAB');

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

INSERT INTO Course (
    course_code,
    course_name,
    credits,
    required_room_type
) VALUES
('INT_AI', N'Artificial Intelligence', 3, 'LECTURE'),
('INT_DM', N'Data Mining', 3, 'LAB'),
('SE_JAVA', N'Java Backend Programming', 3, 'LAB'),
('SE_MOB', N'Cross-platform Mobile Programming', 3, 'LAB'),
('DB_SQL', N'Database Management Systems', 3, 'LAB'),
('CS_DSA', N'Data Structures and Algorithms', 3, 'LECTURE'),
('CS_OS', N'Operating Systems', 3, 'LECTURE'),
('SE_SAD', N'Systems Analysis and Design', 3, 'LECTURE'),
('INT_ML', N'Machine Learning Fundamentals', 3, 'LAB'),
('CS_NW', N'Computer Networks', 3, 'LECTURE');

INSERT INTO CourseSection (
    section_code,
    course_code,
    lecturer_code,
    enrollment,
    duration_periods
) VALUES
('INT_AI_01', 'INT_AI', 'GV01', 55, 3),
('INT_AI_02', 'INT_AI', 'GV01', 60, 3),
('INT_AI_03', 'INT_AI', 'GV03', 75, 3),
('INT_AI_04', 'INT_AI', 'GV03', 50, 3),
('INT_DM_01', 'INT_DM', 'GV08', 40, 4),
('INT_DM_02', 'INT_DM', 'GV08', 45, 4),
('INT_DM_03', 'INT_DM', 'GV11', 40, 4),
('SE_JAVA_01', 'SE_JAVA', 'GV04', 40, 4),
('SE_JAVA_02', 'SE_JAVA', 'GV04', 40, 4),
('SE_JAVA_03', 'SE_JAVA', 'GV06', 45, 4),
('SE_JAVA_04', 'SE_JAVA', 'GV06', 45, 4),
('SE_MOB_01', 'SE_MOB', 'GV09', 40, 4),
('SE_MOB_02', 'SE_MOB', 'GV09', 40, 4),
('SE_MOB_03', 'SE_MOB', 'GV12', 45, 4),
('CS_DSA_01', 'CS_DSA', 'GV02', 65, 3),
('CS_DSA_02', 'CS_DSA', 'GV02', 70, 3),
('CS_DSA_03', 'CS_DSA', 'GV05', 80, 3),
('CS_DSA_04', 'CS_DSA', 'GV05', 80, 3),
('DB_SQL_01', 'DB_SQL', 'GV07', 40, 4),
('DB_SQL_02', 'DB_SQL', 'GV07', 45, 4),
('DB_SQL_03', 'DB_SQL', 'GV10', 40, 4),
('SE_SAD_01', 'SE_SAD', 'GV02', 75, 3),
('SE_SAD_02', 'SE_SAD', 'GV06', 80, 3),
('SE_SAD_03', 'SE_SAD', 'GV12', 60, 3),
('CS_OS_01', 'CS_OS', 'GV05', 90, 3),
('CS_OS_02', 'CS_OS', 'GV11', 85, 3),
('CS_NW_01', 'CS_NW', 'GV10', 70, 3),
('CS_NW_02', 'CS_NW', 'GV10', 75, 3),
('INT_ML_01', 'INT_ML', 'GV01', 40, 4),
('INT_ML_02', 'INT_ML', 'GV08', 45, 4);

GO

-- Indexes used when loading data for optimization.
CREATE NONCLUSTERED INDEX IX_CourseSection_LecturerCode
ON CourseSection(lecturer_code);
GO

CREATE NONCLUSTERED INDEX IX_CourseSection_CourseCode
ON CourseSection(course_code);
GO

-- Create these indexes after a large timetable result has been inserted.
/*
CREATE NONCLUSTERED INDEX IX_TimetableEntry_SectionCode
ON TimetableEntry(section_code);
GO

CREATE NONCLUSTERED INDEX IX_TimetableEntry_RoomCode
ON TimetableEntry(room_code);
GO

CREATE NONCLUSTERED INDEX IX_TimetableEntry_Room_Day_Start
ON TimetableEntry(room_code, day_of_week, start_period);
GO
*/
