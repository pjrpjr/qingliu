/**
 * 提问设计 —— 与离线评测（`jev/judge.py` 的 `questions_for`）逐字对应。
 *
 * 三个问题各司其职：
 *   · `spam`（noul）—— 主信号。noul 是**二值概率**，每条都会给 0–1 的数，
 *     不存在「说不清」把信号吃掉的情况（jev 套利项目的 E18 教训：三选一问题
 *     会让模型在 95% 的样本上弃权）。
 *   · `category`（choice）—— UI 徽章与社区上报载荷用。
 *   · `evidence`（choice）—— UI 上「为什么标它」，让标注可解释。
 */

export type JevQuestionType = 'noul' | 'choice' | 'score';

export interface JevQuestionSpec {
  type: JevQuestionType;
  instructions: string;
  criteria: Record<string, string>;
}

export type JevQuestionSet = Record<string, JevQuestionSpec>;

const CATEGORY_CRITERIA: Record<string, string> = {
  adult_gray_traffic: '色情/成人内容、福利资源或成人网站引流',
  scam_phishing: '诈骗、钓鱼、假空投、假客服、假投资',
  bot_spam: '机器人刷屏、批量复读、无意义灌水',
  engagement_bait: '互动钓鱼：求互关/求涨粉/抽奖/求点赞',
  legit_person: '真人正常使用账号',
  legit_brand: '机构、商家或正规创作者账号',
};

const EVIDENCE_CRITERIA: Record<string, string> = {
  bio: '简介里的表述',
  tweet_text: '推文正文的表述',
  links: '外链域名',
  handle_name: 'handle 或昵称的形态',
  behavior: '账号行为数据（粉丝/关注/推文数的比例）',
  none: '没有明显证据',
};

/** 批量判定时的问题前缀：`a3_`；单账号判定时为空（与评测脚本一致）。 */
export function questionPrefix(index: number, batchSize: number): string {
  return batchSize > 1 ? `a${index}_` : '';
}

export function buildQuestions(batchSize: number): JevQuestionSet {
  const questions: JevQuestionSet = {};
  for (let index = 1; index <= batchSize; index += 1) {
    const prefix = questionPrefix(index, batchSize);
    const ref = batchSize > 1 ? `账号档案 #${index}` : '这个账号档案';
    questions[`${prefix}spam`] = {
      type: 'noul',
      instructions:
        `${ref} 是不是垃圾号？垃圾号指：色情/成人内容或福利资源引流、` +
        '诈骗钓鱼（假空投/假客服/假投资）、机器人刷屏或批量复读、' +
        '互动钓鱼（求互关/求涨粉/抽奖骗互动）。' +
        '真人正常分享生活、正常讨论、正规商家与创作者都不算垃圾号，' +
        '即使内容里有广告或情绪化表达也不算。',
      criteria: {
        true: '有明确证据表明这是垃圾号',
        false: '证据不足，或只是普通用户/正规账号',
      },
    };
    questions[`${prefix}category`] = {
      type: 'choice',
      instructions: `${ref} 属于哪一类？没有垃圾证据就选 legit_person 或 legit_brand。`,
      criteria: CATEGORY_CRITERIA,
    };
    questions[`${prefix}evidence`] = {
      type: 'choice',
      instructions: `判断 ${ref} 时，最主要的依据来自哪里？`,
      criteria: EVIDENCE_CRITERIA,
    };
  }
  return questions;
}
