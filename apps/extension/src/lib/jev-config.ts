/**
 * Jev 识别层设置（本地）。
 *
 * 三件事刻意如此：
 *  1. **默认关闭**。AI 层要联网、要 key、要把页面上的文字发出去 —— 这些都必须
 *     由用户显式开启，不能靠默认值偷偷发生。
 *  2. **用户自带 key（BYO key）**。key 只进 `browser.storage.local`，不上传任何服务器；
 *     成本由用户自己的 Typesafe 账户承担，产品方不碰用户数据也不垫钱。
 *  3. **阈值离线标定**。`DEFAULT_JEV_THRESHOLDS` 来自 `jev/RESULTS.md` 的实测
 *     （FPR ≤ 2% 的最低阈值），不是拍脑袋定的。
 */
import { DEFAULT_JEV_THRESHOLDS, type JevPolicyThresholds } from '@qingliu/jev-detect';

export const JEV_SETTINGS_KEY = 'jevSettingsV1';

export interface JevSettings {
  /** 总开关；关闭时扩展行为与上游原版完全一致。 */
  enabled: boolean;
  /** Typesafe API key（只存本地）。 */
  apiKey: string;
  thresholds: JevPolicyThresholds;
}

export const DEFAULT_JEV_SETTINGS: JevSettings = {
  enabled: false,
  apiKey: '',
  thresholds: DEFAULT_JEV_THRESHOLDS,
};

function normalizeThresholds(value: unknown): JevPolicyThresholds {
  const raw = (value ?? {}) as Partial<JevPolicyThresholds>;
  const review = typeof raw.review === 'number' && raw.review >= 0 && raw.review <= 1
    ? raw.review
    : DEFAULT_JEV_THRESHOLDS.review;
  const blockCandidate =
    typeof raw.blockCandidate === 'number' && raw.blockCandidate >= 0 && raw.blockCandidate <= 1
      ? raw.blockCandidate
      : DEFAULT_JEV_THRESHOLDS.blockCandidate;
  // 批量候选阈值不得低于黄框阈值，否则会出现「没黄框却能进批量列表」的漏洞。
  return { review, blockCandidate: Math.max(review, blockCandidate) };
}

export async function getJevSettings(): Promise<JevSettings> {
  const result = await browser.storage.local.get(JEV_SETTINGS_KEY);
  const value = result[JEV_SETTINGS_KEY] as Partial<JevSettings> | undefined;
  if (!value || typeof value !== 'object') return { ...DEFAULT_JEV_SETTINGS };
  return {
    enabled: value.enabled === true,
    apiKey: typeof value.apiKey === 'string' ? value.apiKey : '',
    thresholds: normalizeThresholds(value.thresholds),
  };
}

export async function setJevSettings(patch: Partial<JevSettings>): Promise<JevSettings> {
  const current = await getJevSettings();
  const next: JevSettings = {
    enabled: patch.enabled ?? current.enabled,
    apiKey: (patch.apiKey ?? current.apiKey).trim(),
    thresholds: normalizeThresholds(patch.thresholds ?? current.thresholds),
  };
  await browser.storage.local.set({ [JEV_SETTINGS_KEY]: next });
  return next;
}

export function subscribeJevSettings(onChange: (settings: JevSettings) => void): () => void {
  const listener = (changes: Record<string, unknown>, areaName: string) => {
    if (areaName !== 'local' || !changes[JEV_SETTINGS_KEY]) return;
    const value = (changes[JEV_SETTINGS_KEY] as { newValue?: Partial<JevSettings> }).newValue;
    if (!value || typeof value !== 'object') return;
    onChange({
      enabled: value.enabled === true,
      apiKey: typeof value.apiKey === 'string' ? value.apiKey : '',
      thresholds: normalizeThresholds(value.thresholds),
    });
  };
  browser.storage.onChanged.addListener(
    listener as Parameters<typeof browser.storage.onChanged.addListener>[0],
  );
  return () =>
    browser.storage.onChanged.removeListener(
      listener as Parameters<typeof browser.storage.onChanged.removeListener>[0],
    );
}

/** 开且配了 key 才真的会调用 —— 两个条件缺一不可。 */
export function isJevActive(settings: JevSettings): boolean {
  return settings.enabled && settings.apiKey.trim().length > 0;
}
