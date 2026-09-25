package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.Course;

import java.util.List;

public interface CourseRepository extends JpaRepository<Course, String> {
    List<Course> findByActiveTrueOrderByCourseCode();
}
