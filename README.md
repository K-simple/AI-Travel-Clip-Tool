# ai-travel-cut

模板驱动的 AI 旅游混剪工具 —— 用一条「模板成片」定义节奏与字幕，用户按槽位上传旅途素材，系统自动匹配并导出竖屏短视频。

## 项目在做什么

### 产品定位

本项目是一个 **「模板槽位 + AI 匹配」** 的轻量视频编辑器，面向旅游混剪场景，交互上借鉴剪映（CapCut）的四轨时间轴与轨道控制，但底层数据模型是 **模板分段槽位（Slot）**，而不是通用 NLE 的自由多轨剪辑。

**典型用户路径：**

1. 上传一条「模板视频」（参考成片），系统镜头检测 → 切成多个槽位，并提取模板音频与字幕。
2. 创建项目，时间轴展示模板各段的时长、缩略图与默认字幕。
3. 上传用户旅途素材，拖入视频轨槽位，或一键 **AI 自动匹配**（CLIP 标签 + 景别 + 画质 + 时长加权）。
4. 在属性面板微调入点、字幕、锁定等；预览区查看当前播放头所在槽位的素材。
5. 保存项目，导出成片：画面来自用户素材拼接，音频/字幕默认来自模板。

### 核心工作流（端到端）

```
模板上传 → 场景切分 + Whisper 字幕
    ↓
创建项目（timeline = 槽位列表）
    ↓
素材上传 → CLIP 分析片段
    ↓
手动拖放 / AI 匹配 → 槽位绑定素材
    ↓
编辑字幕、入点、轨道预览控制
    ↓
保存 timeline → ffmpeg 合成导出 MP4
```

### 技术架构

| 层级 | 技术 | 职责 |
|------|------|------|
| 前端 | Next.js 14 + React + Tailwind | 编辑器 UI、时间轴、预览、API 调用 |
| 后端 | FastAPI + SQLite | REST API、任务编排、文件存储 |
| 视频 | ffmpeg / ffprobe | 抽帧、裁切、拼接、混音、烧录字幕 |
| 镜头 | PySceneDetect | 模板与素材场景切分 |
| 视觉 | OpenCLIP ViT-B/32 | 素材片段标签、景别、画质 |
| 语音 | faster-whisper | 模板/槽位字幕识别 |
| 存储 | `backend/storage/` | 模板、素材、缩略图、导出、临时文件 |

### 能力边界（当前版本）

**已具备：** 模板驱动混剪 MVP、剪映风格四轨 UI、槽位级编辑与 AI 匹配、轨道锁定/隐藏/静音/独奏（预览侧）、项目持久化、1080×1920 导出。

**尚未具备：** 自由多轨剪辑、时间轴裁切拖拽、真实波形、转场特效、封面设置、模板 BGM 预览、导出遵循轨道静音/隐藏、批量槽位字幕识别、异步导出进度等（详见下方「待完善功能」）。

## 项目概览

该仓库由前后端分离的两个部分组成：

- `frontend/` - Next.js 前端应用，用于模板上传、素材管理、编辑流程、自动匹配和导出。
- `backend/` - FastAPI 后端服务，负责文件存储、模板解析、素材分析、项目管理、AI 匹配、字幕生成和视频导出。
- `backend/storage/` - 本地文件存储目录，包含模板、素材、缩略图、导出结果和临时文件。
- `backend/ai_travel_cut.db` - SQLite 数据库存储模板、素材、项目等元数据。

### API 一览

| 模块 | 前缀 | 主要接口 | 功能摘要 |
|------|------|----------|----------|
| 模板 | `/api/template` | `POST /upload`、`GET /list`、`GET /{id}`、`GET /{id}/status`、`POST /{id}/reprocess`、`DELETE /{id}` | 上传模板视频、镜头切分、音频/字幕提取、处理进度查询与重处理 |
| 模板库 | `/api/template-library` | `GET /list`、`GET /{id}/export-ctpl`、`POST /import-ctpl` | 我的模板列表、导出/导入 `.ctpl` 模板包 |
| 素材 | `/api/assets` | `POST /upload`、`GET /list`、`GET /{id}/status`、`GET /tasks/{task_id}`、`POST /{id}/reprocess`、`DELETE /{id}` | 旅途素材上传、CLIP 分析、分段切片、进度轮询与删除 |
| 匹配 | `/api/match` | `POST /run`、`PUT /replace` | AI 自动匹配槽位、手动替换槽位素材 |
| 字幕 | `/api/subtitle` | `POST /recognize`、`POST /recognize-slot` | 整文件语音识别、按槽位时间范围识别字幕 |
| 导出 | `/api/export` | `POST /render`、`POST /render-async`、`GET /tasks/{task_id}`、`GET /codecs` | 同步/异步导出成片、编码器探测 |
| 项目 | `/api/projects` | `POST /create`、`POST /from-template`、`POST /{id}/refresh-from-template`、`GET /list`、`GET /{id}`、`PUT /{id}/timeline` | 项目 CRUD、从模板初始化、保存时间轴 |
| 任务 | `/api/tasks` | `GET /{task_id}` | 通用后台任务状态查询 |
| 认证 | `/api/auth` | `GET /status`、`POST /register`、`POST /login` | 用户注册登录（可选，MVP 占位） |
| 特效 | `/api/effects` | `GET /transitions`、`POST /preview-filter` | 转场预设目录、FFmpeg 滤镜链预览 |
| 云素材 | `/api/cloud` | `GET /list`、`POST /register`、`POST /import/{item_id}` | 云端素材目录浏览、注册与导入到本地 |
| 模板市场 | `/api/marketplace` | `GET /list`、`POST /publish`、`POST /install/{listing_id}` | 模板上架、浏览、安装到项目 |
| 发布 | `/api/publish` | `GET /douyin/status`、`GET /douyin/authorize`、`GET /douyin/callback`、`POST /douyin/upload` | 抖音 OAuth 授权与成片直推 |
| V1.1 能力 | `/api/v11` | `GET /status` | 多轨 EDL、向量检索等扩展能力开关状态 |

