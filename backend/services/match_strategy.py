"""PRD 生成策略配置。"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MatchStrategy:
    strict_mode: bool = True
    allow_cross_slot: bool = False
    dedup_policy: str = "global"
    prefer_4k: bool = True
    color_match_template: bool = True
    transition_inherit: bool = True
    use_vector_match: bool = True
    vector_weight: float = 0.25

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MatchStrategy":
        if not data:
            return cls()
        return cls(
            strict_mode=bool(data.get("strict_mode", True)),
            allow_cross_slot=bool(data.get("allow_cross_slot", False)),
            dedup_policy=str(data.get("dedup_policy", "global")),
            prefer_4k=bool(data.get("prefer_4k", True)),
            color_match_template=bool(data.get("color_match_template", True)),
            transition_inherit=bool(data.get("transition_inherit", True)),
            use_vector_match=bool(data.get("use_vector_match", True)),
            vector_weight=float(data.get("vector_weight", 0.25)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strict_mode": self.strict_mode,
            "allow_cross_slot": self.allow_cross_slot,
            "dedup_policy": self.dedup_policy,
            "prefer_4k": self.prefer_4k,
            "color_match_template": self.color_match_template,
            "transition_inherit": self.transition_inherit,
            "use_vector_match": self.use_vector_match,
            "vector_weight": self.vector_weight,
        }

    def merge_settings(self, settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        base = {
            "strict_duration": self.strict_mode,
            "prefer_quality": self.prefer_4k,
            "dedup_policy": self.dedup_policy,
            "transition_inherit": self.transition_inherit,
            "use_vector_match": self.use_vector_match,
            "vector_weight": self.vector_weight,
        }
        if settings:
            base.update(settings)
        return base
