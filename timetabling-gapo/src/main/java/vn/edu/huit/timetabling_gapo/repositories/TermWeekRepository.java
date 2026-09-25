package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.TermWeek;
import vn.edu.huit.timetabling_gapo.entities.ids.TermWeekId;

import java.util.List;

public interface TermWeekRepository extends JpaRepository<TermWeek, TermWeekId> {
    List<TermWeek> findByAcademicTermTermCodeOrderByWeekNumber(String termCode);
}