---

## 模块功能说明

以下按 **后端 → 前端** 列出每个文件/模块的职责，便于新人快速定位代码。

### 后端

#### `backend/main.py` — 应用入口

- 初始化 SQLite 数据库与 `storage/` 子目录（templates、assets、thumbnails、exports、temp）。
- 挂载 CORS、可选 API Key 中间件、静态文件服务 `/storage`。
- 注册全部业务路由（模板、素材、匹配、导出、项目等 14 个模块）。

#### `backend/models/database.py` — 数据模型

| 模型 | 功能 |
|------|------|
| `Template` | 模板元数据：文件名、时长、槽位 JSON、处理状态、音频路径、字幕样式等 |
| `Asset` | 素材元数据：时长、缩略图、片段列表、CLIP 标签、处理进度 |
| `Project` | 项目：名称、关联模板、timeline JSON、轨道控制、匹配策略、EDL 叠层 |
| `init_db` / `migrate_db` | 建表与轻量字段迁移 |

#### `backend/routers/` — 路由层（HTTP 接口）

| 文件 | 功能 |
|------|------|
| `template.py` | 模板上传（流式写入）、后台线程池处理、列表/详情/删除、处理状态轮询、`reprocess` 重跑切分与字幕 |
| `assets.py` | 素材上传与分析任务、片段列表、处理进度、重处理、删除（含磁盘清理） |
| `match.py` | 接收匹配权重与策略，调用 `matcher` 为各槽位选最优片段；支持手动 `replace` 替换 |
| `subtitle.py` | 整轨 Whisper 识别生成 SRT；按槽位时间从模板音频切片识别 |
| `export.py` | 校验未匹配槽位后调用 `video_exporter` 合成；支持异步导出任务与编码器列表 |
| `project.py` | 创建空项目、从模板初始化 timeline、保存/合并 timeline、刷新模板元数据、列表与加载 |
| `tasks.py` | 统一查询内存/Celery 任务进度 |
| `auth.py` | 简单用户注册/登录（可选扩展） |
| `effects.py` | 返回 100+ 转场预设；根据槽位特效参数编译 FFmpeg 滤镜预览 |
| `cloud.py` | 云素材 catalog 的列表、注册、导入到本地素材库 |
| `marketplace.py` | 模板市场上架、分类浏览、安装模板到用户库 |
| `publish.py` | 抖音开放平台 OAuth 流程与成片上传发布 |
| `template_library.py` | 导出 `.ctpl` 模板包（含 EDL/槽位）、导入还原 |
| `v11.py` | 返回 V1.1+ 扩展能力（EDL、向量库、NVENC 等）是否可用 |

#### `backend/services/` — 服务层（核心业务逻辑）

| 文件 | 功能 |
|------|------|
| `template_processor.py` | 模板处理流水线：快速入库 → 场景精修 → 音频提取 → Whisper 字幕 → 槽位缩略图修复 |
| `asset_processor.py` | 素材处理流水线：快速分段 → CLIP 分析 → 代理视频生成 → 多镜头 MP4 切片 |
| `scene_detector.py` | PySceneDetect 场景切分、ffprobe 读时长、关键帧/间隔抽帧 |
| `asset_analyzer.py` | OpenCLIP 画面标签、景别分类、画质 Laplacian 评分、片段 embedding |
| `segment_extractor.py` | 将分析片段裁成独立 MP4，供时间轴胶片条与匹配使用 |
| `matcher.py` | 槽位-片段加权打分（标签 Jaccard、景别+画质、时长容差），去重与锁定槽位跳过 |
| `match_strategy.py` | PRD 匹配策略数据类：`strict_mode`、`dedup_policy`、`prefer_4k` 等 |
| `slot_analyzer.py` | 为模板槽位补充 CLIP 标签与镜头类型，提升匹配对称性 |
| `subtitle_gen.py` | faster-whisper 懒加载、语音转写、SRT 生成 |
| `slot_subtitle.py` | 按槽位起止时间截取模板音频并识别该段字幕 |
| `audio_processor.py` | 模板音频流复制/转码、轻度滤波与限幅，降低噪点 |
| `video_exporter.py` | FFmpeg 拼接用户素材、混音模板 BGM、烧录 ASS/SRT 字幕、输出 1080×1920 MP4 |
| `proxy_generator.py` | 生成 720p 预览代理；探测 NVENC 硬件编码 |
| `processing_config.py` | 环境变量开关：`FAST_MODE`、`SKIP_CLIP`、`SKIP_SEGMENT_MP4` 等性能调优 |
| `task_queue.py` | 内存线程池异步任务：创建/更新/查询任务状态 |
| `celery_app.py` | 可选 Celery+Redis 任务队列，无 Redis 时回退内存队列 |
| `transitions.py` | 转场预设目录与 xfade 参数解析 |
| `effects_engine.py` | 将关键帧、调色、蒙版、变速编译为 FFmpeg `filter_complex` |
| `edl_exporter.py` | 从 EDL 多轨文档导出（叠层、转场、特效、字幕轨） |
| `beat_detector.py` | 按 BPM 估算节拍点，供时间轴节拍标记显示 |
| `vector_store.py` | 向量检索抽象（Milvus / PGVector / 内存回退） |
| `vector_index.py` | 轻量 JSON 向量索引，用于片段语义相似度加分 |
| `effects_stub.py` | V1.1 能力开关占位字典 |

#### `backend/utils/` — 工具层

| 文件 | 功能 |
|------|------|
| `security.py` | 可选 `API_KEY` 鉴权中间件；上传大小/类型校验；`storage/` 路径白名单防注入 |
| `timeline.py` | 保存项目时合并 timeline，保留模板侧 `slot_start`、`shot_type` 等元数据 |
| `edl_timeline.py` | 槽位 timeline ↔ EDL 文档双向转换，补全资源路径 |
| `upload_stream.py` | 异步流式保存大文件上传（跨盘符安全） |
| `storage_backend.py` | 本地存储路径解析、公开 URL 生成、字节写入 |

