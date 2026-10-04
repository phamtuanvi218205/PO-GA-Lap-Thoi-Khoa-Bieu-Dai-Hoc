package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TeachingPlan;
import vn.edu.huit.timetabling_gapo.enums.TeachingPlanStatus;

import java.util.List;

public interface TeachingPlanRepository extends JpaRepository<TeachingPlan, Long> {
    List<TeachingPlan> findByTeachingPartTeachingPartIdAndStatusOrderByPlanCode(
            Long teachingPartId,
            TeachingPlanStatus status
    );
}
