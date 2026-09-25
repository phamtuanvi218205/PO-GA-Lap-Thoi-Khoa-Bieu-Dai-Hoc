package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.PlanningScenarioItem;
import vn.edu.huit.timetabling_gapo.entities.ids.PlanningScenarioItemId;

import java.util.List;

public interface PlanningScenarioItemRepository
        extends JpaRepository<PlanningScenarioItem, PlanningScenarioItemId> {
    List<PlanningScenarioItem> findByPlanningScenarioScenarioIdOrderByTeachingPartPartCode(Long scenarioId);
}
