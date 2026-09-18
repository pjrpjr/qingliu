import type { Detection } from '@qingliu/detector';
import type { CommunityEntry, MarkStrength } from '@qingliu/community-lists';

/**
 * 扩展端的安全政策层。Detector 保留纯逻辑和规则单测，
 * 但「规则能跑」不等于「足以在用户页面上定罪」。
 */

export type DetectionPresentation = 'block-candidate' | 'review' | 'ignore';

export interface DetectionPolicyInput {
  detection: Detection;
  strength: MarkStrength;
  communityEntry?: CommunityEntry | null;
}

/**
 * 服务器最终账号名单可进入页面「全部拉黑」。
 * 指纹/域名是间接证据，即使在大扫除档黄框提示，也不预选批量动作。
 * 任意内置算法的单关键词启发式不直接进入用户层；用户自己的关键词和
 * 可逐条关闭的官方词库例外，它们只作为人工确认提示，永远不进批量拉黑。
 */
export function classifyDetection(input: DetectionPolicyInput): DetectionPresentation {
  const { detection, communityEntry } = input;
  if (detection.source === 'blocked') return 'review';
  if (detection.source === 'community-list') {
    // 快照只包含服务端已经判定的最终名单；扩展不得再偷偷发明第二套门槛。
    return communityEntry ? 'block-candidate' : 'review';
  }
  if (detection.source === 'builtin-list') {
    return 'block-candidate';
  }
  if (detection.source === 'fingerprint' || detection.source === 'domain') {
    return input.strength === 'deep_clean' ? 'review' : 'ignore';
  }
  if (detection.source === 'ai') {
    // Jev 判定是**语义证据**，不是社区共识：给黄框（人工确认），
    // 但绝不自动进入批量动作 —— 与原版对关键词命中的处置同一档。
    // 理由：模型判错时用户失去的是刷推体验；一旦自动拉黑，用户失去的
    // 可能是一段真实关系。两者代价不对称，所以 AI 永远只做提示。
    return 'review';
  }
  if (detection.source === 'heuristic' && detection.ruleId?.startsWith('keyword:')) {
    return 'review';
  }
  return 'ignore';
}
