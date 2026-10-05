package vn.edu.huit.timetabling_gapo.planning;

import org.junit.jupiter.api.Test;
import vn.edu.huit.timetabling_gapo.enums.LocationType;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class SessionExpanderTest {

    private final SessionExpander expander = new SessionExpander();

    @Test
    void expandsEveryPlanItemWithoutChangingWeekOrDuration() {
        GeneratedTeachingPlan plan = new GeneratedTeachingPlan(
                1,
                "JAVA01_LT_AUTO_01",
                "Tự động: 3 buổi x 3 tiết",
                false,
                List.of(
                        new GeneratedTeachingPlanItem(1, 1, 1, 3, 1),
                        new GeneratedTeachingPlanItem(2, 2, 1, 3, 1),
                        new GeneratedTeachingPlanItem(3, 3, 1, 3, 1)
                )
        );

        List<ExpandedClassSession> sessions = expander.expand(
                plan,
                LocationType.PHYSICAL_ROOM
        );

        assertEquals(3, sessions.size());
        assertEquals(
                new ExpandedClassSession(2, 2, 3, 1, LocationType.PHYSICAL_ROOM),
                sessions.get(1)
        );
    }

    @Test
    void rejectsMissingPlanOrLocationType() {
        GeneratedTeachingPlan plan = new GeneratedTeachingPlan(
                1,
                "JAVA01_LT_AUTO_01",
                "Một buổi",
                false,
                List.of(new GeneratedTeachingPlanItem(1, 1, 1, 3, 1))
        );

        assertThrows(IllegalArgumentException.class, () -> expander.expand(null, LocationType.ONLINE));
        assertThrows(IllegalArgumentException.class, () -> expander.expand(plan, null));
    }
}
