package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TeachingDurationRule;
import vn.edu.huit.timetabling_gapo.entities.ids.TeachingDurationRuleId;
import vn.edu.huit.timetabling_gapo.enums.PartType;

import java.util.List;

public interface TeachingDurationRuleRepository
        extends JpaRepository<TeachingDurationRule, TeachingDurationRuleId> {
    List<TeachingDurationRule> findByPartTypeOrderByDurationPeriods(PartType partType);
}
