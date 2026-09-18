import { describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_JEV_THRESHOLDS,
  JevClient,
  JevDecisionCache,
  accountCacheKey,
  buildAccountState,
  buildQuestions,
  confidencePercent,
  estimateCostUsd,
  formatCreatedAt,
  isBlockCandidate,
  parseInputTokens,
  parseJudgment,
  verdictToDetection,
  type JevVerdict,
} from './index';

const ACCOUNT = {
  handle: 'spamexample',
  displayName: '福利站',
  bio: '会员群福利资源30000部+',
  tweets: ['完整福利在主页置顶推文'],
  linkHostnames: ['t.me'],
  followers: 2137,
  following: 0,
  statuses: 404,
  createdAt: 'Wed Apr 10 16:56:00 +0000 2024',
  hasCustomAvatar: true,
  verified: true,
};

describe('state', () => {
  it('把 X 的注册时间归一成 YYYY-MM', () => {
    expect(formatCreatedAt('Wed Apr 10 16:56:00 +0000 2024')).toBe('2024-04');
    expect(formatCreatedAt('Mon Jan 22 18:04:00 +0000 2024')).toBe('2024-01');
    expect(formatCreatedAt(undefined)).toBe('未知');
    expect(formatCreatedAt('2024-04-10T00:00:00Z')).toBe('2024-04-10');
  });

  it('拼出与离线评测逐字对应的档案块', () => {
    const state = buildAccountState([ACCOUNT]);
    expect(state).toContain('账号档案 #1');
    expect(state).toContain('handle: @spamexample');
    expect(state).toContain('昵称: 福利站');
    expect(state).toContain('简介: 会员群福利资源30000部+');
    expect(state).toContain('粉丝 2137 / 关注 0 / 推文 404 / 注册 2024-04 / 自定义头像 / 蓝标');
    expect(state).toContain('外链域名: t.me');
    expect(state).toContain('  1. 完整福利在主页置顶推文');
  });

  it('缺字段时给占位而不是空白', () => {
    const state = buildAccountState([{ handle: 'nobody' }]);
    expect(state).toContain('昵称: （无）');
    expect(state).toContain('简介: （空）');
    expect(state).toContain('近期推文: （无）');
  });

  it('多个账号带序号，且顺序与输入一致', () => {
    const state = buildAccountState([ACCOUNT, { handle: 'second' }]);
    expect(state.indexOf('账号档案 #1')).toBeLessThan(state.indexOf('账号档案 #2'));
    expect(state).toContain('handle: @second');
  });

  it('限制推文条数与长度（成本闸门）', () => {
    const state = buildAccountState([{
      handle: 'x',
      tweets: Array.from({ length: 20 }, (_, i) => `t${i} ${'字'.repeat(500)}`),
    }]);
    expect(state).toContain('  8. ');
    expect(state).not.toContain('  9. ');
    expect(state.length).toBeLessThan(3000);
  });
});

describe('questions', () => {
  it('单账号判定不加前缀（与评测 batch=1 一致）', () => {
    const questions = buildQuestions(1);
    expect(Object.keys(questions).sort()).toEqual(['category', 'evidence', 'spam']);
    expect(questions.spam?.type).toBe('noul');
    expect(questions.spam?.instructions).toContain('这个账号档案');
  });

  it('批量判定按序号加前缀，并指向对应档案', () => {
    const questions = buildQuestions(3);
    expect(Object.keys(questions)).toHaveLength(9);
    expect(questions.a2_spam?.instructions).toContain('账号档案 #2');
    expect(questions.a3_category?.type).toBe('choice');
  });
});

describe('parse', () => {
  const payload = {
    answers: {
      spam: { type: 'noul', noul: 0.87 },
      category: { type: 'choice', choice: 'adult_gray_traffic' },
      evidence: { type: 'choice', choice: 'bio' },
    },
    usage: { input_tokens: 1136 },
  };

  it('解析出判定与 token 用量', () => {
    const verdicts = parseJudgment({ payload, handles: ['a'], now: 123 });
    expect(verdicts).toEqual([{
      handle: 'a',
      spam: 0.87,
      category: 'adult_gray_traffic',
      evidence: 'bio',
      judgedAt: 123,
    }]);
    expect(parseInputTokens(payload)).toBe(1136);
  });

  it('概率越界时夹到 [0,1]', () => {
    const clamped = parseJudgment({
      payload: { answers: { spam: { noul: 1.7 } } },
      handles: ['a'],
      now: 0,
    });
    expect(clamped[0]?.spam).toBe(1);
  });

  it('缺 spam 概率的账号不产出判定（宁可重试，也不给默认分）', () => {
    const verdicts = parseJudgment({
      payload: { answers: { category: { choice: 'bot_spam' } } },
      handles: ['a'],
      now: 0,
    });
    expect(verdicts).toEqual([]);
  });

  it('未知分类按概率兜底，未知依据退回 none', () => {
    const verdicts = parseJudgment({
      payload: { answers: { spam: { noul: 0.9 }, category: { choice: 'wat' }, evidence: { choice: '?' } } },
      handles: ['a'],
      now: 0,
    });
    expect(verdicts[0]?.category).toBe('bot_spam');
    expect(verdicts[0]?.evidence).toBe('none');
  });

  it('响应形状异常时安全失败（绝不 throw）', () => {
    expect(parseJudgment({ payload: null, handles: ['a'], now: 0 })).toEqual([]);
    expect(parseJudgment({ payload: 'oops', handles: ['a'], now: 0 })).toEqual([]);
    expect(parseJudgment({ payload: { answers: 5 }, handles: ['a'], now: 0 })).toEqual([]);
    expect(parseInputTokens(null)).toBe(0);
  });
});

