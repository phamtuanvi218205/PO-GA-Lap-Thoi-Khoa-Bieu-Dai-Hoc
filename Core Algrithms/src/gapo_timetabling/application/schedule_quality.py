"""Read-only explanations of the existing Fitness, never a new objective."""

from ..core.fitness import calculate_fitness, _get_soft_weight


GENERAL_COMPONENTS = (
    ("SOFT_LECTURER_GAP", "gap_component", "Khoảng trống giảng viên"),
    ("SOFT_LECTURER_CONSECUTIVE", "lecturer_consecutive_component", "Dạy liên tục vượt ngưỡng"),
    ("SOFT_ROOM_DISCOURAGED", "room_discouraged_component", "Dùng phòng vào khung hạn chế"),
    ("SOFT_WORKLOAD_BALANCE", "workload_balance_component", "Cân bằng tải giảng dạy"),
    ("SOFT_ROOM_STABILITY", "room_stability_component", "Thay đổi phòng trong nhóm lịch"),
)


def explain_quality(problem, domains, selected, *, mode):
    fitness = calculate_fitness(problem, selected, domains, preference_domain_mode=mode)
    breakdown = fitness.breakdown
    general = []
    for code, field, label in GENERAL_COMPONENTS:
        weight = _get_soft_weight(problem, code)
        if weight > 0:
            value = getattr(breakdown, field)
            general.append(dict(code=code, label=label, value=value, weight=weight,
                                contribution=weight * value))
    # Reverse the SAME weighted average used by Fitness, not a new preference
    # formula. With a disabled time criterion its unweighted value is unknown.
    dynamic = bool(problem.lecturer_course_capabilities)
    tw = _get_soft_weight(problem, "SOFT_LECTURER_TIME_PREFERENCE") if dynamic else 1.0
    sw = _get_soft_weight(problem, "SOFT_COURSE_SUITABILITY") if dynamic else 0.0
    total = tw + sw
    suitability = breakdown.course_suitability_component
    time_value = None if tw == 0 else max(0.0, min(1.0,
        (fitness.lecturer_preference_score * total - sw * suitability) / tw))
    lecturer = [dict(code="TIME", label="Mong muốn thời gian", value=time_value,
                     weight=tw / total if total else 0,
                     contribution=(tw * time_value / total) if tw and total else 0),
                dict(code="SUITABILITY", label="Mức chưa phù hợp môn–giảng viên",
                     value=suitability, weight=sw / total if total else 0,
                     contribution=sw * suitability / total if total else 0)]
    people = {item.lecturer_index: item for item in problem.lecturers}
    return dict(
        general_quality_score=fitness.general_quality_score,
        lecturer_preference_score=fitness.lecturer_preference_score,
        preference_domain_mode=mode, hard_violation_count=0,
        session_count=len(selected), general_components=general,
        lecturer_components=lecturer,
        lecturer_details=[dict(
            lecturer_code=people[item.lecturer_index].lecturer_code,
            lecturer_name=people[item.lecturer_index].full_name,
            evaluated_session_count=item.evaluated_session_count,
            missed_preferred_penalty=item.missed_preferred_penalty,
            discouraged_overlap_penalty=item.discouraged_overlap_penalty,
        ) for item in breakdown.lecturer_breakdown],
    )
