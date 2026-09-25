package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.AllowedPeriodBlock;
import vn.edu.huit.timetabling_gapo.entities.ids.AllowedPeriodBlockId;

import java.util.List;

public interface AllowedPeriodBlockRepository
        extends JpaRepository<AllowedPeriodBlock, AllowedPeriodBlockId> {
    List<AllowedPeriodBlock> findByActiveTrueOrderByStartPeriod();
}
