# AI-Travel-Clip-Tool

> 模板驱动的 AI 旅游混剪工具 —— 用一条「模板成片」定义节奏与字幕，用户按槽位上传旅途素材，系统自动匹配并导出竖屏短视频，也可导出剪映草稿继续精修。

**GitHub：** [K-simple/AI-Travel-Clip-Tool](https://github.com/K-simple/AI-Travel-Clip-Tool)

## 项目在做什么

### 产品定位

本项目是一个 **「模板槽位 + AI 匹配」** 的轻量视频编辑器，面向旅游混剪场景，交互上借鉴剪映（CapCut）的四轨时间轴与轨道控制，但底层数据模型是 **模板分段槽位（Slot）**，而不是通用 NLE 的自由多轨剪辑。

**典型用户路径（业务五步法）：**

1. **导入模板视频** — 约 30 秒内完成：场景切分、AI 画面理解、批量 OCR 字幕、OpenCV 花字/动画分析。
2. **识别字幕与音频** — 剪映式双路（画面 OCR + 人声 ASR）融合，作为后续修改底稿。
3. **配对换画面** — AI 理解模板每镜画面，从素材库按语义相似度挑选片段（低于阈值不胡乱匹配）；也可手动拖拽。
4. **改字幕配特效** — 自行修改文案；特效库应用花字/动效（AI 仅推荐 preset，需手动点「应用」）。
5. **预览导出** — 导出 MP4 或剪映草稿（CapCut Mate）继续精修。

### 核心工作流

```
模板上传 → intake（切分 + AI + OCR + 花字）≈30s
    ↓
创建项目 → 素材上传 → AI 匹配 / 手动拖放
    ↓
编辑字幕与特效 → 保存 timeline → MP4 / 剪映草稿
```

### 技术架构

| 层级 | 技术 | 职责 |
|------|------|------|
| 前端 | Next.js 14 + React + Tailwind | 编辑器 UI、时间轴、预览 |
| 后端 | FastAPI + SQLite | REST API、任务队列、文件存储 |
| 视频 | ffmpeg / ffprobe | 裁切、拼接、混音、烧录字幕 |
| 视觉 | OpenCLIP + DeepSeek | 标签、景别、画面描述 |
| 语音 | faster-whisper | 字幕 ASR |
| 剪映 | CapCut Mate | 导出 PC 草稿 |

**详细模块边界、hooks 列表、字幕栈：** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

**健康检查：** `GET /health`（`PROCESSING_PRESET`、worker 上限、DeepSeek/CapCut 等能力开关）

### 硬件档位（默认 budget）

目标环境：**千元出头手机浏览器预览** + **~3000 元档 PC（4 核 / 8G / 无独显）** 本地编辑。

| 预设 | 适用 | 要点 |
|------|------|------|
| `budget`（默认） | ~3k PC + 手机预览 | Whisper small、FFmpeg 人声、OCR 懒加载、worker≤2、跳过重 AI enrich |
| `standard` | 主流办公本 | 平衡速度与质量 |
| `quality` | 高配置 / 质量优先 | 全量 AI、Demucs、medium Whisper |

```bash
# backend/.env
PROCESSING_PRESET=budget
```

前端低配（手机 / ≤4 核）自动默认 **480p 预览**、降低状态轮询频率；导出仍为全质量。

### 能力边界

| 状态 | 说明 |
|------|------|
| ✅ 已有 | 模板 intake、双路字幕、AI 匹配、槽位编辑、MP4/剪映导出、项目持久化 |
| 🟡 部分 | EDL 叠层轨、转场/调色预览、抖音 OAuth（默认隐藏 UI） |
| ❌ 未有 | 云渲染、断点续传、PostgreSQL/Redis 生产部署 |

CapCut Mate 未启动时仍可使用 MP4 导出；见 [剪映草稿导出](#剪映草稿导出)。

## 项目概览

- `frontend/` — Next.js 编辑器
- `backend/` — FastAPI 服务
- `backend/storage/` — 模板、素材、导出文件
- `backend/ai_travel_cut.db` — SQLite 元数据

### API 一览

| 模块 | 前缀 | 主要接口 |
|------|------|----------|
| 模板 | `/api/template` | `POST /upload`、`GET /{id}/status` |
| 素材 | `/api/assets` | `POST /upload`、`GET /list` |
| 字幕 | `/api/subtitle` | `POST /recognize-slot-batch` |
| 匹配 | `/api/match` | `POST /run` |
| 导出 | `/api/export` | `POST /render-async`、`POST /capcut-draft` |
| 项目 | `/api/projects` | `POST /from-template`、`PUT /{id}/timeline` |
| 健康 | `/health` | GET |

完整路由见 http://127.0.0.1:8000/docs

---

## 剪映草稿导出

通过 [CapCut Mate](https://github.com/sun-guannan/CapCutMate) 将时间轴写入剪映 PC 草稿。

| 模式 | 说明 |
|------|------|
| **成片模式** | 已匹配素材 + 模板 BGM/字幕/转场 |
| **可替换模板** | 占位片段 + 槽位标签，剪映内逐段「替换素材」 |

前置：剪映 PC 版 + CapCut Mate（默认 `http://localhost:30000`）+ `CAPCUT_MATE_BASE_URL`

---

## 目录结构（速查）

```
backend/main.py          # FastAPI 入口
backend/routers/         # HTTP 路由
backend/services/        # 模板/匹配/导出/字幕核心逻辑
frontend/app/editor/     # 编辑器页面（hooks 编排）
frontend/components/     # UI（Timeline、PreviewPanel 等）
frontend/lib/            # hooks、timeline、导出、上传
docs/ARCHITECTURE.md     # 数据流与模块边界
```

---

## 性能预设

通过 `PROCESSING_PRESET`（或 `backend/.env` 细项）控制 intake 速度：

| PRESET | 用途 |
|--------|------|
| `dev` | 最快启动，跳过 OCR 预加载与自动字幕 |
| `standard` | 默认：~30s intake + 后台增强 |
| `quality` | 关闭 fast 模式，更多 AI/代理 |

完整变量见 `backend/.env.example`。

### 字幕识别（剪映式）

| 操作 | 行为 | 39s 样片参考耗时（CPU） |
|------|------|-------------------------|
| 快速识别 | fast Whisper + fast OCR 并行，低质量槽按需 HQ | ~20–40s |
| 精识别 | 复用 Whisper 缓存 + 并行 HQ OCR 全槽升级 | ~40–90s |
| 烧录字幕 | 跳过 Whisper，仅 OCR（精识别走 HQ 并行） | ~15–45s |

有 NVIDIA GPU 时可设 `WHISPER_DEVICE=cuda`、`OCR_USE_GPU=1` 进一步加速。

---

## 测试

```bash
cd backend && python -m pytest tests/ -q
cd backend && python scripts/run_subtitle_golden_eval.py --mode check
# 真实样片 offline baseline（无需 manifest 样片，可直接指定 mp4）
cd backend && python scripts/run_subtitle_golden_eval.py --mode offline --video path/to/sample.mp4
# 或扫描已上传模板 storage/templates
cd backend && python scripts/run_subtitle_golden_eval.py --mode offline --discover
# 输出：backend/storage/golden-baseline.json
cd frontend && npx tsc --noEmit
```

---

## 环境配置

- 前端：`frontend/.env.example` → `frontend/.env.local`
- 后端：`backend/.env.example` → `backend/.env`（**勿提交 Git**）

## 启动方式

### 一键重启（Windows）

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\restart-all.ps1
```

- 后端 http://127.0.0.1:8000
- 前端 http://localhost:3000
- CapCut Mate http://127.0.0.1:30000

### 手动启动

```bash
# 后端
cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000

# 前端
cd frontend && npm install && npm run dev
```

## 许可证

本项目为私有/学习用途，使用前请确认各依赖与 API Key 的使用条款。