#### `backend/storage/` — 本地文件存储

| 目录 | 内容 |
|------|------|
| `templates/` | 原始模板视频与提取的模板音频 |
| `assets/` | 用户上传素材原片与分段 MP4 |
| `thumbnails/` | 模板/素材/槽位缩略图 |
| `exports/` | 导出的成片 MP4 |
| `temp/` | 导出与识别过程中的临时文件 |
| `cloud/` | 云素材 catalog JSON |
| `marketplace/` | 模板市场上架列表 JSON |

---

### 前端

#### `frontend/app/` — 页面

| 文件 | 功能 |
|------|------|
| `page.tsx` | 产品首页：简介 +「进入编辑器」入口 |
| `editor/page.tsx` | **主编辑器单页**：串联素材库、属性面板、预览、时间轴、工具栏；管理槽位状态、播放头、匹配、保存、导出、撤销重做、拖放、轨道控制 |
| `globals.css` | 全局暗色主题、时间轴工具按钮、滚动条、滑块样式 |
| `layout.tsx` | Next.js 根布局与元数据 |

#### `frontend/components/` — UI 组件

| 文件 | 功能 |
|------|------|
| `Toolbar.tsx` | 顶栏：导入模板/素材、保存项目、载入项目、导出成片、处理进度提示 |
| `AssetLibrary.tsx` | 左侧素材库：本地上传、分段缩略图网格、拖拽到时间轴、删除素材、处理进度 |
| `CloudLibraryPanel.tsx` | 云素材 Tab：搜索/标签筛选、浏览云端 catalog、导入到本地 |
| `MarketplacePanel.tsx` | 模板市场 Tab：分类浏览、安装模板到当前项目 |
| `PropertiesPanel.tsx` | 中间属性区：选中槽位参数（名称、时长、景别、字幕、入点、锁定、原声开关）、匹配权重滑块、匹配策略、AI 自动匹配与槽位字幕识别按钮 |
| `EffectsPanel.tsx` | 槽位特效编辑：调色、蒙版、转场、关键帧滑块（写入 timeline 特效字段） |
| `PreviewPanel.tsx` | 右侧预览：9:16 画幅、清晰度（原片/代理）、播放/暂停、逐帧步进、模板 BGM 混音、叠层预览、导出状态与下载 |
| `PublishPanel.tsx` | 导出后面板：抖音 OAuth 授权、填写标题、一键发布 |
| `Timeline.tsx` | 底部时间轴主容器：五轨布局、播放头拖拽、标尺点击、片段选中、拖放素材、缩放、磁吸、节拍标记、模板空轨提示 |
| `TemplatePanel.tsx` | 旧版模板面板（已废弃，未接入路由） |

#### `frontend/components/timeline/` — 时间轴子模块（剪映风格）

| 文件 | 功能 |
|------|------|
| `timelineTheme.ts` | 剪映配色、轨道高度、片段间距、标尺高度等设计常量 |
| `TimelineToolbar.tsx` | 时间轴工具栏：播放/暂停、撤销重做、分割、磁吸开关、时码显示、缩放滑块 |
| `TrackHeaderPanel.tsx` | 左侧轨道头：封面缩略图、轨道类型图标、锁定/隐藏/静音/独奏四键 |
| `TimelineRuler.tsx` | 顶部时间标尺：主/次刻度、点击/拖拽 seek |
| `TimelinePlayhead.tsx` | 播放头：倒三角手柄 + 贯穿全轨白线，全高可拖拽 |
| `TimelineTrackClips.tsx` | 片段 UI：`CapCutVideoClip`（全高胶片条+底部标签）、字幕块、贴纸块、音频波形块、裁切把手 |
| `ClipFilmstrip.tsx` | 视频片段胶片条：从源视频按时间抽帧、拼成无缝长图铺满片段宽度 |

#### `frontend/lib/` — 共享逻辑

| 文件 | 功能 |
|------|------|
| `api.ts` | API 基址、`apiUrl`/`toMediaUrl` 媒体地址、可选鉴权请求头 |
| `timeline.ts` | `TemplateSlot` 类型；timeline JSON ↔ 编辑器槽位状态双向转换；`applyAssetToSlot` 绑定素材 |
| `timelineLayout.ts` | 根据槽位计算片段 `left/width`、总时长、磁吸吸附、时间码格式化、伪波形数据 |
| `timelineDrop.ts` | 判断拖入的是本地视频还是素材库 ID；按播放头落点查找目标槽位 |
| `trackControls.ts` | 五轨（视频/叠层V2/V3/字幕/音频）锁定、隐藏、静音、独奏；预览混音解析 |
| `slotEdit.ts` | 槽位时间范围、字幕段落 JSON 解析、在播放头处分割槽位 |
| `slotOps.ts` | 删除槽位、重排序、波纹删除右侧、裁切入点/时长 |
| `slotEffects.ts` | 槽位特效结构与 timeline 字段互转 |
| `edlModel.ts` | 叠层轨（V2 贴纸 / V3 画中画）数据模型、布局、拖放创建 |
| `edlTimeline.ts` | EDL 文档类型、从 EDL 读取字幕轨与节拍标记 |
| `matchStrategy.ts` | 前端匹配策略默认值与 API 请求体转换 |
| `previewSettings.ts` | 预览画幅比例预设、原片/代理源解析 |
| `uploadAsset.ts` | 带进度回调的素材/模板 XHR 上传 |
| `useTemplateProcessing.ts` | 轮询模板 `processing_status` 与进度，完成后触发 timeline 刷新 |
| `useAssetProcessing.ts` | 轮询素材分析进度与分段结果 |
| `useSlotHistory.ts` | 槽位编辑撤销/重做栈（最多 40 步） |

