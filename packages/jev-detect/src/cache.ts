import { contentFingerprint } from '@qingliu/detector';
import type { JevAccountInput, JevVerdict } from './types';

/**
 * 判定缓存（roadmap 里的 "AI Decision Cache"，v0.5 规划到收摊都没做）。
 *
 * 为什么必须有：X 时间线上大量账号是**重复出现**的 —— 同一个人反复刷到，
 * 同一批垃圾号反复冒头。没有缓存的话，每滚一次屏就重复问一次同样的账号，
 * 既费钱又费延迟。缓存把成本从「每次曝光」降到「每个账号一次」。
 *
 * 键里带内容指纹：账号改了简介或换了一套话术，就应该重新判 ——
 * 只按 handle 缓存会让换了皮的垃圾号一直享受旧判定。
 */

export interface JevCacheRecord {
  key: string;
  verdict: JevVerdict;
  /** 过期时刻（毫秒）。 */
  expiresAt: number;
}

export interface JevCacheOptions {
  ttlMs: number;
  maxEntries: number;
}

export const DEFAULT_JEV_CACHE_OPTIONS: JevCacheOptions = {
  // 垃圾号会换话术，但不会一天换十次；7 天足够，且能挡住绝大多数重复曝光。
  ttlMs: 7 * 24 * 60 * 60 * 1000,
  maxEntries: 2000,
};

/**
 * 短文本兜底哈希（FNV-1a 32bit，纯函数无依赖）。
 *
 * 为什么需要：`contentFingerprint` 对归一化后短于 12 字的文本**故意不产指纹**
 * （见 `packages/detector/src/fingerprint.ts` 的 MIN_FINGERPRINT_LENGTH —— 太短的
 * 话术碰撞概率不可忽略）。但缓存键需要「内容变了就换键」，否则同一账号改了短简介
 * 会一直复用旧判定。所以短文本走这个兜底哈希，只用于缓存键，不参与社区指纹比对。
 */
function shortTextHash(text: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `s${hash.toString(16).padStart(8, '0')}`;
}

/** 账号内容的稳定指纹：简介 + 近期推文。内容变了，指纹就变，缓存自然失效。 */
export function accountFingerprint(account: JevAccountInput): string {
  const text = [account.bio ?? '', ...(account.tweets ?? [])]
    .join('\n')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return 'empty';
  return contentFingerprint({ text }) ?? shortTextHash(text);
}

export function accountCacheKey(account: JevAccountInput): string {
  return `${account.handle.replace(/^@+/, '').toLowerCase()}|${accountFingerprint(account)}`;
}

export class JevDecisionCache {
  private readonly entries = new Map<string, JevCacheRecord>();
  private readonly options: JevCacheOptions;

  constructor(options: Partial<JevCacheOptions> = {}) {
    this.options = { ...DEFAULT_JEV_CACHE_OPTIONS, ...options };
  }

  get size(): number {
    return this.entries.size;
  }

  get(key: string, now: number): JevVerdict | null {
    const record = this.entries.get(key);
    if (!record) return null;
    if (record.expiresAt <= now) {
      this.entries.delete(key);
      return null;
    }
    // LRU：命中后挪到队尾（Map 保持插入顺序）
    this.entries.delete(key);
    this.entries.set(key, record);
    return record.verdict;
  }

  set(key: string, verdict: JevVerdict, now: number): void {
    this.entries.set(key, { key, verdict, expiresAt: now + this.options.ttlMs });
    this.prune(now);
  }

  /** 清掉过期项；超出容量时从最旧的开始丢。 */
  prune(now: number): void {
    for (const [key, record] of this.entries) {
      if (record.expiresAt <= now) this.entries.delete(key);
    }
    while (this.entries.size > this.options.maxEntries) {
      const oldest = this.entries.keys().next();
      if (oldest.done) break;
      this.entries.delete(oldest.value);
    }
  }

  toJSON(): JevCacheRecord[] {
    return [...this.entries.values()];
  }

  static fromJSON(records: readonly JevCacheRecord[], options: Partial<JevCacheOptions> = {}) {
    const cache = new JevDecisionCache(options);
    for (const record of records) {
      if (record && typeof record.key === 'string' && record.verdict) {
        cache.entries.set(record.key, record);
      }
    }
    return cache;
  }
}
