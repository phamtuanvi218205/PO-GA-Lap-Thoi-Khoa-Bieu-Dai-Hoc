/*
    D097 - Remove the obsolete Q_time result field.

    Recurring schedule genes already enforce one weekday/start-period/location
    pattern for every occurrence in a group. The former time-stability score is
    therefore constant and is no longer part of the optimization contract.

    This migration is idempotent and preserves all remaining run data.
*/

SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.OptimizationRun', N'U') IS NULL
BEGIN
    THROW 50001, 'OptimizationRun table does not exist.', 1;
END;

IF OBJECT_ID(N'dbo.CK_OptimizationRun_TimeScore', N'C') IS NOT NULL
BEGIN
    ALTER TABLE dbo.OptimizationRun
        DROP CONSTRAINT CK_OptimizationRun_TimeScore;
END;

IF COL_LENGTH(N'dbo.OptimizationRun', N'time_stability_score') IS NOT NULL
BEGIN
    ALTER TABLE dbo.OptimizationRun
        DROP COLUMN time_stability_score;
END;

COMMIT TRANSACTION;
GO