#### 编辑器页面数据流（`editor/page.tsx`）

```
URL ?project_id= → 加载项目 timeline
工具栏上传模板 → template API → useTemplateProcessing 轮询 → refresh timeline
素材库上传     → assets API   → useAssetProcessing 轮询 → 刷新分段列表
拖放/自动匹配  → match API    → 更新槽位 matchedAssetId / file_path
属性面板编辑   → 本地 slots 状态 → PUT /projects/{id}/timeline 保存
导出           → export API   → 下载 exports/ 下 MP4
```

---

## 目录结构（速查）

### 后端

- `backend/main.py` - FastAPI 应用入口。
- `backend/routers/` - HTTP 接口（见上方「路由层」表）。
- `backend/services/` - 核心业务逻辑（见上方「服务层」表）。
- `backend/utils/` - 安全、timeline 合并、EDL 转换、上传流。
- `backend/models/database.py` - ORM 与数据库会话。

### 前端

- `frontend/app/` - Next.js 页面（首页 + 编辑器）。
- `frontend/components/` - UI 组件（见上方「UI 组件」表）。
- `frontend/components/timeline/` - 时间轴子模块（见上方表）。
- `frontend/lib/` - API、timeline、拖放、历史、上传等共享逻辑。

## 当前进度

### 已完成（MVP）

**后端**

- 模板上传：镜头切分、缩略图、后台提取音频 + Whisper 全轨字幕、槽位默认字幕挂载。
- 素材上传：时长/缩略图、镜头切分、CLIP 片段分析（标签、景别、画质）。
- 匹配：加权评分（标签 Jaccard、景别+画质、时长）、去重策略、槽位锁定、手动替换。
- 字幕：整文件识别、按槽位时间范围识别（`slot_subtitle.py`）。
- 导出：素材拼接 + 模板音频混音 + ASS/SRT 烧录，未匹配槽位校验。
- 项目：创建、从模板初始化、timeline 合并保存、列表与加载。
- 安全：可选 API Key、上传校验、存储路径白名单。

**前端**

- 编辑器单页：素材库 + 属性面板 + 9:16 预览 + 底部时间轴。
- 剪映风格四轨导轨（视频/字幕/贴纸/音频）、工具栏、标尺、播放头、片段样式。
- 轨道控制：锁定/隐藏/静音/独奏（预览与编辑限制已联动）。
- 拖放：空轨导入模板；有槽位时拖入素材库或本地视频按落点分配。
- 槽位编辑：入点、字幕、锁定、原声开关；播放头处分割；撤销/重做（40 步）。
- 匹配权重滑块、AI 自动匹配、AI 槽位字幕识别、保存/载入/导出。
- 生产构建可通过；`?project_id=` URL 自动加载项目。

### 待完善功能

**2026-06 已补齐（本轮）：**

| 功能 | 状态 |
|------|------|
| 导出遵循轨道静音/隐藏/独奏 | ✅ `export_controls` + 前端 `buildExportPayload` |
| 导出烧录字幕开关 | ✅ 预览抽屉「导出时烧录字幕」 |
| 模板槽位 CLIP 分析 | ✅ `process_template_slot_enrich` 快速入库后自动跑 |
| 项目列表/删除/重命名 | ✅ `ProjectListModal` + `PATCH/DELETE /projects/{id}` |
| 批量槽位字幕识别 | ✅ `POST /subtitle/recognize-slot-batch` |
| 详细 match_reason | ✅ 标签/景别/时长分项展示 |
| 素材详情 `GET /assets/{id}` | ✅ |
| 云素材导入本地 | ✅ `POST /cloud/import/{id}` + UI |
| 封面设置 | ✅ 轨道头点击上传 |
| 匹配去重策略 UI | ✅ `dedup_policy` 下拉 |
| 导出进度条 | ✅ 异步轮询进度 |
| 死代码清理 | ✅ 删除 `TemplatePanel`，移除无用 `onSlotDrop` |
| 快捷键文案 | ✅ 分割 S、重做 Ctrl+Shift+Z |

**仍可继续迭代：**

| 功能 | 现状 |
|------|------|
| 真·多轨自由剪辑 | 仍为槽位驱动 + EDL 叠层 |
| 真实音频波形 | ✅ 模板 BGM 轨已接 `/api/template/{id}/waveform`（需 ffmpeg） |
| 槽位拖拽排序 | ✅ 时间轴 ⋮⋮ 拖拽 + 属性面板 ↑↓ |
| 转场/调色实时预览 | ✅ FFmpeg 滤镜链预览 + 预览区 CSS 近似调色 |
| 抖音直推 | OAuth 需配置环境变量 |
| `.ctpl` 模板库 UI | ✅ 侧栏「模板库」Tab：列表 / 导入 / 导出 |


- `template.py` 与 `video_exporter.py` 中 SRT/ASS 逻辑重复。
- `recognize-slot` 结果不写回 DB，重复识别会重复跑 Whisper。
- `subtitle.py` `/recognize` 临时 SRT 可能残留在 `storage/temp/`。
- 无项目删除/重命名 API；模板处理中导出返回 409，前端无统一轮询 UX。
- Whisper 固定 `base` + CPU；大文件导出无超时与取消。

---

## PRD V1.0 差距分析（ClipTravel）

对照《ClipTravel V1.0 MVP PRD》，当前仓库（`ai-travel-cut`）处于 **「槽位驱动混剪原型」** 阶段：核心闭环可演示，距离 PRD 定义的 **「剪映级交互 + AI 导演引擎」** 仍有大量未开发项。

**图例**：✅ 已有（可用）　🟡 部分实现　❌ 未开发

### 总览对照

