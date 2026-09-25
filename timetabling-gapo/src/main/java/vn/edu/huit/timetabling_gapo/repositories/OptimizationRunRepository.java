package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.OptimizationRun;

import java.util.List;

public interface OptimizationRunRepository extends JpaRepository<OptimizationRun, Long> {
    List<OptimizationRun> findByPlanningScenarioAcademicTermTermCodeOrderByStartedAtDesc(String termCode);
}
