/* Đồng bộ D094/D097/D109 và bổ sung bản điều chỉnh, không xóa run lịch sử. */
SET XACT_ABORT ON;
BEGIN TRANSACTION;

DELETE FROM ConstraintSetting WHERE constraint_code IN (
 'SOFT_CAPACITY','SOFT_TIME_STABILITY','SOFT_TIME_WEEKDAY_STABILITY',
 'SOFT_TIME_START_PERIOD_STABILITY','SOFT_ROOM_STABILITY'
);

MERGE ConstraintSetting AS target
USING (VALUES
 ('HARD_ROOM_CAPACITY',N'Phòng đủ sức chứa lớp học phần','HARD',1,CAST(NULL AS DECIMAL(10,4)),CAST(NULL AS DECIMAL(10,4))),
 ('SOFT_LECTURER_GAP',N'Khoảng trống giảng viên','SOFT',2,0.3720,NULL),
 ('SOFT_LECTURER_CONSECUTIVE',N'Tiết dạy liên tục vượt ngưỡng','SOFT',2,0.1487,6),
 ('SOFT_ROOM_DISCOURAGED',N'Khung giờ phòng hạn chế sử dụng','SOFT',2,0.2975,NULL),
 ('SOFT_WORKLOAD_BALANCE',N'Cân bằng tải giảng dạy','SOFT',2,0.1818,NULL),
 ('SOFT_LECTURER_TIME_PREFERENCE',N'Mong muốn thời gian giảng viên','SOFT',3,0.5000,NULL),
 ('SOFT_COURSE_SUITABILITY',N'Mức phù hợp môn và giảng viên','SOFT',3,0.5000,NULL)
) AS source(code,name,kind,tier,weight,threshold_value)
ON target.constraint_code=source.code
WHEN MATCHED THEN UPDATE SET constraint_name=source.name,constraint_kind=source.kind,
 priority_tier=source.tier,weight=source.weight,threshold_value=source.threshold_value,is_enabled=1
WHEN NOT MATCHED THEN INSERT
 (constraint_code,constraint_name,constraint_kind,priority_tier,weight,threshold_value,is_enabled)
 VALUES(source.code,source.name,source.kind,source.tier,source.weight,source.threshold_value,1);

IF OBJECT_ID(N'dbo.CK_OptimizationRun_TimeScore',N'C') IS NOT NULL
 ALTER TABLE OptimizationRun DROP CONSTRAINT CK_OptimizationRun_TimeScore;
IF COL_LENGTH(N'dbo.OptimizationRun',N'time_stability_score') IS NOT NULL
 ALTER TABLE OptimizationRun DROP COLUMN time_stability_score;
IF NOT EXISTS(SELECT 1 FROM sys.key_constraints WHERE name='UQ_ClassSession_Plan_Week_Group'
 AND parent_object_id=OBJECT_ID('ClassSession'))
 ALTER TABLE ClassSession ADD CONSTRAINT UQ_ClassSession_Plan_Week_Group
 UNIQUE(teaching_plan_id,term_code,week_number,stability_group_no);

IF OBJECT_ID(N'dbo.TimetableRevision',N'U') IS NULL
BEGIN
 CREATE TABLE TimetableRevision(
  revision_id BIGINT IDENTITY(1,1) PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES OptimizationRun(run_id),
  parent_revision_id BIGINT NULL REFERENCES TimetableRevision(revision_id),
  created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
  note NVARCHAR(500) NOT NULL,
  general_quality_score FLOAT NOT NULL,
  lecturer_preference_score FLOAT NOT NULL,
  fitness_breakdown_json NVARCHAR(MAX) NOT NULL CHECK(ISJSON(fitness_breakdown_json)=1),
  CONSTRAINT UQ_TimetableRevision_Id_Run UNIQUE(revision_id,run_id)
 );
 CREATE TABLE TimetableRevisionEntry(
  revision_id BIGINT NOT NULL,
  run_id BIGINT NOT NULL,
  class_session_id BIGINT NOT NULL REFERENCES ClassSession(class_session_id),
  lecturer_code VARCHAR(20) NOT NULL REFERENCES Lecturer(lecturer_code),
  term_code VARCHAR(20) NOT NULL,
  teaching_date DATE NOT NULL,
  location_id BIGINT NOT NULL,
  location_type VARCHAR(20) NOT NULL,
  start_period TINYINT NOT NULL,
  end_period TINYINT NOT NULL,
  PRIMARY KEY(revision_id,class_session_id),
  FOREIGN KEY(revision_id,run_id) REFERENCES TimetableRevision(revision_id,run_id),
  FOREIGN KEY(term_code,teaching_date) REFERENCES TeachingDate(term_code,calendar_date),
  FOREIGN KEY(location_id,location_type) REFERENCES TeachingLocation(location_id,location_type),
  CHECK(start_period BETWEEN 1 AND 16 AND end_period BETWEEN start_period AND 16)
 );
END;
COMMIT TRANSACTION;
