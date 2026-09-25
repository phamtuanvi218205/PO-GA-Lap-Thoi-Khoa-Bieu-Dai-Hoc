package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TeachingPartRequiredEquipment;
import vn.edu.huit.timetabling_gapo.entities.ids.TeachingPartRequiredEquipmentId;

import java.util.List;

public interface TeachingPartRequiredEquipmentRepository
        extends JpaRepository<TeachingPartRequiredEquipment, TeachingPartRequiredEquipmentId> {
    List<TeachingPartRequiredEquipment> findByTeachingPartTeachingPartId(Long teachingPartId);
}
