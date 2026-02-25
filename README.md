# vdb_centor

面向业务系统的向量知识库服务，提供文档入库、QA 维护、混合检索（Vector + BM25）和任务状态追踪能力，可作为 RAG 场景的数据底座。

## 项目介绍

`vdb_centor` 是一个基于 `FastAPI + PostgreSQL(pgvector)` 的知识库中台服务，聚焦两类常见场景：

1. 文档知识入库与检索：支持将 `PDF`、`DOCX` 文档切分后入库，并通过向量检索与 BM25 检索联合召回。
2. FAQ/问答知识维护：支持通过 `XLSX/XLSM` 批量导入 QA，或通过 API 单条新增、更新、删除。

服务按 `project_id` 做项目隔离，适合集成到多租户业务系统中，作为统一的知识管理与检索后端。

## 核心能力

- 异步入库任务：上传后后台执行入库，支持任务状态查询（`ingesting/succeeded/failed`）。
- 多格式文件解析：支持 `PDF`、`DOCX`、`XLSX`、`XLSM`。
- QA 专用知识库：每个项目最多一个 QA 库，支持增删改查和去重（按原始文本）。
- 混合检索：同时返回 `dense`、`bm25` 和去重后的 `merged_results`。
- 软删除机制：支持 KB 与 QA 条目软删除，便于审计和恢复策略扩展。

## 技术栈

- Python 3.11+
- FastAPI + Pydantic
- SQLAlchemy Async + `asyncpg`/`psycopg`
- PostgreSQL + pgvector + `tsvector`(BM25)
- `jieba` 中文分词
- DashScope Embedding API

## 快速开始（本地开发）

### 1) 安装依赖

```bash
uv sync --dev
```

### 2) 启动 pgvector

```bash
docker compose up -d pgvector
```

默认连接端口为 `localhost:45132`（见 `docker-compose.yaml` 注释）。

### 3) 配置环境变量

在项目根目录创建 `.env`，至少包含以下配置：

```dotenv
DEBUG_MODE=true
BIZ_DB_CONNECTION=postgresql+psycopg://pgvector:pgvector@localhost:45132/vdb_centor
VEC_DB_CONNECTION=postgresql+asyncpg://pgvector:pgvector@localhost:45132/vdb_centor
DASHSCOPE_API_KEY=your_api_key
```

可通过以下命令检查配置是否加载成功：

```bash
uv run python -m src.conf.env
```

### 4) 启动 API 服务

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
```

启动后访问：

- Swagger: `http://127.0.0.1:8001/docs`
- OpenAPI: `http://127.0.0.1:8001/openapi.json`

## 主要 API 一览

- `POST /kb/upload`：上传文件并创建/追加入库任务。
- `GET /kb/list`：获取项目下 KB 列表。
- `GET /kb/task/{kb_id}`：查询入库任务状态。
- `POST /kb/delete`：删除指定 KB（软删除，带限制条件）。
- `POST /kb/retrieve/hybrid`：混合检索。
- `POST /kb/qa/item`：新增单条 QA。
- `POST /kb/qa/item/update`：更新单条 QA。
- `POST /kb/qa/item/delete`：删除单条 QA。
- `POST /kb/qa/items/delete`：批量删除 QA。
- `GET /kb/qa/list`：分页查询 QA 列表。

## 项目结构

```text
src/
  conf/      # 环境加载与配置
  db/        # 数据库连接、模型、数据访问
  model/     # API 请求/响应模型
  router/    # FastAPI 路由
  service/   # 核心业务流程（入库/检索/QA）
  utils/     # 文件解析、向量接口等工具
scripts/     # 部署与本地辅助脚本
```

## 测试与自检

```bash
uv run pytest
uv run python -m src.conf.env
uv run python -m src.service.kb_service
```

## 镜像发布与部署

### Push 到 GitHub

```bash
git add .
git commit -m "chore: init project docs"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

### 自动构建多架构镜像

工作流：`.github/workflows/docker-image.yml`

触发条件：

- push 到 `main`
- push tag（例如 `v1.0.0`）
- 手动触发 `workflow_dispatch`

发布位置：`ghcr.io/<owner>/<repo>`

构建平台：

- `linux/amd64`
- `linux/arm64`

### 服务器部署（使用预构建镜像）

```bash
cp .env.server.example .env
```

至少修改以下变量：

- `API_IMAGE`
- `DASHSCOPE_API_KEY`

如果 GHCR 为私有仓库，先登录：

```bash
echo <GH_TOKEN> | docker login ghcr.io -u <github_username> --password-stdin
```

启动与运维命令：

```bash
./scripts/deploy_server.sh up
./scripts/deploy_server.sh status
./scripts/deploy_server.sh logs
./scripts/deploy_server.sh pull
./scripts/deploy_server.sh restart
./scripts/deploy_server.sh down
```
