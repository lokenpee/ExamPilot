import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BookOpen, ArrowRight, ArrowLeft, Check, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Clock3, Download, FileText, Layers3, LoaderCircle, Plus, Search, Send, Settings2, ShieldCheck, Sparkles, Trash2, UploadCloud, X, PanelRightOpen, RotateCcw, Pencil, Link2, MoreHorizontal, GraduationCap } from 'lucide-react';
import './style.css';
import {api} from './api';
import {SettingsPage} from './SettingsPage';

type Json = Record<string, any>;
const types = ['single_choice','multiple_choice','true_false','fill_blank','short_answer','calculation'];
const labels: Json = {single_choice:'单选题',multiple_choice:'多选题',true_false:'判断题',fill_blank:'填空题',short_answer:'简答题',calculation:'计算题'};
const difficulty: Json = {easy:'易',medium:'中',hard:'难'};
const defaults = {title:'课程测试',total_score_units:200,duration_minutes:120,ratios:[30,50,20],requirements:'',sections:types.map((type,i)=>({type,count:[4,2,2,2,2,1][i],score_units:[10,10,10,10,30,40][i]}))};
function score(units: number) { return units/2; }
function locator(c: Json) {
  const l=c.locator;
  return l.kind==='pdf'?`第 ${l.page_number} 页`:l.kind==='pptx'?`第 ${l.slide_number} 张幻灯片`:l.paragraph_index?`第 ${l.paragraph_index} 段`:`表 ${l.table_index} · 行 ${l.row_index} · 列 ${l.cell_index}`;
}
function answerText(a: any) {return typeof a==='boolean'?(a?'正确':'错误'):Array.isArray(a)?a.join('；'):a;}
function Button({children,onClick,disabled=false,kind='',type='button'}: {children:React.ReactNode;onClick?:()=>void;disabled?:boolean;kind?:string;type?:'button'|'submit'}) {return <button type={type} className={'button '+kind} onClick={onClick} disabled={disabled}>{children}</button>}

