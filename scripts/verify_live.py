"""Explicit live-model smoke run, using credentials already configured in the app.

This makes billable model requests. No keys or model doubles are embedded here.
Run only when live verification is intended. Progress is retained for resuming.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "live-verification.json"
sys.stdout.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--phase", choices=["generate", "candidate", "export"], default="generate")
    args = parser.parse_args()
    client = httpx.Client(base_url="http://127.0.0.1:8787", timeout=150)
    report = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}

    def save():
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def call(method, route, **kw):
        response = client.request(method, route, **kw)
        if response.is_error:
            raise RuntimeError(f"{route}: {response.status_code} {response.text[:1000]}")
        return response.json()

    def wait(job_id):
        previous = None
        for _ in range(900):
            job = call("GET", "/api/jobs/" + job_id)
            status = (job["status"], job["stage"], job["completed"], job["total"])
            if status != previous:
                print(job_id, status, flush=True)
                previous = status
            if job["status"] not in ("queued", "running"):
                if job["status"] != "succeeded":
                    raise RuntimeError(job.get("error", job["status"]))
                return job
            time.sleep(2)
        raise RuntimeError("任务仍在运行；进度已保存，可稍后继续检查")

    settings = call("GET", "/api/settings")
    if settings["model"] != args.model:
        raise RuntimeError("当前保存模型与指定实测模型不符，未自动替换模型")
    report["model"] = args.model
    if not report.get("project_id"):
        project = call("POST", "/api/projects", json={"title": "DeepSeek Flash · 真实联调"})
        report["project_id"] = project["id"]
        save()
    project_id = report["project_id"]

    def state():
        return call("GET", "/api/projects/" + project_id)

    if args.phase == "generate":
        current = state()
        for job in current["jobs"]:
            if job["status"] in ("queued", "running"):
                wait(job["id"])
        if not current["documents"]:
            sample = ROOT / "samples" / "数据库原理-原创演示讲义.docx"
            with sample.open("rb") as source:
                result = call("POST", f"/api/projects/{project_id}/documents", files={"file": (sample.name, source, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
            report["analysis_job"] = result["job_id"]
            save()
            wait(result["job_id"])
        for doc in state()["documents"]:
            if doc["status"] != "ready":
                retry = call("POST", f"/api/projects/{project_id}/documents/{doc['id']}/retry")
                wait(retry["id"])
        config = {"title": "数据库原理 · Flash 实测试卷", "total_score_units": 200, "duration_minutes": 120, "ratios": [30, 50, 20], "requirements": "覆盖 SQL、索引和事务；使用文字表达，计算题采用讲义中的简化 I/O 成本条件。", "sections": [{"type": t, "count": n, "score_units": u} for t, n, u in zip(["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer", "calculation"], [4, 2, 2, 2, 2, 1], [10, 10, 10, 10, 30, 40])]}
        if not state()["plan"]:
            result = call("POST", f"/api/projects/{project_id}/plans", json={"config": config})
            wait(result["id"])
        if not report.get("revised_plan"):
            plan = state()["plan"]
            revised = call("POST", f"/api/projects/{project_id}/plans", json={"config": plan["config"], "previous_plan": plan["id"], "feedback": "保持所有题型、题数和分值不变。事务题优先考察原子性与并发隔离；计算题仍采用讲义的简化 I/O 成本模型。"})
            wait(revised["id"])
            report["revised_plan"] = state()["plan"]["id"]
            save()
        current = state()
        if not current["exam"]:
            result = call("POST", f"/api/plans/{current['plan']['id']}/confirm", json={"version": current["plan"]["version"]}, headers={"Idempotency-Key": "live-" + project_id})
            report["generation_job"] = result["id"]
            save()
            wait(result["id"])
        elif not report.get("initial_generated") and len(current["exam"]["questions"]) < 13:
            result = call("POST", f"/api/exams/{current['exam']['id']}/continue")
            report["generation_job"] = result["id"]
            save()
            wait(result["id"])
        current = state()
        if len(current["exam"]["questions"]) != 13 or current["exam"].get("failures"):
            raise RuntimeError("整卷尚未成功：" + json.dumps(current["exam"].get("failures"), ensure_ascii=False))
        report["initial_generated"] = True
        report["exam_id"] = current["exam"]["id"]
        report["generated_at"] = time.time()
        save()
    elif args.phase == "candidate":
        current = state()
        exam = current["exam"]
        if not report.get("vacancy_id"):
            question = next(q for q in exam["questions"] if q["type"] == "single_choice")
            vacancy = call("DELETE", f"/api/exams/{exam['id']}/questions/{question['id']}", headers={"If-Match": str(question["version"])})
            report["vacancy_id"] = vacancy["id"]
            save()
        vid = report["vacancy_id"]
        prompts = ["补一道关于事务原子性的中等难度单选题，保持 5 分，给出四个选项。", "保留题型、知识点和分数，把题干改为转账失败的具体场景，并确保只有一个正确选项。"]
        for index, prompt in enumerate(prompts):
            if report.get("candidate_turns", 0) > index:
                continue
            vacancy = next(v for v in state()["vacancies"] if v["id"] == vid)
            job = call("POST", f"/api/exams/{exam['id']}/vacancies/{vid}/messages", json={"message": prompt, "expected_version": vacancy["version"]})
            wait(job["id"])
            report["candidate_turns"] = index + 1
            report.setdefault("candidate_jobs", []).append(job["id"])
            save()
        assert len(state()["exam"]["questions"]) == 12, "候选在采纳前不得入卷"
    else:
        current = state()
        exam = current["exam"]
        if current["vacancies"]:
            raise RuntimeError("请先审阅并采纳候选，再执行导出验证")
        result = call("POST", f"/api/exams/{exam['id']}/exports", json={"expected_revision": exam["revision"]})
        report["artifacts"] = result["artifacts"]
        report["completed_at"] = time.time()
        save()
        for artifact in result["artifacts"]:
            response = client.get("/api/artifacts/" + artifact["id"])
            response.raise_for_status()
            assert response.content.startswith(b"PK")
            output = ROOT / "data" / ("live-" + artifact["kind"] + ".docx")
            output.write_bytes(response.content)
            print("Downloaded:", str(output))
    current = state()
    print(json.dumps({"project_id": project_id, "model": args.model, "knowledge_points": len(current["knowledge_points"]), "questions": len(current["exam"]["questions"]) if current["exam"] else 0, "checks": current["exam"]["checks"] if current["exam"] else None, "candidate_turns": report.get("candidate_turns", 0)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
