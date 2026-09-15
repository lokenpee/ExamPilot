export type Json = Record<string, any>;

export async function api(url: string, method='GET', body?: any, headers: Json={}) {
  const form = body instanceof FormData;
  let response: Response;
  try {
    response = await fetch('/api'+url,{method,headers:{...(!form && body!==undefined ? {'Content-Type':'application/json'} : {}),...headers},body:body===undefined?undefined:form?body:JSON.stringify(body)});
  } catch {
    throw new Error('无法连接本地服务，请确认 ExamPilot 已启动；当前输入已保留');
  }
  const raw = await response.text();
  let data: any;
  try { data = JSON.parse(raw); }
  catch { throw new Error(`服务返回了无法解析的响应（HTTP ${response.status}），当前输入已保留`); }
  if (!response.ok) throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));
  return data;
}
