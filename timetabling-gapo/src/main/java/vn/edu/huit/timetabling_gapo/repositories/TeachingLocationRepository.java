package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TeachingLocation;
import vn.edu.huit.timetabling_gapo.enums.LocationType;

import java.util.List;

public interface TeachingLocationRepository extends JpaRepository<TeachingLocation, Long> {
    List<TeachingLocation> findByActiveTrueAndLocationTypeOrderByLocationCode(LocationType locationType);
}
