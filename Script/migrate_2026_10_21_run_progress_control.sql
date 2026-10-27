/* D098 - Persist optimization progress, timeout and cancellation state. */
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH(N'dbo.OptimizationRun', N'current_fitness_evaluations') IS NULL
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD current_fitness_evaluations BIGINT NOT NULL
        CONSTRAINT DF_OptimizationRun_CurrentFE DEFAULT 0 WITH VALUES;');

IF COL_LENGTH(N'dbo.OptimizationRun', N'completed_iterations') IS NULL
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD completed_iterations INT NOT NULL
        CONSTRAINT DF_OptimizationRun_CompletedIterations DEFAULT 0 WITH VALUES;');

IF COL_LENGTH(N'dbo.OptimizationRun', N'progress_updated_at') IS NULL
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD progress_updated_at DATETIME2 NULL;');

IF COL_LENGTH(N'dbo.OptimizationRun', N'cancel_requested') IS NULL
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD cancel_requested BIT NOT NULL
        CONSTRAINT DF_OptimizationRun_CancelRequested DEFAULT 0 WITH VALUES;');

IF COL_LENGTH(N'dbo.OptimizationRun', N'timeout_seconds') IS NULL
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD timeout_seconds INT NULL;');

DECLARE @status_constraint sysname;
SELECT @status_constraint = cc.name
FROM sys.check_constraints AS cc
WHERE cc.parent_object_id = OBJECT_ID(N'dbo.OptimizationRun')
  AND cc.name = N'CK_OptimizationRun_Status';

IF @status_constraint IS NOT NULL
    ALTER TABLE dbo.OptimizationRun DROP CONSTRAINT CK_OptimizationRun_Status;

EXEC(N'ALTER TABLE dbo.OptimizationRun ADD CONSTRAINT CK_OptimizationRun_Status
    CHECK (status IN (''PENDING'', ''RUNNING'', ''COMPLETED'', ''FAILED'', ''CANCELLED'', ''TIMED_OUT''));');

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.OptimizationRun')
      AND name = N'CK_OptimizationRun_CurrentFE'
)
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD CONSTRAINT CK_OptimizationRun_CurrentFE
        CHECK (current_fitness_evaluations >= 0
               AND current_fitness_evaluations <= max_fitness_evaluations);');

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.OptimizationRun')
      AND name = N'CK_OptimizationRun_CompletedIterations'
)
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD CONSTRAINT CK_OptimizationRun_CompletedIterations
        CHECK (completed_iterations >= 0);');

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.OptimizationRun')
      AND name = N'CK_OptimizationRun_Timeout'
)
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD CONSTRAINT CK_OptimizationRun_Timeout
        CHECK (timeout_seconds IS NULL OR timeout_seconds > 0);');

COMMIT TRANSACTION;
