package vn.edu.huit.timetabling_gapo.snapshot;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import vn.edu.huit.timetabling_gapo.entities.*;
import vn.edu.huit.timetabling_gapo.enums.LocationType;
import vn.edu.huit.timetabling_gapo.enums.PlanningScenarioStatus;
import vn.edu.huit.timetabling_gapo.enums.TeachingPlanStatus;
import vn.edu.huit.timetabling_gapo.planning.TeachingAssignmentPolicy;
import vn.edu.huit.timetabling_gapo.repositories.*;

import java.util.*;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * Chụp toàn bộ dữ liệu cần thiết của một scenario đã LOCKED thành hợp đồng
 * ProblemInstance v1. Builder không sinh SessionOption và không chạy thuật
 * toán; hai trách nhiệm đó thuộc encoder và optimizer Python.
 */
@Service
@RequiredArgsConstructor
public class ProblemInstanceSnapshotBuilder {

    private final PlanningScenarioRepository scenarioRepository;
    private final PlanningScenarioItemRepository scenarioItemRepository;
    private final TermWeekRepository termWeekRepository;
    private final TeachingDateRepository teachingDateRepository;
    private final TimePeriodRepository timePeriodRepository;
    private final AllowedPeriodBlockRepository allowedPeriodBlockRepository;
    private final TeachingDurationRuleRepository durationRuleRepository;
    private final TeachingLocationRepository locationRepository;
    private final RoomRepository roomRepository;
    private final OnlineLocationRepository onlineLocationRepository;
    private final RoomEquipmentRepository roomEquipmentRepository;
    private final TeachingPartRequiredEquipmentRepository partEquipmentRepository;
    private final ClassSessionRepository classSessionRepository;
    private final LecturerAvailabilityRepository lecturerAvailabilityRepository;
    private final RoomAvailabilityRepository roomAvailabilityRepository;
    private final CampusTravelTimeRepository campusTravelTimeRepository;
    private final ConstraintSettingRepository constraintSettingRepository;
    private final ProblemInstanceSnapshotSerializer serializer;

