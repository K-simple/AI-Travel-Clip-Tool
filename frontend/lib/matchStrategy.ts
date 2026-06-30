export type MatchStrategy = {
  strict_mode: boolean;
  allow_cross_slot: boolean;
  dedup_policy: 'global' | 'none';
  prefer_4k: boolean;
  color_match_template: boolean;
  transition_inherit: boolean;
  use_vector_match: boolean;
  vector_weight: number;
  semantic_weight: number;
  min_match_score: number;
};

export const DEFAULT_MATCH_STRATEGY: MatchStrategy = {
  strict_mode: true,
  allow_cross_slot: false,
  dedup_policy: 'global',
  prefer_4k: true,
  color_match_template: true,
  transition_inherit: true,
  use_vector_match: true,
  vector_weight: 0.25,
  semantic_weight: 0.4,
  min_match_score: 0.38,
};

export function strategyToSettings(strategy: MatchStrategy) {
  return {
    strict_duration: strategy.strict_mode,
    prefer_quality: strategy.prefer_4k,
    dedup_policy: strategy.dedup_policy,
    transition_inherit: strategy.transition_inherit,
    use_vector_match: strategy.use_vector_match,
    vector_weight: strategy.vector_weight,
    semantic_weight: strategy.semantic_weight,
    min_match_score: strategy.min_match_score,
  };
}
