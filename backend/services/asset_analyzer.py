import os
import cv2
import numpy as np
from PIL import Image
import torch

from services.ai_label_enricher import enrich_items_with_ai_labels
from services.processing_config import SKIP_CLIP
from services.scene_detector import detect_scenes

_clip_model = None
_clip_preprocess = None
_device = None

SCENE_PROMPTS = [
    "sea beach ocean waves",
    "mountain forest nature",
    "city street urban",
    "ancient town old street",
    "night scene city lights",
    "food restaurant meal",
    "hotel room interior",
    "aerial drone view",
    "sunset sunrise sky",
    "waterfall river lake",
    "desert sand",
    "snow mountain winter",
]

SCENE_LABELS = [
    "sea", "mountain", "city", "ancient_town",
    "night", "food", "hotel", "aerial",
    "sunset", "waterfall", "desert", "snow",
]

SHOT_PROMPTS = [
    "wide shot landscape panorama",
    "medium shot person waist up",
    "close up detail macro",
    "aerial bird eye view top down",
]

SHOT_LABELS = ["wide", "medium", "close_up", "aerial"]


def _get_clip():
    global _clip_model, _clip_preprocess, _device
    if _clip_model is None:
        import clip

        _device = "cuda" if torch.cuda.is_available() else "cpu"
        print("正在加载 CLIP 模型...")
        _clip_model, _clip_preprocess = clip.load("ViT-B/32", device=_device)
        print("CLIP 模型加载完成")
    return _clip_model, _clip_preprocess, _device


def get_frame_embedding(image_path: str) -> list:
    """CLIP 图像向量，用于语义匹配。"""
    try:
        if not image_path or not os.path.exists(image_path):
            return []
        model, preprocess, device = _get_clip()
        image = preprocess(Image.open(image_path)).unsqueeze(0).to(device)
        with torch.no_grad():
            emb = model.encode_image(image)
            emb = emb / emb.norm(dim=-1, keepdim=True)
        return [float(x) for x in emb[0].cpu().tolist()]
    except Exception as e:
        print(f"CLIP embedding 失败: {e}")
        return []


def analyze_frame(image_path: str) -> dict:
    try:
        import clip

        model, preprocess, device = _get_clip()
        image = preprocess(Image.open(image_path)).unsqueeze(0).to(device)

        scene_tokens = clip.tokenize(SCENE_PROMPTS).to(device)
        with torch.no_grad():
            logits, _ = model(image, scene_tokens)
            probs = logits.softmax(dim=-1)[0]

        scene_tags = [
            SCENE_LABELS[i]
            for i in range(len(SCENE_LABELS))
            if probs[i].item() > 0.1
        ]
        if not scene_tags:
            scene_tags = [SCENE_LABELS[probs.argmax().item()]]

        shot_tokens = clip.tokenize(SHOT_PROMPTS).to(device)
        with torch.no_grad():
            logits, _ = model(image, shot_tokens)
            probs_shot = logits.softmax(dim=-1)[0]
        shot_type = SHOT_LABELS[probs_shot.argmax().item()]

        person_tokens = clip.tokenize([
            "photo with people person human",
            "landscape scenery without people",
        ]).to(device)
        with torch.no_grad():
            logits, _ = model(image, person_tokens)
            probs_person = logits.softmax(dim=-1)[0]
        has_person = probs_person[0].item() > 0.5

        return {
            "scene_tags": scene_tags,
            "shot_type": shot_type,
            "has_person": has_person,
        }

    except Exception as e:
        print(f"CLIP分析失败: {e}")
        return {
            "scene_tags": [],
            "shot_type": "wide",
            "has_person": False,
        }


def analyze_quality(video_path: str, start: float, end: float) -> float:
    try:
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)

        scores = []
        count = 0

        while cap.isOpened() and count < 5:
            ret, frame = cap.read()
            if not ret:
                break
            current_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            if current_ms > end * 1000:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            score = cv2.Laplacian(gray, cv2.CV_64F).var()
            scores.append(score)
            count += 1

        cap.release()

        if not scores:
            return 0.5

        avg = float(np.mean(scores))
        return round(min(avg / 500.0, 1.0), 3)

    except Exception as e:
        print(f"质量评分失败: {e}")
        return 0.5


def _apply_segment_defaults(segments: list, asset_id: str, video_path: str) -> list:
    for i, seg in enumerate(segments):
        if not seg.get("segment_id"):
            seg["segment_id"] = f"seg_{i + 1}"
        seg["asset_id"] = asset_id
        seg["type"] = "video"
        seg.setdefault("scene_tags", [])
        seg.setdefault("shot_type", "wide")
        seg.setdefault("has_person", False)
        seg.setdefault("quality_score", 0.5)
        seg.setdefault("file_path", video_path)
        seg.setdefault("segment_file_path", "")
        seg.setdefault("clip_start", float(seg.get("start", 0)))
    return segments


def enrich_segments(
    segments: list,
    video_path: str,
    asset_id: str,
    *,
    skip_ai_labels: bool = False,
) -> list:
    """CLIP 打标、画质评分与 DeepSeek 中文标签。"""
    for i, seg in enumerate(segments):
        if not SKIP_CLIP:
            thumb_path = seg.get("thumbnail", "")
            if thumb_path and os.path.exists(thumb_path):
                frame_info = analyze_frame(thumb_path)
                seg["scene_tags"] = frame_info["scene_tags"]
                seg["shot_type"] = frame_info["shot_type"]
                seg["has_person"] = frame_info["has_person"]
                emb = get_frame_embedding(thumb_path)
                if emb:
                    seg["clip_embedding"] = emb
                    try:
                        from services.vector_index import upsert_segment_embedding

                        upsert_segment_embedding(
                            f"{asset_id}_{seg.get('segment_id', i)}",
                            emb,
                            {"asset_id": asset_id, "start": seg.get("start"), "end": seg.get("end")},
                        )
                    except Exception:
                        pass
        seg["quality_score"] = analyze_quality(video_path, seg["start"], seg["end"])
    if skip_ai_labels:
        return segments
    return enrich_items_with_ai_labels(segments, label="素材片段")


def analyze_asset_fast(video_path: str, asset_id: str, thumb_dir: str) -> list:
    """快速镜头切分，不含物理切片与 CLIP。"""
    os.makedirs(thumb_dir, exist_ok=True)
    segments = detect_scenes(video_path, thumb_dir)
    return _apply_segment_defaults(segments, asset_id, video_path)
