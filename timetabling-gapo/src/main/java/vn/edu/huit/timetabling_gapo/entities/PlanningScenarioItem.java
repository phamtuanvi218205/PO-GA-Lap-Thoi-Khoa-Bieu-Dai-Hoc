package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.entities.ids.PlanningScenarioItemId;

@Entity
@Table(name = "PlanningScenarioItem")
@IdClass(PlanningScenarioItemId.class)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class PlanningScenarioItem {
    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "scenario_id", nullable = false)
    private PlanningScenario planningScenario;

    @Id
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "teaching_part_id", nullable = false)
    private TeachingPart teachingPart;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "teaching_plan_id", nullable = false)
    private TeachingPlan teachingPlan;
}
