package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TeachingDate;
import vn.edu.huit.timetabling_gapo.entities.ids.TeachingDateId;

import java.util.List;

public interface TeachingDateRepository extends JpaRepository<TeachingDate, TeachingDateId> {
    List<TeachingDate> findByAcademicTermTermCodeAndWeekNumberOrderByCalendarDate(
            String termCode,
            Integer weekNumber
    );
}
