package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.edu.huit.timetabling_gapo.entities.CourseSection;

import java.util.List;

@Repository
public interface CourseSectionRepository extends JpaRepository<CourseSection, String> {

    List<CourseSection> findByAcademicTermTermCodeOrderBySectionCodeAsc(String termCode);
}
