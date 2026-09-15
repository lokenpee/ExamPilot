import httpx
import pytest
from fastapi.testclient import TestClient

from backend.providers import Settings, discover_models, normalize_base_url
from backend.store import Store


@pytest.fixture
def settings(tmp_path, monkeypatch):
    credentials = {}
    monkeypatch.setattr('backend.providers.keyring.get_password', lambda service, ref: credentials.get((service, ref)))
    monkeypatch.setattr('backend.providers.keyring.set_password', lambda service, ref, value: credentials.__setitem__((service, ref), value))
    monkeypatch.delenv('EXAMPILOT_API_KEY', raising=False)
    return Settings(Store(tmp_path))


def test_saved_custom_url_key_and_model_survive_reload(settings):
    payload={'provider':'deepseek','base_url':'https://saved.example/custom/v1/','api_key':'test-secret','model':'model-a'}
    saved=settings.save(payload)
    assert saved['base_url']=='https://saved.example/custom/v1'
    assert saved['has_key'] and 'api_key' not in saved
    reloaded=Settings(settings.store)
    assert reloaded.public()['base_url']==saved['base_url']
    assert reloaded.public()['model']=='model-a'
    assert reloaded.public()['has_key']
    reloaded.save({**saved,'api_key':'','model':'model-b'})
    assert reloaded.key()=='test-secret'
    assert 'test-secret' not in str(settings.store.get('settings','main'))


def test_model_discovery_draft_requires_no_model_and_does_not_save(settings):
    settings.save({'provider':'deepseek','base_url':'https://saved.example/v1','api_key':'saved-secret','model':'saved-model'})
    before=settings.raw()
    draft={'provider':'custom','base_url':'https://draft.example/v1','api_key':'draft-secret','model':''}
    config,key=settings.connection(draft,require_model=False)
    assert config['model']=='' and key=='draft-secret'
    assert config['base_url']==draft['base_url']
    assert settings.raw()==before
    assert settings.key()=='saved-secret'
    with pytest.raises(ValueError,match='模型 ID'):
        settings.save(draft)
    assert settings.raw()==before


def test_saved_key_is_not_forwarded_to_another_host(settings):
    settings.save({'base_url':'https://saved.example/v1','api_key':'saved-secret','model':'model-a'})
    _,same_key=settings.connection({'base_url':'https://saved.example/v1/chat/completions','model':''},require_model=False)
    _,different_key=settings.connection({'base_url':'https://other.example/v1','model':''},require_model=False)
    assert same_key=='saved-secret'
    assert different_key==''
    assert normalize_base_url('https://saved.example/v1/models/')=='https://saved.example/v1'


@pytest.mark.asyncio
async def test_get_models_without_selected_model_and_with_pasted_url(settings,monkeypatch):
    calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(200,json={'data':[{'id':'model-b'},{'id':'model-a'},{'id':'model-a'},{}]})
    factory=httpx.AsyncClient
    monkeypatch.setattr('backend.providers.httpx.AsyncClient', lambda **kw: factory(transport=httpx.MockTransport(handle),**kw))
    config,key=settings.connection({'base_url':'https://draft.example/v1/chat/completions','api_key':'draft-secret','model':''},require_model=False)
    result=await discover_models(config,key)
    assert result=={'models':['model-a','model-b'],'base_url':'https://draft.example/v1'}
    assert str(calls[0].url)=='https://draft.example/v1/models'
    assert calls[0].headers['authorization']=='Bearer draft-secret'
    assert settings.store.get('settings','main') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body,message',[(401,{},'API Key'),(404,{},'Base URL'),(200,{'unexpected':True},'格式不兼容')])
async def test_model_discovery_errors_do_not_change_saved_profile(settings,monkeypatch,status,body,message):
    settings.save({'base_url':'https://saved.example/v1','api_key':'saved-secret','model':'saved-model'})
    before=settings.raw()
    factory=httpx.AsyncClient
    monkeypatch.setattr('backend.providers.httpx.AsyncClient',lambda **kw: factory(transport=httpx.MockTransport(lambda r:httpx.Response(status,json=body)),**kw))
    config,key=settings.connection({'base_url':'https://draft.example/v1','api_key':'draft-secret','model':''},require_model=False)
    with pytest.raises(ValueError,match=message):
        await discover_models(config,key)
    assert settings.raw()==before and settings.key()=='saved-secret'


def test_post_models_endpoint_accepts_unsaved_form_without_model(settings,monkeypatch):
    import backend.api as module
    monkeypatch.setattr(module,'settings',settings)
    async def fetch(config,key):
        assert config['model']=='' and key=='draft-secret'
        return {'models':['model-a'],'base_url':config['base_url']}
    monkeypatch.setattr(module,'discover_models',fetch)
    # No lifespan needed for this isolated settings endpoint test.
    client=TestClient(module.app)
    response=client.post('/api/settings/models',json={'base_url':'https://draft.example/v1','api_key':'draft-secret','model':''})
    assert response.status_code==200,response.text
    assert response.json()['models']==['model-a']
    assert settings.store.get('settings','main') is None