| PRD 模块 | 完成度 | 说明 |
|----------|--------|------|
| 双模式入口（AI 成片 / 专业剪辑） | ❌ | 仅单一 `/editor` 页，无向导式 AI 工作台 |
| 模块一：AI 智能成片工作台 | 🟡 ~25% | 有模板解析+匹配，缺向导 UI、策略面板、完整落轨 |
| 模块二：专业时间轴编辑器 | 🟡 ~15% | 有四轨 UI 壳，缺真多轨、关键帧、调色、转场等 |
| 模块三：素材与模板资产管理 | 🟡 ~10% | 本地 SQLite+磁盘，无云库/`.ctpl`/模板中心 |
| 模块四：导出与分发 | 🟡 ~20% | 单分辨率同步导出，无预设/批量/直推 |
| 后端 AI 引擎（DAG/向量/EDL） | 🟡 ~30% | PySceneDetect+CLIP+Whisper 有，缺 LLM/YOLO/向量库/标准 EDL |
| 非功能性需求（NFR） | ❌ | 无压测基线、无任务队列、无审计/加密 |
| V1.0 验收 Checklist（第九章） | ❌ ~5% | 绝大多数条目未满足 |

---

### 一、产品入口与用户路径

| PRD 要求 | 状态 | 当前实现 |
|----------|------|----------|
| 新建项目 → 选择「AI 智能成片」/「专业剪辑」 | ❌ | 直接进入编辑器 |
| AI 成片三步向导（模板→素材→辅助输入） | ❌ | 工具栏上传模板 + 侧边素材库 |
| 一键生成草稿 → 打开时间轴（工程非成片） | 🟡 | 匹配后更新槽位，非 PRD 标准 Timeline JSON |
| 生成后「90% 完成态」（转场/字幕动画/BGM 卡点已落轨） | ❌ | 仅视频槽填素材，无转场/动画/节拍轨 |

---

### 二、模块一：AI 智能成片工作台

#### 3.1.2 模板解析区

| 功能 | 状态 | 差距 |
|------|------|------|
| 拖拽/云端选取模板 | 🟡 | 本地拖拽+工具栏上传；无云端库 |
| 一键拆解 + **前端轮询进度条** | 🟡 | 后台 `processing_status`，前端无统一进度 UI |
| 槽位缩略图流 + 时长 | ✅ | 时间轴视频轨展示 |
| AI 标签（航拍·海边·远景…） | ❌ | 模板槽位 **未跑 CLIP**，标签为空 |
| 人工修正标签 / 锁定 / 删除 / 拖拽调序 | ❌ | 仅槽位锁定；无标签编辑、删槽、排序 |
| 模板另存为「我的模板库」 | ❌ | 无模板库 CRUD UI |
| `.ctpl` 模板文件格式 | ❌ | 无规范与导入导出 |

#### 3.1.3 素材上传与索引

| 功能 | 状态 | 差距 |
|------|------|------|
| 批量/文件夹拖拽 | ❌ | 单文件上传 |
| 后台静默索引（切分+打标+指纹） | 🟡 | 有切分+CLIP；**无素材指纹去重** |
| 素材墙 + 标签筛选 + 画质排序 | ❌ | 简单网格列表，Tab 占位 |
| 运动/人物/构图等完整 AssetSegment | 🟡 | 缺 `camera_motion`、`person_boxes`、`loudness` 等 |

#### 3.1.4 辅助输入区

| 功能 | 状态 |
|------|------|
| 旁白音频 / 文案 → LLM 拆句映射槽位 | ❌ |
| BGM 自动卡点 / 鸭子音 | ❌ |
| 风格预设（治愈慢调 / 卡点快调 / 电影感…） | ❌ |

#### 3.1.5 生成策略面板

| PRD 字段 | 状态 |
|----------|------|
| `strict_mode` / `allow_cross_slot` | ❌ |
| `dedup_policy` | 🟡 后端有 `global`/`none`，前端未暴露 |
| `prefer_4k` / `color_match_template` / `transition_inherit` | ❌ |
| 完整权重 `SlotSpec.hard` / `soft` | ❌ 当前为简化 tags/visual/duration 权重 |

#### 3.1.6 匹配打分（PRD 4.3 核心 IP）

| 能力 | 状态 |
|------|------|
| 硬约束守门（景别/人物/时长） | 🟡 部分在 `matcher.py` |
| CLIP 向量 `ref_keyframe_emb` 语义相似 | ❌ 模板无 embedding |
| 运动匹配 `camera_motion` | ❌ 未采集 |
| 美学分 `aesthetic_score` + 技术分 | 🟡 仅有画质 Laplacian |
| 同素材多样性惩罚 | 🟡 基础去重 |
| 向量检索 Hybrid Search + Rerank | ❌ 无 Milvus/PGVector |

---

### 三、模块二：专业时间轴编辑器（剪映对标）

#### 界面布局

| PRD 区域 | 状态 |
|----------|------|
| 顶部：预览质量 / 分享 / 云同步 | ❌ |
| 左侧：模板/字幕/音频/特效分面板 | 🟡 仅素材库，Tab 未切换 |
| 右侧：效果/调色/音频属性面板 | 🟡 仅有槽位属性，无效果链 |
| 底部：时码/帧率/代理/GPU 状态栏 | ❌ |
| 多视频轨（V3/V2/V1）+ 多字幕轨 + 多音频轨 | ❌ 四轨均为 **同一槽位镜像** |

#### 核心交互（PRD 3.2.2）

