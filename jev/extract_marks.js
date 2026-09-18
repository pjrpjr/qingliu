// 取出页面上所有被标账号的细节，用于复核 AI 判得对不对（误标是产品级事故）。
// 单独放文件：嵌在 Python 字符串里会被 Python 的转义规则吃掉（踩过两次）。
() => {
  return [...document.querySelectorAll('[data-fs-marked]')].map(cell => {
    const art = cell.querySelector('article') || cell;
    const name = art.querySelector('[data-testid="User-Name"]');
    const text = art.querySelector('[data-testid="tweetText"]');
    const reason = cell.querySelector('.fs-reason');
    const bio = art.querySelector('[data-testid="UserDescription"]');
    return {
      source: cell.getAttribute('data-fs-marked'),
      handle: name ? (name.innerText || '').split(String.fromCharCode(10)).join(' ').slice(0, 80) : null,
      text: text ? (text.innerText || '').slice(0, 200) : '(无正文·可能仅图片)',
      bio: bio ? (bio.innerText || '').slice(0, 160) : null,
      reason: reason ? reason.textContent : null,
    };
  });
}