    /**
     * Tạo snapshot xác định. Cùng dữ liệu database và cùng scenario sẽ tạo
     * cùng JSON, cùng thứ tự index và cùng checksum.
     */
    @Transactional(readOnly = true)
    public BuiltProblemInstanceSnapshot build(long scenarioId) {
        PlanningScenario scenario = scenarioRepository.findById(scenarioId)
                .orElseThrow(() -> new IllegalArgumentException(
                        "Không tìm thấy PlanningScenario " + scenarioId + "."));
        if (scenario.getStatus() != PlanningScenarioStatus.LOCKED) {
            throw new IllegalStateException(
                    "Chỉ PlanningScenario LOCKED mới được tạo snapshot production."
            );
        }

        List<PlanningScenarioItem> scenarioItems = scenarioItemRepository
                .findByPlanningScenarioScenarioIdOrderByTeachingPartPartCode(scenarioId);
        if (scenarioItems.isEmpty()) {
            throw new IllegalStateException("Scenario LOCKED không có TeachingPart nào.");
        }

        validateScenarioItems(scenario, scenarioItems);
        AcademicTerm term = scenario.getAcademicTerm();
        String termCode = term.getTermCode();

        List<TeachingPart> parts = scenarioItems.stream()
                .map(PlanningScenarioItem::getTeachingPart)
                .sorted(Comparator.comparing(TeachingPart::getPartCode))
                .toList();
        TeachingAssignmentPolicy.requireOneLecturerPerCourseSection(parts);
        Map<Long, Integer> partIndexById = indexBy(
                parts,
                TeachingPart::getTeachingPartId
        );

        List<TeachingPlan> plans = scenarioItems.stream()
                .map(PlanningScenarioItem::getTeachingPlan)
                .sorted(Comparator.comparingInt(plan ->
                        requireIndex(partIndexById, plan.getTeachingPart().getTeachingPartId())))
                .toList();

        List<Lecturer> lecturers = parts.stream()
                .map(TeachingPart::getLecturer)
                .collect(Collectors.toMap(
                        Lecturer::getLecturerCode,
                        Function.identity(),
                        (left, right) -> left,
                        TreeMap::new
                ))
                .values().stream().toList();
        Map<String, Integer> lecturerIndexByCode = indexBy(
                lecturers,
                Lecturer::getLecturerCode
        );

        List<CourseSection> sections = parts.stream()
                .map(TeachingPart::getCourseSection)
                .collect(Collectors.toMap(
                        CourseSection::getSectionCode,
                        Function.identity(),
                        (left, right) -> left,
                        TreeMap::new
                ))
                .values().stream().toList();
        List<Course> courses = sections.stream()
                .map(CourseSection::getCourse)
                .collect(Collectors.toMap(
                        Course::getCourseCode,
                        Function.identity(),
                        (left, right) -> left,
                        TreeMap::new
                ))
                .values().stream().toList();

        List<TeachingLocation> locations = locationRepository.findAll().stream()
                .sorted(Comparator
                        .comparing(TeachingLocation::getLocationCode)
                        .thenComparing(TeachingLocation::getLocationId))
                .toList();
        Map<Long, Integer> locationIndexById = indexBy(
                locations,
                TeachingLocation::getLocationId
        );

        ProblemInstanceSnapshot snapshot = new ProblemInstanceSnapshot(
                ProblemInstanceSnapshot.SCHEMA_VERSION,
                mapTerm(term),
                mapScenario(scenario, scenarioItems, partIndexById),
                mapWeeks(termCode),
                mapTeachingDates(termCode),
                mapTimePeriods(),
                mapAllowedPeriodBlocks(),
                mapDurationRules(),
                mapLocations(locations, locationIndexById),
                mapLecturers(lecturers, lecturerIndexByCode),
                mapCourses(courses),
                mapCourseSections(sections),
                mapTeachingParts(parts, partIndexById, lecturerIndexByCode),
                mapTeachingPlans(plans, partIndexById),
                mapClassSessions(plans),
                mapLecturerAvailabilities(termCode, lecturers, lecturerIndexByCode),
                mapRoomAvailabilities(termCode, locations, locationIndexById),
                mapCampusTravelTimes(),
                mapConstraintSettings()
        );
        return serializer.serialize(snapshot);
    }

    private void validateScenarioItems(
            PlanningScenario scenario,
            List<PlanningScenarioItem> items
    ) {
        Set<Long> partIds = new HashSet<>();
        for (PlanningScenarioItem item : items) {
            TeachingPart part = item.getTeachingPart();
            TeachingPlan plan = item.getTeachingPlan();
            if (!partIds.add(part.getTeachingPartId())) {
                throw new IllegalStateException("Scenario chọn nhiều plan cho cùng TeachingPart.");
            }
            if (plan.getStatus() != TeachingPlanStatus.VALID) {
                throw new IllegalStateException("Snapshot chỉ nhận TeachingPlan VALID.");
            }
            if (!Objects.equals(
                    plan.getTeachingPart().getTeachingPartId(),
                    part.getTeachingPartId()
            )) {
                throw new IllegalStateException("TeachingPlan không thuộc TeachingPart tương ứng.");
            }
            String partTermCode = part.getCourseSection().getAcademicTerm().getTermCode();
            if (!scenario.getAcademicTerm().getTermCode().equals(partTermCode)) {
                throw new IllegalStateException("TeachingPart không thuộc học kỳ của scenario.");
            }
        }
    }

    private ProblemInstanceSnapshot.TermSnapshot mapTerm(AcademicTerm term) {
        return new ProblemInstanceSnapshot.TermSnapshot(
                term.getTermCode(),
                term.getTermName(),
                term.getStartDate(),
                term.getEndDate(),
                term.getStatus().name()
        );
    }

