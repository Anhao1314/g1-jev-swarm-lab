"""Cost accounting must include unusable provider responses exactly once."""
from scripts.analyze_source_authority_pilot import wire_accounting

def test_reasoning_only_budget_exhaustion_has_real_provider_cost():
    evidence={'events':[{'status':'SUCCESS','provider_document':{
        'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},
        'output':[{'type':'reasoning','summary':[]}],
        'usage':{'input_tokens':100,'output_tokens':4096,'total_tokens':4600}}}],
        'responses':[{'error_type':'LLMBackendError'}]}
    out=wire_accounting(evidence)
    assert out['provider_reported_total_tokens']==4600
    assert out['budget_exhausted_responses']==1 and out['empty_assistant_responses']==1

def test_successful_wire_usage_is_not_added_to_final_usage_twice():
    usage={'total_tokens':200}
    out=wire_accounting({'events':[{'status':'SUCCESS','provider_document':{
        'status':'completed','usage':usage,'output':[{'content':[{'type':'output_text','text':'{}'}]}]}}],
        'responses':[{'usage':usage}]})
    assert out['provider_reported_total_tokens']==200 and out['responses_with_usage']==1
    assert out['empty_assistant_responses']==0

def test_transport_failure_and_missing_accounting_are_distinct():
    out=wire_accounting({'events':[{'status':'TIMEOUT'},{'status':'SUCCESS','provider_document':{'status':'incomplete'}}], 'responses':[]})
    assert out['transport_failure_attempts']==1
    assert out['wire_responses_missing_token_accounting']==1
    assert out['provider_reported_total_tokens']==0

def test_response_only_fallback_preserves_reported_total():
    out=wire_accounting({'events':[],'responses':[{'usage':{'input_tokens':1,'output_tokens':2,'total_tokens':17}}]})
    assert out['provider_reported_total_tokens']==17
