package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import vn.edu.huit.timetabling_gapo.entities.TimetableEntry;

import java.util.List;

public interface TimetableEntryRepository extends JpaRepository<TimetableEntry, Long> {
    @Query("""
            select te
            from TimetableEntry te
            join fetch te.classSession cs
            join fetch cs.termWeek tw
            join fetch cs.teachingPlan plan
            join fetch plan.teachingPart part
            join fetch part.lecturer lecturer
            join fetch part.courseSection section
            join fetch section.course course
            join fetch te.teachingLocation location
            where te.optimizationRun.runId = :runId
            order by te.teachingDate, te.startPeriod, section.sectionCode
            """)
    List<TimetableEntry> findDetailedScheduleByRunId(@Param("runId") Long runId);

    @Query("""
            select te
            from TimetableEntry te
            join fetch te.classSession cs
            join fetch cs.termWeek tw
            join fetch cs.teachingPlan plan
            join fetch plan.teachingPart part
            join fetch part.lecturer lecturer
            join fetch part.courseSection section
            join fetch section.course course
            join fetch te.teachingLocation location
            where te.optimizationRun.runId = :runId
              and lecturer.lecturerCode = :lecturerCode
            order by te.teachingDate, te.startPeriod
            """)
    List<TimetableEntry> findDetailedScheduleByRunAndLecturer(
            @Param("runId") Long runId,
            @Param("lecturerCode") String lecturerCode
    );
}
