package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.ConstraintSetting;

import java.util.List;

public interface ConstraintSettingRepository extends JpaRepository<ConstraintSetting, String> {
    List<ConstraintSetting> findByEnabledTrueOrderByPriorityTierAscConstraintCodeAsc();
}
