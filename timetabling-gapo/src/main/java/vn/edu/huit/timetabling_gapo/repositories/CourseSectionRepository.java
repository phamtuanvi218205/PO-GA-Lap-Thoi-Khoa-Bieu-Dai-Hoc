package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.CourseSection;

import java.util.List;

public interface CourseSectionRepository extends JpaRepository<CourseSection, String> {
    List<CourseSection> findByAcademicTermTermCodeOrderBySectionCode(String termCode);
}
