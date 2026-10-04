package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.OnlineLocation;

public interface OnlineLocationRepository extends JpaRepository<OnlineLocation, Long> {
}
