package vn.edu.huit.timetabling_gapo;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.transaction.annotation.Transactional;
import vn.edu.huit.timetabling_gapo.enums.PlanningScenarioStatus;
import vn.edu.huit.timetabling_gapo.enums.ScenarioScopeType;
import vn.edu.huit.timetabling_gapo.planning.AutomaticScenarioRequest;
import vn.edu.huit.timetabling_gapo.planning.PlanningScenarioOrchestrationService;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest
class TimetablingGapoApplicationTests {

	@Autowired
	private PlanningScenarioOrchestrationService scenarioService;

	@Test
	void contextLoads() {
	}

	@Test
	@Transactional
	void automaticPlanningFlowWorksAgainstTheRealDevelopmentSchema() {
		var scenarios = scenarioService.createAndLockCandidates(
				new AutomaticScenarioRequest(
						"2026_HK1",
						ScenarioScopeType.FULL_TERM,
						Set.of(),
						3
				)
		);

		assertFalse(scenarios.isEmpty());
		assertTrue(scenarios.stream()
				.allMatch(scenario -> scenario.getStatus() == PlanningScenarioStatus.LOCKED));
	}

}
