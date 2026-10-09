"""Only synthetic data / static source checks; no simulation or policy imports."""
import copy
import importlib.util
import math
from pathlib import Path
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('m26a_design_check',HERE/'check_design.py')
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
PROTO=mod.read(HERE/'protocol.json')


def rows():
    result=[]
    for cell in PROTO['cells_in_order']:
        id=cell['id']
        row={'cell_id':id,'status':'VALID','integrity_valid':True,'control_valid':True}
        if id=='normal_stop_control': row.update(parent_branch='NORMAL_STOP',halt='NOT_REQUESTED',hold='SUCCEEDED')
        elif id in ('seen_plus_y_early_control','unseen_plus_y_late_partner'):
            row.update(parent_branch='STRICT_PASS_NO_HALT',halt='NOT_REQUESTED',hold='NOT_RUN')
        else:
            row.update(parent_branch='STRICT_TRIGGER',halt='SUCCEEDED',hold='SUCCEEDED',request_distinct=True,hold_entry_distinct=True,distinct_from_other_primary=True)
        result.append(row)
    return result


def state():
    return {'qpos':[0,0,.8,1,0,0,0]+[0.1]*12,'qvel':[.4,.03,.01,0,0,.05]+[.2]*12,'case_id':'same','counter':100}


def test_static_contract_and_bound_sources():
    assert mod.validate()['status']=='CANDIDATE_DESIGN_CHECK_PASS_NO_PHYSICS'


@pytest.mark.parametrize('cell',[1,2,3,4])
def test_exact_force_prefix_interval_and_clearance(cell):
    push=PROTO['cells_in_order'][cell]['push']; start=push['native_pre_step_start_index']
    assert all(mod.force_at_pre_step(push,n)==(0,0,0) for n in range(start))
    assert sum(mod.force_at_pre_step(push,n)!=(0,0,0) for n in range(start+101))==100
    assert mod.force_at_pre_step(push,start+100)==(0,0,0)


def test_translation_global_yaw_seed_and_counter_are_not_distinct():
    a=state(); b=copy.deepcopy(a); theta=.7
    b['qpos'][:2]=[100,-37]; b['qpos'][3:7]=[math.cos(theta/2),0,0,math.sin(theta/2)]
    b['qvel'][0]=math.cos(theta)*a['qvel'][0]-math.sin(theta)*a['qvel'][1]
    b['qvel'][1]=math.sin(theta)*a['qvel'][0]+math.cos(theta)*a['qvel'][1]
    b['case_id']='renamed-seed999'; b['counter']=20000
    d=mod.state_difference(a,b,PROTO['state_distinctness']['features'])
    assert not d['operationally_distinct']


def test_physical_joint_difference_can_qualify_and_raw_deltas_retained():
    a=state(); b=copy.deepcopy(a); b['qpos'][7:]=[x+.03 for x in b['qpos'][7:]]
    d=mod.state_difference(a,b,PROTO['state_distinctness']['features'])
    assert d['operationally_distinct'] and d['deltas']['joint_position_rms_difference_rad']==pytest.approx(.03)


def test_nonfinite_novelty_is_unavailable_not_imputed():
    b=state(); b['qvel'][0]=float('nan')
    with pytest.raises(ValueError): mod.descriptor(b)


def test_bounded_support_and_normal_excluded_from_halt_denominator():
    result=mod.campaign_decision(PROTO,rows())
    assert result['scientific_signal']=='BOUNDED_PRIMARY_PAIR_SUPPORTED'
    assert result['failure_chain_halt_denominator']==3
    assert result['failure_chain_hold_denominator']==3


def test_required_nontrigger_is_coverage_gap_not_halt_failure():
    x=rows(); x[1].update(parent_branch='STRICT_PASS_NO_HALT',halt='NOT_REQUESTED',hold='NOT_RUN')
    r=mod.campaign_decision(PROTO,x)
    assert r['scientific_signal']=='INCONCLUSIVE_COVERAGE_OR_TECHNICAL' and not r['counterexamples']


def test_unsupported_physical_failure_retained_without_forced_halt():
    x=rows(); x[1].update(parent_branch='SKILL_OR_PHYSICAL_FAILURE_NO_HALT',halt='NOT_REQUESTED',hold='NOT_RUN')
    r=mod.campaign_decision(PROTO,x)
    assert x[1]['cell_id'] in r['coverage_or_integrity_problems'] and not r['counterexamples']