    private ProblemInstanceSnapshot.ScenarioSnapshot mapScenario(
            PlanningScenario scenario,
            List<PlanningScenarioItem> items,
            Map<Long, Integer> partIndexById
    ) {
        List<ProblemInstanceSnapshot.ScenarioItemSnapshot> mappedItems = items.stream()
                .map(item -> new ProblemInstanceSnapshot.ScenarioItemSnapshot(
                        requireIndex(partIndexById, item.getTeachingPart().getTeachingPartId()),
                        item.getTeachingPlan().getTeachingPlanId()
                ))
                .sorted(Comparator.comparingInt(
                        ProblemInstanceSnapshot.ScenarioItemSnapshot::teachingPartIndex))
                .toList();
        return new ProblemInstanceSnapshot.ScenarioSnapshot(
                scenario.getScenarioId(),
                scenario.getScenarioCode(),
                scenario.getAcademicTerm().getTermCode(),
                scenario.getScopeType().name(),
                scenario.getStatus().name(),
                mappedItems
        );
    }

    private List<ProblemInstanceSnapshot.WeekSnapshot> mapWeeks(String termCode) {
        return termWeekRepository.findByAcademicTermTermCodeOrderByWeekNumber(termCode)
                .stream()
                .map(week -> new ProblemInstanceSnapshot.WeekSnapshot(
                        week.getWeekNumber(),
                        week.getStartDate(),
                        week.getEndDate()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.TeachingDateSnapshot> mapTeachingDates(String termCode) {
        return teachingDateRepository.findByAcademicTermTermCodeOrderByCalendarDate(termCode)
                .stream()
                .map(item -> new ProblemInstanceSnapshot.TeachingDateSnapshot(
                        item.getCalendarDate(),
                        item.getWeekNumber(),
                        item.getIsoWeekday(),
                        item.getDateStatus().name()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.TimePeriodSnapshot> mapTimePeriods() {
        return timePeriodRepository.findAll().stream()
                .sorted(Comparator.comparing(TimePeriod::getPeriodNumber))
                .map(item -> new ProblemInstanceSnapshot.TimePeriodSnapshot(
                        item.getPeriodNumber(),
                        item.getStartTime(),
                        item.getEndTime(),
                        item.getSessionName().name()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.AllowedPeriodBlockSnapshot> mapAllowedPeriodBlocks() {
        return allowedPeriodBlockRepository.findAll().stream()
                .filter(item -> Boolean.TRUE.equals(item.getActive()))
                .sorted(Comparator
                        .comparing(AllowedPeriodBlock::getStartPeriod)
                        .thenComparing(AllowedPeriodBlock::getDurationPeriods))
                .map(item -> new ProblemInstanceSnapshot.AllowedPeriodBlockSnapshot(
                        item.getStartPeriod(),
                        item.getDurationPeriods()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.TeachingDurationRuleSnapshot> mapDurationRules() {
        return durationRuleRepository.findAll().stream()
                .sorted(Comparator
                        .comparing((TeachingDurationRule item) -> item.getPartType().name())
                        .thenComparing(TeachingDurationRule::getDurationPeriods))
                .map(item -> new ProblemInstanceSnapshot.TeachingDurationRuleSnapshot(
                        item.getPartType().name(),
                        item.getDurationPeriods(),
                        Boolean.TRUE.equals(item.getStandard())
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.LocationSnapshot> mapLocations(
            List<TeachingLocation> locations,
            Map<Long, Integer> locationIndexById
    ) {
        Map<Long, Room> roomsById = roomRepository.findAll().stream()
                .collect(Collectors.toMap(Room::getLocationId, Function.identity()));
        Map<Long, OnlineLocation> onlineById = onlineLocationRepository.findAll().stream()
                .collect(Collectors.toMap(OnlineLocation::getLocationId, Function.identity()));

        List<ProblemInstanceSnapshot.LocationSnapshot> result = new ArrayList<>();
        for (TeachingLocation location : locations) {
            int index = requireIndex(locationIndexById, location.getLocationId());
            if (location.getLocationType() == LocationType.PHYSICAL_ROOM) {
                Room room = roomsById.get(location.getLocationId());
                if (room == null) {
                    throw new IllegalStateException(
                            "TeachingLocation " + location.getLocationCode() + " thiếu bản ghi Room."
                    );
                }
                result.add(new ProblemInstanceSnapshot.LocationSnapshot(
                        index,
                        location.getLocationId(),
                        location.getLocationCode(),
                        location.getLocationName(),
                        location.getLocationType().name(),
                        Boolean.TRUE.equals(location.getActive()),
                        room.getCampus().getCampusCode(),
                        room.getRoomType().name(),
                        room.getCapacity(),
                        mapRoomEquipment(room.getLocationId()),
                        null
                ));
            } else {
                OnlineLocation online = onlineById.get(location.getLocationId());
                if (online == null) {
                    throw new IllegalStateException(
                            "TeachingLocation " + location.getLocationCode()
                                    + " thiếu bản ghi OnlineLocation."
                    );
                }
                result.add(new ProblemInstanceSnapshot.LocationSnapshot(
                        index,
                        location.getLocationId(),
                        location.getLocationCode(),
                        location.getLocationName(),
                        location.getLocationType().name(),
                        Boolean.TRUE.equals(location.getActive()),
                        null,
                        null,
                        null,
                        List.of(),
                        online.getPlatformName()
                ));
            }
        }
        return List.copyOf(result);
    }

    private List<ProblemInstanceSnapshot.EquipmentQuantitySnapshot> mapRoomEquipment(long roomId) {
        return roomEquipmentRepository.findByRoomLocationId(roomId).stream()
                .sorted(Comparator.comparing(item -> item.getEquipment().getEquipmentCode()))
                .map(item -> new ProblemInstanceSnapshot.EquipmentQuantitySnapshot(
                        item.getEquipment().getEquipmentCode(),
                        item.getQuantity()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.LecturerSnapshot> mapLecturers(
            List<Lecturer> lecturers,
            Map<String, Integer> lecturerIndexByCode
    ) {
        return lecturers.stream()
                .map(item -> new ProblemInstanceSnapshot.LecturerSnapshot(
                        requireIndex(lecturerIndexByCode, item.getLecturerCode()),
                        item.getLecturerCode(),
                        item.getFullName(),
                        item.getHomeCampus() == null
                                ? null
                                : item.getHomeCampus().getCampusCode()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.CourseSnapshot> mapCourses(List<Course> courses) {
        return courses.stream()
                .map(item -> new ProblemInstanceSnapshot.CourseSnapshot(
                        item.getCourseCode(),
                        item.getCourseName()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.CourseSectionSnapshot> mapCourseSections(
            List<CourseSection> sections
    ) {
        return sections.stream()
                .map(item -> new ProblemInstanceSnapshot.CourseSectionSnapshot(
                        item.getSectionCode(),
                        item.getCourse().getCourseCode(),
                        item.getSectionName() == null ? "" : item.getSectionName(),
                        item.getExpectedEnrollment()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.TeachingPartSnapshot> mapTeachingParts(
            List<TeachingPart> parts,
            Map<Long, Integer> partIndexById,
            Map<String, Integer> lecturerIndexByCode
    ) {
        return parts.stream()
                .map(item -> new ProblemInstanceSnapshot.TeachingPartSnapshot(
                        requireIndex(partIndexById, item.getTeachingPartId()),
                        item.getTeachingPartId(),
                        item.getPartCode(),
                        item.getCourseSection().getSectionCode(),
                        item.getPartType().name(),
                        requireIndex(lecturerIndexByCode, item.getLecturer().getLecturerCode()),
                        item.getTotalPeriods(),
                        item.getRequiredLocationType().name(),
                        item.getRequiredRoomType() == null
                                ? null
                                : item.getRequiredRoomType().name(),
                        mapRequiredEquipment(item.getTeachingPartId())
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.EquipmentQuantitySnapshot> mapRequiredEquipment(long partId) {
        return partEquipmentRepository.findByTeachingPartTeachingPartId(partId).stream()
                .sorted(Comparator.comparing(item -> item.getEquipment().getEquipmentCode()))
                .map(item -> new ProblemInstanceSnapshot.EquipmentQuantitySnapshot(
                        item.getEquipment().getEquipmentCode(),
                        item.getMinimumQuantity()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.TeachingPlanSnapshot> mapTeachingPlans(
            List<TeachingPlan> plans,
            Map<Long, Integer> partIndexById
    ) {
        return plans.stream()
                .map(item -> new ProblemInstanceSnapshot.TeachingPlanSnapshot(
                        item.getTeachingPlanId(),
                        item.getPlanCode(),
                        requireIndex(partIndexById, item.getTeachingPart().getTeachingPartId()),
                        item.getStatus().name(),
                        Boolean.TRUE.equals(item.getAllowsIntensive())
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.ClassSessionSnapshot> mapClassSessions(
            List<TeachingPlan> plans
    ) {
        List<ProblemInstanceSnapshot.ClassSessionSnapshot> result = new ArrayList<>();
        int sessionIndex = 0;
        for (TeachingPlan plan : plans) {
            List<ClassSession> sessions = classSessionRepository
                    .findByTeachingPlanTeachingPlanIdOrderBySessionNumber(plan.getTeachingPlanId());
            if (sessions.isEmpty()) {
                throw new IllegalStateException(
                        "Plan " + plan.getPlanCode() + " không có ClassSession."
                );
            }
            for (ClassSession session : sessions) {
                result.add(new ProblemInstanceSnapshot.ClassSessionSnapshot(
                        sessionIndex++,
                        session.getClassSessionId(),
                        plan.getTeachingPlanId(),
                        session.getSessionNumber(),
                        session.getStabilityGroupNo(),
                        session.getTermWeek().getWeekNumber(),
                        session.getDurationPeriods(),
                        session.getRequiredLocationType().name()
                ));
            }
        }
        return List.copyOf(result);
    }

    private List<ProblemInstanceSnapshot.AvailabilitySnapshot> mapLecturerAvailabilities(
            String termCode,
            List<Lecturer> lecturers,
            Map<String, Integer> lecturerIndexByCode
    ) {
        List<ProblemInstanceSnapshot.AvailabilitySnapshot> result = new ArrayList<>();
        for (Lecturer lecturer : lecturers) {
            int index = requireIndex(lecturerIndexByCode, lecturer.getLecturerCode());
            for (LecturerAvailability item : lecturerAvailabilityRepository
                    .findByAcademicTermTermCodeAndLecturerLecturerCode(
                            termCode,
                            lecturer.getLecturerCode()
                    )) {
                result.add(new ProblemInstanceSnapshot.AvailabilitySnapshot(
                        index,
                        item.getScopeType().name(),
                        item.getStartPeriod(),
                        item.getEndPeriod(),
                        item.getAvailabilityType().name(),
                        item.getCalendarDate(),
                        item.getIsoWeekday(),
                        item.getPreferenceWeight() == null
                                ? null
                                : item.getPreferenceWeight().doubleValue()
                ));
            }
        }
        return result.stream().sorted(availabilityComparator()).toList();
    }

    private List<ProblemInstanceSnapshot.AvailabilitySnapshot> mapRoomAvailabilities(
            String termCode,
            List<TeachingLocation> locations,
            Map<Long, Integer> locationIndexById
    ) {
        List<ProblemInstanceSnapshot.AvailabilitySnapshot> result = new ArrayList<>();
        for (TeachingLocation location : locations) {
            if (location.getLocationType() != LocationType.PHYSICAL_ROOM) {
                continue;
            }
            int index = requireIndex(locationIndexById, location.getLocationId());
            for (RoomAvailability item : roomAvailabilityRepository
                    .findByAcademicTermTermCodeAndRoomLocationId(
                            termCode,
                            location.getLocationId()
                    )) {
                result.add(new ProblemInstanceSnapshot.AvailabilitySnapshot(
                        index,
                        item.getScopeType().name(),
                        item.getStartPeriod(),
                        item.getEndPeriod(),
                        item.getAvailabilityType().name(),
                        item.getCalendarDate(),
                        item.getIsoWeekday(),
                        null
                ));
            }
        }
        return result.stream().sorted(availabilityComparator()).toList();
    }

    private Comparator<ProblemInstanceSnapshot.AvailabilitySnapshot> availabilityComparator() {
        return Comparator
                .comparingInt(ProblemInstanceSnapshot.AvailabilitySnapshot::resourceIndex)
                .thenComparing(ProblemInstanceSnapshot.AvailabilitySnapshot::scopeType)
                .thenComparing(
                        ProblemInstanceSnapshot.AvailabilitySnapshot::calendarDate,
                        Comparator.nullsFirst(Comparator.naturalOrder())
                )
                .thenComparing(
                        ProblemInstanceSnapshot.AvailabilitySnapshot::isoWeekday,
                        Comparator.nullsFirst(Comparator.naturalOrder())
                )
                .thenComparingInt(ProblemInstanceSnapshot.AvailabilitySnapshot::startPeriod)
                .thenComparingInt(ProblemInstanceSnapshot.AvailabilitySnapshot::endPeriod)
                .thenComparing(ProblemInstanceSnapshot.AvailabilitySnapshot::availabilityType);
    }

    private List<ProblemInstanceSnapshot.CampusTravelTimeSnapshot> mapCampusTravelTimes() {
        return campusTravelTimeRepository.findAll().stream()
                .sorted(Comparator
                        .comparing((CampusTravelTime item) ->
                                item.getFromCampus().getCampusCode())
                        .thenComparing(item -> item.getToCampus().getCampusCode()))
                .map(item -> new ProblemInstanceSnapshot.CampusTravelTimeSnapshot(
                        item.getFromCampus().getCampusCode(),
                        item.getToCampus().getCampusCode(),
                        item.getTravelMinutes()
                ))
                .toList();
    }

    private List<ProblemInstanceSnapshot.ConstraintSettingSnapshot> mapConstraintSettings() {
        return constraintSettingRepository.findAll().stream()
                .sorted(Comparator.comparing(ConstraintSetting::getConstraintCode))
                .map(item -> new ProblemInstanceSnapshot.ConstraintSettingSnapshot(
                        item.getConstraintCode(),
                        item.getConstraintKind().name(),
                        item.getPriorityTier(),
                        item.getWeight() == null ? null : item.getWeight().doubleValue(),
                        Boolean.TRUE.equals(item.getEnabled())
                ))
                .toList();
    }

    private <K, V> Map<K, Integer> indexBy(
            List<V> values,
            Function<V, K> keyExtractor
    ) {
        Map<K, Integer> result = new HashMap<>();
        for (int index = 0; index < values.size(); index++) {
            K key = keyExtractor.apply(values.get(index));
            if (result.put(key, index) != null) {
                throw new IllegalStateException("Snapshot gặp khóa trùng: " + key + ".");
            }
        }
        return result;
    }

    private <K> int requireIndex(Map<K, Integer> indexes, K key) {
        Integer index = indexes.get(key);
        if (index == null) {
            throw new IllegalStateException("Không tìm thấy index snapshot cho khóa " + key + ".");
        }
        return index;
    }
}