| 类别 | PRD 要求 | 状态 |
|------|----------|------|
| 时间轴 | 磁性吸附 | ✅ |
| 时间轴 | 链接/解链接、轨道高度自适应、缩放到帧级 | ❌ |
| 时间轴 | `S` 分割 | ✅ |
| 时间轴 | `A` 全选右侧、`Q/W` 波纹删除 | ❌ |
| 时间轴 | 片段边缘拖拽修剪 + 预监出入点 | ❌ 手柄纯装饰 |
| 预览 | `Space` 播放/暂停 | ✅ |
| 预览 | `J/K/L` 变速、`←/→` 帧进退 | ❌ |
| 预览 | 安全区 / 九宫格 / 8K 代理预览 | ❌ |
| 历史 | 无限级撤销/重做 | 🟡 槽位 40 步 |
| 缩放 | `Alt+滚轮` 以指针为中心 | 🟡 Ctrl+滚轮 缩放 |
| 关键帧 | 位置/缩放/旋转/透明度/音量… | ❌ |
| 变速 | 曲线变速 / 光流 / 冻结帧 | ❌ |
| 蒙版 | 矩形/圆形/画笔/羽化/关键帧 | ❌ |
| 调色 | HSL/曲线/LUT/示波器 | ❌ |
| 字幕 | 花字/气泡/逐字动画/双语/SRT 导入导出 | 🟡 仅文本框+ASR |
| 音频 | 真实波形/降噪/EQ/压缩/节拍标记/鸭子音 | ❌ 伪波形 |
| 转场 | 100+ 预设 / 自定义时长 | ❌ |
| 特效/滤镜 | 分类预览 / 参数面板 | ❌ |
| 贴纸 | 矢量/Lottie/独立轨 | ❌ |
| 代理工作流 | 自动生成/挂载/清理 | ❌ |

#### AI 草稿落轨规范（PRD 3.2.3）

| 轨道 | PRD 要求 | 状态 |
|------|----------|------|
| 视频主轨 | 已切点、对时长、**加好转场** | 🟡 仅填槽，无转场 |
| 视频 2+ | 叠加/遮罩 | ❌ |
| 字幕 1 | 按句断开 + **入出点动画** | 🟡 有分段，无动画 |
| 字幕 2 | 关键词高亮/双语 | ❌ |
| 音频 1 | 旁白降噪/压缩/鸭子音 | ❌ |
| 音频 2 | BGM 卡点标记/淡入淡出 | ❌ |
| 模板 BGM 预览播放 | — | ❌ |

---

### 四、模块三：素材与模板资产管理

| 功能 | 状态 |
|------|------|
| 云素材库（文件夹树/智能相册） | ❌ 本地 `storage/` |
| 素材指纹去重（感知哈希） | ❌ |
| 代理文件云端复用 | ❌ |
| 官方爆款模板 / 我的模板 / 团队模板 | ❌ |
| 模板市场（V2） | ❌ |
| 预签名上传 / 断点续传（Tus/Uppy） | ❌ |

---

### 五、模块四：导出与分发

| 功能 | 状态 |
|------|------|
| 多导出预设（抖音4K/小红书封面/ProRes…） | ❌ 写死 `1080x1920` |
| 批量导出（主版+封面+多标题） | ❌ |
| OAuth 直推抖音/视频号/小红书/B站 | ❌ |
| 工程归档 `.zip` | ❌ |
| 云渲染 + WebSocket 进度 | ❌ 同步 `POST /render` |
| Timeline → FFmpeg filter_complex 编译器 | 🟡 简化拼接，非通用 EDL |
| 导出遵循轨道静音/隐藏/独奏 | ❌ |
| NVENC/H.265 硬编 | ❌ 未配置 |

---

### 六、后端 AI 引擎与基础设施（PRD 第四、八章）

| PRD 规格 | 当前仓库 | 差距 |
|----------|----------|------|
| 任务流 DAG（Parse/Index/Match/Assemble） | 路由内同步+BackgroundTasks | 无 Celery/Temporal、无可视化任务 |
| WebSocket 推送「可打开编辑器」 | ❌ | |
| PostgreSQL + Redis + Milvus/PGVector | SQLite 单文件 | |
| S3/MinIO 对象存储 | 本地磁盘 | |
| SlotSpec / AssetSegment 完整模型 | 简化 JSON 字段 | |
| 标准 EDL Timeline JSON（tracks/clips/styles） | 槽位数组 `timeline` | **数据结构不兼容 PRD** |
| YOLOv8 人物检测 | ❌ | |
| Qwen-VL / LLM 结构化 Slot Spec | ❌ | |
| faster-whisper-large-v3 / SenseVoice | whisper `base` CPU | |
| CLIP-ViT-L/14 / SigLIP | ViT-B/32 懒加载 | |
| JWT 账号体系 | 可选 API Key | |
| 桌面端 Tauri/Electron | 仅 Web | |
| 自研 Canvas Timeline Engine | DOM + CSS 片段块 | |
| Zustand 全局工程状态 | React `useState` 集中在 page | |
| 监控 Prometheus/Grafana | ❌ | |

---

### 七、V1.0 验收 Checklist 自检（PRD 第九章）

| 验收项 | 状态 |
|--------|------|
| 60s 模板 90s 内出槽位，标签准确率 >85% | ❌ 无模板 CLIP 标签 |
| 5GB 素材 15min 入库 + 秒级标签筛选 | ❌ |
| 30 槽位 <5s 返回 Timeline JSON | 🟡 匹配有，非 PRD JSON |
| 打开草稿：转场+字幕分句+BGM 卡点已落轨 | ❌ |
| `Q` 波纹删除、关键帧缩放、实时预览无卡顿 | ❌ |
| 4K H.265 云渲染 <45s | ❌ |
| 一键发布抖音/小红书 | ❌ |
| 剪映快捷键全集（J/K/L、Alt+滚轮、贝塞尔关键帧…） | ❌ |
| 单测覆盖 >80%、E2E 10 条、4h 无内存泄漏 | ❌ |

---

### 八、建议开发优先级（对齐 PRD Sprint）

若按 PRD **8–10 周 V1.0** 推进，建议在现有代码基线上分阶段补齐：

