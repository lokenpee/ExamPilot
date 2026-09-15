from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.engine import Engine
from backend.exports import export_docx, ordered_questions
from backend.mcp_client import KnowledgeClient
from backend.providers import Settings, Provider, discover_models, decode_json
from backend.schemas import ExamConfig, Question
from backend.store import ROOT, DATA, Store, uid

store = Store()
settings = Settings(store)
mcp = KnowledgeClient(store)
engine = Engine(store, settings, mcp)


@asynccontextmanager
async def lifespan(app):
    for job in store.all("jobs"):
        if job["status"] in ("running", "queued"):
            job.update(status="interrupted", error="应用曾中断，可从已保存的进度继续")
            store.put("jobs", job)
    for exam in store.all("exams"):
        if exam["status"] in ("generating", "preparing_evidence"):
            exam["status"] = "editing"
            store.put("exams", exam)
    await mcp.start()
    yield
    for job_id in list(engine.tasks):
        await engine.cancel(job_id)
    await mcp.close()


app = FastAPI(title="ExamPilot", version="0.3.0", lifespan=lifespan)


@app.middleware("http")
async def local_origin(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in ("localhost", "127.0.0.1", "testserver"):
            return JSONResponse({"detail": "本地 Demo 不接受外部网站请求"}, status_code=403)
    return await call_next(request)


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({"detail": str(exc)[:1500]}, status_code=422)


def require(kind, ident, project_id=None):
    result = store.get(kind, ident)
    if not result or project_id and result.get("project_id") != project_id:
        raise HTTPException(404, "记录不存在")
    return result


def active(project_id, kinds=None):
    return [j for j in store.all("jobs") if j["project_id"] == project_id and j["status"] in ("running", "queued") and (kinds is None or j["kind"] in kinds)]


def editable(exam):
    if active(exam["project_id"], {"generate"}):
        raise HTTPException(409, "整卷生成结束或取消后才能编辑")


def check_version(actual, expected):
    if actual != expected:
        raise HTTPException(409, "内容已更新，请刷新后重试")


def exam_checks(exam):
    errors = []
    actual = sum(q["score_units"] for q in exam["questions"])
    if not exam["questions"]:
        errors.append("试卷中还没有题目")
    if actual != exam["target_score_units"]:
        errors.append(f"实际 {actual/2:g} 分，目标 {exam['target_score_units']/2:g} 分；请补题或修改目标总分")
    for i, question in enumerate(ordered_questions(exam), 1):
        try:
            Question.model_validate(question)
            citations = {c["source_id"]: c for c in question.get("citations", [])}
            if set(question["source_ids"]) != set(citations):
                raise ValueError("引用编号不一致")
            for citation in citations.values():
                chunk = store.get("chunks", citation["chunk_id"])
                corpus = store.get("corpora", f"{exam['project_id']}_v{citation['corpus_version']}")
                if not chunk or not corpus or chunk["id"] not in corpus["chunk_ids"] or chunk["project_id"] != exam["project_id"]:
                    raise ValueError("引用来源不存在")
                segment = next((seg for seg in chunk["segments"] if seg["source_id"] == citation["source_id"]), None)
                if not segment or segment["text"] != citation["text"] or segment["locator"] != citation["locator"] or chunk["text_hash"] != citation["text_hash"]:
                    raise ValueError("引用原文或定位已改变")
        except (ValueError, KeyError) as exc:
            errors.append(f"第 {i} 题：{str(exc)[:160]}")
    pending = [q["id"] for q in exam["questions"] if q.get("warnings") and not q.get("reviewed")]
    return {"errors": errors, "pending_review": pending, "actual_score_units": actual, "can_export": not errors and not pending}


@app.get("/api/health")
async def health():
    return {"ok": True, "mcp": mcp.health(), "configured": settings.public()["has_key"]}


@app.get("/api/settings")
async def get_settings():
    return {**settings.public(), "mcp": mcp.health()}


@app.put("/api/settings")
async def save_settings(payload: dict):
    return {**settings.save(payload), "mcp": mcp.health()}


@app.post("/api/settings/test")
async def test_settings(payload: dict | None = None):
    config, api_key = settings.connection(payload)
    if not api_key:
        raise ValueError("请填写当前接口地址的 API Key")
    provider = Provider(config, api_key, store, "system")
    structured = await provider.json('返回 {"ok": true}', {}, "capability-structured-output")
    json_ok = structured.get("ok") is True
    tools = [{"type": "function", "function": {"name": "connection_probe", "description": "用于验证原生工具调用", "parameters": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}}}]
    messages = [{"role": "user", "content": '先调用 connection_probe 工具，message 填 ok。收到工具结果后仅返回 JSON {"ok":true}。'}]
    response = await provider.complete(messages, "capability-tool-call", tools, {"type": "function", "function": {"name": "connection_probe"}})
    calls = response.get("tool_calls", [])
    tool_ok = bool(calls and all(call.get("function", {}).get("name") == "connection_probe" for call in calls))
    roundtrip_ok = False
    if tool_ok:
        messages.append(Provider.assistant_message(response))
        for call in calls:
            args = json.loads(call["function"]["arguments"])
            if args.get("message") != "ok":
                tool_ok = False
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": '{"ok":true}'})
        followup = await provider.complete(messages, "capability-tool-roundtrip", tools, "none")
        roundtrip_ok = not followup.get("tool_calls") and decode_json(followup.get("content") or "").get("ok") is True
    capabilities = {"tool_calling": tool_ok, "tool_roundtrip": roundtrip_ok, "structured_output": json_ok, "execution_mode": "non-thinking" if provider.controlled_deepseek_mode else "provider-default", "tested_at": time.time(), "model": config["model"], "base_url": config["base_url"]}
    if payload is None:
        record = settings.raw()
        record["capabilities"] = capabilities
        store.put("settings", record)
    return capabilities


