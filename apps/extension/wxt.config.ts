import { defineConfig } from 'wxt';

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  manifest: {
    name: '清流 Qingliu',
    short_name: '清流',
    // 商店描述：先说清做什么，再说清代价（黄框标注、绝不隐藏内容）
    description:
      'X 时间线清洁工：黄框标注垃圾账号，一键原生拉黑，全端同步消失。AI 判定层默认关闭，只标注、不隐藏、不自动拉黑。',
    permissions: ['storage'],
    host_permissions: [
      'https://x.com/*',
      // Jev 判定层：默认关闭，用户在设置里填自己的 key 后才启用（见 packages/jev-detect）
      'https://api.typesafe.ai/*',
      // 社区名单服务默认不启用（上游那台 Worker 已停运，见 src/lib/community-store.ts）。
      // 自部署 apps/community-api 后，在这里加回你的域名。
    ],
    icons: {
      16: '/icon-16.png',
      32: '/icon-32.png',
      48: '/icon-48.png',
      64: '/icon.png',
      128: '/icon-128.png',
    },
  },
  zip: {
    name: 'qingliu',
  },
});
