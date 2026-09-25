package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.PlanningScenario;

import java.util.List;

public interface PlanningScenarioRepository extends JpaRepository<PlanningScenario, Long> {
    List<PlanningScenario> findByAcademicTermTermCodeOrderByCreatedAtDesc(String termCode);
}
