package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TeachingPart;

import java.util.List;

public interface TeachingPartRepository extends JpaRepository<TeachingPart, Long> {
    List<TeachingPart> findByCourseSectionAcademicTermTermCodeOrderByPartCode(String termCode);
    List<TeachingPart> findByLecturerLecturerCodeOrderByPartCode(String lecturerCode);
}
