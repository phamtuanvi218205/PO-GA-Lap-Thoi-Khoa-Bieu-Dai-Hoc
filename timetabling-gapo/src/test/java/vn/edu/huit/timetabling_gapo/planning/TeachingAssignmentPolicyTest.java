package vn.edu.huit.timetabling_gapo.planning;

import org.junit.jupiter.api.Test;
import vn.edu.huit.timetabling_gapo.entities.CourseSection;
import vn.edu.huit.timetabling_gapo.entities.Lecturer;
import vn.edu.huit.timetabling_gapo.entities.TeachingPart;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TeachingAssignmentPolicyTest {

    @Test
    void acceptsLectureAndPracticeOfSameSectionWithSameLecturer() {
        CourseSection section = section("JAVA01");
        Lecturer lecturer = lecturer("GV01");

        assertDoesNotThrow(() ->
                TeachingAssignmentPolicy.requireOneLecturerPerCourseSection(List.of(
                        part("JAVA01_LT", section, lecturer),
                        part("JAVA01_TH", section, lecturer)
                ))
        );
    }

    @Test
    void rejectsDifferentLecturersWithinSameCourseSection() {
        CourseSection section = section("JAVA01");

        IllegalStateException exception = assertThrows(
                IllegalStateException.class,
                () -> TeachingAssignmentPolicy.requireOneLecturerPerCourseSection(List.of(
                        part("JAVA01_LT", section, lecturer("GV01")),
                        part("JAVA01_TH", section, lecturer("GV02"))
                ))
        );

        assertTrue(exception.getMessage().contains("phải dùng chung một giảng viên"));
    }

    @Test
    void allowsDifferentCourseSectionsToUseDifferentLecturers() {
        assertDoesNotThrow(() ->
                TeachingAssignmentPolicy.requireOneLecturerPerCourseSection(List.of(
                        part("JAVA01_LT", section("JAVA01"), lecturer("GV01")),
                        part("JAVA02_LT", section("JAVA02"), lecturer("GV02"))
                ))
        );
    }

    private CourseSection section(String code) {
        CourseSection section = new CourseSection();
        section.setSectionCode(code);
        return section;
    }

    private Lecturer lecturer(String code) {
        Lecturer lecturer = new Lecturer();
        lecturer.setLecturerCode(code);
        return lecturer;
    }

    private TeachingPart part(
            String code,
            CourseSection section,
            Lecturer lecturer
    ) {
        TeachingPart part = new TeachingPart();
        part.setPartCode(code);
        part.setCourseSection(section);
        part.setLecturer(lecturer);
        return part;
    }
}
