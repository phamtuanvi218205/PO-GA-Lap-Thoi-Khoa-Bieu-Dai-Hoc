package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.Equipment;

public interface EquipmentRepository extends JpaRepository<Equipment, String> {
}