| 阶段 | 目标 | 关键交付 |
|------|------|----------|
| **Phase A**（补齐闭环） | 让「AI 成片」路径可验收 | 模板槽位 CLIP 打标、PRD 策略面板、标准 Timeline JSON、模板进度轮询、项目列表 UI、槽位字幕进导出 |
| **Phase B**（编辑器可用） | 时间轴能精修 | 真裁切手柄、槽位增删排序、`Q/W` 删除、模板 BGM 预览、真实波形、异步导出+进度 |
| **Phase C**（PRD MVP 达标） | 接近 3.2.3 落轨规范 | 转场预设、字幕分句落轨+基础动画、BGM 节拍标记、`.ctpl`、向量检索匹配 |
| **Phase D**（基础设施） | 可规模化 | PostgreSQL、对象存储、任务队列、WebSocket、账号体系 |
| **V1.1+** | 剪映专业功能 | 关键帧、调色、蒙版、光流变速、代理工作流、模板市场 |

> **结论**：当前项目 ≈ PRD **Week 1 端到端 Demo 的「槽位特化版」**（W1-05~08 部分完成），约占 PRD V1.0 全量功能的 **15%–20%**。最大结构性差距是：**数据模型仍是 Slot 列表，而非 PRD 定义的多轨 EDL 工程 JSON**。

### Sprint 实施记录（2026-06-10 续）

已按 Phase A–D 落地 **MVP 级实现**（非剪映全量专业功能）：

| Phase | 交付 |
|-------|------|
| **A** | 模板槽位 CLIP 打标；`processing_progress` 轮询；PRD EDL JSON（`utils/edl_timeline.py`）；生成策略面板；槽位字幕优先导出 |
| **B** | 片段裁切手柄；槽位删除(W)/波纹清空(Q)；模板 BGM 预览；`POST /api/export/render-async` 异步导出 |
| **C** | 匹配后 `transition_out`；EDL 字幕 animation 字段；BGM `beat_markers`；`.ctpl` 导入导出；CLIP 向量加权匹配 |
| **D** | `DATABASE_URL` 可切 PostgreSQL；`storage_backend.py`；内存任务队列；`/api/auth` JWT 占位 |
| **V1.1+** | `/api/v11/status` 能力占位（关键帧/调色/蒙版/光流/代理/模板市场） |

### 专业 NLE 迭代（2026-06-10 二轮）

原「剪映级占位项」已落地 **可运行 MVP**（生产级依赖需配置环境变量）：

| 能力 | 实现 |
|------|------|
| **真·多轨 V1/V2/V3** | EDL `tracks.video[v1,v2,v3]`；时间轴独立叠层轨；`edl_exporter.py` xfade + overlay 合成 |
| **关键帧 / 调色 / 蒙版 / 光流变速** | `effects_engine.py` → FFmpeg `eq`/`scale`/`crop`/`setpts`/`minterpolate`；属性面板 `EffectsPanel` |
| **100+ 转场** | `transitions.py` + `transitions_catalog.json`，`GET /api/effects/transitions`（120 预设） |
| **云素材库 / 模板市场 / 抖音 OAuth** | `/api/cloud/*`、`/api/marketplace/*`、`/api/publish/douyin/*`；侧栏云库/市场 Tab；`PublishPanel` |
| **Celery/Redis** | `celery_app.py`（`USE_CELERY=true` + `REDIS_URL`） |
| **Milvus/PGVector** | `vector_store.py`（`VECTOR_BACKEND` + `MILVUS_URI` / `PGVECTOR_DSN`，默认 JSON 回退） |
| **4K NVENC + 代理** | 导出 `use_nvenc` + `pick_video_codec`；上传生成 `proxy_path`（720p） |

**新增 API**：`/api/effects/*`、`/api/cloud/*`、`/api/marketplace/*`、`/api/publish/*`、`/api/export/codecs`；导出默认走 **EDL 管线**（`use_edl=true`）

**环境变量（可选）**：`USE_CELERY`、`REDIS_URL`、`VECTOR_BACKEND`、`MILVUS_URI`、`PGVECTOR_DSN`、`DOUYIN_CLIENT_ID`、`DOUYIN_CLIENT_SECRET`

**新增 API（Phase A–D）**：`/api/export/render-async`、`/api/export/tasks/{id}`、`/api/template-library/*`、`/api/auth/*`、`/api/v11/status`

## 更新日志

### 2026-06-10

#### 1. 剪映风格时间轴导轨

- **`frontend/components/timeline/`** 拆分为独立子模块，统一由 `timelineTheme.ts` 管理配色（`#face15` 选中高亮、四轨图标色）与轨道高度。
- **`TimelineToolbar`**：选择、播放/暂停、撤销/重做、分割、磁吸；当前时间（黄）/ 总时长；缩放滑块（Ctrl + 滚轮亦可缩放）。
- **`TimelineRuler`**：秒级细分线 + 5 秒主刻度，点击标尺跳转播放头。
- **`TimelinePlayhead`**：标尺区白色倒三角 + 贯穿全轨竖线，可拖拽。
- **`TrackHeaderPanel`**：封面行 + 四轨头（视频绿 / 字幕 T 橙 / 贴纸星绿 / 音频蓝），每轨锁定·隐藏·静音·独奏四按钮；选中轨左侧黄条指示。
- **`TimelineTrackClips`**：
  - 视频轨：深绿标题栏 + 胶片条缩略图，选中黄框与左右裁切手柄。
  - 字幕轨：橙色渐变胶囊 + T 图标。
  - 贴纸轨：深绿底 + 缩略图/星标。
  - 音频轨：对称蓝色波形。
- 编辑器底部时间轴区域高度调整为 `300px`。

#### 2. 轨道控制（锁定 / 隐藏 / 静音 / 独奏）

