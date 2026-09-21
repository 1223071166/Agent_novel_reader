# AgentReader

AgentReader 是一个面向中文小说的本地 AI 阅读助手。它可以导入 TXT 小说、按章节建立向量索引，并通过大模型完成剧情问答、章节检索、分层总结和防剧透阅读。

## 主要功能

- 导入并管理多本 TXT 小说
- 为每本书独立拆章、建立向量索引和保存阅读状态
- 基于语义检索与关键词检索等多种工具回答小说内容问题
- 管理多轮对话并流式显示回复
- 生成章节、分段和全书总结
- 按已读章节限制检索范围，避免剧透
- 支持硅基流动以及自定义 OpenAI 兼容接口
- 可选显示模型 Token 用量

## 运行环境

当前验证过的开发环境：

- Windows 10/11
- Python 3.13
- Node.js 24 和 npm 11

前端使用 Vite 7，因此 Node.js 至少需要 `20.19`，或者使用 `22.12` 及以上版本。首次建立向量索引时需要联网下载嵌入和重排模型，并占用一定磁盘空间。

## 安装

在项目根目录执行以下命令。

### 1. 创建 Python 虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果 PowerShell 不允许执行激活脚本，也可以不激活环境，后续直接使用 `.\.venv\Scripts\python.exe`。

### 2. 安装前端依赖

```powershell
npm --prefix frontend ci
```

前端的精确依赖版本由 `frontend/package-lock.json` 管理，不需要在 README 中手动同步版本号。

## 启动

先激活 Python 虚拟环境，然后运行：

```powershell
.\run.bat
```

默认地址：

- 前端：http://localhost:5173
- 后端：http://127.0.0.1:8000
- 健康检查：http://127.0.0.1:8000/api/health

也可以分别启动前后端，便于查看日志：

```powershell
# 终端 1：后端
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload

# 终端 2：前端
npm --prefix frontend run dev
```

后端目前只允许来自 `http://localhost:5173` 的浏览器请求，因此启动前请确保 5173 端口可用。

## 配置模型

启动应用后，在左下角打开“设置”：

1. 选择“硅基流动”并填写 API Key；
2. 或者选择“自定义”，填写 OpenAI 兼容接口的 Base URL、模型名称和 API Key。

模型凭据保存在本机的 `data/model_credentials.json`

默认配置包括：

- 对话模型：`deepseek-ai/DeepSeek-V4-Flash`（硅基流动）
- 嵌入模型：`BAAI/bge-base-zh-v1.5`
- 重排模型：`BAAI/bge-reranker-v2-m3`

## 导入和使用书籍

1. 点击“导入书籍”，选择 TXT 小说。
2. 确认书名和书籍信息。
3. 启动向量索引构建并等待完成。
4. 从“当前书籍”切换目标小说，然后创建对话。

索引任务在后台运行。首次运行通常较慢，因为需要下载并初始化模型。不同书籍的章节、向量索引、总结和阅读进度彼此独立。

## 测试与构建

运行后端测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

运行前端测试：

```powershell
npm --prefix frontend test
```

检查前端生产构建：

```powershell
npm --prefix frontend run build
```

## 项目结构

```text
backend/             FastAPI 接口
frontend/            React + TypeScript 前端
services/            对话、导入、设置、总结等业务逻辑
scripts/             拆章、检索评估和辅助脚本
tests/               Python 单元测试
data/                本地书籍、索引、会话和设置数据
config.py            路径、模型和检索参数
embedding.py         向量构建与混合检索
novel_tools.py       提供给对话模型的小说工具
summaries.py         分层总结逻辑
```

## 本地数据说明

以下内容只保存在本机，不应提交到 Git：

- 导入的小说原文和章节
- 向量数据库
- 对话数据库
- 模型 API Key
- 当前书籍、阅读进度和应用设置

如果需要备份个人数据，请完整备份 `data/` 目录。不要把含有 API Key 的 `data/model_credentials.json` 分享给他人。

