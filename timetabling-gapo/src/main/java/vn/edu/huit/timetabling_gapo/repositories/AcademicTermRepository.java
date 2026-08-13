package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.edu.huit.timetabling_gapo.entities.AcademicTerm;

import java.util.Optional;

@Repository
public interface AcademicTermRepository extends JpaRepository<AcademicTerm, String> {

    Optional<AcademicTerm> findFirstByActiveTrue();
}
