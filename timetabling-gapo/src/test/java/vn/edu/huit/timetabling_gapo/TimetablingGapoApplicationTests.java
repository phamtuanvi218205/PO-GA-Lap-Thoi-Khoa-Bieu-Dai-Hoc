package vn.edu.huit.timetabling_gapo;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.transaction.annotation.Transactional;
import vn.edu.huit.timetabling_gapo.enums.PlanningScenarioStatus;
import vn.edu.huit.timetabling_gapo.enums.ScenarioScopeType;
import vn.edu.huit.timetabling_gapo.planning.AutomaticScenarioRequest;
import vn.edu.huit.timetabling_gapo.planning.PlanningScenarioOrchestrationService;
import vn.edu.huit.timetabling_gapo.snapshot.ProblemInstanceSnapshotBuilder;
import vn.edu.huit.timetabling_gapo.snapshot.ProblemInstanceSnapshotSerializer;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest
class TimetablingGapoApplicationTests {

	@Autowired
	private PlanningScenarioOrchestrationService scenarioService;

	@Autowired
	private ProblemInstanceSnapshotBuilder snapshotBuilder;

	@Autowired
	private ProblemInstanceSnapshotSerializer snapshotSerializer;

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

	@Test
	@Transactional
	void lockedScenarioProducesDeterministicRoundTripSnapshot() {
		var scenario = scenarioService.createAndLockCandidates(
				new AutomaticScenarioRequest(
						"2026_HK1",
						ScenarioScopeType.FULL_TERM,
						Set.of(),
						1
				)
		).getFirst();

		var first = snapshotBuilder.build(scenario.getScenarioId());
		var second = snapshotBuilder.build(scenario.getScenarioId());
		var restored = snapshotSerializer.deserialize(first.canonicalJson());

		assertEquals(first.canonicalJson(), second.canonicalJson());
		assertEquals(first.sha256Checksum(), second.sha256Checksum());
		assertEquals(64, first.sha256Checksum().length());
		assertEquals(first.snapshot(), restored);
		assertEquals("problem-instance.v1", restored.schemaVersion());
		assertFalse(restored.classSessions().isEmpty());
		assertEquals(0, restored.classSessions().getFirst().sessionIndex());
		assertNotNull(restored.scenario());
		assertTrue(first.canonicalJson().contains("\"schema_version\""));
		assertTrue(first.canonicalJson().contains("\"class_sessions\""));
	}

}
