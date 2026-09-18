import { buildQuestions } from './questions';
import { buildAccountState } from './state';
import { parseInputTokens, parseJudgment } from './parse';
import type { JevAccountInput, JevJudgment, JevVerdict } from './types';

/**
 * Jev API 客户端。
 *
 * 为什么调用必须发生在**背景页/Service Worker**、而不是内容脚本：
 * 内容脚本的 fetch 受页面 CORS 约束，x.com 不会放行对 api.typesafe.ai 的跨域请求；
 * 背景页带 host_permissions 才能直接发。
 *
 * 与 jev 套利项目实测一致的接口事实：
 *   POST https://api.typesafe.ai/v1/systemone
 *   Authorization: Bearer <key>   model: jev-latest
 *   → { answers: { <name>: { type, noul|choice|score } }, usage: { input_tokens } }
 *   单价 $0.042 / Mtok 输入，输出免费
 */

export const JEV_ENDPOINT = 'https://api.typesafe.ai/v1/systemone';
export const JEV_MODEL = 'jev-latest';
/** 输入 token 单价（美元），用于成本核算。 */
export const JEV_PRICE_PER_MTOK = 0.042;

/** 一次调用的扇出宽度。离线评测的 H2 专门量过「加宽会不会串味」。 */
export const DEFAULT_JEV_BATCH_SIZE = 10;

export interface JevFetchResponse {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}

export type JevFetch = (
  url: string,
  init: {
    method: string;
    headers: Record<string, string>;
    body: string;
    signal?: AbortSignal;
  },
) => Promise<JevFetchResponse>;

export interface JevClientOptions {
  apiKey: string;
  endpoint?: string;
  model?: string;
  timeoutMs?: number;
  batchSize?: number;
  /** 注入 fetch 便于单测；浏览器里用全局 fetch。 */
  fetchImpl?: JevFetch;
}

export type JevFailureReason = 'no-key' | 'network' | 'http' | 'parse' | 'empty';

export type JevJudgeOutcome =
  | { ok: true; judgment: JevJudgment }
  | { ok: false; reason: JevFailureReason; status?: number };

function defaultFetch(): JevFetch {
  return (url, init) => fetch(url, init) as unknown as Promise<JevFetchResponse>;
}

export class JevClient {
  private readonly options: Required<Omit<JevClientOptions, 'fetchImpl'>> & {
    fetchImpl: JevFetch;
  };

  constructor(options: JevClientOptions) {
    this.options = {
      apiKey: options.apiKey,
      endpoint: options.endpoint ?? JEV_ENDPOINT,
      model: options.model ?? JEV_MODEL,
      timeoutMs: options.timeoutMs ?? 8000,
      batchSize: options.batchSize ?? DEFAULT_JEV_BATCH_SIZE,
      fetchImpl: options.fetchImpl ?? defaultFetch(),
    };
  }

  /**
   * 判一批账号。账号数超过扇出宽度时自动切片，逐片调用后合并结果。
   *
   * 任何失败都返回 `{ ok: false }`，**不抛异常** —— 识别层挂掉时扩展应该照常
   * 用名单/词库/指纹工作，绝不能让 AI 层的故障影响基本功能。
   */
  async judge(accounts: readonly JevAccountInput[], now = Date.now()): Promise<JevJudgeOutcome> {
    if (!this.options.apiKey.trim()) return { ok: false, reason: 'no-key' };
    if (accounts.length === 0) return { ok: false, reason: 'empty' };

    const verdicts: JevVerdict[] = [];
    let inputTokens = 0;
    let latencyMs = 0;
    let batchSizeUsed = 0;

    for (let offset = 0; offset < accounts.length; offset += this.options.batchSize) {
      const slice = accounts.slice(offset, offset + this.options.batchSize);
      const outcome = await this.judgeSlice(slice, now);
      if (!outcome.ok) return outcome;
      verdicts.push(...outcome.verdicts);
      inputTokens += outcome.inputTokens;
      latencyMs += outcome.latencyMs;
      batchSizeUsed = Math.max(batchSizeUsed, slice.length);
    }

    return {
      ok: true,
      judgment: {
        verdicts,
        usage: {
          inputTokens,
          latencyMs,
          batchSize: batchSizeUsed,
        },
      },
    };
  }

  private async judgeSlice(
    accounts: readonly JevAccountInput[],
    now: number,
  ): Promise<
    | { ok: true; verdicts: JevVerdict[]; inputTokens: number; latencyMs: number }
    | { ok: false; reason: JevFailureReason; status?: number }
  > {
    const state = buildAccountState(accounts);
    const questions = buildQuestions(accounts.length);
    const body = JSON.stringify({ state, model: this.options.model, questions });

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.options.timeoutMs);
    const startedAt = Date.now();
    let response: JevFetchResponse;
    try {
      response = await this.options.fetchImpl(this.options.endpoint, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${this.options.apiKey}`,
          'Content-Type': 'application/json',
        },
        body,
        signal: controller.signal,
      });
    } catch {
      return { ok: false, reason: 'network' };
    } finally {
      clearTimeout(timer);
    }
    const latencyMs = Date.now() - startedAt;

    if (!response.ok) {
      return {
        ok: false,
        reason: response.status === 429 ? 'network' : 'http',
        status: response.status,
      };
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return { ok: false, reason: 'parse' };
    }

    const handles = accounts.map((account) => account.handle);
    const verdicts = parseJudgment({ payload, handles, now });
    if (verdicts.length === 0) return { ok: false, reason: 'parse' };

    return { ok: true, verdicts, inputTokens: parseInputTokens(payload), latencyMs };
  }
}

/** 单账号判定的成本（美元）—— 统计页显示用。 */
export function estimateCostUsd(inputTokens: number): number {
  return (inputTokens / 1_000_000) * JEV_PRICE_PER_MTOK;
}