@app.get("/api/settings/models")
async def list_models():
    config, key = settings.connection(require_model=False)
    return await discover_models(config, key)


@app.post("/api/settings/models")
async def preview_models(payload: dict):
    config, key = settings.connection(payload, require_model=False)
    return await discover_models(config, key)


@app.post("/api/mcp/reconnect")
async def reconnect():
    if any(j["status"] in ("running", "queued") for j in store.all("jobs")):
        raise HTTPException(409, "任务运行中，请先取消任务再重连")
    await mcp.close()
    mcp.ready.clear()
    await mcp.start()
    return mcp.health()


@app.get("/api/projects")
async def projects():
    return store.all("projects")


@app.post("/api/projects")
async def create_project(payload: dict):
    return store.put("projects", {"id": uid("project"), "title": str(payload.get("title") or "新的组卷项目")[:120], "corpus_version": 0, "created_at": time.time(), "plan_id": None, "exam_id": None})


@app.get("/api/projects/{project_id}")
async def project_state(project_id: str):
    project = require("projects", project_id)
    docs = [d for d in store.all("documents") if d["project_id"] == project_id and d["status"] != "removed"]
    corpus = store.get("corpora", f"{project_id}_v{project['corpus_version']}")
    exam = store.get("exams", project["exam_id"]) if project.get("exam_id") else None
    return {"project": project, "documents": [{k: v for k, v in d.items() if k not in ("extracted", "path", "knowledge_points")} for d in docs], "knowledge_points": corpus["knowledge_points"] if corpus else [], "plan": store.get("plans", project["plan_id"]) if project.get("plan_id") else None, "exam": {**exam, "checks": exam_checks(exam)} if exam else None, "vacancies": [v for v in store.all("vacancies") if exam and v["exam_id"] == exam["id"] and v["status"] == "open"], "jobs": [j for j in store.all("jobs") if j["project_id"] == project_id][-30:]}


