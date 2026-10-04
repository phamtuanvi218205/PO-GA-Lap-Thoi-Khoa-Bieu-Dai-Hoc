package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.Lecturer;

import java.util.List;

public interface LecturerRepository extends JpaRepository<Lecturer, String> {
    List<Lecturer> findByActiveTrueOrderByLecturerCode();
}
