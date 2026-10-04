package vn.edu.huit.timetabling_gapo.entities.ids;

import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.NoArgsConstructor;

import java.io.Serializable;

@NoArgsConstructor
@AllArgsConstructor
@EqualsAndHashCode
public class PlanningScenarioItemId implements Serializable {
    private Long planningScenario;
    private Long teachingPart;
}