function App() {
  const [projects,setProjects]=useState<Json[]>([]);
  const [projectId,setProjectId]=useState(localStorage.getItem('exampilot.project')||'');
  const [state,setState]=useState<Json|null>(null);
  const [settings,setSettings]=useState<Json|null>(null);
  const [page,setPage]=useState(sessionStorage.getItem('exampilot.page')==='settings'?'settings':'work');
  const [settingsDrafts,setSettingsDrafts]=useState<Json>({});
  const [settingsProvider,setSettingsProvider]=useState<string|null>(null);
  useEffect(()=>{sessionStorage.setItem('exampilot.page',page)},[page]);
  const [stage,setStage]=useState(0);
  const [config,setConfig]=useState<Json>(structuredClone(defaults));
  const [feedback,setFeedback]=useState('');
  const [busy,setBusy]=useState(false);
  const [toast,setToast]=useState('');
  const [source,setSource]=useState<Json[]|null>(null);
  const [vacancyId,setVacancyId]=useState<string|null>(null);
  const [message,setMessage]=useState('');
  const [edit,setEdit]=useState<Json|null>(null);
  const [traceId,setTraceId]=useState<string|null>(null);
  const [traces,setTraces]=useState<Json[]>([]);
  const [artifacts,setArtifacts]=useState<Json[]>([]);
  const uploadRef=useRef<HTMLInputElement>(null);
  const autoIds=useRef({plan:'',exam:''});
  const projectRef=useRef(projectId); projectRef.current=projectId;
  const initialised=useRef(false);

  async function refresh(id=projectRef.current) {
    if (!id) return;
    const next=await api(`/projects/${id}`);
    if (projectRef.current!==id) return;
    setState(next);
    if (next.plan?.config && autoIds.current.plan!==next.plan.id) setConfig(structuredClone(next.plan.config));
    if (next.exam && autoIds.current.exam!==next.exam.id) {setStage(2);autoIds.current.exam=next.exam.id;}
    else if (next.plan && autoIds.current.plan!==next.plan.id) {setStage(1);autoIds.current.plan=next.plan.id;}
    if (next.plan) autoIds.current.plan=next.plan.id;
  }
  async function run(fn:()=>Promise<any>) {
    setBusy(true);
    try {await fn();await refresh();} catch(e:any){setToast(e.message||'操作失败，请重试');}
    finally {setBusy(false);}
  }
  useEffect(()=>{if(initialised.current)return;initialised.current=true;(async()=>{
    try {
      setSettings(await api('/settings'));
      let list=await api('/projects');
      if(!list.length) list=[await api('/projects','POST',{})];
      setProjects(list);
      if(!list.some((p:Json)=>p.id===projectId)) setProjectId(list[0].id);
    }catch(e:any){setToast(e.message);}
  })()},[]);
  useEffect(()=>{
    if(!projectId)return;
    localStorage.setItem('exampilot.project',projectId);setState(null);setConfig(structuredClone(defaults));setStage(0);setArtifacts([]);setVacancyId(null);autoIds.current={plan:'',exam:''};
    refresh(projectId).catch(e=>setToast(e.message));
    const timer=setInterval(()=>refresh(projectId).catch(()=>{}),2500);
    return ()=>clearInterval(timer);
  },[projectId]);
  const jobs:Json[]=state?.jobs||[];
  const running=jobs.filter(j=>['queued','running'].includes(j.status));
  const generating=running.some(j=>j.kind==='generate');
  const vacancy=state?.vacancies?.find((v:Json)=>v.id===vacancyId);
  const candidateBusy=running.some(j=>j.payload?.vacancy_id===vacancyId);
  const eventKey=running.map(j=>j.id).join(',');
  useEffect(()=>{
    const sources=eventKey?eventKey.split(',').map(id=>{
      const es=new EventSource(`/api/jobs/${id}/events`);
      es.onmessage=(e)=>{const data=JSON.parse(e.data);if(['question_completed','progress'].includes(data.name)) refresh().catch(()=>{});};
      es.addEventListener('done',()=>{es.close();refresh().catch(()=>{});});
      return es;
    }):[];
    return()=>sources.forEach(es=>es.close());
  },[eventKey]);
  useEffect(()=>{if(!traceId)return;const load=()=>api(`/jobs/${traceId}/traces`).then(setTraces).catch(()=>{});load();const t=setInterval(load,1500);return()=>clearInterval(t)},[traceId]);
  useEffect(()=>{if(!toast)return;const t=setTimeout(()=>setToast(''),7000);return()=>clearTimeout(t)},[toast]);
  const docs:Json[]=state?.documents||[];
  const plan=state?.plan;
  const exam=state?.exam;
  const ready=docs.length>0&&docs.every(d=>d.status==='ready');
  const sum=config.sections.reduce((a:number,s:Json)=>a+s.count*s.score_units,0);
  const ratioSum=config.ratios.reduce((a:number,b:number)=>a+b,0);
  const count=config.sections.reduce((a:number,s:Json)=>a+s.count,0);
  const configValid=sum===config.total_score_units&&ratioSum===100&&count>0&&count<=50&&config.sections.every((s:Json)=>Number.isInteger(s.score_units)&&s.score_units>0&&Number.isInteger(s.count)&&s.count>=0);

  function updateSection(i:number,field:string,value:number){
    setConfig((c:Json)=>({...c,sections:c.sections.map((s:Json,n:number)=>{
      if(n!==i)return s;
      const next={...s};const total=s.count*s.score_units;
      if(field==='count') {next.count=value;if(s._last==='total_units'&&value>0)next.score_units=total/value;}
      else if(field==='score_units') {next.score_units=value;if(s._last==='total_units'&&value>0)next.count=total/value;}
      else if(field==='total_units') {if(s._last==='score_units'||!s.count)next.count=value/s.score_units;else next.score_units=value/s.count;}
      next._last=field;return next;
    })}));
  }
  async function uploadFiles(files: FileList|File[]) {
    if(!settings?.has_key){setPage('settings');setToast('请先配置模型接口，上传后将立即开始真实分析');return;}
    await run(async()=>{for(const file of Array.from(files)){const data=new FormData();data.append('file',file);await api(`/projects/${projectId}/documents`,'POST',data);}setToast('资料已上传，正在提取文字与分析知识点');});
  }
  async function sample(){await run(async()=>{const list=await api('/samples');if(!list.length)throw new Error('示例资料尚未生成');const response=await fetch(list[0].url);const file=new File([await response.blob()],list[0].name);await uploadFiles([file]);});}
  async function createPlan(){await run(async()=>{await api(`/projects/${projectId}/plans`,'POST',{config},{'Idempotency-Key':crypto.randomUUID()});});}
  async function revisePlan(){await run(async()=>{await api(`/projects/${projectId}/plans`,'POST',{config:plan.config,feedback,previous_plan:plan.id},{'Idempotency-Key':crypto.randomUUID()});setFeedback('');});}
  async function confirmPlan(){await run(async()=>{await api(`/plans/${plan.id}/confirm`,'POST',{version:plan.version},{'Idempotency-Key':crypto.randomUUID()});setStage(2);});}
  async function removeQuestion(q:Json){await run(async()=>{const v=await api(`/exams/${exam.id}/questions/${q.id}`,'DELETE',undefined,{'If-Match':String(q.version)});setVacancyId(v.id);setMessage('');});}
  async function sendCandidate(){await run(async()=>{await api(`/exams/${exam.id}/vacancies/${vacancy.id}/messages`,'POST',{message,expected_version:vacancy.version},{'Idempotency-Key':crypto.randomUUID()});setMessage('');});}
  async function adopt(){await run(async()=>{await api(`/exams/${exam.id}/vacancies/${vacancy.id}/adopt`,'POST',{candidate_id:vacancy.candidate.id,expected_version:vacancy.version});setVacancyId(null);setToast('已采纳，题目已加入试卷');});}
  async function exportBoth(){await run(async()=>{const result=await api(`/exams/${exam.id}/exports`,'POST',{expected_revision:exam.revision});setArtifacts(result.artifacts);setToast('两个 Word 文件已生成，可以下载');});}
  const latestJob=jobs.at(-1);

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e=>{e.preventDefault();setPage('work')}}><span className="brand-icon"><Layers3 size={23}/></span><span>ExamPilot<small>让好问题，有据可依</small></span></a>
      <div className="nav-label">工作空间</div>
      <button className={'nav-item '+(page==='work'?'selected':'')} onClick={()=>setPage('work')}><BookOpen size={19}/>组卷工作台<span className="nav-dot"/></button>
      <button className={'nav-item '+(page==='settings'?'selected':'')} onClick={()=>setPage('settings')}><Settings2 size={19}/>API 设置</button>
      <div className="nav-label project-label">我的项目<button title="新建项目" onClick={()=>run(async()=>{const p=await api('/projects','POST',{title:`组卷项目 ${projects.length+1}`});setProjects(await api('/projects'));setProjectId(p.id);setConfig(structuredClone(defaults));})}><Plus size={17}/></button></div>
      <div className="project-list">{projects.map(p=><button key={p.id} className={p.id===projectId?'current':''} onClick={()=>{setProjectId(p.id);setPage('work')}}><span className="project-glyph"><FileText size={15}/></span><span>{p.title}</span></button>)}</div>
      <div className="sidebar-bottom"><div className="sidebar-note"><ShieldCheck size={19}/><strong>每道题，都有出处</strong><p>从课程资料到完整试卷，<br/>保留每一步的原文依据。</p></div><div className="local-status"><span className="status-dot"/>本地工作空间<span>DEMO 0.3</span></div></div>
    </aside>
    <main>
      <header className="topbar"><div>工作空间 <ChevronRight size={14}/><span>{page==='settings'?'API 设置':state?.project?.title||'组卷工作台'}</span></div><div className="top-right"><span className="local-badge"><span className={'status-dot '+(!settings?.mcp?.connected?'amber':'')}/>{settings?.mcp?.connected?'知识工具已连接':'知识工具连接中'}</span><span className="avatar">EP</span></div></header>
      {page==='settings'?<SettingsPage initial={settings} drafts={settingsDrafts} setDrafts={setSettingsDrafts} selectedProvider={settingsProvider} setSelectedProvider={setSettingsProvider} onChange={setSettings} onBack={()=>setPage('work')}/>:<div className="workspace">
        <div className="page-heading"><div className="eyebrow">TEACH BETTER. ASSESS SMARTER.</div><div className="heading-row"><div><h1>把出题的时间，还给教学。</h1><p>上传课程资料，与 AI 一起规划一份有依据的好试卷。</p></div><button className="subtle-link" onClick={()=>{setTraceId(latestJob?.id||null);if(!latestJob)setToast('开始分析或出题后，这里会显示真实执行记录')}}><PanelRightOpen size={17}/>执行记录</button></div></div>
        <nav className="steps">{['配置与资料','组卷规划','试卷编辑'].map((text,i)=><button key={text} disabled={i===1&&!plan||i===2&&!exam&&!generating} onClick={()=>setStage(i)} className={stage===i?'active':stage>i?'complete':''}><span>{stage>i?<Check size={15}/>:String(i+1).padStart(2,'0')}</span><div>{text}<small>{['设定要求，导入课程内容','先看方案，再开始出题','审阅、补题与导出'][i]}</small></div>{i<2&&<ChevronRight size={18} className="step-arrow"/>}</button>)}</nav>
        {!settings?.has_key&&<div className="notice setup-notice"><Sparkles size={20}/><div><strong>连接模型，开始第一次组卷</strong><span>支持 DeepSeek、GPT、硅基流动。资料将在所选模型上进行真实分析。</span></div><Button kind="small" onClick={()=>setPage('settings')}>配置 API <ArrowRight size={15}/></Button></div>}
        {running.length>0&&<div className="job-stack">{running.map(job=><JobProgress key={job.id} job={job} onCancel={()=>run(()=>api(`/jobs/${job.id}/cancel`,'POST'))} onTrace={()=>setTraceId(job.id)}/>)}</div>}
        {latestJob?.status==='failed'&&<div className="notice error"><CircleAlert size={18}/><div><strong>这一步尚未完成</strong><span>{latestJob.error}</span></div><button className="subtle-link" onClick={()=>setTraceId(latestJob.id)}>查看记录</button></div>}
        {stage===0&&<div className="config-layout"><div className="main-column">
          <section className="card"><div className="section-heading"><span className="section-icon"><FileText size={18}/></span><div><h2>试卷基本信息</h2><p>定义这次考核的目标与结构</p></div></div><div className="field-grid"><label className="wide">试卷名称<input value={config.title} onChange={e=>setConfig({...config,title:e.target.value})}/></label><label>目标总分<div className="input-unit"><input type="number" min="0.5" max="500" step="0.5" value={score(config.total_score_units)} onChange={e=>setConfig({...config,total_score_units:Number(e.target.value)*2})}/><span>分</span></div></label><label>考试时长<div className="input-unit"><input type="number" min="1" max="300" value={config.duration_minutes} onChange={e=>setConfig({...config,duration_minutes:Number(e.target.value)})}/><span>分钟</span></div></label></div>
          <div className="section-divider"/><div className="small-heading"><h3>题型与分值</h3><span>自由组合六种题型</span></div><div className="type-table"><div className="type-header"><span>题型</span><span>题数</span><span>每题分值</span><span>小计</span></div>{config.sections.map((s:Json,i:number)=><div className={'type-row '+(!s.count?'muted':'')} key={s.type}><span className="type-name"><input type="checkbox" checked={s.count>0} onChange={e=>updateSection(i,'count',e.target.checked?1:0)}/>{labels[s.type]}</span><input aria-label={labels[s.type]+'题数'} type="number" min="0" max="50" value={s.count} onChange={e=>updateSection(i,'count',Number(e.target.value))}/><div className="input-unit compact"><input aria-label={labels[s.type]+'每题分值'} type="number" min="0.5" step="0.5" value={score(s.score_units)} onChange={e=>updateSection(i,'score_units',Number(e.target.value)*2)}/><span>分</span></div><div className="input-unit compact subtotal"><input aria-label={labels[s.type]+'小计'} type="number" min="0" step="0.5" value={score(s.count*s.score_units)} onChange={e=>updateSection(i,'total_units',Number(e.target.value)*2)}/><span>分</span></div></div>)}</div><div className={'table-total '+(sum!==config.total_score_units?'invalid':'')}><span>共 <b>{count}</b> 道题</span><span>合计 <strong>{score(sum)}</strong> / {score(config.total_score_units)} 分 {sum===config.total_score_units?<CheckCircle2 size={15}/>:<CircleAlert size={15}/>}</span></div></section>
          <section className="card"><div className="section-heading"><span className="section-icon"><Layers3 size={18}/></span><div><h2>难度与考察重点</h2><p>各题型分别按比例分配，少量题目自动取整</p></div></div><div className="difficulty-bar">{config.ratios.map((r:number,i:number)=><span key={i} style={{flex:r||0.1}} className={'d'+i}/>)}</div><div className="ratio-fields">{['基础 · 易','理解 · 中','应用 · 难'].map((l,i)=><label key={l}><span><i className={'legend d'+i}/>{l}</span><div className="input-unit"><input aria-label={l+'比例'} type="number" min="0" max="100" value={config.ratios[i]} onChange={e=>setConfig({...config,ratios:config.ratios.map((v:number,n:number)=>n===i?Number(e.target.value):v)})}/><span>%</span></div></label>)}</div>{ratioSum!==100&&<p className="field-error">难度比例应合计 100%，当前为 {ratioSum}%</p>}<label className="full-label">知识点要求 <span>选填</span><textarea value={config.requirements} onChange={e=>setConfig({...config,requirements:e.target.value})} placeholder="例如：事务必须覆盖；减少记忆题，增加 SQL 应用题。" rows={3}/></label></section>
        </div><aside className="right-column"><section className="card upload-card"><div className="section-heading"><span className="section-icon"><BookOpen size={18}/></span><div><h2>课程资料</h2><p>出题与引用的唯一依据</p></div><span className="counter">{docs.length}/5</span></div><input ref={uploadRef} hidden type="file" multiple accept=".pdf,.pptx,.docx" onChange={e=>{if(e.target.files)uploadFiles(e.target.files);e.target.value=''}}/><button disabled={busy||generating} className="dropzone" onClick={()=>uploadRef.current?.click()} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();if(!busy&&!generating)uploadFiles(e.dataTransfer.files)}}><span className="upload-icon"><UploadCloud size={25}/></span><strong>点击上传，或拖拽文件到这里</strong><span>文字型 PDF · PPTX · DOCX</span><small>每个文件最多 20 MB</small></button><div className="file-list">{docs.map(doc=><div className="file-item" key={doc.id}><FileText size={20}/><div><strong title={doc.name}>{doc.name}</strong><span>{doc.status==='ready'?`${doc.chunk_ids?.length||0} 个文本块 · 分析完成`:doc.status==='failed'?'分析失败，可重试':'分析中，请等待'}{doc.status==='ready'&&<CheckCircle2 size={12}/>}</span>{doc.error&&<small className="field-error">{doc.error}</small>}</div>{doc.status==='failed'?<button title="重试分析" disabled={busy} onClick={()=>run(()=>api(`/projects/${projectId}/documents/${doc.id}/retry`,'POST'))}><RotateCcw size={15}/></button>:null}<button title="移除资料" disabled={running.length>0||busy} onClick={()=>run(()=>api(`/projects/${projectId}/documents/${doc.id}`,'DELETE'))}><X size={15}/></button></div>)}</div><div className="file-tip"><ShieldCheck size={15}/><span>文件保存在本地；分析时，相关文本会发送至你配置的模型服务。</span></div>{!docs.length&&<button className="sample-link" onClick={sample} disabled={busy}><Sparkles size={14}/>没有资料？试用原创数据库讲义<ArrowRight size={14}/></button>}</section>
          <section className="knowledge-preview"><div className="small-heading"><h3>知识点概览</h3><span>{state?.knowledge_points?.length||0} 个</span></div>{state?.knowledge_points?.length?<div className="knowledge-chips">{state.knowledge_points.map((kp:Json)=><span key={kp.name} title={kp.summary}>{kp.name}</span>)}</div>:<div className="knowledge-empty"><Search size={23}/><p>上传资料后，AI 将提取<br/>可考察的知识点</p></div>}</section><div className="how-it-works"><span className="eyebrow">A LITTLE LESS BUSYWORK</span><h3>先确定考什么，<br/>再一起打磨好题。</h3><p>你掌握命题方向，AI 负责整理资料、生成初稿与寻找依据。</p></div></aside></div>}
        {stage===0&&<div className="action-bar"><div><ShieldCheck size={17}/><span>{ready?'课程资料已就绪':'请上传资料并等待分析完成'}{!configValid&&' · 请检查题数、分值或难度比例'}</span></div><Button kind="primary" disabled={busy||running.length>0||!ready||!configValid||!settings?.has_key} onClick={createPlan}><Sparkles size={17}/>AI 组卷规划<ArrowRight size={17}/></Button></div>}
        {stage===1&&plan&&<div className="plan-layout"><section className="card plan-card"><div className="section-heading"><span className="section-icon"><Sparkles size={20}/></span><div><h2>先看方案，再开始出题</h2><p>规划 Agent · 第 {plan.version} 版方案 · 还没有生成具体题目</p></div><span className="pill green">{plan.slots.length} 道题</span></div><p className="plan-summary">{plan.summary}</p><div className="plan-metrics"><div><strong>{score(plan.config.total_score_units)}</strong><span>总分</span></div><div><strong>{plan.config.duration_minutes}</strong><span>分钟</span></div><div><strong>{new Set(plan.slots.map((s:Json)=>s.knowledge_point)).size}</strong><span>主要知识点</span></div></div><div className="plan-table"><div className="plan-table-head"><span>题型 / 分值</span><span>考察知识点</span><span>难度</span></div>{plan.slots.map((s:Json,i:number)=><div key={s.id}><span><small>{String(i+1).padStart(2,'0')}</small>{labels[s.type]} · {score(s.score_units)} 分</span><span>{s.knowledge_point}<small>{s.focus}</small></span><span className={'pill diff-'+s.difficulty}>{difficulty[s.difficulty]}</span></div>)}</div>{[...(plan.warnings||[]),...(plan.unresolved||[])].map((w:string,i:number)=><div className="inline-warning" key={i}><CircleAlert size={15}/>{w}</div>)}</section><aside className="plan-chat card"><span className="eyebrow">YOUR CALL</span><h2>调整一下，<br/>更贴近你的教学。</h2><p>告诉规划 Agent 想强调的知识点、希望调整的难度。它会重新安排整张试卷。</p>{plan.feedback&&<div className="last-feedback"><small>最近一次调整</small>{plan.feedback}</div>}<textarea rows={5} value={feedback} onChange={e=>setFeedback(e.target.value)} placeholder="例如：增加事务的考察比重，把索引的题目改为中等难度。"/><Button kind="outline full" disabled={busy||running.length>0||!feedback.trim()} onClick={revisePlan}><Send size={16}/>发送调整要求</Button><div className="plan-confirm"><p>满意后，再交给出题 Agent。</p><Button kind="primary full" disabled={busy||running.length>0||!!plan.unresolved?.length||plan.corpus_version!==state?.project.corpus_version} onClick={confirmPlan}>确认方案并出题<ArrowRight size={16}/></Button></div></aside></div>}
        {stage===2&&<div className="exam-layout">{!exam?<div className="card empty-state"><LoaderCircle className="spin"/><h2>正在准备试卷</h2></div>:<><section className="exam-title card"><div><span className="eyebrow">EXAM DRAFT</span><h2>{exam.title}</h2><p>{exam.questions.length} 道已入卷题 · {exam.duration_minutes} 分钟{generating?' · 正在逐题生成，完成或取消后可编辑':' · 已自动保存至本地'}</p></div><div className="exam-score"><strong>{score(exam.checks.actual_score_units)}</strong><span>/ {score(exam.target_score_units)} 分</span><button disabled={busy||generating} onClick={()=>{const value=prompt('修改目标总分（实际分数不会自动改变）',String(score(exam.target_score_units)));if(value!==null)run(()=>api(`/exams/${exam.id}`,'PATCH',{expected_revision:exam.revision,target_score_units:Number(value)*2}));}} title="修改目标总分"><Pencil size={14}/></button></div></section>
          {types.map(type=>{const questions=exam.questions.filter((q:Json)=>q.type===type).sort((a:Json,b:Json)=>a.display_order-b.display_order);const gaps=(state?.vacancies||[]).filter((v:Json)=>v.original.type===type);if(!questions.length&&!gaps.length)return null;return <section className="question-group" key={type}><div className="group-heading"><h3>{labels[type]}<span>{questions.length} 题 · {score(questions.reduce((a:number,q:Json)=>a+q.score_units,0))} 分</span></h3></div>{questions.map((q:Json)=><QuestionCard key={q.id} q={q} disabled={generating||busy} onSource={()=>setSource(q.citations)} onDelete={()=>removeQuestion(q)} onEdit={()=>setEdit(structuredClone(q))} onReview={()=>run(()=>api(`/exams/${exam.id}/questions/${q.id}/review`,'POST',{expected_version:q.version}))}/>)}{gaps.map((v:Json)=><button className="vacancy-card" key={v.id} disabled={busy||generating} onClick={()=>{setVacancyId(v.id);setMessage('')}}><span className="vacancy-plus"><Plus size={21}/></span><div><strong>这里有一道题的空缺</strong><p>与 AI 沟通补题，满意并采纳后加入试卷</p></div><span>{v.candidate?'查看候选':'开始补题'}<ArrowRight size={16}/></span></button>)}</section>})}
          {!exam.questions.length&&generating&&<div className="card empty-state"><Sparkles size={28}/><h3>正在准备第一道题</h3><p>集中检索原文后，题目会依次出现在这里。</p></div>}
          {!generating&&((Object.keys(exam.failures||{}).length>0)||exam.questions.length+(state?.vacancies?.length||0)<(plan?.slots.length||0))&&<div className="notice"><CircleAlert size={18}/><div><strong>部分题目尚未生成</strong><span>{Object.values(exam.failures||{}).join('；')||'任务曾取消或中断，可继续生成剩余题目。'}</span></div><Button kind="small" disabled={busy||running.length>0} onClick={()=>run(()=>api(`/exams/${exam.id}/continue`,'POST'))}>继续生成</Button></div>}
          {!generating&&exam.checks.errors.map((e:string)=><div className="inline-warning" key={e}><CircleAlert size={15}/>{e}</div>)}
          <div className="action-bar exam-actions"><div><ShieldCheck size={18}/><span>{exam.checks.can_export?'结构与引用检查通过，可导出':exam.checks.pending_review.length?`${exam.checks.pending_review.length} 道题有待确认的内容提醒`:'请处理分值或题目中的硬错误'}</span></div><Button kind="primary" onClick={exportBoth} disabled={busy||generating||!exam.checks.can_export}><Download size={17}/>生成 Word 双版本</Button></div>{artifacts.length>0&&<div className="download-row">{artifacts.map(a=><a key={a.id} href={'/api/artifacts/'+a.id} className="download-card"><FileText size={25}/><div><strong>{a.kind==='student'?'下载纯试卷':'下载答案解析'}</strong><span>Word 文档 · 同一试卷版本 v{a.exam_revision}</span></div><Download size={18}/></a>)}</div>}
        </>}</div>}
        <footer className="workspace-footer"><span>ExamPilot · 每一步都有依据</span><span>AI 辅助命题，最终内容由教师审阅</span></footer>
      </div>}
    </main>
    {toast&&<div role="alert" className="toast"><CircleAlert size={17}/><span>{toast}</span><button onClick={()=>setToast('')}><X size={16}/></button></div>}
    {source&&<Drawer level={120} title="原文依据" subtitle="来自检索系统的真实定位" onClose={()=>setSource(null)}>{source.map((c,i)=><div className="source-block" key={i}><div className="source-title"><FileText size={19}/><strong>{c.document_name}</strong></div><span className="pill">{locator(c)}</span><blockquote>{c.text}</blockquote><code>{c.source_id}</code>{c.locator.kind==='pdf'&&<a href={`/api/documents/${c.document_id}/original#page=${c.locator.page_number}`} target="_blank" rel="noreferrer" className="subtle-link"><Link2 size={15}/>打开 PDF 对应页</a>}</div>)}</Drawer>}
    {vacancy&&<Drawer title="把这道题，一起打磨好" subtitle="候选未采纳，不计入试卷或分数" onClose={()=>setVacancyId(null)} wide><div className="vacancy-info"><span>原题：{labels[vacancy.original.type]} · {score(vacancy.original.score_units)} 分</span><button disabled={busy||generating} className="subtle-link" onClick={()=>run(async()=>{await api(`/exams/${exam.id}/vacancies/${vacancy.id}/restore`,'POST',{expected_version:vacancy.version});setVacancyId(null)})}><RotateCcw size={14}/>撤销删除</button></div><div className="conversation">{!vacancy.messages.length&&<div className="assistant-message"><Sparkles size={18}/><p>想在这里考察什么？你可以指定知识点、难度或题型。未指定的设置会沿用被删题。</p></div>}{vacancy.messages.map((m:Json,i:number)=><div className={'chat-message '+m.role} key={i}>{m.content}</div>)}</div>{vacancy.candidate&&<div className="candidate-preview"><div className="small-heading"><h3>当前候选</h3><span>尚未入卷</span></div><QuestionCard q={vacancy.candidate} onSource={()=>setSource(vacancy.candidate.citations)}/><Button kind="primary full" disabled={busy||candidateBusy} onClick={adopt}><Check size={17}/>采纳这道题</Button></div>}{candidateBusy&&<div className="working-line"><LoaderCircle size={17} className="spin"/>正在生成候选，已保存的试卷不会改变</div>}<form className="chat-compose" onSubmit={e=>{e.preventDefault();sendCandidate()}}><textarea autoFocus rows={3} value={message} onChange={e=>setMessage(e.target.value)} placeholder="例如：改成一道考察事务隔离的中等难度简答题，仍为 5 分。"/><Button kind="primary" type="submit" disabled={busy||candidateBusy||!message.trim()}><Send size={16}/>{vacancy.candidate?'继续修改':'生成候选'}</Button></form></Drawer>}
    {edit&&<Drawer title="编辑题目" subtitle="手动保存后，需要重新确认内容与答案" onClose={()=>setEdit(null)} wide><QuestionEditor question={edit} onSave={(question)=>run(async()=>{await api(`/exams/${exam.id}/questions/${edit.id}`,'PATCH',{expected_version:edit.version,question});setEdit(null);})} busy={busy}/></Drawer>}
    {traceId&&<Drawer title="执行记录" subtitle="真实模型请求、MCP 调用与证据缓存" onClose={()=>setTraceId(null)} wide><select value={traceId} onChange={e=>setTraceId(e.target.value)}>{[...jobs].reverse().map(j=><option key={j.id} value={j.id}>{({analyze:'资料分析',plan:'整卷规划',generate:'出题',candidate:'补题'} as Json)[j.kind]} · {j.status} · {j.id.slice(-5)}</option>)}</select><div className="trace-list">{!traces.length&&<p>任务记录正在准备。</p>}{traces.map((t,i)=><div className="trace-item" key={t.id}><span className="trace-number">{i+1}</span><div><strong>{t.tool||({progress:t.stage,model_completed:'模型响应完成',evidence_cached:'证据写入缓存',evidence_cache_hit:'复用原文证据',question_completed:'题目生成完成',job_failed:'任务失败'} as Json)[t.name]||t.name}</strong><small>{t.agent_role||'应用服务'}{t.transport?' · MCP / '+t.transport:''}{t.duration_ms?` · ${t.duration_ms} ms`:''}</small><details><summary>查看详情</summary><pre>{JSON.stringify(t,null,2)}</pre></details></div></div>)}</div></Drawer>}
  </div>
}

