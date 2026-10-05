package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TeachingPlanItem;

import java.util.List;

public interface TeachingPlanItemRepository extends JpaRepository<TeachingPlanItem, Long> {
    List<TeachingPlanItem> findByTeachingPlanTeachingPlanIdOrderByItemNumber(Long teachingPlanId);
}
