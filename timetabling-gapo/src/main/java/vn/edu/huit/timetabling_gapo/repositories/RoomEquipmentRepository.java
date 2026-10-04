package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.RoomEquipment;
import vn.edu.huit.timetabling_gapo.entities.ids.RoomEquipmentId;

import java.util.List;

public interface RoomEquipmentRepository extends JpaRepository<RoomEquipment, RoomEquipmentId> {
    List<RoomEquipment> findByRoomLocationId(Long locationId);
}
