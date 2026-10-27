/* D099 - Persist queued run configuration and restart-safe job metadata. */
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH(N'dbo.OptimizationRun', N'request_config_json') IS NULL
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD request_config_json NVARCHAR(MAX) NULL;');

IF COL_LENGTH(N'dbo.OptimizationRun', N'queued_at') IS NULL
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD queued_at DATETIME2 NOT NULL
        CONSTRAINT DF_OptimizationRun_QueuedAt DEFAULT SYSUTCDATETIME() WITH VALUES;');

IF COL_LENGTH(N'dbo.OptimizationRun', N'worker_id') IS NULL
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD worker_id VARCHAR(64) NULL;');

IF COL_LENGTH(N'dbo.OptimizationRun', N'lease_expires_at') IS NULL
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD lease_expires_at DATETIME2 NULL;');

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.OptimizationRun')
      AND name = N'CK_OptimizationRun_RequestConfigJson'
)
    EXEC(N'ALTER TABLE dbo.OptimizationRun ADD CONSTRAINT CK_OptimizationRun_RequestConfigJson
        CHECK (request_config_json IS NULL OR ISJSON(request_config_json) = 1);');

IF EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.OptimizationRun')
      AND name = N'IX_OptimizationRun_Queue'
)
    DROP INDEX IX_OptimizationRun_Queue ON dbo.OptimizationRun;

EXEC(N'CREATE INDEX IX_OptimizationRun_Queue
    ON dbo.OptimizationRun(status, cancel_requested, lease_expires_at, queued_at, run_id);');

COMMIT TRANSACTION;
