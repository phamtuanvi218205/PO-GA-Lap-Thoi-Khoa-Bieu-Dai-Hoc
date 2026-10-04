package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TimePeriod;

public interface TimePeriodRepository extends JpaRepository<TimePeriod, Integer> {
}
