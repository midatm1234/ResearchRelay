"""Credential-free provider contract checks. These do not claim live model execution."""
import json
import os
from pathlib import Path
import sys
import threading

import httpx
import pytest

from researchrelay.providers import (APIReportProvider, CommandReportProvider, ProviderError,
                                    REPORT_SCHEMA, validate_profile)

REPORT = {'body':'# Finding\n\nIndependent review is required.', 'findings':['The supplied evidence supports a bounded comparison.'],
          'citations':['https://example.org/source'], 'assumptions':['Sources describe the relevant setting.'],
          'limitations':['No independent experiment was performed.'], 'validation_results':['Evidence references retained.'],
          'unresolved_questions':['Does the result generalize?'], 'next_actions':['Independent agent review.']}


def response_envelope(report=REPORT):
    return {'status':'completed','model':'configured-model','output':[{'type':'message','content':[
        {'type':'output_text','text':json.dumps(report)}]}]}


def test_openai_responses_uses_strict_schema_and_keeps_credentials_out_of_context(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','local-provider-secret')
    received = []
    def endpoint(request):
        payload = json.loads(request.content)
        received.append(payload)
        assert str(request.url)=='https://api.openai.com/v1/responses'
        assert request.headers['Authorization']=='Bearer local-provider-secret'
        assert 'local-provider-secret' not in request.content.decode()
        assert payload['model']=='explicit-model'
        assert payload['store'] is False
        assert payload['text']['format']['strict'] is True
        assert payload['text']['format']['schema']==REPORT_SCHEMA
        return httpx.Response(200,json=response_envelope())
    provider = APIReportProvider({'provider':'openai-responses','model':'explicit-model'},transport=httpx.MockTransport(endpoint))
    assert provider.generate({'task':{'objective':'Review provided sources'}})==REPORT
    assert len(received)==1


def test_compatible_local_model_has_actual_request_and_validated_report():
    def endpoint(request):
        assert request.url.path=='/v1/chat/completions'
        assert 'Authorization' not in request.headers
        assert json.loads(request.content)['response_format']=={'type':'json_object'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(REPORT)}}]})
    profile={'provider':'openai-compatible','model':'local-model','base_url':'http://127.0.0.1:11434/v1'}
    assert APIReportProvider(profile,transport=httpx.MockTransport(endpoint)).generate({'task':{}})==REPORT


@pytest.mark.parametrize('status,code',[(401,'authentication'),(403,'authentication'),(429,'rate_limit'),(503,'provider_failure')])
def test_provider_failures_are_visible_and_do_not_echo_response_secrets(monkeypatch,status,code):
    monkeypatch.setenv('OPENAI_API_KEY','local-provider-secret')
    provider=APIReportProvider({'provider':'openai-responses','model':'model'},transport=httpx.MockTransport(
        lambda request:httpx.Response(status,json={'error':'local-provider-secret confidential-body'})))
    with pytest.raises(ProviderError) as captured:
        provider.generate({'task':{}})
    assert captured.value.code==code
    assert str(status) in str(captured.value)
    assert 'local-provider-secret' not in str(captured.value)
    assert 'confidential-body' not in str(captured.value)


@pytest.mark.parametrize('envelope',[
    {'status':'incomplete','output':[]},
    {'output':[{'type':'message','content':[{'type':'refusal','refusal':'Cannot complete'}]}]},
    {'output':[{'type':'message','content':[{'type':'output_text','text':'not JSON'}]}]},
    response_envelope({'body':'A missing-provenance report'}),
])
def test_incomplete_refused_or_invalid_outputs_cannot_become_results(monkeypatch,envelope):
    monkeypatch.setenv('OPENAI_API_KEY','local-provider-secret')
    provider=APIReportProvider({'provider':'openai-responses','model':'model'},transport=httpx.MockTransport(
        lambda request:httpx.Response(200,json=envelope)))
    with pytest.raises(ProviderError):
        provider.generate({'task':{}})


def test_missing_model_key_and_lost_claim_fail_before_network(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    def forbidden(request):
        pytest.fail('No provider request should be made')
    transport=httpx.MockTransport(forbidden)
    with pytest.raises(ProviderError,match='explicit model'):
        APIReportProvider({'provider':'openai-responses'},transport=transport).generate({})
    with pytest.raises(ProviderError,match='credential is missing'):
        APIReportProvider({'provider':'openai-responses','model':'model'},transport=transport).generate({})
    lost=threading.Event();lost.set()
    with pytest.raises(ProviderError,match='claim was lost'):
        APIReportProvider({'provider':'openai-responses','model':'model'},transport=transport).generate({},lost)


@pytest.mark.parametrize('profile',[
    {'provider':'openai-responses','api_key':'secret'},
    {'provider':'openai-responses','api_key_env':'sk-secret-value'},
    {'provider':'openai-responses','api_key_env':'RESEARCHRELAY_TOKENS'},
    {'provider':'openai-compatible','base_url':'https://secret@example.org/v1'},
    {'provider':'openai-compatible','base_url':'https://example.org/v1?api_key=secret'},
    {'provider':'command','command':['tool','--api-key','secret']},
    {'provider':'command','command':['tool','sk-12345678901234567890']},
])
def test_profiles_reject_credential_values_and_ambiguous_connections(profile):
    with pytest.raises(ValueError):
        validate_profile(profile)


def test_command_adapter_runs_real_participant_command_without_coordinator_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv('RESEARCHRELAY_TOKEN','server-token-never-forward')
    script=tmp_path/'agent.py'
    script.write_text('import json,os,sys\ncontext=json.load(sys.stdin)\nassert "RESEARCHRELAY_TOKEN" not in os.environ\nassert context["task"]["objective"]=="Review sources"\nprint('+repr(json.dumps(REPORT))+')\n',encoding='utf-8')
    profile={'provider':'command','command':[sys.executable,str(script)]}
    assert CommandReportProvider(profile).generate({'task':{'objective':'Review sources'}},workspace=tmp_path)==REPORT


@pytest.mark.parametrize('profile',[
    {'provider':'claude-cli','model':'sk-live-credential-value'},
    {'provider':'claude-cli','allowed_tools':'Read,Bash(echo ghp_12345678901234567890)'},
    {'provider':'command','command':['tool','--password=private-value']},
    {'provider':'command','command':['shell','-c','tool --access-token private-value']},
    {'provider':'command','command':['tool','-----BEGIN OPENSSH PRIVATE KEY-----']},
])
def test_profile_metadata_cannot_smuggle_credentials_in_other_allowed_fields(profile):
    with pytest.raises(ValueError) as error:
        validate_profile(profile)
    assert 'private-value' not in str(error.value)
    assert 'sk-live-credential-value' not in str(error.value)


def test_nonsecret_model_names_with_task_prefix_remain_usable():
    assert validate_profile({'provider':'openai-compatible','model':'task-agent-local-model'})['model']=='task-agent-local-model'
