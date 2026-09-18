import {
  JEV_CATEGORIES,
  JEV_EVIDENCE,
  type JevCategory,
  type JevEvidence,
  type JevVerdict,
} from './types';
import { questionPrefix } from './questions';

/**
 * 响应解析 —— 与上游 `packages/x-adapter/src/api/parse.ts` 同一条纪律：
 * **响应形状变化时安全失败，绝不 throw**。判不了就不标注，不能让一个字段改名
 * 把整个内容脚本搞崩。
 */

interface RawAnswer {
  noul?: unknown;
  choice?: unknown;
}

function readAnswer(answers: Record<string, unknown>, name: string): RawAnswer | null {
  const value = answers[name];
  if (!value || typeof value !== 'object') return null;
  return value as RawAnswer;
}

function readNoul(answer: RawAnswer | null): number | null {
  const value = answer?.noul;
  if (typeof value !== 'number' || Number.isNaN(value)) return null;
  return Math.min(1, Math.max(0, value));
}

function readChoice<T extends string>(
  answer: RawAnswer | null,
  allowed: readonly T[],
): T | null {
  const value = answer?.choice;
  if (typeof value !== 'string') return null;
  return (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

export interface ParseJudgmentInput {
  /** Jev 响应体（已 JSON.parse）。 */
  payload: unknown;
  /** 本次调用送进去的 handle，顺序必须与提问时的档案顺序一致。 */
  handles: readonly string[];
  /** 判定时刻（毫秒）；由调用方注入，便于测试。 */
  now: number;
}

/**
 * 把一次 Jev 响应解析成判定列表。
 *
 * 拿不到 `spam` 概率的账号**不产出判定**（调用方可以重试），
 * 而不是给个默认分 —— 默认分会污染缓存与统计。
 */
export function parseJudgment(input: ParseJudgmentInput): JevVerdict[] {
  const { payload, handles, now } = input;
  if (!payload || typeof payload !== 'object') return [];
  const answers = (payload as { answers?: unknown }).answers;
  if (!answers || typeof answers !== 'object') return [];
  const table = answers as Record<string, unknown>;
  const batchSize = handles.length;
  const verdicts: JevVerdict[] = [];

  handles.forEach((handle, index) => {
    const prefix = questionPrefix(index + 1, batchSize);
    const spam = readNoul(readAnswer(table, `${prefix}spam`));
    if (spam === null) return;

    const category =
      readChoice(readAnswer(table, `${prefix}category`), JEV_CATEGORIES) ??
      // 分类缺失时按概率兜底：高分归入通用刷屏类，低分归入正常用户。
      (spam >= 0.5 ? ('bot_spam' as JevCategory) : ('legit_person' as JevCategory));
    const evidence =
      readChoice(readAnswer(table, `${prefix}evidence`), JEV_EVIDENCE) ??
      ('none' as JevEvidence);

    verdicts.push({ handle, spam, category, evidence, judgedAt: now });
  });

  return verdicts;
}

/** 从响应里读 input_tokens（成本核算用）；缺失按 0 记，不猜。 */
export function parseInputTokens(payload: unknown): number {
  if (!payload || typeof payload !== 'object') return 0;
  const usage = (payload as { usage?: unknown }).usage;
  if (!usage || typeof usage !== 'object') return 0;
  const value = (usage as { input_tokens?: unknown }).input_tokens;
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}
