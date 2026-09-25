package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.RoomAvailability;

import java.util.List;

public interface RoomAvailabilityRepository extends JpaRepository<RoomAvailability, Long> {
    List<RoomAvailability> findByAcademicTermTermCodeAndRoomLocationId(
            String termCode,
            Long locationId
    );
}
