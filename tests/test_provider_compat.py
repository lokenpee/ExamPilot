import httpx
import pytest

from backend.providers import Provider
from backend.store import Store


@pytest.mark.asyncio
async def test_flash_forced_tool_uses_non_thinking_without_changing_model(tmp_path,monkeypatch):
    observed=[]
    def handle(request):
        import json
        observed.append(json.loads(request.content))
        return httpx.Response(200,json={"choices":[{"message":{"role":"assistant","content":None,"tool_calls":[]},"finish_reason":"stop"}]})
    factory=httpx.AsyncClient
    monkeypatch.setattr('backend.providers.httpx.AsyncClient',lambda **kw:factory(transport=httpx.MockTransport(handle),**kw))
    provider=Provider({'provider':'deepseek','model':'deepseek-flash','base_url':'https://api.deepseek.com','timeout':10,'max_tokens':4096},'test-key',Store(tmp_path),'test')
    choice={'type':'function','function':{'name':'search'}}
    await provider.complete([{'role':'user','content':'search'}],'test',tools=[{'type':'function','function':{'name':'search'}}],tool_choice=choice)
    assert observed[0]['model']=='deepseek-flash'
    assert observed[0]['thinking']=={'type':'disabled'}
    assert observed[0]['tool_choice']==choice


def test_tool_followup_preserves_required_provider_fields():
    reply={'role':'assistant','content':None,'tool_calls':[{'id':'call_1'}],'reasoning_content':'private provider continuation','other':'ignore'}
    message=Provider.assistant_message(reply)
    assert message['reasoning_content']==reply['reasoning_content']
    assert message['tool_calls']==reply['tool_calls']
    assert 'other' not in message


@pytest.mark.asyncio
async def test_error_keeps_cause_but_redacts_credentials(tmp_path,monkeypatch):
    secret='sk-test_credential_123456789'
    factory=httpx.AsyncClient
    monkeypatch.setattr('backend.providers.httpx.AsyncClient',lambda **kw:factory(transport=httpx.MockTransport(lambda r:httpx.Response(400,json={'error':{'message':'Thinking mode does not support this tool_choice. '+secret,'param':'tool_choice'}})),**kw))
    store=Store(tmp_path)
    provider=Provider({'provider':'custom','model':'example','base_url':'https://example.test','timeout':10,'max_tokens':4096},secret,store,'test')
    with pytest.raises(ValueError,match='Thinking mode does not support') as error:
        await provider.complete([{'role':'user','content':'test'}],'test')
    assert secret not in str(error.value)
    assert secret not in str(store.all('events'))
    assert store.all('events')[0]['status_code']==400
