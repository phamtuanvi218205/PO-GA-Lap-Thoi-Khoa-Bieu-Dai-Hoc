package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.edu.huit.timetabling_gapo.entities.TimetableEntry;

import java.util.List;

@Repository
public interface TimetableEntryRepository extends JpaRepository<TimetableEntry, Long> {

    List<TimetableEntry> findByOptimizationRunRunIdOrderByDayOfWeekAscStartPeriodAsc(Long runId);
}
