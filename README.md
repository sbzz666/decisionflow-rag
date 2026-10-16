# DecisionFlow RAG：基于 FastAPI、React 与 BM25 的多 Agent 决策助手

面向实时语音对话与决策辅助的个人项目。当前 v0.2 已可本机运行：输入现场发言、检索背景、产生有引用的提醒，再继续追问。

技术：Python、FastAPI、asyncio、WebSocket、SQLite、Pydantic、React、TypeScript、Vite、BM25、RAG。模型采用可配置的 Chat Completions 兼容接口。

## v0.2 RAG（当前实现）

资料 → 带重叠的原文分块 → 中文双字词/英文词项 → BM25 排序 → 最多 5 个片段、2200 字上下文预算 → 问答或并行分析 → 引用校验/候选审核。

- 分块大小上限 500 字符，重叠 80 字符，优先按句末切分；保留文档 ID、内容哈希版本与字符起止位置。
- SQLite 保存会话、文档与片段；查询只使用当前会话的实时资料，不跨会话检索。旧会话会自动生成片段。
- BM25 使用 k1=1.2、b=0.75；不是向量检索，没有 Embedding 或神经重排序，不声称具备通用语义召回能力。
- 所有分析角色共享检索证据；拒绝不存在的引用。引用存在不代表语义正确，模型审核仍可能出错。
- 删除文档同步移除片段及直接引用它的提醒、回答。当前不支持文件上传、OCR 或历史版本管理；编辑请删除旧资料后添加新资料。
- 资料中的指令被提示为不可信内容；这不能保证完全防止提示词注入。
- 未配置模型时仅运行检索与规则演示。已验证模拟模型收到片段并返回可解析引用，尚未验证真实供应商效果。

求职项目名称：**DecisionFlow RAG：基于 FastAPI、React 与 BM25 的多 Agent 决策助手**。
简历可描述：实现文档分块、BM25 检索增强、并行 LLM 角色编排、证据引用校验、WebSocket 会话通信及 SQLite 持久化。不要写成 LangGraph、向量数据库或已上线生产系统。

详见 [RAG 设计与边界](docs/rag.md)。研究文档中的候选架构不代表已实现功能。

## 立即体验

首次使用请先按下节安装依赖并构建前端，再运行 `start.cmd` 或 `start.ps1`，打开 http://127.0.0.1:8765 。服务运行时保留终端窗口，Ctrl+C 停止。

1. 点击“试试付款谈判演示”，载入虚构历史约定。
2. 发送预填的现场发言“这次希望发货前把货款付清。”。
3. 右侧出现付款提醒，展开背景与原话依据。
4. 切换“向 AI 提问”，输入“为什么提醒我？”。
5. 切回“现场发言”，发送“不是改合同，仍然验收后付尾款。”，提醒更新为已澄清。

不配置模型也可完成规则演示，界面明确标记离线状态。个人微信、邮件、独立 ASR 和跨会话自动记忆尚未接入。

## 安装与运行

需要 Python 3.11+、Node.js 20.19+ 和 npm。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

如 Python 发行版无法初始化 pip，可用 `uv venv .venv` 和 `uv pip install --python .venv/Scripts/python.exe -r requirements.txt`。

Linux / macOS 可用以下命令（Windows 使用上面的命令）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
(cd frontend && npm ci && npm run build)
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

## GitHub 与自动检查

`.github/workflows/ci.yml` 包含 Python 3.12 后端测试和 Node.js 22 前端构建任务，不需要模型密钥。需要仓库启用 GitHub Actions；远端流水线状态以实际运行结果为准。

提交范围仅包括源码、依赖锁文件、测试、说明和虚构研究样例。`.env`、数据库、真实会话、依赖目录和本地构建输出不提交。当前没有配置自动部署或任何模型 CI 密钥。

## 接入真实模型

密钥只配置在本机服务端，不放入浏览器或代码。`.env.example` 供参考，程序不会自动读取 `.env`。

```powershell
$env:DECISIONFLOW_API_KEY="你的密钥"
$env:DECISIONFLOW_BASE_URL="https://api.deepseek.com"
$env:DECISIONFLOW_MODEL="deepseek-chat"
.\start.ps1
```

随后在页面开启“云端分析”。相关原话和检索资料将发送至配置的供应商。模型路径实际执行两个并行分析角色、证据复核和参与策略；尚未用真实密钥验证效果。

## 验证与状态

```powershell
New-Item -ItemType Directory -Force .test-runs | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --basetemp .test-runs/local-check
cd frontend
npm.cmd run build
```

14 项后端测试通过，模型路径使用 Mock；TypeScript 与生产构建通过；页面已验证演示、追问与澄清。详见 [实现与验证记录](docs/implementation-status.md)。

当前会话串行处理，分析期间新输入排队；模型整条回复；检索为分块 BM25 排序；资料仅当前会话可见。浏览器语音识别后编辑发送，不是独立流式 ASR。

## 代码结构

- `app/main.py`：API、WebSocket、输入和本地访问校验。
- `app/engine.py`：背景检索、规则演示、模型分析与复核、提醒控制。
- `app/rag.py`：分块、内容版本标识、BM25 排序和检索预算。
- `app/store.py`：SQLite 持久化。
- `frontend/src/`：对话、资料、提醒、轨迹及浏览器语音界面。
- `tests/`：工作流、接口和模型 Mock 测试。

## 研究目标

参考 NBBOSS 公开演示，研究持续对话、企业背景记忆、主动介入与多 Agent 协作的可复现机制。研究结论区分公开披露、视频观察、架构推断和待验证设计，不声称掌握原产品内部实现。

## 文档

- [项目简报](docs/project-brief.md)：目标、候选范围、里程碑和待确认事项。
- [证据与行为拆解](docs/evidence.md)：公开来源、视频时间点和证据限制。
- [候选算法与 Agent 架构](docs/architecture.md)：状态、调用关系、记忆和介入控制。
- [算法验证计划](docs/evaluation.md)：实验输入、标注与指标；当前没有实测成绩。
- [算法详细说明](docs/algorithm-spec.md)：介入状态机、模型职责和时序约束。
- [候选提示词契约](docs/prompt-contracts.md)：检测、路由、分析、复核、对话及记忆。
- [完整调度演练](docs/walkthrough.md)：付款提议变化、后续澄清与用户追问。
- [虚构回放样例](research/fixtures/README.md)：6 组输入和独立评估标注，尚未运行模型。

## 实现边界

研究文档描述完整候选设计，已实现范围以实现记录为准。当前仅为本地个人原型，不代表复现了原厂算法或企业级效果。

未来简历只陈述实际实现和测量过的能力。

下图为 v0.1 演示截图，v0.2 已更新名称与 RAG 引用展示。

![界面验证](docs/screenshots/conversation.jpg)
