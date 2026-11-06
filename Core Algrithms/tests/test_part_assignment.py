"""LT and TH may have distinct qualified lecturers; weekly part stays assigned."""
from dataclasses import replace
from pathlib import Path
import pytest
from gapo_timetabling.core.models import PartType
from gapo_timetabling.core.encoder import build_option_domains
from gapo_timetabling.core.decoder import decode_vector,decode_saved_vector,encoding_for_problem,PART_PLACEMENT_ENCODING,PLACEMENT_ENCODING
from gapo_timetabling.core.constraints import validate_timetable,HardViolationCode
from gapo_timetabling.core.fitness import calculate_fitness
from gapo_timetabling.core.population import initialize_population,CandidateEvaluationConfig
from gapo_timetabling.core.ga import run_ga,GAConfig
from gapo_timetabling.core.po import run_po,PoConfig
from gapo_timetabling.core.hybrid import run_hybrid,HybridConfig
from gapo_timetabling.core.greedy_baseline import build_greedy_vector
from gapo_timetabling.application.snapshot_builder import ProblemInstanceSnapshotBuilder
from gapo_timetabling.application.semester_preparation import SemesterReadinessService
from gapo_timetabling.core.snapshot import build_gene_option_mapping,prepare_snapshot_for_optimization
from tests import test_dynamic_lecturer_assignment as dynamic_fixture


def problem():
    old=dynamic_fixture.TestDynamicLecturerAssignment().build_problem(first_lecturer_unavailable=False)
    caps=tuple(replace(c,can_teach_lecture=c.lecturer_index==0,can_teach_practice=c.lecturer_index==1,
        suitability_score=.9 if c.lecturer_index==0 else .7) for c in old.lecturer_course_capabilities)
    return replace(old,lecturer_assignment_scope='TEACHING_PART',lecturer_course_capabilities=caps)


def test_separate_eligibility_and_decoder_validator_allow_split_teachers():
    p=problem(); d=build_option_domains(p)
    assert p.assignment_dimension==2
    assert p.eligible_assignment_lecturers(p.assignment_keys[0])==(0,)
    assert p.eligible_assignment_lecturers(p.assignment_keys[1])==(1,)
    assert p.eligible_lecturer_indices(p.course_sections[0].section_code)==()
    result=decode_vector(p,d,(.5,)*p.dimension,1000)
    assert result.is_success
    assert result.selected_lecturer_indices==(0,1)
    assert validate_timetable(p,result.selected_options).is_valid
    assert encoding_for_problem(p)==PART_PLACEMENT_ENCODING
    assert decode_saved_vector(p,d,result.repaired_vector,1000,encoding=PART_PLACEMENT_ENCODING)==result
    with pytest.raises(ValueError): decode_saved_vector(p,d,result.repaired_vector,1000,encoding=PLACEMENT_ENCODING)


def test_wrong_part_qualification_is_rejected():
    p=problem(); d=build_option_domains(p)
    result=decode_vector(p,d,(.5,)*p.dimension,1000)
    options=list(result.selected_options)
    options[0]=replace(options[0],lecturer_index=1)
    validation=validate_timetable(p,tuple(options))
    assert not validation.is_valid
    assert any(v.code==HardViolationCode.LECTURER_NOT_QUALIFIED for v in validation.violations)


def test_suitability_counts_each_part_teacher_with_period_weights():
    p=problem(); d=build_option_domains(p)
    result=decode_vector(p,d,(.5,)*p.dimension,1000)
    f=calculate_fitness(p,result.selected_options,d)
    periods={part.part_type:part.total_periods for part in p.teaching_parts}
    expected=(periods[PartType.LECTURE]*.1+periods[PartType.PRACTICE]*.3)/sum(periods.values())
    assert f.breakdown.course_suitability_component==pytest.approx(expected)


@pytest.mark.parametrize('method',['GA','PO','GA_PO'])
def test_all_optimizers_support_split_assignment(method):
    p=problem(); d=build_option_domains(p); evaluation=CandidateEvaluationConfig(1000,True,3)
    initial=initialize_population(p,d,population_size=10,max_initialization_attempts=100,seed=42,evaluation_config=evaluation)
    assert initial.is_success
    cfg=dict(max_fitness_evaluations=30,max_offspring_attempts=5,seed=42,evaluation_config=evaluation)
    runner,config={'GA':(run_ga,GAConfig),'PO':(run_po,PoConfig),'GA_PO':(run_hybrid,HybridConfig)}[method]
    result=runner(p,d,initial,config(**cfg))
    assert validate_timetable(p,result.best_individual.selected_options).is_valid
    assert result.metrics.fitness_evaluations<=30
    replay=decode_vector(p,d,result.best_individual.vector,1000)
    assert replay.selected_options==result.best_individual.selected_options


def test_greedy_and_mapping_use_part_genes():
    p=problem(); d=build_option_domains(p)
    vector=build_greedy_vector(p,d)
    assert decode_vector(p,d,vector,1000).is_success
    mapping=build_gene_option_mapping(p,d,'test')
    assert mapping['schema_version']=='gene-option-mapping.v6'
    assert [g['part_code'] for g in mapping['assignment_genes']]==list(p.assignment_keys)
    assert mapping['vector_encoding']==PART_PLACEMENT_ENCODING


