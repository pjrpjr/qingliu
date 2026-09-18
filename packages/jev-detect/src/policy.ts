import type { Detection } from '@qingliu/detector';
import type { JevPolicyThresholds, JevVerdict } from './types';

/**
 * 判定 → 标注（喂给扩展的安全政策层 `classifyDetection`）。
 *
 * 三条硬规矩，都来自原版福滤娃的产品红线：
 *   1. **标注永不隐藏内容** —— 只出黄框，不动 DOM 的可见性。
 *   2. **AI 判定不直接进批量拉黑** —— 只有 `blockCandidate` 档才允许把账号
 *      预选进「一键拉黑」列表，而且仍然要用户亲手按下按钮。
 *      这是原版对关键词命中的一贯处置（`detection-policy.ts` 注释原文：
 *      「任意内置算法的单关键词启发式不直接进入用户层」）。
 *   3. **可解释** —— 每条标注都带类别、置信度与依据来源。
 */

/** 置信度取整成百分比：UI 上显示 87%，不显示 0.8734。 */
export function confidencePercent(spam: number): number {
  return Math.round(Math.min(1, Math.max(0, spam)) * 100);
}

export function verdictRuleId(verdict: JevVerdict): string {
  return `jev-${verdict.category}`;
}

/**
 * 生成标注。分数没到 `review` 阈值就返回 null（不产出任何 UI）。
 *
 * `reason` 里保留置信度百分比，本地化文案由 `apps/extension/src/lib/i18n.ts`
 * 按 ruleId 前缀 `jev-` 处理，把数字取出来拼进人话里。
 */
export function verdictToDetection(
  verdict: JevVerdict,
  thresholds: JevPolicyThresholds,
): Detection | null {
  if (!Number.isFinite(verdict.spam) || verdict.spam < thresholds.review) return null;
  return {
    handle: verdict.handle.replace(/^@+/, '').toLowerCase(),
    marked: true,
    source: 'ai',
    reason: `AI 判定（${confidencePercent(verdict.spam)}%）`,
    ruleId: verdictRuleId(verdict),
  };
}

/** 是否允许进入「一键拉黑」候选。 */
export function isBlockCandidate(verdict: JevVerdict, thresholds: JevPolicyThresholds): boolean {
  return Number.isFinite(verdict.spam) && verdict.spam >= thresholds.blockCandidate;
}

/**
 * 按页面已有的「识别强度」档位调整黄框阈值 —— 与社区名单/指纹层共用同一套档位，
 * 用户不用学第二套概念。数字全部来自 `jev/RESULTS.md` 的阈值扫描（见该文件表格）。
 */
export const JEV_REVIEW_THRESHOLD_BY_STRENGTH: Record<'refresh' | 'standard' | 'deep_clean', number> = {
  /** 清爽：几乎只标最确定的（实测召回 ~30–43%，误杀 0） */
  refresh: 0.85,
  /** 标准：默认档（实测召回 56.8%，误杀 0/141） */
  standard: 0.7,
  /** 大扫除：愿意用 5% 误杀换 73% 召回，适合已经被垃圾号淹没的时间线 */
  deep_clean: 0.5,
};

export function thresholdsForStrength(
  strength: 'refresh' | 'standard' | 'deep_clean',
  base: JevPolicyThresholds,
): JevPolicyThresholds {
  const review = JEV_REVIEW_THRESHOLD_BY_STRENGTH[strength] ?? base.review;
  // 批量候选阈值永远不低于黄框阈值；AI 也永远不自动进入批量动作。
  return { review, blockCandidate: Math.max(review, base.blockCandidate) };
}
