package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.edu.huit.timetabling_gapo.entities.Lecturer;

@Repository
public interface LecturerRepository extends JpaRepository<Lecturer, String> {
}
