# ExamPilot

本地运行的智能组卷 Demo。上传文字资料，由规划 Agent 安排试卷，出题 Agent 通过真实 MCP 批量取得证据，再逐题生成。删除题目后才能对话补题；候选题可多轮调整，采纳后才入卷。

## 运行

**日常使用直接双击根目录：**

- `启动ExamPilot.bat`：后台启动服务与 MCP，准备好后自动打开浏览器；重复点击不会启动第二份。
- `停止ExamPilot.bat`：取消进行中的任务，关闭本项目服务与 MCP，保留资料、试卷和配置；不会关闭其他 Python 程序。

启动日志位于 `data/runtime/`。关闭浏览器不会停止后台服务，请使用停止 BAT。缺少依赖／前端构建时启动入口会尝试初始化，首次需要联网。

需要 Windows、Python 3.10+、Node.js 20.19+／22.12+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。当前工作区已完成依赖安装和前端构建。

```powershell
# 在项目根目录执行。已有依赖和构建产物时，直接启动：
.venv\Scripts\python.exe -m backend.run
```

打开 [http://127.0.0.1:8787](http://127.0.0.1:8787)。首次完整安装／更新可使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

脚本执行 `uv sync --frozen`、`npm ci`、前端构建，再启动本地服务。保持该终端运行；Ctrl+C 停止后端和 MCP 子进程。端口已占用时可传 `-Port 8788`。后端使用单 worker，禁止同时开启多个服务进程共享同一数据目录。

前端开发可在另一个终端运行：

```powershell
cd frontend
npm.cmd run dev
```

Vite 默认在 5173 提供页面并将 `/api` 转发到 8787。生产构建由 FastAPI 直接提供，无需两个长期运行的 Web 服务。

## 第一次实际使用

1. 打开“API 设置”，选择 DeepSeek、GPT、硅基流动或自定义兼容服务。
2. 输入 Base URL 和自己的 API Key，点击“获取模型”（不要求先填模型 ID，也不会自动保存），从显式下拉列表选择模型，或手动填写模型 ID。然后保存配置；“测试连接与能力”也可直接使用当前草稿，不会清空输入。应选择支持原生 function/tool calling 的模型。
3. 返回工作台。点击“试用原创数据库讲义”，或上传文字型 PDF、PPTX、DOCX。
4. 等待全部资料分析完成。默认 13 题、100 分，六种题型；各题型难度配额由代码分配。
5. 点击“AI 组卷规划”，通过对话调整知识点／难度，再“确认方案并出题”。
6. 等待逐题生成结束；检查答案和原文。完整题仅有手动编辑／删除。
7. 删除一题后，在空缺对话输入补题要求，反复修改候选，点击“采纳”。未采纳候选不计分、不导出。
8. 总分或来源硬错误必须修复；内容提醒可由教师核对后确认。导出 Word 学生版与教师答案解析版。

用户删除题目后目标总分不自动变化。可以补题恢复原总分，或通过试卷标题区的总分编辑入口修改目标，再导出。

## 模型与密钥

采用 Chat Completions 风格的兼容适配层。服务地址与模型可配置；GPT 推理模型使用相应输出预算字段。不同模型的权限和工具能力须实际测试，不能由服务商名称推断。

DeepSeek Flash／V4 在受控出题流程中显式使用 `thinking: {type: "disabled"}`，避免默认思考模式与强制工具选择冲突；模型名称保持不变。能力测试包含结构化输出、原生工具调用与工具结果回传后的继续响应。服务商错误会脱敏显示具体原因，不再仅返回笼统 HTTP 400。

密钥优先保存到系统凭据管理器，按服务地址隔离；失败时只保存在当前后端会话，不落入数据库和浏览器 localStorage。也可在本地 `.env` 中设置：

```dotenv
EXAMPILOT_API_KEY=your-key
EXAMPILOT_BASE_URL=https://api.deepseek.com
EXAMPILOT_MODEL=deepseek-flash
```

不要提交 `.env`。项目仅监听 `127.0.0.1`，本期没有公网账号／权限体系。资料保存在本地，但知识提取和出题会把相关文本发送至所选模型服务商。

## 架构与真实 MCP

```text
React 工作台 / API 设置
            │ HTTP + SSE
FastAPI + 任务状态机 + SQLite
  ├─ Planning Agent：独立指令与上下文，整卷规划
  ├─ Generation Agent：独立指令与上下文，生成／候选补题
  │     │ 原生模型工具调用
  │     └─ MCP Client ── stdio ── 独立 Knowledge MCP Server
  │                                ├─ search（支持批量）
  │                                └─ get_chunk_context（支持批量）
  ├─ Evidence Cache：原文、来源编号、资料版本、调用记录
  ├─ pypdf / python-pptx / python-docx：文本与定位
  └─ Word 导出器：明确字段白名单，两版同一快照
```

MCP 生命周期由后端管理，使用 `mcp` SDK 真实执行 initialize、tools/list 和 tools/call。`/api/health` 可查看连接与工具名。任务的“执行记录”可看到模型角色、MCP 调用及缓存命中；缓存命中不会伪造工具调用。

搜索采用中文分词与 BM25；GraphRAG 和向量数据库未接入。检索返回真实 `source_id` 与页／段落定位，模型只选择来源编号；后端构建引用。DOCX 显示段落或表格位置，不虚构页码。

`skills/` 中五份 SKILL.md 由应用按阶段加载，不依赖个人电脑上安装的同名插件。两个 Agent 可共用同一模型服务，独立保存输入上下文，通过结构化 Plan 交接。

## 数据与恢复

- 业务数据、原件、证据缓存与导出保存在 `data/`，已加入忽略规则。
- 资料分块分析逐块记录检查点；分析失败或取消后可重试，已完成块可复用。
- 生成失败保留已完成题，点击“继续生成”仅补未完成部分。页面刷新不会创建新任务。
- 后端重启将任务标记 interrupted；候选对话和成功候选保留，可继续提要求。
- 删除／采纳使用版本与状态检查；重复采纳不会重复加题；撤销删除后晚到候选不能入卷。
- 当前工程为单应用写入进程。SQLite 使用 WAL，MCP 进程只读已发布快照。

## 验证

```powershell
uv run pytest -q
cd frontend
npm.cmd run build
```

自动检查覆盖难度分配、PDF／PPTX／DOCX 来源映射、真实 MCP 批量调用、六题型闭环、证据缓存、空缺候选多轮调整与幂等采纳、编辑锁定、总分修改、引用篡改拒绝及 Word 答案隔离。

**自动化工作流测试中的模型响应使用 `tests/test_workflow.py` 内的确定性替身；应用和 stdio MCP 使用真实实现。另已使用真实 `deepseek-flash` 完成 27 块资料分析、两轮规划、13 题／100 分生成、两轮候选补题、采纳与双 Word 导出，见 [真实联调记录](docs/demo/deepseek-flash-live.md)。GPT、硅基流动及其他具体模型仍需各自验收。**

设置页专项回归：`uv run pytest tests/test_settings.py -q` 与 `node tests/settings-browser.cjs`。后者在浏览器中隔离拦截 API，不读取或修改用户凭据，验证空模型发现、草稿保留、失败不清空和保存后刷新。新版设置页通过 `POST /api/settings/models` 查询未保存草稿，原 GET 接口仍用于查询已保存配置。

浏览器闭环脚本在独立测试服务器上执行，不能指向正式工作区：

```powershell
# 终端 A，专用隔离数据；只能用于测试
$env:EXAMPILOT_TEST_MODE='1'
$env:EXAMPILOT_DATA_DIR="$PWD\data\browser-test"
.venv\Scripts\python.exe -m tests.serve_browser_fixture

# 终端 B：前端 npm ci 已安装 playwright 测试依赖
node tests/browser-smoke.cjs
```

脚本默认调用本机 Chrome 的 headless 模式；检查上传→规划调整→13 题→删除→两轮候选→来源侧栏→采纳→Word 下载，并验证移动端无横向溢出。截图与下载保存在 `data/browser-check/`。该服务器强制要求测试环境变量，不会被普通启动脚本使用。

## 当前限制与下一步验证

- DeepSeek Flash 已完成一份真实样例的业务闭环；不同学科和三家供应商的其他模型仍需分别验证，不能将该样例视为全部出题质量保证。
- 扫描件、图片文字、复杂公式与图表不做 OCR。纯图片页会提示转换资料；混合页面只处理可提取文字，视觉内容需教师另行核对。
- 计算题给出步骤并经过模型复核，尚未接入通用数学求解器；不能保证模型计算正确。
- 重复检查目前覆盖相同题干，语义近似重复仍需教师审阅。
- 模型控制的规划和知识提取仍可能返回不合要求的结构；系统会提示并保留前序成果，可重试，不以假内容补齐。
- 尚未实现公网部署、多用户、多进程任务队列、PDF 导出和 GraphRAG；复杂学校模板及 Word 公式排版也后置。

产品规则见 [出题AGENT-PRD.md](出题AGENT-PRD.md)，实现与验收记录见 [docs/demo/implementation-status.md](docs/demo/implementation-status.md)。
