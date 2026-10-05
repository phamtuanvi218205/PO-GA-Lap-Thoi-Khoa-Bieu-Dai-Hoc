package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import vn.edu.huit.timetabling_gapo.entities.TeachingPlan;
import vn.edu.huit.timetabling_gapo.enums.TeachingPlanStatus;

import java.util.List;

public interface TeachingPlanRepository extends JpaRepository<TeachingPlan, Long> {
    List<TeachingPlan> findByTeachingPartTeachingPartIdAndStatusOrderByCandidateRank(
            Long teachingPartId,
            TeachingPlanStatus status
    );

    List<TeachingPlan> findByTeachingPartTeachingPartIdAndGenerationKeyOrderByCandidateRank(
            Long teachingPartId,
            String generationKey
    );

    @Query("""
            select coalesce(max(plan.generationNo), 0)
            from TeachingPlan plan
            where plan.teachingPart.teachingPartId = :teachingPartId
            """)
    int findMaximumGenerationNo(@Param("teachingPartId") Long teachingPartId);
}
