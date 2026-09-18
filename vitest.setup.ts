/**
 * 测试期环境注入。
 *
 * `community-store.ts` 的社区服务地址默认留空（上游那台 Worker 已停运，见该文件注释）。
 * 但「上报 / 标签同步」这条链路本身仍然需要覆盖 —— 自部署用户与商业化后的托管档都要用。
 * 所以测试里统一注入一个假地址：链路被真实执行，网络请求由各测试自己 mock。
 */
import.meta.env.WXT_COMMUNITY_API_BASE = 'https://community.test.invalid';
