/**
 * Jev 识别层的输出契约。
 *
 * 上游 `@qingliu/detector` 的 `DetectionSource` 早就留了 `'ai'`，但从 v0.1 到收摊
 * 都没产出过一条判定（roadmap 里挂成 "Optional AI"）。这个包就是那一层。
 *
 * 与其它识别层的关系：**Jev 是最后一层，不是第一层**。
 * 名单命中、指纹命中、用户自己的关键词都优先；只有在前面全部 miss 且账号还没被
 * 判过（缓存未命中）时，才会走到这里。
 */

/** 送进 Jev 的账号档案 —— 字段与评测集（jev/PREREGISTRATION.md 第三节）逐字对应。 */
export interface JevAccountInput {
  handle: string;
  displayName?: string;
  bio?: string;
  /** 近期推文正文（时间线里能看到的那些）。 */
  tweets?: readonly string[];
  /** 外链 hostname（已由 Reader 解析，本包不做 URL 解析）。 */
  linkHostnames?: readonly string[];
  followers?: number;
  following?: number;
  statuses?: number;
  /** X 原始格式的注册时间字符串。 */
  createdAt?: string;
  hasCustomAvatar?: boolean;
  verified?: boolean;
}

/** 判定类别 —— 与 UI 徽章、社区上报载荷共用同一套取值。 */
export const JEV_CATEGORIES = [
  'adult_gray_traffic',
  'scam_phishing',
  'bot_spam',
  'engagement_bait',
  'legit_person',
  'legit_brand',
] as const;
export type JevCategory = (typeof JEV_CATEGORIES)[number];

/** 判定依据 —— UI 上「为什么标它」用。 */
export const JEV_EVIDENCE = [
  'bio',
  'tweet_text',
  'links',
  'handle_name',
  'behavior',
  'none',
] as const;
export type JevEvidence = (typeof JEV_EVIDENCE)[number];

/** 单个账号的判定结果。 */
export interface JevVerdict {
  handle: string;
  /** 0–1 的垃圾号概率（Jev 的 noul 输出）。 */
  spam: number;
  category: JevCategory;
  evidence: JevEvidence;
  /** 判定时刻（毫秒）。 */
  judgedAt: number;
}

/** 一次调用的元数据 —— 直接进统计页与成本核算。 */
export interface JevCallUsage {
  inputTokens: number;
  latencyMs: number;
  /** 本次调用塞了几个账号（扇出宽度）。 */
  batchSize: number;
}

export interface JevJudgment {
  verdicts: JevVerdict[];
  usage: JevCallUsage;
}

/** 阈值。默认值由离线评测（jev/RESULTS.md）标定，不靠拍脑袋。 */
export interface JevPolicyThresholds {
  /** 到这个分数才黄框标注。 */
  review: number;
  /** 到这个分数才允许进入「一键拉黑」候选（仍然必须由用户按下按钮）。 */
  blockCandidate: number;
}

/**
 * 默认阈值：由 `jev/label_audit.py` 在**修正标签后**的 37 阳 / 141 阴上选出
 * （实测见 `jev/RESULTS.md`）。定 0.70 的依据：
 *   · 0.70 → 误杀 0/141 = 0.0%，召回 21/37 = 56.8%
 *   · 0.60 → 误杀 2/141 = 1.4%，召回 64.9%
 *   · 0.50 → 误杀 7/141 = 5.0%，召回 73.0%
 * 取 0.70 是「误杀为零」的最保守档；想更激进由用户按强度档下调（见 policy.ts）。
 */
export const DEFAULT_JEV_THRESHOLDS: JevPolicyThresholds = {
  review: 0.7,
  blockCandidate: 0.9,
};
