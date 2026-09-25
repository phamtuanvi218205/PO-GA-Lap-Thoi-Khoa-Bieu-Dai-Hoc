package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.Room;
import vn.edu.huit.timetabling_gapo.enums.RoomType;

import java.util.List;

public interface RoomRepository extends JpaRepository<Room, Long> {
    List<Room> findByTeachingLocationActiveTrueOrderByTeachingLocationLocationCode();
    List<Room> findByRoomTypeAndTeachingLocationActiveTrueOrderByTeachingLocationLocationCode(
            RoomType roomType
    );
}
