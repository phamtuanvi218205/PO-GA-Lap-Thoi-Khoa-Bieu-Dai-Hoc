package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.edu.huit.timetabling_gapo.entities.TeachingEvent;

import java.util.List;

@Repository
public interface TeachingEventRepository extends JpaRepository<TeachingEvent, Integer> {

    List<TeachingEvent> findByCourseSectionAcademicTermTermCodeOrderByEventIdAsc(String termCode);
}
