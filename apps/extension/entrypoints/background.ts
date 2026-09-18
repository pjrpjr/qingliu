import { syncCommunitySnapshot } from '@qingliu/community-lists';
import { JevClient, type JevAccountInput } from '@qingliu/jev-detect';
import { COMMUNITY_SYNC_SOURCES, snapshotStore } from '../src/lib/community-store';
import { flushContributions } from '../src/lib/contribute';
import { getJevSettings, isJevActive } from '../src/lib/jev-config';
import { syncKeywordPackCatalog } from '../src/lib/keyword-packs';

export default defineBackground(() => {
  // MV3 service worker 随时可能被回收：这里只做事件入口。
  // 名单/词库同步不做定时 alarm：数据只在 X 页面打开时才被消费，
  // content script 启动、每 15 分钟、回到前台与 popup 打开都会触发同步，
  // 无需浏览器级定时唤醒（也避免 CWS 多解释一个 alarms 权限）。

  function sync(force: boolean) {
    return syncCommunitySnapshot({
      sources: COMMUNITY_SYNC_SOURCES,
      fetchImpl: (url) => fetch(url),
      store: snapshotStore,
      force,
    });
  }

  function syncKeywordPacks(force: boolean) {
    return syncKeywordPackCatalog({ force });
  }

  /**
   * Jev 判定通道。
   *
   * 为什么必须在背景页调用：内容脚本的 fetch 受 x.com 页面的 CORS 约束，
   * 页面不会放行对 api.typesafe.ai 的跨域请求；只有带 host_permissions 的
   * 背景页能直接发。key 只从本地设置读，不经过任何自建服务器。
   */
  let jevClient: JevClient | null = null;
  let jevClientKey = '';

  async function judgeWithJev(accounts: JevAccountInput[]) {
    const settings = await getJevSettings();
    if (!isJevActive(settings)) {
      return { type: 'feedsieve:jev-judge', ok: false, reason: 'disabled' };
    }
    if (!jevClient || jevClientKey !== settings.apiKey) {
      // 扇出宽度取离线评测验证过的 10（见 jev/RESULTS.md 的 H2）。
      jevClient = new JevClient({ apiKey: settings.apiKey, batchSize: 10 });
      jevClientKey = settings.apiKey;
    }
    const outcome = await jevClient.judge(accounts);
    if (!outcome.ok) {
      return { type: 'feedsieve:jev-judge', ok: false, reason: outcome.reason, status: outcome.status };
    }
    return {
      type: 'feedsieve:jev-judge',
      ok: true,
      verdicts: outcome.judgment.verdicts,
      usage: outcome.judgment.usage,
    };
  }

  browser.runtime.onInstalled.addListener((details) => {
    console.info(`[FeedSieve] installed (${details.reason})`);
    // 安装/更新后立即拉一次社区快照和关键词包。
    void sync(true);
    void syncKeywordPacks(true);
    // 升级后补传历史黑名单/白名单；同步状态会防止重复上传。
    void flushContributions();
  });

  browser.runtime.onStartup.addListener(() => {
    // 社区名单与关键词包各自控制节流；关键词包当前每 15 分钟可检查一次 manifest。
    void sync(false);
    void syncKeywordPacks(false);
    // 补交上次网络失败时积压的社区贡献
    void flushContributions();
  });

  // 内容脚本启动/每 15 分钟/重新回到前台时请求关键词同步；popup 手动同步带 force。
  browser.runtime.onMessage.addListener((message: unknown) => {
    const msg = message as
      | { type?: string; force?: boolean; accounts?: JevAccountInput[] }
      | null;
    if (msg?.type === 'feedsieve:jev-judge') {
      const accounts = Array.isArray(msg.accounts) ? msg.accounts : [];
      if (accounts.length === 0) {
        return Promise.resolve({ type: 'feedsieve:jev-judge', ok: false, reason: 'empty' });
      }
      return judgeWithJev(accounts);
    }
    if (msg?.type === 'feedsieve:community-sync') {
      return sync(msg.force === true).then((outcome) => ({
        type: 'feedsieve:community-sync',
        outcome,
      }));
    }
    if (msg?.type === 'feedsieve:keyword-packs-sync') {
      return syncKeywordPacks(msg.force === true).then((outcome) => ({
        type: 'feedsieve:keyword-packs-sync',
        outcome,
      }));
    }
    if (msg?.type === 'feedsieve:labels-sync') {
      return flushContributions().then(() => ({ type: 'feedsieve:labels-sync', ok: true }));
    }
    return undefined;
  });
});
