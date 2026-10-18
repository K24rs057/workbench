// 段取りさんの画面。画面ごとに描く関数を持ち、帯のボタンで切り替える(UI 試作と同じ作り)
const IC = {
  top: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 9.5 10 3.5l7 6V17H12.5v-4.5h-5V17H3z"/></svg>',
  sched: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4.5" width="14" height="12.5" rx="2"/><path d="M3 8.5h14M7 2.5v4M13 2.5v4"/></svg>',
  mail: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2.5" y="4.5" width="15" height="11" rx="1.8"/><path d="m3 5.5 7 5.5 7-5.5"/></svg>',
  box: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 7.5h14V16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M2.5 4.5h15v3h-15z"/><path d="M8 11h4"/></svg>',
  set: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="10" cy="10" r="2.6"/><path d="M10 2.5v2.2M10 15.3v2.2M2.5 10h2.2M15.3 10h2.2M4.7 4.7l1.6 1.6M13.7 13.7l1.6 1.6M4.7 15.3l1.6-1.6M13.7 6.3l1.6-1.6"/></svg>',
  brand: '<svg viewBox="0 0 24 24" fill="none" stroke="var(--blue)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="4.5" width="14" height="17" rx="2"/><path d="M9 3h6v3H9z"/><path d="m8.5 11 1.5 1.5 3-3M8.5 16.5l1.5 1.5 3-3"/><path d="M15 11.5h1.5M15 17h1.5"/></svg>',
};
const ILL = {
  desk: '<svg viewBox="0 0 120 90" fill="none" stroke="var(--ill)" stroke-width="1.6" stroke-linecap="round"><path d="M14 62h92M24 62v20M96 62v20"/><path d="M30 62V50h26v12"/><path d="M34 50V40h18v10" stroke="var(--ill-accent)"/><path d="M76 62V36M76 36l12-12M88 24l8 4-4 8z"/><circle cx="64" cy="57" r="4"/></svg>',
  env: '<svg viewBox="0 0 120 90" fill="none" stroke="var(--ill)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="28" y="28" width="64" height="42" rx="3"/><path d="m29 30 31 22 31-22"/><path d="M60 14v8M46 18l3 6M74 18l-3 6" stroke="var(--ill-accent)"/></svg>',
  cal: '<svg viewBox="0 0 120 90" fill="none" stroke="var(--ill)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="30" y="24" width="60" height="50" rx="4"/><path d="M30 38h60M44 18v12M76 18v12"/><path d="M48 52h6M62 52h6M48 62h6" stroke="var(--ill-accent)"/></svg>',
  box: '<svg viewBox="0 0 120 90" fill="none" stroke="var(--ill)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M30 40h60v32H30z"/><path d="M30 40l8-12h44l8 12"/><path d="M50 52h20"/><path d="M84 22l4-4M90 30h6M88 25l5-2" stroke="var(--ill-accent)"/></svg>',
};
const SCREENS = [
  ['top', 'トップ', IC.top],
  ['sched', '予定', IC.sched],
  ['mail', '連絡', IC.mail],
  ['cont', '授業・会社・開発', IC.box, '授業など'],
  ['set', '設定', IC.set],
];
const S = { screen: 'top' };
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));

function today() {
  const d = new Date();
  return `${d.getMonth() + 1}月${d.getDate()}日(${'日月火水木金土'[d.getDay()]})`;
}

function recLine() {
  // 区切り4で、自動の作業記録とつなぐ
  return '<div class="recmini"><span class="pulse"></span>記録なし</div>';
}

function side() {
  const nav = SCREENS.map(([k, n, i]) => `<button class="nav ${S.screen === k ? 'on' : ''}" data-go="${k}">${i}${esc(n)}</button>`).join('');
  $('#side').innerHTML = `<div class="brand">${IC.brand}段取りさん</div>${nav}${recLine()}`;
  $('#tabbar').innerHTML = recLine() + SCREENS.map(([k, n, i, short]) => `<button class="${S.screen === k ? 'on' : ''}" data-go="${k}">${i}${esc(short || n)}</button>`).join('');
}

function bar(title, extra = '') {
  return `<div class="bar"><h1>${esc(title)}</h1>${extra}</div>`;
}

function emptyState(ill, head, body) {
  return `<div class="empty">${ill}<b>${esc(head)}</b><span>${esc(body)}</span></div>`;
}

const VIEWS = {
  top: () => bar('トップ', `<span class="date">${today()}</span>`) +
    `<div class="col">${emptyState(ILL.desk, 'まだタスクがありません', '「授業・会社・開発」の画面で授業や会社を作り、タスクを足すと、ここに今日と今週のやることが並びます。')}</div>`,
  sched: () => bar('予定') +
    `<div class="col">${emptyState(ILL.cal, 'あとでつながります', 'Google カレンダーとつなぐのは作る順番の③です。それまでは、トップの「今日の時間」に時間割の授業が出ます。')}</div>`,
  mail: () => bar('連絡') +
    `<div class="col">${emptyState(ILL.env, 'あとでつながります', 'メールの取り込みは作る順番の②です。段取りさんからの質問(「確認してほしいこと」)は、作業記録ができたらここに出ます。')}</div>`,
  cont: () => bar('授業・会社・開発', '<span class="date">ひとつずつ押すと、中のタスク・リンク・記録が見られます</span>') +
    `<div class="col">${emptyState(ILL.box, 'まだ何もありません', '次の区切りで、授業・会社・開発を足せるようになります。')}</div>`,
  set: () => bar('設定') +
    `<div class="col">${emptyState(ILL.desk, '設定はこれから足していきます', '種類・大学・作業記録・モッチなどの設定が、区切りごとにここに増えます。')}</div>`,
};

function render() {
  side();
  $('#main').innerHTML = VIEWS[S.screen]();
}

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-go]');
  if (!el) return;
  S.screen = el.dataset.go;
  location.hash = S.screen;
  render();
});

window.addEventListener('hashchange', () => {
  const k = location.hash.slice(1);
  if (VIEWS[k] && k !== S.screen) { S.screen = k; render(); }
});

(function start() {
  const k = location.hash.slice(1);
  if (VIEWS[k]) S.screen = k;
  render();
})();
