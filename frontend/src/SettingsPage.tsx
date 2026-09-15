import {useState} from 'react';
import type {Dispatch, SetStateAction} from 'react';
import {ArrowLeft, CheckCircle2, ChevronDown, CircleAlert, Layers3, Link2, LoaderCircle, RotateCcw, Settings2, ShieldCheck} from 'lucide-react';
import {api, type Json} from './api';

const presets: Json = {
  deepseek:{base_url:'https://api.deepseek.com',model:'deepseek-flash'},
  openai:{base_url:'https://api.openai.com/v1',model:''},
  siliconflow:{base_url:'https://api.siliconflow.cn/v1',model:''},
  custom:{base_url:'',model:''},
};
const providerLabels = [['deepseek','DeepSeek'],['openai','GPT'],['siliconflow','硅基流动'],['custom','自定义']];
const sameUrl = (a: string, b: string) => a.trim().replace(/\/+$/,'').replace(/\/(chat\/completions|models)$/,'') === b.trim().replace(/\/+$/,'').replace(/\/(chat\/completions|models)$/,'');

type Props = {
  initial: Json | null;
  drafts: Json;
  setDrafts: Dispatch<SetStateAction<Json>>;
  selectedProvider: string | null;
  setSelectedProvider: (provider:string)=>void;
  onChange: (value:Json)=>void;
  onBack: ()=>void;
};

