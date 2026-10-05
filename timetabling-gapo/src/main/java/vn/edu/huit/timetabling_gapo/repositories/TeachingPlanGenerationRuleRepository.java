package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TeachingPlanGenerationRule;

import java.util.Optional;

public interface TeachingPlanGenerationRuleRepository
        extends JpaRepository<TeachingPlanGenerationRule, Long> {

    Optional<TeachingPlanGenerationRule> findByTeachingPartTeachingPartIdAndActiveTrue(
            Long teachingPartId
    );
}
