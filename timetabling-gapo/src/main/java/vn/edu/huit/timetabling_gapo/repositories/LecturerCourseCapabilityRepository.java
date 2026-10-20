package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.LecturerCourseCapability;
import vn.edu.huit.timetabling_gapo.entities.ids.LecturerCourseCapabilityId;

import java.util.List;

public interface LecturerCourseCapabilityRepository
        extends JpaRepository<LecturerCourseCapability, LecturerCourseCapabilityId> {
    List<LecturerCourseCapability> findByCourseCourseCodeInOrderByCourseCourseCodeAscLecturerLecturerCodeAsc(
            List<String> courseCodes
    );
}
