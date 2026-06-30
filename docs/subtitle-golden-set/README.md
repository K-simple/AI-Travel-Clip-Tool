# 字幕黄金评测集

用于每周自动化跑分，避免凭感觉调 fusion 阈值。

## 目录结构

```
subtitle-golden-set/
  README.md
  manifest.example.json    # 复制为 manifest.json 并填写
  samples/                 # 可选：放短样片 mp4（勿提交大文件到 Git）
  expected/                # 与 manifest 中 expected_file 对应
```

## manifest.json 格式

见 `manifest.example.json`。每条用例包含：

- `id`：用例 ID
- `category`：`burned_in` | `voiceover` | `weak_audio`
- `template_video`：相对路径或绝对路径（本地评测用）
- `expected_file`：期望槽位字幕 JSON
- `slot_ranges`：可选，槽位 `[{start, end}, ...]`

## 跑分

```bash
cd backend
# 结构检查（无需样片）
python scripts/run_subtitle_golden_eval.py --mode check

# 本地跑分（需 manifest 中 mp4 + expected）
python scripts/run_subtitle_golden_eval.py --mode offline --json-out storage/golden-report.json

# HTTP 跑分（需 backend :8000 已启动）
python scripts/run_subtitle_golden_eval.py --mode api --api-base http://127.0.0.1:8000
```

指标：槽位非空率、重复率、来源分布、槽位匹配率、可选 CER（`pip install jiwer`）。
