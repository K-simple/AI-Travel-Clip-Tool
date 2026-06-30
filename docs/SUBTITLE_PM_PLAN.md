# 字幕识别 PM 方案（实施跟踪）

## 核心判断

字幕问题 = **产品承诺** + **性能预算** + **技术链路** + **用户反馈** 叠加。

## 验收标准（黄金集）

| 模板类型 | 成功标准 | 失败可接受 |
|----------|----------|------------|
| 烧录字幕旅游片 | 槽位一致率 ≥90% | 否 |
| 纯口播 | ASR 字准率 ≥85% | 可人工改 |
| BGM 重/人声弱 | 空槽 + 提示手填 | 是 |

评测集：`docs/subtitle-golden-set/` · 脚本：`backend/scripts/run_subtitle_golden_eval.py`

## 产品分档

| 模式 | 用户感知 | 技术 |
|------|----------|------|
| **快速**（默认） | 大部分槽位有字 + 来源/质量可见 | `SUBTITLE_RECOGNITION_MODE=fast` |
| **精识别**（显式按钮） | 1～3 分钟，更准确 | API `quality=true` |

## 实施状态

- [x] 黄金集目录 + 评分脚本骨架
- [x] `SUBTITLE_RECOGNITION_MODE` 环境开关
- [x] 槽位级 `subtitle_source` / `subtitle_quality` / `subtitle_status_reason`
- [x] `GET /api/subtitle/status/{template_id}`
- [x] 前端来源/质量展示 + 状态栏进度
- [x] 统一「识别字幕」+「精识别」按钮
- [x] 槽位边界对齐：`resolveSegmentTimelineRange` 源/相对/时间轴坐标
- [x] UI 标红重复/空槽（时间轴红/橙描边 + 属性面板警告）
- [x] Golden set 评测脚本（check / offline / api 三模式 + 指标单测）
- [x] Intake OCR 与精识别解耦（intake 固定 fast OCR + 预算跳过 enrich）
- [x] 前端批量刷新后重算跨槽重复

## 环境变量

```env
SUBTITLE_RECOGNITION_MODE=fast   # fast | quality（后台自动字幕批次默认档位）
AUTO_SUBTITLE_AFTER_INTAKE=1     # intake 完成后排队字幕融合
```
