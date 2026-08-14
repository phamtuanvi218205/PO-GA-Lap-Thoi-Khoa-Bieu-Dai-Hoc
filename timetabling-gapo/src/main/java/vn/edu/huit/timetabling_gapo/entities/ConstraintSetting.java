package vn.edu.huit.timetabling_gapo.entities;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import vn.edu.huit.timetabling_gapo.enums.ConstraintType;

import java.math.BigDecimal;

@Entity
@Table(
        name = "ConstraintSetting",
        uniqueConstraints = @UniqueConstraint(
                name = "UQ_ConstraintSetting_Term_Code",
                columnNames = {"term_code", "constraint_code"}
        )
)
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class ConstraintSetting {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "constraint_setting_id")
    private Integer constraintSettingId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "term_code", nullable = false)
    private AcademicTerm academicTerm;

    @Column(name = "constraint_code", nullable = false, length = 30)
    private String constraintCode;

    @Column(name = "constraint_name", nullable = false, length = 150)
    private String constraintName;

    @Enumerated(EnumType.STRING)
    @Column(name = "constraint_type", nullable = false, length = 10)
    private ConstraintType constraintType;

    @Column(name = "weight_value", nullable = false, precision = 12, scale = 4)
    private BigDecimal weightValue;

    @Column(name = "is_enabled", nullable = false)
    private Boolean enabled;

    @Column(name = "description", length = 500)
    private String description;
}