def test_halt_failure_is_qualified_counterexample_no_hold():
    x=rows(); x[1].update(halt='FAILED',hold='NOT_RUN')
    r=mod.campaign_decision(PROTO,x)
    assert r['counterexamples']==[x[1]['cell_id']] and r['scientific_signal']=='BOUNDED_UNSEEN_COUNTEREXAMPLE'


def test_hold_failure_and_secondary_failure_veto_support():
    x=rows(); x[3].update(parent_branch='STRICT_TRIGGER',halt='SUCCEEDED',hold='FAILED',request_distinct=True,hold_entry_distinct=True)
    assert mod.campaign_decision(PROTO,x)['scientific_signal']=='BOUNDED_UNSEEN_COUNTEREXAMPLE'


def test_aliased_success_does_not_count_as_new_hold_coverage():
    x=rows(); x[1]['hold_entry_distinct']=False
    assert mod.campaign_decision(PROTO,x)['scientific_signal']=='INCONCLUSIVE_COVERAGE_OR_TECHNICAL'


def test_condition_new_failure_not_distinct_not_unseen_counterexample():
    x=rows(); x[1].update(hold='FAILED',request_distinct=False)
    r=mod.campaign_decision(PROTO,x)
    assert r['condition_negatives_not_distinct']==[x[1]['cell_id']] and not r['counterexamples']


def test_valid_counterexample_survives_later_technical_partial():
    x=rows(); x[1].update(halt='FAILED',hold='NOT_RUN'); x[2]['status']='TECHNICAL_PARTIAL'
    for r in x[3:]: r['status']='NOT_RUN'
    result=mod.campaign_decision(PROTO,x)
    assert result['campaign_completion']=='PARTIAL' and result['counterexamples']==[x[1]['cell_id']]


@pytest.mark.parametrize('cell',[0,5])
def test_seen_or_normal_control_physical_failure_never_hidden_by_primary_pass(cell):
    x=rows(); x[cell]['hold']='FAILED'
    result=mod.campaign_decision(PROTO,x)
    assert result['scientific_signal']=='INCONCLUSIVE_COVERAGE_OR_TECHNICAL'
    assert result['seen_or_control_physical_negatives']==[x[cell]['cell_id']]


def test_zero_denominators_are_na_and_missing_cells_not_dropped():
    x=rows()
    for r in x: r.update(parent_branch='STRICT_PASS_NO_HALT',halt='NOT_REQUESTED',hold='NOT_RUN')
    result=mod.campaign_decision(PROTO,x)
    assert result['halt_success_fraction'] is None and result['hold_success_fraction'] is None
    with pytest.raises(ValueError): mod.campaign_decision(PROTO,x[:-1])


@pytest.mark.parametrize('change',[{'parent_branch':'STRICT_TRIGGER','halt':'NOT_REQUESTED','hold':'NOT_RUN'},
                                 {'parent_branch':'STRICT_PASS_NO_HALT','halt':'SUCCEEDED','hold':'SUCCEEDED'},
                                 {'parent_branch':'NORMAL_STOP','halt':'SUCCEEDED','hold':'SUCCEEDED'},
                                 {'parent_branch':'STRICT_TRIGGER','halt':'FAILED','hold':'SUCCEEDED'}])
def test_layer_conflation_or_forced_halt_rejected(change):
    x=rows(); x[1].update(change)
    with pytest.raises(ValueError): mod.campaign_decision(PROTO,x)


@pytest.mark.parametrize('field,value',[('force_n',90),('duration_s',.3),('relative_first_walk_trigger_s',4.1)])
def test_result_driven_force_redefinition_rejected(field,value):
    p=copy.deepcopy(PROTO); p['cells_in_order'][2]['push'][field]=value
    with pytest.raises(AssertionError): mod.validate(p)


def test_hold_threshold_change_and_insufficient_full_parent_budget_rejected():
    p=copy.deepcopy(PROTO); p['layer3_hold']['contract']['acceptance']['hold_xy_path_length_at_most_m']=.25
    with pytest.raises(AssertionError): mod.validate(p)
    p=copy.deepcopy(PROTO); p['budget']['max_native_steps_per_cell']=21500
    with pytest.raises(AssertionError): mod.validate(p)
