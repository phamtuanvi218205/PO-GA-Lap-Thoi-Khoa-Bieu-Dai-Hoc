package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.Campus;

import java.util.List;

public interface CampusRepository extends JpaRepository<Campus, String> {
    List<Campus> findByActiveTrueOrderByCampusCode();
}
