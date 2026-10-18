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
const WEEK = '日月火水木金土';
const S = { screen: 'top', cont: null, ctab: 'task', endedOpen: false };
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));

// ---------- 本体とのやりとり ----------
async function api(method, path, data) {
  const res = await fetch('/api' + path, {
    method,
    headers: data ? { 'Content-Type': 'application/json' } : {},
    body: data ? JSON.stringify(data) : undefined,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || '保存できませんでした。もう一度押してください');
  return json;
}

// ---------- 小窓と知らせ ----------
let toastTimer;
function toast(msg, undo) {
  clearTimeout(toastTimer);
  document.querySelector('.toast')?.remove();
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = `<span>${esc(msg)}</span>${undo ? '<button>元に戻す</button>' : ''}`;
  document.body.appendChild(t);
  if (undo) t.querySelector('button').onclick = async () => { t.remove(); await undo(); render(); };
  toastTimer = setTimeout(() => t.remove(), 5000);
}
function modal(html, onReady) {
  $('#layer').innerHTML = `<div class="ov" data-close><div class="modal" role="dialog">${html}<div class="err" id="merr"></div></div></div>`;
  onReady && onReady($('#layer .modal'));
  const first = $('#layer input, #layer select');
  first && first.focus();
}
function closeModal() { $('#layer').innerHTML = ''; }
function modalError(e) { const el = $('#merr'); if (el) el.textContent = e.message; }

// ---------- 小さな部品 ----------
function today() {
  const d = new Date();
  return `${d.getMonth() + 1}月${d.getDate()}日(${WEEK[d.getDay()]})`;
}
function isoToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function dueLabel(t) {
  if (!t.due_date) return '';
  const [, m, d] = t.due_date.split('-').map(Number);
  const md = t.due_date === isoToday() ? '今日' : `${m}/${d}`;
  return t.due_time ? `${md} ${t.due_time}` : md;
}
function kindLabel(name, color) {
  return `<span class="lb" style="color:${color};background:color-mix(in srgb, ${color} 14%, transparent)">${esc(name)}</span>`;
}
function bar(title, extra = '') { return `<div class="bar"><h1>${esc(title)}</h1>${extra}</div>`; }
function emptyState(ill, head, body) { return `<div class="empty">${ill}<b>${esc(head)}</b><span>${esc(body)}</span></div>`; }
function recLine() { return '<div class="recmini"><span class="pulse"></span>記録なし</div>'; }

function side() {
  const on = (k) => S.screen === k || (k === 'cont' && S.screen === 'inside');
  const nav = SCREENS.map(([k, n, i]) => `<button class="nav ${on(k) ? 'on' : ''}" data-go="${k}">${i}${esc(n)}</button>`).join('');
  $('#side').innerHTML = `<div class="brand">${IC.brand}段取りさん</div>${nav}${recLine()}`;
  $('#tabbar').innerHTML = recLine() + SCREENS.map(([k, n, i, short]) => `<button class="${on(k) ? 'on' : ''}" data-go="${k}">${i}${esc(short || n)}</button>`).join('');
}

function taskRow(t, label) {
  const name = t.open_target
    ? `<a class="tlink" href="${esc(t.open_target)}" target="_blank" rel="noopener" title="${esc(t.open_label)}を開く">${esc(t.name)}</a><span class="to">${esc(t.open_label)}</span>`
    : esc(t.name);
  const rep = t.repeat_weekday !== null && t.repeat_weekday !== undefined ? `<span class="mk mk-rep">毎週${WEEK[(t.repeat_weekday + 1) % 7]}</span>` : '';
  const late = t.due_date && !t.done && t.due_date < isoToday();
  return `<div class="task ${label ? 'withLab' : ''} ${t.done ? 'done' : ''}">
    <button class="ck" data-done="${t.id}" aria-label="${t.done ? '完了を外す' : '完了にする'}"></button>${label || ''}
    <span class="nm">${name}${rep}<button class="link" data-edit="${t.id}" style="margin-left:8px;font-size:11.5px">直す</button></span>
    <span class="due ${late ? 'late' : ''}">${late ? '遅れ ' : ''}${esc(dueLabel(t))}</span></div>`;
}

// ---------- 画面 ----------
const VIEWS = {
  top: () => bar('トップ', `<span class="date">${today()}</span>`) +
    `<div class="col">${emptyState(ILL.desk, 'トップはこれから作ります', '次の区切りで、今日と今週のやることが締切の順に並びます。今は「授業・会社・開発」の画面で、授業や会社とタスクを足せます。')}</div>`,
  sched: () => bar('予定') +
    `<div class="col">${emptyState(ILL.cal, 'あとでつながります', 'Google カレンダーとつなぐのは作る順番の③です。それまでは、トップの「今日の時間」に時間割の授業が出ます。')}</div>`,
  mail: () => bar('連絡') +
    `<div class="col">${emptyState(ILL.env, 'あとでつながります', 'メールの取り込みは作る順番の②です。段取りさんからの質問(「確認してほしいこと」)は、作業記録ができたらここに出ます。')}</div>`,
  cont: contView,
  inside: insideView,
  set: setView,
};

async function contView() {
  const ov = await api('GET', '/containers');
  S.ov = ov;
  const row = (i) => {
    const n = i.next;
    const nx = n
      ? `<span class="${n.overdue ? 'late' : ''}">${esc(n.name)}</span><span class="fd ${n.overdue ? 'late' : ''}">${n.overdue ? '遅れ ' : ''}${esc(dueLabel(n))}</span>`
      : '<span class="fnone">締切のあるタスクはありません</span>';
    return `<button class="frow" data-open="${i.id}"><span class="fn">${esc(i.name)}</span><span class="fx">${nx}</span><span class="fc"><i class="fl">残り </i>${i.left ? i.left + '件' : 'なし'}</span><span class="fc">${esc(i.week_label)}</span></button>`;
  };
  const kinds = ov.kinds.map((k) => `<div class="kind"><h3><i style="background:${k.color}"></i>${esc(k.name)}<span>${k.items.length}個</span></h3>${k.items.length ? k.items.map(row).join('') : '<div class="none">まだありません</div>'}</div>`).join('');
  const ended = ov.ended.length
    ? `<button class="fold" data-ended>終わった授業・会社 ${ov.ended.length}件 ${S.endedOpen ? '▾' : '▸'}</button>${S.endedOpen ? ov.ended.map((i) => `<div class="frow"><span class="fn">${esc(i.name)}</span><span class="fx"><span class="fnone">終了</span></span><span class="fc"></span><span class="fc"><button class="link" data-restore="${i.id}">戻す</button></span></div>`).join('') : ''}`
    : '';
  return bar('授業・会社・開発', '<span class="date">ひとつずつ押すと、中のタスク・リンク・記録が見られます</span><span class="r"><button class="btn" data-addc>+ 足す</button></span>') +
    `<div class="col">${ov.unsorted ? `<button class="band" data-sort>未分類 ${ov.unsorted}件 ― どれのタスクか選んでください ›</button>` : ''}
    <div class="fhd"><span>名前</span><span>次の締切</span><span class="fc">残りのタスク</span><span class="fc">今週の作業</span></div>${kinds}${ended}</div>`;
}

async function insideView() {
  const c = await api('GET', `/containers/${S.cont}`);
  S.c = c;
  const color = c.kind ? c.kind.color : '#77746e';
  const kindName = c.kind ? c.kind.name : '未分類';
  const prog = c.progress === null ? 'タスクなし' : `<span class="gtrack"><i style="width:${c.progress}%"></i></span>${c.progress}% 完了`;
  const tabs = [['task', 'タスク'], ['log', '記録'], ['link', 'リンク'], ['cset', '設定']];
  let body = '';
  if (S.ctab === 'task') {
    body = `<div class="sec"><div class="rowb"><button class="btn pri" data-addt>+ 「${esc(c.name)}」にタスクを足す</button><span class="hint">締切・時刻・毎週の繰り返し・押したときに開くページを入れられます</span></div></div>
      <div class="sec">${c.tasks.length ? c.tasks.map((t) => taskRow(t)).join('') : emptyState(ILL.desk, 'タスクはまだありません', '「タスクを足す」から入れてください。')}</div>`;
  } else if (S.ctab === 'log') {
    body = emptyState(ILL.desk, '作業記録は区切り4で作ります', 'パソコンで前に出ている画面から、自動で記録がたまるようになります。');
  } else if (S.ctab === 'link') {
    body = emptyState(ILL.desk, 'リンクは区切り3で作ります', '学習サイトや PC のフォルダを登録すると、トップの「今日のリンク」とタスクの名前から開けるようになります。');
  } else {
    body = c.is_unsorted ? '<div class="sec hint">未分類は、名前や種類を変えたり、終了にしたりできません。</div>' : `<div class="sec">
      <div class="field"><span>名前</span><input id="cname" value="${esc(c.name)}"></div>
      <div class="field"><span>種類</span><select id="ckind">${(S.kinds || []).map((k) => `<option value="${k.id}" ${k.id === c.kind_id ? 'selected' : ''}>${esc(k.name)}</option>`).join('')}</select></div>
      <div class="rowb"><button class="btn pri" data-csave>保存</button></div></div>
      <div class="sec"><div class="rowb"><button class="btn" data-cend>終了にする</button><span class="hint">一覧とトップから見えなくなります。中身は残り、あとで戻せます</span></div>
      <div class="rowb"><button class="btn danger" data-cdel ${c.deletable ? '' : 'disabled'}>消す</button><span class="hint">${c.deletable ? '中身が空なので消せます' : '中身があるので消せません。かわりに「終了にする」を使ってください'}</span></div></div>`;
  }
  return `<div class="chead"><button class="back" data-go="cont">‹ 授業・会社・開発</button>
    <div class="t">${esc(c.name)}${kindLabel(kindName, color)}</div>
    <div class="m"><span>${prog}</span><span>今週 ${esc(c.week_label)}/全部で ${esc(c.total_label)}</span><span>残り ${c.left}件</span></div></div>
    <div class="tabs">${tabs.map(([k, n]) => `<button class="${S.ctab === k ? 'on' : ''}" data-ctab="${k}">${n}</button>`).join('')}</div>
    <div class="col">${body}</div>`;
}

async function setView() {
  const kinds = await api('GET', '/kinds');
  S.kinds = kinds;
  const rows = kinds.map((k) => `<div class="krow">
    <input type="color" value="${esc(k.color)}" data-kcolor="${k.id}" aria-label="${esc(k.name)}の色">
    <input class="nmin" value="${esc(k.name)}" data-kname="${k.id}" aria-label="種類の名前">
    <span class="tg"><button class="sw ${k.sort_first ? 'on' : ''}" data-ksw="${k.id}" data-f="sort_first" aria-label="同じ締切のとき先に並べる"></button>同じ締切のとき先に並べる</span>
    <span class="tg"><button class="sw ${k.notify_untouched ? 'on' : ''}" data-ksw="${k.id}" data-f="notify_untouched" aria-label="手つかずの通知"></button>締切なしに手つかずの通知</span>
    ${k.builtin ? '<span class="hint">初めから</span>' : `<button class="link danger" data-kdel="${k.id}">消す</button>`}</div>`).join('');
  return bar('設定') + `<div class="col">
    <div class="sset"><h3>種類</h3>${rows}<div class="rowb"><button class="btn" data-kadd>+ 種類を足す</button><span class="hint">灰色は未分類だけの色なので選べません。中に授業・会社・開発がある種類は消せません</span></div></div>
    <div class="sset"><h3>これから足す設定</h3><div class="hint">大学(学期の終わりの日)・作業記録(覚えた画面の名前)・本体の様子・モッチは、区切りごとにここに増えます。</div></div></div>`;
}

// ---------- 小窓の中身 ----------
function taskForm(t, containerId) {
  const w = t && t.repeat_weekday !== null && t.repeat_weekday !== undefined ? t.repeat_weekday : '';
  const opts = ['なし', ...[0, 1, 2, 3, 4, 5, 6].map((i) => `毎週 ${WEEK[(i + 1) % 7]}曜`)];
  modal(`<h3>${t ? 'タスクを直す' : 'タスクを足す'}</h3>
    <div class="field"><span>名前</span><input id="tname" value="${esc(t ? t.name : '')}" placeholder="第11回課題"></div>
    <div class="field"><span>締切</span><div class="two"><input id="tdate" type="date" value="${esc(t ? t.due_date || '' : '')}"><input id="ttime" placeholder="23:59(なくてもよい)" value="${esc(t ? t.due_time || '' : '')}"></div></div>
    <div class="field"><span>繰り返し</span><select id="trep">${opts.map((o, i) => `<option value="${i === 0 ? '' : i - 1}" ${String(w) === (i === 0 ? '' : String(i - 1)) ? 'selected' : ''}>${o}</option>`).join('')}</select></div>
    <div class="field"><span>押したときに開くページ</span><input id="turl" value="${esc(t ? t.open_url || '' : '')}" placeholder="https://…(空なら自動)"></div>
    <div class="hint">締切がないタスクは「締切なし」にまとまります。開くページが空のときは、その授業・会社のリンクを使います。</div>
    <div class="acts">${t ? `<button class="btn danger l" data-tdel="${t.id}">消す</button>` : ''}<button class="btn" data-close>やめる</button><button class="btn pri" data-tsave="${t ? t.id : ''}" data-cid="${containerId}">${t ? '保存' : '足す'}</button></div>`);
}

async function sortModal() {
  const d = await api('GET', '/unsorted');
  if (!d.tasks.length) { closeModal(); return render(); }
  const opts = d.options.map((o) => `<option value="${o.id}">${esc(o.kind)}:${esc(o.name)}</option>`).join('');
  modal(`<h3>未分類の仕分け</h3><div class="hint">どれのタスクかを選ぶと、その授業・会社・開発に移ります。</div>
    ${d.tasks.map((t) => `<div class="field"><span>${esc(t.name)}</span><div class="two"><select data-pickfor="${t.id}"><option value="">選ぶ…</option>${opts}</select></div></div>`).join('')}
    ${d.options.length ? '' : '<div class="hint">先に「+ 足す」で授業・会社・開発を作ってください。</div>'}
    <div class="acts"><button class="btn" data-close>閉じる</button></div>`);
}

// ---------- 描く ----------
async function render() {
  side();
  if (!S.kinds) S.kinds = await api('GET', '/kinds').catch(() => []);
  try {
    $('#main').innerHTML = await VIEWS[S.screen]();
  } catch (e) {
    $('#main').innerHTML = bar('うまく読めませんでした') + `<div class="col">${emptyState(ILL.desk, '本体から読めませんでした', e.message)}</div>`;
  }
}
function go(screen) {
  closeModal();
  S.screen = screen;
  location.hash = screen === 'inside' ? `inside-${S.cont}` : screen;
  render();
}

// ---------- 押したとき ----------
document.addEventListener('click', async (e) => {
  const el = e.target.closest('button,[data-close]');
  if (!el) return;
  const d = el.dataset;
  try {
    if (d.close !== undefined && (e.target === el || el.tagName === 'BUTTON')) { closeModal(); return; }
    if (d.go) { go(d.go); return; }
    if (d.open) { S.cont = +d.open; S.ctab = 'task'; go('inside'); return; }
    if (d.ctab) { S.ctab = d.ctab; render(); return; }
    if (d.ended !== undefined) { S.endedOpen = !S.endedOpen; render(); return; }
    if (d.restore) { await api('PATCH', `/containers/${d.restore}`, { ended: false }); toast('戻しました'); render(); return; }
    if (d.sort !== undefined) { await sortModal(); return; }
    if (d.addc !== undefined) {
      const opts = S.kinds.map((k) => `<option value="${k.id}">${esc(k.name)}</option>`).join('');
      modal(`<h3>授業・会社・開発を足す</h3><div class="field"><span>名前</span><input id="ncname" placeholder="情報工学演習"></div>
        <div class="field"><span>種類</span><select id="nckind">${opts}</select></div>
        <div class="acts"><button class="btn" data-close>やめる</button><button class="btn pri" data-csubmit>足す</button></div>`);
      return;
    }
    if (d.csubmit !== undefined) {
      const nm = $('#ncname').value.trim();
      const r = await api('POST', '/containers', { name: nm, kind_id: +$('#nckind').value });
      closeModal(); toast(`「${nm}」を足しました`); S.cont = r.id; S.ctab = 'task'; go('inside'); return;
    }
    if (d.addt !== undefined) { taskForm(null, S.cont); return; }
    if (d.edit) { taskForm(S.c.tasks.find((t) => t.id === +d.edit), S.cont); return; }
    if (d.tsave !== undefined) {
      const data = { name: $('#tname').value, due_date: $('#tdate').value, due_time: $('#ttime').value.trim(), repeat_weekday: $('#trep').value, open_url: $('#turl').value };
      if (d.tsave) await api('PATCH', `/tasks/${d.tsave}`, data);
      else await api('POST', '/tasks', { ...data, container_id: +d.cid });
      closeModal(); toast(d.tsave ? '直しました' : `「${data.name}」を足しました`); render(); return;
    }
    if (d.tdel) {
      if (!el.dataset.sure) { el.dataset.sure = '1'; el.textContent = 'ほんとうに消す'; return; }
      await api('DELETE', `/tasks/${d.tdel}`); closeModal(); toast('消しました'); render(); return;
    }
    if (d.done) {
      const t = (S.c?.tasks || []).find((x) => x.id === +d.done);
      const next = !(t && t.done);
      await api('PATCH', `/tasks/${d.done}`, { done: next });
      render();
      if (next) toast(`「${t ? t.name : 'タスク'}」を完了にしました`, () => api('PATCH', `/tasks/${d.done}`, { done: false }));
      return;
    }
    if (d.csave !== undefined) { await api('PATCH', `/containers/${S.cont}`, { name: $('#cname').value, kind_id: +$('#ckind').value }); toast('保存しました'); render(); return; }
    if (d.cend !== undefined) { await api('PATCH', `/containers/${S.cont}`, { ended: true }); toast(`「${S.c.name}」を終了にしました`, () => api('PATCH', `/containers/${S.cont}`, { ended: false })); go('cont'); return; }
    if (d.cdel !== undefined) {
      if (!el.dataset.sure) { el.dataset.sure = '1'; el.textContent = 'ほんとうに消す'; return; }
      await api('DELETE', `/containers/${S.cont}`); toast('消しました'); go('cont'); return;
    }
    if (d.kadd !== undefined) {
      modal(`<h3>種類を足す</h3><div class="field"><span>名前</span><input id="nkname" placeholder="アルバイト"></div>
        <div class="field"><span>色</span><input id="nkcolor" type="color" value="#a8457a"></div>
        <div class="hint">新しい種類は「同じ締切のとき先に並べる」がオフ、「手つかずの通知」がオンで始まります。</div>
        <div class="acts"><button class="btn" data-close>やめる</button><button class="btn pri" data-ksubmit>足す</button></div>`);
      return;
    }
    if (d.ksubmit !== undefined) { await api('POST', '/kinds', { name: $('#nkname').value, color: $('#nkcolor').value }); closeModal(); S.kinds = null; render(); return; }
    if (d.ksw) { await api('PATCH', `/kinds/${d.ksw}`, { [d.f]: el.classList.contains('on') ? 0 : 1 }); S.kinds = null; render(); return; }
    if (d.kdel) {
      if (!el.dataset.sure) { el.dataset.sure = '1'; el.textContent = 'ほんとうに消す'; return; }
      await api('DELETE', `/kinds/${d.kdel}`); S.kinds = null; render(); return;
    }
  } catch (err) {
    if ($('#merr')) modalError(err); else toast(err.message);
  }
});

document.addEventListener('change', async (e) => {
  const t = e.target;
  try {
    if (t.dataset.kname) { await api('PATCH', `/kinds/${t.dataset.kname}`, { name: t.value }); S.kinds = null; toast('種類の名前を変えました'); }
    if (t.dataset.kcolor) { await api('PATCH', `/kinds/${t.dataset.kcolor}`, { color: t.value }); S.kinds = null; render(); }
    if (t.dataset.pickfor && t.value) { await api('PATCH', `/tasks/${t.dataset.pickfor}`, { container_id: +t.value }); toast('移しました'); await sortModal(); }
  } catch (err) {
    if ($('#merr')) modalError(err); else { toast(err.message); render(); }
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeModal();
  if (e.key === 'Enter' && !e.isComposing && e.target.closest('.modal') && e.target.tagName === 'INPUT') {
    const pri = $('#layer .btn.pri');
    pri && pri.click();
  }
});

window.addEventListener('hashchange', () => {
  closeModal();
  const h = location.hash.slice(1);
  if (h.startsWith('inside-')) { const id = +h.slice(7); if (id !== S.cont || S.screen !== 'inside') { S.cont = id; S.screen = 'inside'; render(); } return; }
  if (VIEWS[h] && h !== S.screen) { S.screen = h; render(); }
});

(function start() {
  const h = location.hash.slice(1);
  if (h.startsWith('inside-')) { S.cont = +h.slice(7); S.screen = 'inside'; }
  else if (VIEWS[h]) S.screen = h;
  render();
})();
