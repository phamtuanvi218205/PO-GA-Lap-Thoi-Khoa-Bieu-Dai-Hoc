package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.CampusTravelTime;
import vn.edu.huit.timetabling_gapo.entities.ids.CampusTravelTimeId;

public interface CampusTravelTimeRepository
        extends JpaRepository<CampusTravelTime, CampusTravelTimeId> {
}