function JobProgress({job,onCancel,onTrace}:{job:Json;onCancel:()=>void;onTrace:()=>void}) {
  const elapsed=Math.max(0,Math.round((Date.now()/1000-job.created_at)/60));
  const remaining=job.completed>1&&job.total>job.completed?Math.ceil((Date.now()/1000-(job.stage_started_at||job.created_at))/job.completed*(job.total-job.completed)/60):null;
  return <div className="job-progress"><LoaderCircle size={20} className="spin"/><div><strong>{job.stage}</strong><span>{job.total?`${job.completed} / ${job.total} 完成`:'正在确定处理范围'} · 已用约 {elapsed} 分钟{remaining!==null?` · 预计还需约 ${remaining} 分钟，随处理更新`:''}</span><div className={'progress-track '+(!job.total?'indeterminate':'')}><i style={{width:job.total?`${job.completed/job.total*100}%`:'30%'}}/></div></div><button className="subtle-link" onClick={onTrace}>查看过程</button><button className="subtle-link" onClick={onCancel}>取消</button></div>
}

function QuestionCard({q,disabled,onSource,onDelete,onEdit,onReview}:{q:Json;disabled?:boolean;onSource:()=>void;onDelete?:()=>void;onEdit?:()=>void;onReview?:()=>void}) {
  return <article className="question-card card"><div className="question-top"><span className={'pill diff-'+q.difficulty}>{difficulty[q.difficulty]}</span><span className="question-kp">{q.knowledge_point}</span><span className="question-points">{score(q.score_units)} 分</span>{onEdit&&<button disabled={disabled} title="手动编辑" onClick={onEdit}><Pencil size={15}/></button>}{onDelete&&<button disabled={disabled} title="删除后补题" onClick={onDelete}><Trash2 size={15}/></button>}</div><h3 className="question-stem">{q.stem}</h3>{q.options?.length>0&&<div className="options-grid">{q.options.map((o:Json)=><div key={o.id}><span>{o.id}</span>{o.text}</div>)}</div>}<details className="answer-details"><summary><CheckCircle2 size={16}/>答案与解析<ChevronDown size={15}/></summary><div className="answer-content"><strong>参考答案：{answerText(q.answer)}</strong>{q.rubric?.map((r:Json,i:number)=><p key={i}>{r.text}（{score(r.score_units)} 分）</p>)}<p>{q.analysis}</p></div></details><div className="question-bottom"><button className="source-link" onClick={onSource}><BookOpen size={15}/>原文依据 · {q.citations?.length||0} 处<ArrowRight size={13}/></button><span><ShieldCheck size={13}/>来源已定位</span></div>{q.warnings?.length>0&&<div className="question-warning"><CircleAlert size={15}/><div>{q.warnings.map((w:string,i:number)=><p key={i}>{w}</p>)}{onReview&&(q.reviewed?<span className="reviewed"><Check size={13}/>教师已确认</span>:<button disabled={disabled} className="subtle-link" onClick={onReview}>我已核对，确认保留</button>)}</div></div>}</article>
}
function Drawer({title,subtitle,onClose,wide=false,children,level=100}:{title:string;subtitle:string;onClose:()=>void;wide?:boolean;children:React.ReactNode;level?:number}) {return <div style={{zIndex:level}} className="drawer-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><section role="dialog" aria-modal="true" aria-label={title} className={'drawer '+(wide?'wide':'')}><header><div><h2>{title}</h2><p>{subtitle}</p></div><button onClick={onClose} title="关闭"><X size={21}/></button></header><div className="drawer-body">{children}</div></section></div>}

function QuestionEditor({question,onSave,busy}:{question:Json;onSave:(q:Json)=>void;busy:boolean}) {
  const [q,setQ]=useState(question);
  const [answer,setAnswer]=useState(answerText(question.answer));
  function save(){const a=q.type==='true_false'?answer==='正确':['single_choice','multiple_choice','fill_blank'].includes(q.type)?answer.split(/[；;,，]/).map((x:string)=>x.trim()).filter(Boolean):answer;onSave({...q,answer:a});}
  return <div className="editor-form"><label>题干<textarea rows={5} value={q.stem} onChange={e=>setQ({...q,stem:e.target.value})}/></label><label>分值<input type="number" min="0.5" step="0.5" value={score(q.score_units)} onChange={e=>setQ({...q,score_units:Number(e.target.value)*2})}/></label>{q.options.map((o:Json,i:number)=><label key={o.id}>选项 {o.id}<input value={o.text} onChange={e=>setQ({...q,options:q.options.map((v:Json,n:number)=>n===i?{...v,text:e.target.value}:v)})}/></label>)}<label>答案 {['single_choice','multiple_choice','fill_blank'].includes(q.type)&&<small>多项用分号分隔</small>}{q.type==='true_false'?<select value={answer} onChange={e=>setAnswer(e.target.value)}><option>正确</option><option>错误</option></select>:<textarea rows={3} value={answer} onChange={e=>setAnswer(e.target.value)}/>}</label><label>解析<textarea rows={4} value={q.analysis} onChange={e=>setQ({...q,analysis:e.target.value})}/></label>{q.rubric?.length>0&&<div><h3>评分要点</h3>{q.rubric.map((r:Json,i:number)=><div className="rubric-editor" key={i}><input value={r.text} onChange={e=>setQ({...q,rubric:q.rubric.map((v:Json,n:number)=>n===i?{...v,text:e.target.value}:v)})}/><input type="number" step="0.5" min="0.5" value={score(r.score_units)} onChange={e=>setQ({...q,rubric:q.rubric.map((v:Json,n:number)=>n===i?{...v,score_units:Number(e.target.value)*2}:v)})}/><span>分</span></div>)}</div>}<p className="form-note">原文引用保持不变。保存后请重新核对内容；AI 补题仅在删除产生空缺后开放。</p><Button kind="primary full" disabled={busy} onClick={save}>保存修改</Button></div>
}

createRoot(document.getElementById('root')!).render(<App/>);
