# 数据流与模块边界

## 业务五步 → 代码入口

| 步骤 | 用户动作 | 后端入口 | 写入字段 |
|------|----------|----------|----------|
| 1 导入模板 | 上传 MP4 | `template_processor.process_template_edit_ready` → `template_intake` | `Template.slots[]`：切分、OCR、AI 描述、花字 |
| 1b 自动字幕 | intake 后后台 | `template_subtitle_auto.queue_auto_subtitle_batch` | 槽位 `subtitle_text` / `subtitle_segments`（OCR+ASR 融合） |
| 2 创建项目 | 从模板建项目 | `POST /api/projects/from-template` | `Project.timeline` |
| 3 智能匹配 | 点击 AI 匹配 | `POST /api/match/run` → `smart_matcher` + `matcher` | 槽位 `asset_id`、`match_score`、`match_reason` |
| 4 字幕/特效 | 批量识别 / 特效库 | `POST /api/subtitle/recognize-slot-batch`、`effects_catalog` | 槽位字幕与 preset 推荐 |
| 5 导出 | MP4 / 剪映 | `export.py` → `video_exporter` / `capcut_draft_exporter` | 文件 / 草稿 |

## 字幕栈（唯一出口：槽位 JSON）

```
template_intake._batch_ocr          → 导入时烧录字幕快路径
template_subtitle_auto              → intake 后 ASR+OCR 融合（AUTO_SUBTITLE_AFTER_INTAKE）
subtitle_pipeline.recognize_all_*   → 用户手动批量/单槽识别
subtitle_scene_ai                   → 花字/画面对齐（persist 时 enrich）
subtitle_render                     → ASS/SRT 生成、模板字幕 fallback、MP4 烧录
media_probe                         → ffprobe/ffmpeg 音频探测与 Whisper 抽轨
```

## 前端 hooks（编辑器）

| Hook | 职责 |
|------|------|
| `useTemplateProcessing` | 模板 intake / 增强 / 自动字幕批次轮询 |
| `useTemplateFlow` | 模板上传、市场安装、模板库切换 |
| `useAssetList` | 素材列表加载与 API 映射 |
| `useAssetUpload` | 素材上传（并发 3） |
| `useAssetProcessing` | 素材分析进度轮询 |
| `useMatchFlow` | AI 智能匹配 |
| `useSubtitleFlow` | 批量字幕识别 |
| `useProjectPersistence` | 加载 / 保存 / 自动保存 / 从模板建项目 |
| `useExportFlow` | MP4 + 剪映草稿导出 |
| `useEditorPlayback` | 播放头、播放/暂停、逐帧步进 |
| `useTimelineScrub` | 时间轴 scrub、磁吸、播放头拖拽 |
| `useTimelineTrackResize` | 轨道高度拖拽 |
| `useTimelineWaveform` | 模板 BGM 波形数据 |

## 前端组件拆分

| 组件 / 模块 | 说明 |
|-------------|------|
| `editor/page.tsx` | 编排层：组合 hooks + 布局 |
| `PreviewPanel.tsx` + `PreviewExportDrawer.tsx` | 预览与导出侧栏 |
| `previewPanelUi.tsx` | 预览 transport 图标、时码、菜单 |
| `Timeline.tsx` + `components/timeline/*` | 五轨时间轴 |

## 已移除 / 默认隐藏

- `/api/v11/*` → 合并为 `GET /health` 能力探测
- `PUT /api/match/replace` → 前端拖拽改 timeline，已删 API
- 抖音发布 / 云库 / 市场 → 默认隐藏 UI（`NEXT_PUBLIC_ENABLE_*=1` 开启）
- `effects_stub.py`、`cloud_seed.json`、`vector_store.py` → 已删

## 环境预设

| PRESET | 用途 |
|--------|------|
| `dev` | 最快启动，跳过 OCR 预加载与自动字幕 |
| `standard` | 默认：~30s intake + 后台增强 + 自动字幕融合 |
| `quality` | 关闭 fast 模式，同步更多 AI/代理 |

CapCut Mate **不在本仓库**，未启动时仅 MP4 导出可用；见 `.env.example` 中 `CAPCUT_MATE_BASE_URL`。

## 测试

```bash
cd backend && python -m pytest tests/ -q
cd frontend && npx tsc --noEmit
```

后端：`test_matcher`、`test_processing_config`、`test_subtitle_render`、`test_health`（12+ 用例）。