describe('policy', () => {
  const verdict: JevVerdict = {
    handle: '@SpamExample',
    spam: 0.8734,
    category: 'adult_gray_traffic',
    evidence: 'bio',
    judgedAt: 0,
  };

  it('低于 review 阈值不产出标注', () => {
    expect(verdictToDetection({ ...verdict, spam: 0.2 }, DEFAULT_JEV_THRESHOLDS)).toBeNull();
  });

  it('过阈值产出 ai 来源的标注，handle 归一化、分数取整', () => {
    const detection = verdictToDetection(verdict, DEFAULT_JEV_THRESHOLDS);
    expect(detection).toEqual({
      handle: 'spamexample',
      marked: true,
      source: 'ai',
      reason: 'AI 判定（87%）',
      ruleId: 'jev-adult_gray_traffic',
    });
  });

  it('只有高分才进批量候选', () => {
    expect(isBlockCandidate(verdict, DEFAULT_JEV_THRESHOLDS)).toBe(false);
    expect(isBlockCandidate({ ...verdict, spam: 0.95 }, DEFAULT_JEV_THRESHOLDS)).toBe(true);
  });

  it('置信度百分比夹在 0–100', () => {
    expect(confidencePercent(-1)).toBe(0);
    expect(confidencePercent(2)).toBe(100);
  });
});

describe('cache', () => {
  const verdict: JevVerdict = {
    handle: 'a', spam: 0.9, category: 'bot_spam', evidence: 'none', judgedAt: 0,
  };

  it('写入后能读出，过期后失效', () => {
    const cache = new JevDecisionCache({ ttlMs: 1000, maxEntries: 10 });
    cache.set('k', verdict, 0);
    expect(cache.get('k', 500)).toEqual(verdict);
    expect(cache.get('k', 1001)).toBeNull();
    expect(cache.size).toBe(0);
  });

  it('超出容量时丢最旧的', () => {
    const cache = new JevDecisionCache({ ttlMs: 10_000, maxEntries: 2 });
    cache.set('a', verdict, 0);
    cache.set('b', verdict, 1);
    cache.set('c', verdict, 2);
    expect(cache.get('a', 3)).toBeNull();
    expect(cache.get('c', 3)).toEqual(verdict);
  });

  it('内容变了就换键（换话术的垃圾号必须重判）', () => {
    const first = accountCacheKey({ handle: 'a', bio: '福利在主页' });
    const second = accountCacheKey({ handle: 'a', bio: '福利在简介' });
    const sameHandle = accountCacheKey({ handle: '@A', bio: '福利在主页' });
    expect(first).not.toBe(second);
    expect(first).toBe(sameHandle);
  });

  it('可序列化再恢复（跨会话复用）', () => {
    const cache = new JevDecisionCache({ ttlMs: 1000, maxEntries: 10 });
    cache.set('k', verdict, 0);
    const restored = JevDecisionCache.fromJSON(cache.toJSON());
    expect(restored.get('k', 10)).toEqual(verdict);
  });
});

describe('client', () => {
  const okResponse = (payload: unknown) => ({
    ok: true,
    status: 200,
    json: async () => payload,
  });

  it('成功时返回判定与用量', async () => {
    const fetchImpl = vi.fn(async () => okResponse({
      answers: { spam: { noul: 0.91 }, category: { choice: 'adult_gray_traffic' } },
      usage: { input_tokens: 1200 },
    }));
    const client = new JevClient({ apiKey: 'k', fetchImpl });
    const outcome = await client.judge([ACCOUNT], 42);
    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect(outcome.judgment.verdicts[0]?.spam).toBe(0.91);
      expect(outcome.judgment.usage.inputTokens).toBe(1200);
    }
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, { headers: Record<string, string> }];
    expect(url).toBe('https://api.typesafe.ai/v1/systemone');
    expect(init.headers.Authorization).toBe('Bearer k');
  });

  it('没有 key 时直接失败，不发请求', async () => {
    const fetchImpl = vi.fn();
    const client = new JevClient({ apiKey: '  ', fetchImpl });
    expect(await client.judge([ACCOUNT])).toEqual({ ok: false, reason: 'no-key' });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('网络异常不抛，返回 network', async () => {
    const client = new JevClient({
      apiKey: 'k',
      fetchImpl: async () => {
        throw new Error('boom');
      },
    });
    expect(await client.judge([ACCOUNT])).toEqual({ ok: false, reason: 'network' });
  });

  it('HTTP 错误如实带上状态码', async () => {
    const client = new JevClient({
      apiKey: 'k',
      fetchImpl: async () => ({ ok: false, status: 401, json: async () => ({}) }),
    });
    expect(await client.judge([ACCOUNT])).toEqual({ ok: false, reason: 'http', status: 401 });
  });

  it('超过扇出宽度时切片调用并合并用量', async () => {
    const fetchImpl = vi.fn(async () => okResponse({
      answers: {
        a1_spam: { noul: 0.9 }, a2_spam: { noul: 0.1 },
        a1_category: { choice: 'bot_spam' }, a2_category: { choice: 'legit_person' },
      },
      usage: { input_tokens: 500 },
    }));
    const client = new JevClient({ apiKey: 'k', batchSize: 2, fetchImpl });
    const outcome = await client.judge([
      { handle: 'a' }, { handle: 'b' }, { handle: 'c' }, { handle: 'd' },
    ]);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect(outcome.judgment.usage.inputTokens).toBe(1000);
      expect(outcome.judgment.usage.batchSize).toBe(2);
    }
  });

  it('成本按 $0.042/Mtok 折算', () => {
    expect(estimateCostUsd(1_000_000)).toBeCloseTo(0.042, 6);
    expect(estimateCostUsd(1136)).toBeCloseTo(0.0000477, 7);
  });
});