export function SettingsPage({initial,drafts,setDrafts,selectedProvider,setSelectedProvider,onChange,onBack}:Props) {
  const provider = selectedProvider || initial?.provider || 'deepseek';
  const savedForProvider = initial?.provider === provider;
  const fallback: Json = savedForProvider ? {...initial,api_key:''} : {provider,...presets[provider],timeout:90,concurrency:2,max_tokens:4096,api_key:''};
  const form = drafts[provider] || fallback;
  const [modelLists,setModelLists] = useState<Json>({});
  const [result,setResult] = useState<Json|null>(null);
  const [action,setAction] = useState('');
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const busy = !!action || !initial;
  const models: string[] = modelLists[form.base_url] || [];
  const hasSavedKey = (initial?.has_key && sameUrl(form.base_url,initial.base_url)) ||
    (form.has_saved_key && sameUrl(form.base_url,form.saved_base_url || ''));

  function change(patch: Json) {
    setSelectedProvider(provider);
    setDrafts(previous=>({...previous,[provider]:{...form,...patch}}));
    setError('');setNotice('');setResult(null);
  }
  function selectProvider(id:string) {
    if(id===provider)return; // Clicking the current provider is never a reset action.
    setDrafts(previous=>({...previous,[provider]:{...form}}));
    setSelectedProvider(id);
    setError('');setNotice('');setResult(null);
  }
  async function execute(name:string, fn:()=>Promise<void>) {
    setAction(name);setError('');setNotice('');
    try {await fn();} catch(e:any){setError(e.message || '操作失败，当前输入已保留');}
    finally {setAction('');}
  }
  async function fetchModels() {
    await execute('models',async()=>{
      // Model discovery neither requires a model ID nor writes the saved profile.
      const response=await api('/settings/models','POST',form);
      const base=response.base_url || form.base_url;
      setModelLists(previous=>({...previous,[base]:response.models}));
      if(base!==form.base_url)setDrafts(previous=>({...previous,[provider]:{...form,base_url:base}}));
      setNotice(response.models.length ? `已获取 ${response.models.length} 个模型，请从下方列表选择；当前输入未保存。` : '接口连接成功，但返回了空模型列表。可以手动输入模型 ID。');
    });
  }
  async function save() {
    await execute('save',async()=>{
      const next=await api('/settings','PUT',form);
      onChange(next);
      setDrafts(previous=>({...previous,[provider]:{...next,api_key:'',has_saved_key:next.has_key,saved_base_url:next.base_url}}));
      setNotice(next.has_key ? next.secret_storage==='session' ? '接口配置已保存。系统凭据存储不可用，密钥仅在当前后端会话可用；重启服务后需重新输入。' : '配置与密钥已保存。密钥不回显，留空不会删除已保存的密钥。' : '接口配置已保存，但当前地址还没有 API Key。');
    });
  }
  async function test() {
    await execute('test',async()=>{
      const next=await api('/settings/test','POST',form);
      setResult(next);
      setNotice('已使用当前填写的接口测试；测试不会自动保存或清空输入。');
    });
  }

  if(!initial)return <div className="settings-page"><h1>API 设置</h1><p className="working-line"><LoaderCircle size={18} className="spin"/>正在读取已保存的接口配置…</p></div>;
  return <div className="settings-page">
    <button type="button" className="subtle-link" onClick={onBack}><ArrowLeft size={15}/>返回工作台</button>
    <div className="eyebrow">MAKE IT YOURS</div><h1>连接你的 AI 模型</h1>
    <p className="settings-lead">填写接口地址与密钥，获取模型后再保存。切换服务商会保留本次填写。</p>
    <div className="settings-layout"><section className="card">
      <div className="section-heading"><span className="section-icon"><Settings2 size={19}/></span><div><h2>模型接口</h2><p>规划与出题使用独立上下文，共用此模型配置</p></div></div>
      <div className="provider-tabs">{providerLabels.map(([id,label])=><button type="button" key={id} disabled={busy} className={provider===id?'active':''} onClick={()=>selectProvider(id)}>{label}</button>)}</div>
      <div className="editor-form">
        <label>API Base URL<input disabled={busy} value={form.base_url||''} onChange={e=>change({base_url:e.target.value})} placeholder="https://your-provider.example/v1"/></label>
        <label>API Key<input disabled={busy} autoComplete="off" type="password" value={form.api_key||''} onChange={e=>change({api_key:e.target.value})} placeholder={hasSavedKey?'密钥已保存，留空保持不变':'输入当前接口地址的 API Key'}/>
          <span className={'key-state '+(hasSavedKey?'configured':'')}>{form.api_key?'已输入新密钥，保存后生效':hasSavedKey?'✓ 此地址已有密钥；为安全起见不回显原文':'尚未确认此地址有已保存密钥；如曾保存，可留空尝试获取模型'}</span>
        </label>
        <div className="models-discovery"><span>先获取可用模型，无需提前填写模型 ID。</span><button type="button" className="button outline" disabled={busy||!form.base_url?.trim()} onClick={fetchModels}>{action==='models'?<LoaderCircle size={16} className="spin"/>:<RotateCcw size={15}/>}获取模型</button></div>
        {models.length>0&&<label>可用模型（{models.length} 个）<select disabled={busy} value={models.includes(form.model)?form.model:''} onChange={e=>change({model:e.target.value})}><option value="" disabled>请选择一个模型</option>{models.map(model=><option key={model} value={model}>{model}</option>)}</select></label>}
        <label>模型 ID<input disabled={busy} value={form.model||''} onChange={e=>change({model:e.target.value})} placeholder="从上方列表选择，也可以手动输入模型 ID"/></label>
        <details className="advanced-settings"><summary>高级设置<ChevronDown size={15}/></summary><div className="field-grid">
          <label>请求超时（秒）<input disabled={busy} type="number" min="10" max="300" value={form.timeout??90} onChange={e=>change({timeout:Number(e.target.value)})}/></label>
          <label>逐题生成并发<input disabled={busy} type="number" min="1" max="4" value={form.concurrency??2} onChange={e=>change({concurrency:Number(e.target.value)})}/></label>
          <label className="wide">单次最大输出 token<input disabled={busy} type="number" min="1024" max="16000" step="1024" value={form.max_tokens??4096} onChange={e=>change({max_tokens:Number(e.target.value)})}/></label>
        </div></details>
      </div>
      {error&&<div className="notice error" role="alert"><CircleAlert size={19}/><div><strong>操作未完成</strong><span>{error}</span></div></div>}
      {notice&&<div className="notice success" role="status"><CheckCircle2 size={18}/><div><span>{notice}</span></div></div>}
      <div className="settings-actions">
        <button type="button" className="button outline" disabled={busy||!form.model?.trim()||!form.base_url?.trim()} onClick={test}>{action==='test'?<LoaderCircle size={16} className="spin"/>:<Link2 size={16}/>}测试连接与能力</button>
        <button type="button" className="button primary" disabled={busy||!form.model?.trim()||!form.base_url?.trim()} onClick={save}>{action==='save'&&<LoaderCircle size={16} className="spin"/>}保存配置</button>
      </div>
      {result&&<div className={'notice '+(result.tool_calling&&result.structured_output&&result.tool_roundtrip!==false?'success':'error')}><ShieldCheck size={19}/><div><strong>{result.tool_calling&&result.structured_output&&result.tool_roundtrip!==false?'模型已通过能力测试':'该模型的 Agent 能力未通过测试'}</strong><span>原生工具调用：{result.tool_calling?'可用':'不可用'} · 工具往返：{result.tool_roundtrip===undefined?'未测试':result.tool_roundtrip?'可用':'未通过'} · 结构化输出：{result.structured_output?'可用':'未通过'}{result.execution_mode==='non-thinking'?' · 非思考模式':''}</span></div></div>}
    </section><aside>
      <section className="card mcp-card"><div className="section-heading"><span className="section-icon"><Layers3 size={19}/></span><div><h2>知识检索 MCP</h2><p>独立本地进程 · stdio</p></div></div>
        <div className="mcp-status"><span className={'status-dot '+(!initial?.mcp?.connected?'amber':'')}/>{initial?.mcp?.connected?'已连接，工具已发现':'服务未连接'}</div>
        {['search','get_chunk_context'].map((name,i)=><div className="mcp-tool" key={name}><CheckCircle2 size={15}/><div><code>{name}</code><span>{i?'原文、页码与句段编号':'按知识点批量检索资料'}</span></div></div>)}
        <button type="button" className="button outline full small" disabled={busy} onClick={()=>execute('mcp',async()=>{await api('/mcp/reconnect','POST');onChange(await api('/settings'));setNotice('知识检索服务已重新连接，表单草稿保持不变。')})}><RotateCcw size={14}/>重新连接</button>
      </section>
      <div className="settings-note"><ShieldCheck size={22}/><h3>保存的配置不会恢复为默认值</h3><p>获取模型与测试连接只使用当前输入，不自动保存。点击保存后，自定义 URL 和模型会写入本地数据库。</p><p>密钥优先保存在系统凭据中；获取模型失败不会清空输入。切换页面保留本次草稿，手动刷新浏览器前请先保存。</p><p>系统凭据不可用时，密钥仅保存在后端会话，重启服务后需重新输入；页面会显示实际保存状态。</p></div>
    </aside></div>
  </div>;
}
