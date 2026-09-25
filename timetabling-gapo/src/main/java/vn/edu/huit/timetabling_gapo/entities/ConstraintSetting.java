package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.*;
import lombok.*;
import vn.edu.huit.timetabling_gapo.enums.ConstraintType;

import java.math.BigDecimal;

@Entity
@Table(name = "ConstraintSetting")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor
public class ConstraintSetting {
    @Id
    @Column(name = "constraint_code", length = 50)
    private String constraintCode;

    @Column(name = "constraint_name", nullable = false, length = 200)
    private String constraintName;

    @Enumerated(EnumType.STRING)
    @Column(name = "constraint_kind", nullable = false, length = 20)
    private ConstraintType constraintKind;

    @Column(name = "priority_tier", nullable = false)
    private Integer priorityTier;

    @Column(name = "weight", precision = 12, scale = 4)
    private BigDecimal weight;

    @Column(name = "is_enabled", nullable = false)
    private Boolean enabled;

    @Column(name = "note", length = 500)
    private String note;
}
