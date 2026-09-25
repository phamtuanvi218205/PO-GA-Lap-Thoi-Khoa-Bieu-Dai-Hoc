package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.LecturerAvailability;

import java.util.List;

public interface LecturerAvailabilityRepository extends JpaRepository<LecturerAvailability, Long> {
    List<LecturerAvailability> findByAcademicTermTermCodeAndLecturerLecturerCode(
            String termCode,
            String lecturerCode
    );
}