def test_readiness_and_snapshot_builder_do_not_require_joint_qualification():
    parts=[dict(section_code='S',course_code='C',teaching_part_id=1,part_code='S_LT',part_type='LECTURE'),
        dict(section_code='S',course_code='C',teaching_part_id=2,part_code='S_TH',part_type='PRACTICE')]
    capabilities=[dict(course_code='C',lecturer_code='A',can_teach_lecture=True,can_teach_practice=False),
        dict(course_code='C',lecturer_code='B',can_teach_lecture=False,can_teach_practice=True)]
    ProblemInstanceSnapshotBuilder._validate_capabilities(parts,capabilities)
    issues=[]
    SemesterReadinessService(None)._check_sections_and_capabilities(parts,capabilities,issues)
    assert not issues
    with pytest.raises(RuntimeError): ProblemInstanceSnapshotBuilder._validate_capabilities(parts,capabilities[:1])


def test_same_teacher_still_allowed_when_qualified_for_both():
    p=problem()
    p=replace(p,lecturer_course_capabilities=tuple(replace(c,can_teach_lecture=True,can_teach_practice=True) for c in p.lecturer_course_capabilities))
    d=build_option_domains(p)
    result=decode_vector(p,d,(0.,0.)+(.5,)*(p.dimension-2),1000)
    assert result.is_success and result.selected_lecturer_indices==(0,0)
    assert validate_timetable(p,result.selected_options).is_valid


def test_load_limits_are_charged_to_each_actual_teacher():
    p=problem()
    # Each lecturer can cover one part, not the combined LT+TH load.
    limits={0:p.teaching_parts[0].total_periods,1:p.teaching_parts[1].total_periods}
    p=replace(p,lecturers=tuple(replace(l,max_teaching_periods=limits[l.lecturer_index]) for l in p.lecturers))
    d=build_option_domains(p)
    result=decode_vector(p,d,(.5,)*p.dimension,1000)
    assert result.is_success and validate_timetable(p,result.selected_options).is_valid
    overloaded=replace(p,lecturers=tuple(replace(l,max_teaching_periods=1) if l.lecturer_index==0 else l for l in p.lecturers))
    assert not decode_vector(overloaded,build_option_domains(overloaded),(.5,)*p.dimension,1000).is_success


def test_v3_scope_contradiction_is_not_silently_accepted():
    from tests.test_snapshot import make_snapshot_payload
    payload=make_snapshot_payload()
    payload.update(schema_version='problem-instance.v3',lecturer_assignment_scope='SECTION')
    with pytest.raises(ValueError,match='scope'):prepare_snapshot_for_optimization(payload)


def test_one_part_cannot_switch_lecturers_across_weeks():
    from datetime import timedelta
    from gapo_timetabling.core.models import SessionOption
    p=problem()
    # Both teachers qualified for both types so mismatch cannot be hidden by
    # a qualification failure; duplicate the full validated week consistently.
    p=replace(p,lecturer_course_capabilities=tuple(replace(c,can_teach_lecture=True,can_teach_practice=True) for c in p.lecturer_course_capabilities))
    shift=timedelta(days=7); n=len(p.class_sessions)
    p=replace(p,term=replace(p.term,end_date=p.term.end_date+shift),
        weeks=p.weeks+(replace(p.weeks[0],week_number=2,start_date=p.weeks[0].start_date+shift,end_date=p.weeks[0].end_date+shift),),
        teaching_dates=p.teaching_dates+tuple(replace(d,calendar_date=d.calendar_date+shift,week_number=2) for d in p.teaching_dates),
        teaching_parts=tuple(replace(part,total_periods=part.total_periods*2) for part in p.teaching_parts),
        class_sessions=p.class_sessions+tuple(replace(s,session_index=s.session_index+n,class_session_id=s.class_session_id+100,
            session_number=2,week_number=2) for s in p.class_sessions))
    d=build_option_domains(p)
    decoded=decode_vector(p,d,(.1,)*p.dimension,1000)
    assert decoded.is_success
    options=list(decoded.selected_options)
    # Alter only first part's second week to the other qualified lecturer.
    options[n]=replace(options[n],lecturer_index=1)
    assert any(v.code==HardViolationCode.PART_LECTURER_MISMATCH for v in validate_timetable(p,tuple(options)).violations)


def test_legacy_snapshot_keeps_section_scope():
    p=prepare_snapshot_for_optimization(Path(__file__).resolve().parents[1]/'demo_data/dynamic_assignment_snapshot_v2.json').problem
    assert p.lecturer_assignment_scope=='SECTION'
    assert p.assignment_dimension==len(p.assignment_section_codes)
    assert encoding_for_problem(p)==PLACEMENT_ENCODING


def test_v3_snapshot_request_envelope_and_parallel_replay(monkeypatch):
    from tests.test_snapshot import make_snapshot_payload
    from tests.test_run_contract import make_run_request_payload
    from gapo_timetabling.application.run_contract import execute_prepared_run_request,parse_run_request
    from gapo_timetabling.application.parallel_execution import execute_web_run_request
    payload=make_snapshot_payload()
    payload['schema_version']='problem-instance.v3'
    payload['lecturer_assignment_scope']='TEACHING_PART'
    prepared=prepare_snapshot_for_optimization(payload)
    assert prepared.problem.lecturer_assignment_scope=='TEACHING_PART'
    req=parse_run_request(make_run_request_payload('unused.json'),base_directory=Path.cwd())
    expected=execute_prepared_run_request(req,prepared)
    assert expected['status']=='COMPLETED'
    assert expected['solver_pipeline']==PART_PLACEMENT_ENCODING
    monkeypatch.setenv('GAPO_EVALUATION_WORKERS','2')
    actual=execute_web_run_request(req,prepared)
    actual.pop('execution')
    for r in (expected,actual):r['result']['metrics'].pop('runtime_seconds')
    assert expected==actual
