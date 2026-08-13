package vn.edu.huit.timetabling_gapo.repositories;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.edu.huit.timetabling_gapo.entities.SectionStudentGroup;

import java.util.List;

@Repository
public interface SectionStudentGroupRepository extends JpaRepository<SectionStudentGroup, Integer> {

    List<SectionStudentGroup> findByCourseSectionSectionCode(String sectionCode);
}