- **`frontend/lib/trackControls.ts`**：四轨状态、`toggleTrackControl`、`resolvePreviewMix`（预览显隐与静音）、`describeTrackToggle`（操作提示文案）。
- **锁定**：禁止拖放素材、分割、清空槽位及对应属性编辑；时间轴显示斜纹遮罩。
- **隐藏**：时间轴显示「已隐藏」，预览不渲染该轨内容。
- **静音**：预览静音，时间轴片段变暗；视频轨与音频轨分别控制素材原声。
- **独奏**：仅显示/播放当前轨，其余轨显示「独奏模式中已隐藏」。
- 修复轨道头按钮点击无效：增大热区、阻止事件冒泡、`.track-control-btn` 规避全局 button 样式覆盖；操作后底部短暂状态提示。

#### 3. 时间轴拖放工作流

- **`frontend/lib/timelineDrop.ts`**：识别 OS 视频文件与素材库拖拽数据。
- 无槽位时：拖入本地视频 → 作为模板上传并自动分段。
- 有槽位时：拖入素材或本地视频 → 上传后按落点时间匹配槽位并赋值 `matchedAssetId`、`asset_file_path` 等。
- 视频轨锁定时拒绝拖放；拖放与分割逻辑在 `editor/page.tsx` 中统一校验。

#### 4. 槽位字幕 AI 识别

- **`backend/services/slot_subtitle.py`**：按 `slot_start` ~ `slot_end` 从模板音频切片，Whisper 转写并换算为绝对时间戳。
- **`POST /api/subtitle/recognize-slot`**：请求体 `{ template_id, slot_start, slot_end, slot_id? }`，返回 `subtitle_text` 与 `subtitle_segments`。
- 模板上传处理链：场景检测 → 提取音频 → 全模板 ASR → `attach_subtitles_to_slots()` 写入各槽位默认字幕。
- **`PropertiesPanel`**：字幕文本框 +「AI 根据人声识别字幕」按钮；字幕轨锁定时禁用编辑。

#### 5. 时间轴编辑增强

- **`frontend/lib/slotEdit.ts`**：槽位时间范围、播放头处分割。
- **`frontend/lib/useSlotHistory.ts`**：槽位变更撤销/重做（最多 40 步）。
- **`PreviewPanel`**：根据 `trackControls` 控制视频/字幕/贴纸显隐与静音，播放头跟随当前槽位。

#### 6. 槽位字幕识别 API 示例

```json
POST /api/subtitle/recognize-slot
{
  "template_id": "...",
  "slot_start": 0.0,
  "slot_end": 3.5,
  "slot_id": 1
}
```

响应示例：

```json
{
  "subtitle_text": "欢迎来到大理",
  "subtitle_segments": [
    { "start": 0.2, "end": 1.8, "text": "欢迎来到" },
    { "start": 1.8, "end": 3.4, "text": "大理" }
  ]
}
```

### 2026-06-09

#### 1. 匹配权重配置（前后端联动）

- **后端 `matcher.py`**：新增 `MatchWeights` 配置类，支持 `tags_weight`、`visual_weight`、`duration_tolerance`；按权重动态计算标签分、视觉分（景别 + 画质）、时长分；时长权重自动补齐为 `1 - tags - visual`。
- **后端 `match.py`**：新增 Pydantic 模型 `MatchWeightsConfig`；`POST /api/match/run` 接收 `weights` 并透传给匹配器；`settings`（`dedup_policy`、`prefer_quality`、`strict_duration`）已接入算法。
- **前端 `PropertiesPanel.tsx`**：新增「匹配权重设置」区域，三个 Tailwind 滑块；权重联动归一化，防止标签 + 视觉超过 100%。
- **前端 `editor/page.tsx`**：`matchWeights` 状态与自动匹配 API 绑定，点击匹配时发送最新配置。

#### 2. 全项目问题修复与工程化

**前端**

- 修复生产构建：删除错误的 `types/react` 桩类型，固定 `@types/react` 版本，修正 `tsconfig.json`。
- 修复 Timeline 数据流：新增 `lib/timeline.ts`，保存/加载/匹配时保留 `slot_start`、`shot_type`、`scene_tags`、`template_thumbnail`、`locked` 等字段。
- 修复拖拽匹配后预览失效：拖入素材时同步写入 `asset_file_path` 等路径信息。
- 修复素材预览 URL、时长显示、导出状态展示、`selectedSlot` 空值崩溃等问题。
- 安装并配置 Tailwind CSS；`next.config.mjs` 增加 API 代理；补充 `frontend/.env.example`。

**后端**

- 新增 `utils/security.py`：可选 `API_KEY` 鉴权、上传大小与视频类型校验、`storage/` 路径白名单（防止 ffmpeg 路径注入）。
- 新增 `utils/timeline.py`：保存项目时合并 timeline，避免覆盖模板元数据。
- 修复匹配、素材、导出、项目、模板、字幕等路由的错误码与边界情况。
- 素材/模板上传改为线程池执行，避免阻塞事件循环；CLIP 改为懒加载。
- 导出时校验未匹配槽位并给出明确错误；删除素材时清理磁盘文件。
- 模板新增 `list`、`status`、`delete` 接口及 `processing_status` 字段；项目新增 `name` 字段。
- 补充 `backend/.env.example`；修正 `.gitignore`；移除死代码（`SlotCard.tsx`、`axios` 依赖）。

#### 3. 匹配 API 请求示例

```json
POST /api/match/run
{
  "project_id": "...",
  "template_id": "...",
  "asset_ids": ["..."],
  "overwrite": false,
  "settings": {
    "dedup_policy": "global",
    "prefer_quality": true,
    "strict_duration": true
  },
  "weights": {
    "tags_weight": 0.35,
    "visual_weight": 0.35,
    "duration_tolerance": 2.0
  }
}
```

## 环境配置

复制示例环境文件并按需修改：

- 前端：`frontend/.env.example` → `frontend/.env.local`
- 后端：`backend/.env.example` → `backend/.env`（可选 `API_KEY` 开启鉴权）

## 启动方式

1. 前端：进入 `frontend/`，运行 `npm install`，然后 `npm run dev`
2. 后端：进入 `backend/`，运行 `pip install -r requirements.txt`，然后 `uvicorn main:app --reload`
