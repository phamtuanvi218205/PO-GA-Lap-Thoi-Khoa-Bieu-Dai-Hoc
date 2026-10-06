package vn.edu.huit.timetabling_gapo.snapshot;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;

/**
 * Hợp đồng JSON bất biến mà Java tạo từ một PlanningScenario đã khóa và
 * Python đọc để dựng đúng một ProblemInstance.
 *
 * <p>Các record chỉ chứa kiểu dữ liệu trao đổi, không chứa entity JPA. Nhờ đó
 * snapshot không phụ thuộc persistence context và không thể vô tình thay đổi
 * khi dữ liệu database được chỉnh sau thời điểm tạo.</p>
 */
public record ProblemInstanceSnapshot(
        String schemaVersion,
        TermSnapshot term,
        ScenarioSnapshot scenario,
        List<WeekSnapshot> weeks,
        List<TeachingDateSnapshot> teachingDates,
        List<TimePeriodSnapshot> timePeriods,
        List<AllowedPeriodBlockSnapshot> allowedPeriodBlocks,
        List<TeachingDurationRuleSnapshot> teachingDurationRules,
        List<LocationSnapshot> locations,
        List<LecturerSnapshot> lecturers,
        List<CourseSnapshot> courses,
        List<CourseSectionSnapshot> courseSections,
        List<TeachingPartSnapshot> teachingParts,
        List<TeachingPlanSnapshot> teachingPlans,
        List<ClassSessionSnapshot> classSessions,
        List<AvailabilitySnapshot> lecturerAvailabilities,
        List<AvailabilitySnapshot> roomAvailabilities,
        List<CampusTravelTimeSnapshot> campusTravelTimes,
        List<ConstraintSettingSnapshot> constraintSettings
) {
    public static final String SCHEMA_VERSION = "problem-instance.v1";

    public ProblemInstanceSnapshot {
        weeks = List.copyOf(weeks);
        teachingDates = List.copyOf(teachingDates);
        timePeriods = List.copyOf(timePeriods);
        allowedPeriodBlocks = List.copyOf(allowedPeriodBlocks);
        teachingDurationRules = List.copyOf(teachingDurationRules);
        locations = List.copyOf(locations);
        lecturers = List.copyOf(lecturers);
        courses = List.copyOf(courses);
        courseSections = List.copyOf(courseSections);
        teachingParts = List.copyOf(teachingParts);
        teachingPlans = List.copyOf(teachingPlans);
        classSessions = List.copyOf(classSessions);
        lecturerAvailabilities = List.copyOf(lecturerAvailabilities);
        roomAvailabilities = List.copyOf(roomAvailabilities);
        campusTravelTimes = List.copyOf(campusTravelTimes);
        constraintSettings = List.copyOf(constraintSettings);
    }

    public record TermSnapshot(
            String termCode,
            String termName,
            LocalDate startDate,
            LocalDate endDate,
            String status
    ) {
    }

    public record ScenarioSnapshot(
            long scenarioId,
            String scenarioCode,
            String termCode,
            String scopeType,
            String status,
            List<ScenarioItemSnapshot> items
    ) {
        public ScenarioSnapshot {
            items = List.copyOf(items);
        }
    }

    public record ScenarioItemSnapshot(
            int teachingPartIndex,
            long teachingPlanId
    ) {
    }

    public record WeekSnapshot(
            int weekNumber,
            LocalDate startDate,
            LocalDate endDate
    ) {
    }

    public record TeachingDateSnapshot(
            LocalDate calendarDate,
            int weekNumber,
            int isoWeekday,
            String status
    ) {
    }

    public record TimePeriodSnapshot(
            int periodNumber,
            LocalTime startTime,
            LocalTime endTime,
            String sessionType
    ) {
    }

    public record AllowedPeriodBlockSnapshot(
            int startPeriod,
            int durationPeriods
    ) {
    }

    public record TeachingDurationRuleSnapshot(
            String partType,
            int durationPeriods,
            boolean standard
    ) {
    }

    public record EquipmentQuantitySnapshot(
            String equipmentCode,
            int quantity
    ) {
    }

    /**
     * Bản ghi chung cho phòng vật lý và địa điểm online. Các trường không áp
     * dụng cho loại địa điểm hiện tại mang giá trị null hoặc danh sách rỗng.
     */
    public record LocationSnapshot(
            int locationIndex,
            long locationId,
            String locationCode,
            String locationName,
            String locationType,
            boolean active,
            String campusCode,
            String roomType,
            Integer capacity,
            List<EquipmentQuantitySnapshot> equipmentQuantities,
            String platformName
    ) {
        public LocationSnapshot {
            equipmentQuantities = List.copyOf(equipmentQuantities);
        }
    }

    public record LecturerSnapshot(
            int lecturerIndex,
            String lecturerCode,
            String fullName,
            String homeCampusCode
    ) {
    }

    public record CourseSnapshot(
            String courseCode,
            String courseName
    ) {
    }

    public record CourseSectionSnapshot(
            String sectionCode,
            String courseCode,
            String sectionName,
            Integer expectedEnrollment
    ) {
    }

    public record TeachingPartSnapshot(
            int teachingPartIndex,
            long teachingPartId,
            String partCode,
            String sectionCode,
            String partType,
            int lecturerIndex,
            int totalPeriods,
            String requiredLocationType,
            String requiredRoomType,
            List<EquipmentQuantitySnapshot> requiredEquipment
    ) {
        public TeachingPartSnapshot {
            requiredEquipment = List.copyOf(requiredEquipment);
        }
    }

    public record TeachingPlanSnapshot(
            long teachingPlanId,
            String planCode,
            int teachingPartIndex,
            String status,
            boolean allowsIntensive
    ) {
    }

    public record ClassSessionSnapshot(
            int sessionIndex,
            long classSessionId,
            long teachingPlanId,
            int sessionNumber,
            int stabilityGroupNo,
            int weekNumber,
            int durationPeriods,
            String requiredLocationType
    ) {
    }

    public record AvailabilitySnapshot(
            int resourceIndex,
            String scopeType,
            Integer startPeriod,
            Integer endPeriod,
            String availabilityType,
            LocalDate calendarDate,
            Integer isoWeekday,
            Double preferenceWeight
    ) {
    }

    public record CampusTravelTimeSnapshot(
            String fromCampusCode,
            String toCampusCode,
            int travelMinutes
    ) {
    }

    public record ConstraintSettingSnapshot(
            String constraintCode,
            String constraintType,
            int priorityTier,
            Double weight,
            boolean enabled
    ) {
    }
}
