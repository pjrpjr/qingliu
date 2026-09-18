import type { JevAccountInput } from './types';

/**
 * 把账号档案拼成 Jev 的 `state` 文本。
 *
 * 这段文本与离线评测（`jev/judge.py` 的 `build_state`）**逐字对应**。
 * 任何一边改了格式，评测里标定出来的阈值就失效 —— 改动必须同时更新评测脚本
 * 并重跑，否则线上行为会与评测结论脱钩。
 *
 * 只包含扩展在时间线上真能拿到的字段：XHR 桥给的 bio/计数，加上 DOM 给的推文正文。
 * 不喂名单成员身份、社区票数、关注关系 —— 那些要么是答案泄漏，要么滚动时拿不到。
 */

const MAX_TWEETS = 8;
const TWEET_CHARS = 160;
const BIO_CHARS = 400;
const MAX_HOSTS = 8;

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * X 的注册时间形如 `Wed Apr 10 16:56:00 +0000 2024`，归一成 `YYYY-MM`。
 * 不用 Date 解析：该格式不是 ISO，各引擎行为不一致（评测脚本里已踩过截断丢年份的坑）。
 */
export function formatCreatedAt(value?: string): string {
  if (!value) return '未知';
  const match = /([A-Z][a-z]{2}) (\d{1,2}) \d{2}:\d{2}:\d{2} [+-]\d{4} (\d{4})/.exec(value);
  if (match) {
    const month = MONTHS.indexOf(match[1] ?? '') + 1;
    if (month > 0) {
      return `${match[3]}-${String(month).padStart(2, '0')}`;
    }
  }
  return value.slice(0, 10);
}

function trim(value: string, limit: number): string {
  return value.replace(/\s+/g, ' ').trim().slice(0, limit);
}

/** 单个账号的档案块。`index` 从 1 开始，与提问里的「账号档案 #N」对应。 */
export function buildAccountBlock(account: JevAccountInput, index: number): string {
  const lines: string[] = [
    `账号档案 #${index}`,
    `handle: @${account.handle.replace(/^@+/, '')}`,
    `昵称: ${account.displayName ? trim(account.displayName, 80) : '（无）'}`,
    `简介: ${account.bio ? trim(account.bio, BIO_CHARS) : '（空）'}`,
  ];

  const counters = [
    `粉丝 ${account.followers ?? '未知'}`,
    `关注 ${account.following ?? '未知'}`,
    `推文 ${account.statuses ?? '未知'}`,
    `注册 ${formatCreatedAt(account.createdAt)}`,
    account.hasCustomAvatar === false ? '默认头像' : '自定义头像',
  ];
  if (account.verified) counters.push('蓝标');
  lines.push(counters.join(' / '));

  const hosts = (account.linkHostnames ?? []).filter(Boolean).slice(0, MAX_HOSTS);
  if (hosts.length > 0) {
    lines.push(`外链域名: ${hosts.join(', ')}`);
  }

  const tweets = (account.tweets ?? []).filter((text) => text && text.trim()).slice(0, MAX_TWEETS);
  if (tweets.length > 0) {
    lines.push('近期推文:');
    tweets.forEach((text, tweetIndex) => {
      lines.push(`  ${tweetIndex + 1}. ${trim(text, TWEET_CHARS)}`);
    });
  } else {
    lines.push('近期推文: （无）');
  }

  return lines.join('\n');
}

/**
 * 一批账号拼成一个 state。
 *
 * 扇出（多个账号塞进一次调用）是 Jev 唯一「不像 LLM」的地方：1→20 个问题
 * 延迟只涨 3–11%，单条判定成本降 9–14×。但它有**串味**风险（#3 的黄推味
 * 污染 #7 的判断），所以离线评测里有 H2 专门量这件事；batch 宽度不得超过
 * 评测验证过的宽度。
 */
export function buildAccountState(accounts: readonly JevAccountInput[]): string {
  return accounts.map((account, index) => buildAccountBlock(account, index + 1)).join('\n\n');
}
