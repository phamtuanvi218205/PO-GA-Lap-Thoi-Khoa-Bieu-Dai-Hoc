package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import vn.edu.huit.timetabling_gapo.entities.AcademicTerm;
import vn.edu.huit.timetabling_gapo.enums.AcademicTermStatus;

import java.util.List;

public interface AcademicTermRepository extends JpaRepository<AcademicTerm, String> {
    List<AcademicTerm> findByStatusOrderByStartDateDesc(AcademicTermStatus status);
}