@app.post("/api/projects/{project_id}/documents", status_code=202)
async def upload(project_id: str, file: UploadFile = File(...)):
    require("projects", project_id)
    if active(project_id, {"generate", "plan", "candidate"}):
        raise HTTPException(409, "请等当前任务完成或取消后再上传")
    settings.provider()  # Do not accept a file that cannot enter its mandatory analysis step.
    docs = [d for d in store.all("documents") if d["project_id"] == project_id and d["status"] != "removed"]
    if len(docs) >= 5:
        raise ValueError("每项目最多 5 个文件")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx", ".pptx"):
        raise ValueError("仅支持文字型 PDF、PPTX、DOCX")
    content = await file.read(20 * 1024 * 1024 + 1)
    if not content or len(content) > 20 * 1024 * 1024:
        raise ValueError("文件为空或超过 20 MB")
    if suffix == ".pdf" and not content.startswith(b"%PDF") or suffix != ".pdf" and not content.startswith(b"PK"):
        raise ValueError("文件内容与扩展名不一致")
    digest = hashlib.sha256(content).hexdigest()
    duplicate = next((d for d in docs if d["sha256"] == digest), None)
    if duplicate:
        return {"document_id": duplicate["id"], "reused": True}
    doc_id = uid("doc")
    path = store.directory / "uploads" / (doc_id + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    doc = {"id": doc_id, "project_id": project_id, "name": Path(file.filename).name[:180], "path": str(path), "sha256": digest, "status": "uploaded", "size": len(content), "created_at": time.time()}
    store.put("documents", doc)
    job = engine.launch(project_id, "analyze", {"document_id": doc_id})
    return {"document_id": doc_id, "job_id": job["id"]}


@app.post("/api/projects/{project_id}/documents/{doc_id}/retry", status_code=202)
async def retry_document(project_id, doc_id):
    doc = require("documents", doc_id, project_id)
    if active(project_id, {"generate", "plan", "candidate"}) or any(j["payload"].get("document_id") == doc_id for j in active(project_id)):
        raise HTTPException(409, "相关任务正在执行")
    if doc["status"] in ("ready", "removed"):
        raise ValueError("该资料无需重试")
    return engine.launch(project_id, "analyze", {"document_id": doc_id})


@app.delete("/api/projects/{project_id}/documents/{doc_id}")
async def remove_document(project_id, doc_id):
    doc = require("documents", doc_id, project_id)
    if active(project_id):
        raise HTTPException(409, "请先等任务完成或取消，再移除资料")
    doc["status"] = "removed"
    store.put("documents", doc)
    engine.publish(project_id)
    return {"ok": True}


@app.get("/api/documents/{doc_id}/original")
async def original(doc_id):
    doc = require("documents", doc_id)
    return FileResponse(doc["path"], media_type="application/pdf" if doc["name"].lower().endswith(".pdf") else None, filename=doc["name"], content_disposition_type="inline")


@app.post("/api/projects/{project_id}/plans", status_code=202)
async def plan(project_id: str, payload: dict, request: Request):
    require("projects", project_id)
    if active(project_id):
        raise HTTPException(409, "当前项目仍有任务运行")
    engine.corpus(project_id)
    config = ExamConfig.model_validate(payload["config"])
    previous = payload.get("previous_plan")
    if previous:
        require("plans", previous, project_id)
    return engine.launch(project_id, "plan", {"config": config.model_dump(), "feedback": str(payload.get("feedback", ""))[:5000], "previous_plan": previous}, request.headers.get("idempotency-key"))


@app.post("/api/plans/{plan_id}/confirm", status_code=202)
async def confirm(plan_id: str, payload: dict, request: Request):
    plan = require("plans", plan_id)
    project = require("projects", plan["project_id"])
    key = request.headers.get("idempotency-key")
    if key:
        existing = next((j for j in store.all("jobs") if j.get("idempotency_key") == key and j["project_id"] == project["id"] and j["kind"] == "generate"), None)
        if existing:
            return existing
    if active(project["id"]):
        raise HTTPException(409, "当前项目仍有任务运行")
    check_version(plan["version"], payload.get("version"))
    corpus = engine.corpus(project["id"])
    if plan["corpus_version"] != corpus["version"] or project["plan_id"] != plan_id:
        raise HTTPException(409, "资料或规划已有更新，请重新规划后确认")
    if plan.get("unresolved"):
        raise ValueError("请先解决规划中待处理的问题")
    settings.provider()
    exam = {"id": uid("exam"), "project_id": project["id"], "plan_id": plan_id, "title": plan["config"]["title"], "duration_minutes": plan["config"]["duration_minutes"], "target_score_units": plan["config"]["total_score_units"], "questions": [], "deleted_slots": [], "revision": 1, "status": "preparing_evidence", "created_at": time.time()}
    project["exam_id"] = exam["id"]
    store.put_many([("exams", exam), ("projects", project)])
    return engine.launch(project["id"], "generate", {"exam_id": exam["id"]}, key)


@app.post("/api/exams/{exam_id}/continue", status_code=202)
async def continue_exam(exam_id):
    exam = require("exams", exam_id)
    if active(exam["project_id"]):
        raise HTTPException(409, "当前项目仍有任务运行")
    return engine.launch(exam["project_id"], "generate", {"exam_id": exam_id})


@app.patch("/api/exams/{exam_id}")
async def patch_exam(exam_id: str, payload: dict):
    exam = require("exams", exam_id)
    editable(exam)
    check_version(exam["revision"], payload.get("expected_revision"))
    score = payload.get("target_score_units", exam["target_score_units"])
    if type(score) is not int or not 0 < score <= 1000:
        raise ValueError("目标总分为 0.5–500 分")
    exam.update(target_score_units=score, title=str(payload.get("title", exam["title"]))[:120], revision=exam["revision"] + 1)
    return store.put("exams", exam)


@app.patch("/api/exams/{exam_id}/questions/{qid}")
async def patch_question(exam_id: str, qid: str, payload: dict):
    exam = require("exams", exam_id)
    editable(exam)
    question = next((q for q in exam["questions"] if q["id"] == qid), None)
    if not question:
        raise HTTPException(404, "题目不存在")
    check_version(question["version"], payload.get("expected_version"))
    updated = Question.model_validate({**question, **payload.get("question", {})}).model_dump()
    citations = {c["source_id"]: c for c in question["citations"]}
    if not set(updated["source_ids"]) <= set(citations):
        raise ValueError("手动编辑不能伪造新引用")
    store.put("question_history", {**question, "id": f"{qid}_v{question['version']}"})
    question.update(updated, citations=[citations[s] for s in updated["source_ids"]], reviewed=False, warnings=["题目经过人工编辑，请确认题干、答案与原文仍一致"], version=question["version"] + 1)
    exam["revision"] += 1
    store.put("exams", exam)
    return question


@app.post("/api/exams/{exam_id}/questions/{qid}/review")
async def review_question(exam_id: str, qid: str, payload: dict):
    exam = require("exams", exam_id)
    editable(exam)
    question = next((q for q in exam["questions"] if q["id"] == qid), None)
    if not question:
        raise HTTPException(404, "题目不存在")
    check_version(question["version"], payload.get("expected_version"))
    question.update(reviewed=True, reviewed_at=time.time())
    exam["revision"] += 1
    store.put("exams", exam)
    return {"ok": True}


@app.delete("/api/exams/{exam_id}/questions/{qid}")
async def delete_question(exam_id: str, qid: str, request: Request):
    exam = require("exams", exam_id)
    editable(exam)
    question = next((q for q in exam["questions"] if q["id"] == qid), None)
    if not question:
        old = next((v for v in store.all("vacancies") if v["exam_id"] == exam_id and v["original"]["id"] == qid and v["status"] == "open"), None)
        if old:
            return old
        raise HTTPException(404, "题目不存在")
    check_version(question["version"], int(request.headers.get("if-match", "0")))
    vacancy = {"id": uid("vacancy"), "project_id": exam["project_id"], "exam_id": exam_id, "original": question, "version": 1, "status": "open", "messages": [], "candidate_history": [], "candidate": None}
    exam["questions"] = [q for q in exam["questions"] if q["id"] != qid]
    if question.get("slot_id") and question["slot_id"] not in exam["deleted_slots"]:
        exam["deleted_slots"].append(question["slot_id"])
    exam["revision"] += 1
    store.put_many([("exams", exam), ("vacancies", vacancy)])
    return vacancy


@app.post("/api/exams/{exam_id}/vacancies/{vid}/messages", status_code=202)
async def vacancy_message(exam_id: str, vid: str, payload: dict, request: Request):
    exam = require("exams", exam_id)
    editable(exam)
    vacancy = require("vacancies", vid, exam["project_id"])
    if vacancy["exam_id"] != exam_id or vacancy["status"] != "open":
        raise HTTPException(409, "只有当前试卷的删除空缺才能补题")
    key = request.headers.get("idempotency-key")
    if key:
        previous = next((j for j in store.all("jobs") if j.get("idempotency_key") == key and j["project_id"] == exam["project_id"] and j["payload"].get("vacancy_id") == vid), None)
        if previous:
            return previous
    if any(j["payload"].get("vacancy_id") == vid for j in active(exam["project_id"])):
        raise HTTPException(409, "当前候选仍在生成")
    check_version(vacancy["version"], payload.get("expected_version"))
    text = str(payload.get("message", "")).strip()
    if not text or len(text) > 3000:
        raise ValueError("请输入 1–3000 字的补题要求")
    settings.provider()
    vacancy["messages"].append({"role": "user", "content": text})
    vacancy["version"] += 1
    store.put("vacancies", vacancy)
    return engine.launch(exam["project_id"], "candidate", {"vacancy_id": vid}, key)


@app.post("/api/exams/{exam_id}/vacancies/{vid}/adopt")
async def adopt(exam_id: str, vid: str, payload: dict):
    exam = require("exams", exam_id)
    editable(exam)
    vacancy = require("vacancies", vid, exam["project_id"])
    if vacancy["exam_id"] != exam_id:
        raise HTTPException(404, "空缺不存在")
    if vacancy["status"] == "filled" and vacancy.get("adopted_candidate_id") == payload.get("candidate_id"):
        return {"ok": True, "question_id": vacancy["adopted_question_id"]}
    if vacancy["status"] != "open":
        raise HTTPException(409, "空缺已关闭")
    check_version(vacancy["version"], payload.get("expected_version"))
    if any(j["payload"].get("vacancy_id") == vid for j in active(exam["project_id"])):
        raise HTTPException(409, "请等待本轮候选完成，或取消后再采纳")
    candidate = next((c for c in vacancy["candidate_history"] if c["id"] == payload.get("candidate_id")), None)
    if not candidate:
        raise ValueError("候选不存在或尚未完成")
    Question.model_validate(candidate)
    question = {**copy.deepcopy(candidate), "id": uid("q"), "version": 1}
    trial = {**exam, "questions": [question], "target_score_units": question["score_units"]}
    if exam_checks(trial)["errors"]:
        raise ValueError("候选存在结构或引用错误，不能采纳")
    exam["questions"].append(question)
    exam["revision"] += 1
    vacancy.update(status="filled", version=vacancy["version"] + 1, adopted_candidate_id=candidate["id"], adopted_question_id=question["id"])
    store.put_many([("exams", exam), ("vacancies", vacancy)])
    return {"ok": True, "question_id": question["id"]}


@app.post("/api/exams/{exam_id}/vacancies/{vid}/restore")
async def restore(exam_id: str, vid: str, payload: dict):
    exam = require("exams", exam_id)
    editable(exam)
    vacancy = require("vacancies", vid, exam["project_id"])
    if vacancy["exam_id"] != exam_id or vacancy["status"] != "open":
        raise HTTPException(409, "空缺已填入或不存在，无法撤销原删除")
    check_version(vacancy["version"], payload.get("expected_version"))
    # Mark closed before awaiting cancellation so late generation cannot commit.
    vacancy.update(status="restored", version=vacancy["version"] + 1)
    exam["questions"].append(vacancy["original"])
    exam["revision"] += 1
    store.put_many([("exams", exam), ("vacancies", vacancy)])
    for job in active(exam["project_id"]):
        if job["payload"].get("vacancy_id") == vid:
            await engine.cancel(job["id"])
    return {"ok": True}


@app.post("/api/exams/{exam_id}/exports")
async def exports(exam_id: str, payload: dict):
    exam = copy.deepcopy(require("exams", exam_id))
    editable(exam)
    check_version(exam["revision"], payload.get("expected_revision"))
    checks = exam_checks(exam)
    if not checks["can_export"]:
        raise ValueError("；".join(checks["errors"]) or "请先确认待复核的内容提醒")
    artifacts = []
    for kind in ("student", "teacher"):
        ident = uid("export")
        path = store.directory / "exports" / (ident + ".docx")
        await asyncio.to_thread(export_docx, exam, path, kind == "teacher")
        record = {"id": ident, "exam_id": exam_id, "exam_revision": exam["revision"], "kind": kind, "path": str(path), "name": ("试卷" if kind == "student" else "答案解析") + f"_v{exam['revision']}.docx"}
        store.put("artifacts", record)
        artifacts.append({k: v for k, v in record.items() if k != "path"})
    return {"artifacts": artifacts}


@app.get("/api/artifacts/{artifact_id}")
async def download(artifact_id):
    record = require("artifacts", artifact_id)
    return FileResponse(record["path"], filename=record["name"], media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/api/jobs/{job_id}")
async def get_job(job_id):
    return require("jobs", job_id)


@app.get("/api/jobs/{job_id}/traces")
async def traces(job_id):
    require("jobs", job_id)
    return [e for e in store.all("events") if e["job_id"] == job_id]


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id):
    require("jobs", job_id)
    await engine.cancel(job_id)
    return require("jobs", job_id)


@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str, request: Request):
    require("jobs", job_id)
    try:
        initial = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        initial = 0

    async def stream():
        sent = initial
        while not await request.is_disconnected():
            history = [e for e in store.all("events") if e["job_id"] == job_id]
            for index, event in enumerate(history[sent:], sent + 1):
                yield f"id: {index}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                sent = index
            job = require("jobs", job_id)
            if job["status"] not in ("queued", "running"):
                yield f"event: done\ndata: {json.dumps({'status': job['status']})}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.8)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/samples")
async def samples():
    return [{"name": p.name, "url": "/api/samples/" + p.name} for p in (ROOT / "samples").glob("*.docx")]


@app.get("/api/samples/{name}")
async def sample(name: str):
    path = ROOT / "samples" / Path(name).name
    if not path.is_file() or path.suffix != ".docx":
        raise HTTPException(404)
    return FileResponse(path, filename=path.name)


dist = ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
