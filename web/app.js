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
function recLine() {
  const r = S.rec;
  return r
    ? `<div class="recmini on" title="段取りさんが自動で判断して記録している作業です。まちがっていたら、中の画面の「記録」で直せます"><span class="pulse"></span>記録中: ${esc(r.name)} <span class="clk">${esc(r.elapsed)}</span></div>`
    : '<div class="recmini" title="今は記録していません(どれの作業か決まっていない窓・ロック中・記録しない窓のとき)"><span class="pulse"></span>記録なし</div>';
}
async function refreshRec() {
  try { S.rec = await api('GET', '/work-logs/current'); } catch (e) { return; }
  document.querySelectorAll('.recmini').forEach((el) => { el.outerHTML = recLine(); });
}
setInterval(refreshRec, 30000);
async function refreshNewMail() {
  try { const s = await api('GET', '/messages/summary'); if (S.newMail !== s.new && S.screen !== 'mail') { S.newMail = s.new; side(); } } catch (e) { /* 本体が止まっているとき */ }
}
setInterval(refreshNewMail, 60000);

function side() {
  const on = (k) => S.screen === k || (k === 'cont' && S.screen === 'inside');
  const dot = (k) => (k === 'mail' && S.newMail ? '<span class="dot" title="新しい連絡"></span>' : '');
  const nav = SCREENS.map(([k, n, i]) => `<button class="nav ${on(k) ? 'on' : ''}" data-go="${k}">${i}${esc(n)}${dot(k)}</button>`).join('');
  $('#side').innerHTML = `<div class="brand">${IC.brand}段取りさん</div>${nav}${recLine()}`;
  $('#tabbar').innerHTML = recLine() + SCREENS.map(([k, n, i, short]) => `<button class="${on(k) ? 'on' : ''}" data-go="${k}">${i}${esc(short || n)}${dot(k)}</button>`).join('');
}

function taskRow(t, label) {
  const web = t.open_target && /^https?:\/\//.test(t.open_target);
  const name = !t.open_target ? esc(t.name)
    : web ? `<a class="tlink" href="${esc(t.open_target)}" target="_blank" rel="noopener" title="${esc(t.open_label)}を開く">${esc(t.name)}</a><span class="to">${esc(t.open_label)}</span>`
    : `<button class="tlink" data-topen="${t.id}" title="${esc(t.open_label)}を開く">${esc(t.name)}</button><span class="to">${esc(t.open_label)}</span>`;
  const ai = t.ai ? `<button class="mk mk-ai" data-aibadge="${t.id}" title="Claude が読み取った。押すと、読み取った部分が見られます">AI</button>` : '';
  const fm = t.from_mail && !t.ai ? '<span class="mk mk-mail" title="メールから自動で入った">メール</span>' : '';
  const warn = t.warn ? `<span class="mk mk-warn">${esc(t.warn)}</span>` : '';
  const pick = t.unsorted ? '<button class="mk mk-pick" data-sort>どれのタスクか選んで</button>' : '';
  const rep = t.repeat_weekday !== null && t.repeat_weekday !== undefined ? `<span class="mk mk-rep">毎週${WEEK[(t.repeat_weekday + 1) % 7]}</span>` : '';
  const late = t.due_date && !t.done && t.due_date < isoToday();
  return `<div class="task ${label ? 'withLab' : ''} ${t.done ? 'done' : ''}">
    <button class="ck" data-done="${t.id}" aria-label="${t.done ? '完了を外す' : '完了にする'}"></button>${label || ''}
    <span class="nm">${name}${ai}${fm}${rep}${warn}${pick}<button class="link" data-edit="${t.id}" style="margin-left:8px;font-size:11.5px">直す</button></span>
    <span class="due ${late ? 'late' : ''}">${late ? '遅れ ' : ''}${esc(dueLabel(t))}</span></div>`;
}

// ---------- 画面 ----------
const VIEWS = {
  top: topView,
  sched: () => bar('予定') +
    `<div class="col">${emptyState(ILL.cal, 'あとでつながります', 'Google カレンダーとつなぐのは作る順番の③です。それまでは、トップの「今日の時間」に時間割の授業が出ます。')}</div>`,
  mail: mailView,
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
    const [logs, commits] = await Promise.all([api('GET', `/containers/${S.cont}/logs`), c.repo_path ? api('GET', `/containers/${S.cont}/commits`) : []]);
    S.logs = logs;
    const hm = (iso) => (iso ? iso.slice(11, 16) : '記録中');
    const dur = (l) => { const e = l.ended_at ? new Date(l.ended_at) : new Date(); const m = Math.max(0, Math.round((e - new Date(l.started_at)) / 60000)); return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`; };
    // 記録にくっついたコミットはその記録の下に、くっつかなかったものは「その時刻にしたこと」の点として並べる(F7)
    const onLog = {};
    const rows = logs.map((l) => ({ at: l.started_at, l }));
    commits.forEach((m) => { if (m.work_log_id && logs.some((l) => l.id === m.work_log_id)) (onLog[m.work_log_id] ||= []).push(m); else rows.push({ at: m.committed_at, m }); });
    rows.sort((a, b) => (a.at < b.at ? 1 : -1));
    const byDay = {};
    rows.forEach((r) => { (byDay[r.at.slice(0, 10)] ||= []).push(r); });
    const cm = (m) => `<div class="commit"><span class="tm">${hm(m.committed_at)}</span><span class="cmsg">${IC_COMMIT}${esc(m.message)}</span><span><button class="link danger" data-cmdel="${m.id}">消す</button></span></div>`;
    const logRow = (l) => `<div class="log"><span class="tm">${hm(l.started_at)}〜${hm(l.ended_at)}</span><span>${dur(l)}${l.note ? ` <span class="cm">${esc(l.note)}</span>` : ''}${l.edited ? ' <span class="cm">(手で直した)</span>' : ''}</span><span><button class="link" data-logedit="${l.id}">直す</button></span></div>${(onLog[l.id] || []).sort((a, b) => (a.committed_at < b.committed_at ? -1 : 1)).map((m) => cm(m).replace('class="commit"', 'class="commit on"')).join('')}`;
    body = `<div class="sec"><div class="rowb" style="margin-top:0"><button class="btn" data-logadd>+ 記録を足す</button><span class="hint">記録は、前に出ている窓から自動でつきます。${c.repo_path ? 'git のコミットも10分ごとに入ります。' : ''}まちがっていたら直す・消すができます</span></div></div>` +
      (rows.length ? Object.entries(byDay).map(([d, rs]) => `<div class="sec"><div class="sh">${esc(d.slice(5).replace('-', '/'))}</div>${rs.map((r) => (r.l ? logRow(r.l) : cm(r.m))).join('')}</div>`).join('')
        : emptyState(ILL.desk, 'まだ記録はありません', 'この授業・会社・開発の窓を開いていると、自動で記録がたまります。'));
  } else if (S.ctab === 'link') {
    const links = await api('GET', `/containers/${S.cont}/links`);
    body = `<div class="sec"><div class="sh">リンク</div>${links.length ? links.map((l) => `<div class="task"><span>${IC_LINK}</span><span class="nm">${linkBtn(l)}<span class="to">${esc(l.target)}</span></span><button class="link danger" data-ldel="${l.id}">消す</button></div>`).join('') : '<div class="hint">まだありません。学習サイトや、PC のフォルダ・ファイルを足せます。</div>'}
      <div class="rowb"><button class="btn" data-ladd>+ リンクを足す</button></div></div>
      <div class="sec"><span class="tg"><button class="sw ${c.links_always_top ? 'on' : ''}" data-lalways aria-label="いつもトップに出す"></button>このリンクを、毎日トップの「今日のリンク」に出す</span>
      <div class="hint" style="margin-top:6px">授業のリンクは、時間割でその授業がある日に自動で出ます。それ以外の日も出したいときにオンにします。</div></div>`;
  } else {
    body = c.is_unsorted ? '<div class="sec hint">未分類は、名前や種類を変えたり、終了にしたりできません。</div>' : `<div class="sec">
      <div class="field"><span>名前</span><input id="cname" value="${esc(c.name)}"></div>
      <div class="field"><span>種類</span><select id="ckind">${(S.kinds || []).map((k) => `<option value="${k.id}" ${k.id === c.kind_id ? 'selected' : ''}>${esc(k.name)}</option>`).join('')}</select></div>
      ${isJob(c) ? `<div class="field"><span>会社のメールアドレスの @ から後ろ</span><input id="cdom" value="${esc(c.company_domain || '')}" placeholder="example.co.jp(なくてもよい)"></div>
      <div class="hint">ここから届いたメールと、件名・本文に「${esc(c.name)}」が入ったメールを、この会社の連絡にします</div>` : ''}
      <div class="field"><span>リポジトリの場所</span><input id="crepo" value="${esc(c.repo_path || '')}" placeholder="C:\\Users\\…\\workbench(なくてもよい)"></div>
      <div class="field"><span>その中のフォルダ</span><input id="crsub" value="${esc(c.repo_subdir || '')}" placeholder="products/fx-practice(1つのリポジトリにアプリがいくつもあるとき)"></div>
      <div class="hint">入れると、git のコミットを10分ごとに読んで記録に並べます(読むだけです)。中のフォルダを入れると、そのフォルダを変えたコミットだけを読みます</div>
      ${c.repo_path ? `<div class="field"><span>説明の一言</span><input id="cdesc" value="${esc(c.own_description || '')}" placeholder="${esc((c.dev && c.dev.readme) || 'README がないときに、何を作っているかを一言')}"></div>
      <div class="hint">入れると、README の説明のかわりにこちらを出します</div>
      ${c.dev && c.dev.has_spec ? '' : `<div class="field"><span>開発の状態</span><select id="cstate"><option value="">選ばない</option>${c.dev_states.map((s) => `<option ${s === c.dev_state ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
      <div class="hint">spec-excel の工程(docs/spec-excel-status.md)がないときに出します</div>`}` : ''}
      <div class="rowb"><button class="btn pri" data-csave>保存</button></div></div>
      <div class="sec"><div class="rowb"><button class="btn" data-cend>終了にする</button><span class="hint">一覧とトップから見えなくなります。中身は残り、あとで戻せます</span></div>
      <div class="rowb"><button class="btn danger" data-cdel ${c.deletable ? '' : 'disabled'}>消す</button><span class="hint">${c.deletable ? '中身が空なので消せます' : '中身があるので消せません。かわりに「終了にする」を使ってください'}</span></div></div>`;
  }
  return `<div class="chead"><button class="back" data-go="cont">‹ 授業・会社・開発</button>
    <div class="t">${esc(c.name)}${kindLabel(kindName, color)}</div>
    ${c.dev ? `<div class="dv">${c.dev.description ? `<span class="ds">${esc(c.dev.description)}</span>` : '<span class="ds none">説明はまだありません(設定で一言書けます)</span>'}${c.dev.stage || c.dev.state ? `<span class="st">${esc(c.dev.stage || c.dev.state)}</span>` : ''}</div>` : ''}
    <div class="m"><span>${prog}</span><span>今週 ${esc(c.week_label)}/全部で ${esc(c.total_label)}</span><span>残り ${c.left}件</span></div></div>
    <div class="tabs">${tabs.map(([k, n]) => `<button class="${S.ctab === k ? 'on' : ''}" data-ctab="${k}">${n}</button>`).join('')}</div>
    <div class="col">${body}</div>`;
}

async function rulesSection() {
  const rules = await api('GET', '/window-rules');
  const rows = rules.map((r) => `<div class="krow" style="grid-template-columns:90px minmax(0,1fr) minmax(0,1fr) auto"><span class="hint">${esc(r.app)}</span><input class="nmin" value="${esc(r.pattern)}" data-rpat="${r.id}" aria-label="覚える文字"><span>${r.ignore ? '記録しない' : esc(r.container || '')}</span><button class="link danger" data-rdel="${r.id}">消す</button></div>`).join('');
  return `<div class="sset"><h3>作業記録</h3><div class="hint" style="margin-bottom:6px">覚えた窓の名前と、どれの作業かの組み合わせです。覚える文字は直せます。消すと、次に見たときにまた聞きます。</div>${rows || '<div class="hint">まだありません。</div>'}</div>`;
}
async function statusSection() {
  const st = await api('GET', '/status');
  const t = (iso) => (iso ? iso.replace('T', ' ').slice(5, 16) : 'まだ動いていません');
  const jobs = st.jobs.map((j) => `<div class="kv"><span>${esc(j.job)}</span><span class="${j.late && j.last_run_at ? 'late' : ''}">最後に動いた ${esc(t(j.last_run_at))}${j.late && j.last_run_at ? ' ― 遅れています' : ''}${j.error ? `(${esc(j.error)})` : ''}</span></div>`).join('');
  const auto = Object.entries(st.autostart).map(([n, ok]) => `<div class="kv"><span>${esc(n)}</span><span class="${ok ? '' : 'late'}">${ok ? '登録されています' : '登録されていません'}</span></div>`).join('');
  return `<div class="sset"><h3>本体の様子</h3>${jobs}<div class="sh" style="margin-top:10px">タスクスケジューラ(PC を起動したら自動で動き出す)</div>${auto}</div>`;
}
const isJob = (c) => ((S.kinds || []).find((k) => k.id === c.kind_id) || {}).name === '就活';
async function mailSection() {
  const [ms, bl, bt] = await Promise.all([api('GET', '/settings/mail'), api('GET', '/blocked-senders'), api('GET', '/baito')]);
  const g = ms.google;
  const gtext = { 合鍵なし: 'まだ合鍵がありません。手順のとおり Google Cloud で合鍵を作ってください', 未許可: '合鍵はあります。下のボタンで、Google の画面から許可してください', 許可済み: 'Gmail を読むことを許可しています(読むだけ)' }[g.state];
  const baito = bt.map((b) => `<div class="krow"><input class="nmin" style="border-color:var(--line2)" value="${esc(b.name)}" data-btname="${b.id}" aria-label="バイト先の名前">
    <input class="nmin" style="width:170px;border-color:var(--line2)" value="${esc(b.domain || '')}" data-btdom="${b.id}" placeholder="@ から後ろ(直接届くとき)" aria-label="バイト先のアドレス">
    <span class="hint">${b.addresses.length ? '覚えた中継アドレス ' + b.addresses.length + '件' : ''}</span><button class="link danger" data-btdel="${b.id}">消す</button></div>`).join('');
  return `<div class="sset"><h3>メールと連絡</h3>
    <div class="kv"><span>大学のアドレスの形</span><span><input class="nmin" style="width:220px;border-color:var(--line2)" id="udom" value="${esc(ms.university_domain)}" placeholder="example.ac.jp"> <button class="btn sm" data-domsave>保存</button></span></div>
    <div class="hint" style="margin:2px 0 8px">@ から後ろ。この形(と、その下のアドレス)から届いたメールだけを、大学の連絡として読みます。PC の中にだけ保存します</div>
    <div class="kv"><span>止めた差出人</span><span>${bl.length ? bl.map((b) => `<div>${esc(b.address)} <button class="link" data-bdel="${b.id}">外す</button></div>`).join('') : 'なし'}</span></div>
    <div class="hint" style="margin:2px 0 8px">リクナビ・マイナビ・理系ナビ・学情からの「受付中」「おすすめ」などの宣伝は、初めから取り込みません</div>
    <div class="kv"><span>バイト先</span><span>${baito || 'まだありません'}<div class="rowb"><button class="btn sm" data-btadd>+ バイト先を足す</button></div></span></div>
    <div class="hint" style="margin:2px 0 8px">Indeed・タウンワークなどの中継アドレスは、初めて届いたときに「どのバイト先?」と聞いて覚えます。お店から直接届くときは、@ から後ろを入れておきます</div>
    <div class="kv"><span>シフト表での自分の名前</span><span><input class="nmin" style="width:160px;border-color:var(--line2)" id="shname" value="${esc(ms.shift_name)}" placeholder="山田(名字だけ、など)"> <button class="btn sm" data-shsave>保存</button></span></div>
    <div class="hint" style="margin:2px 0 8px">シフト表の写真を「予定」の画面に落とすと、この名前の行だけを読みます。PC の中にだけ保存します</div></div>
    <div class="sset"><h3>Google</h3>
    <div class="kv"><span>Gmail</span><span>${esc(g.state)} ${g.state === '合鍵なし' ? '' : `<a class="btn sm" href="/auth/google">${g.state === '許可済み' ? '許可し直す' : 'Google と連携する'}</a>`}</span></div>
    <div class="hint" style="margin:2px 0 8px">${esc(gtext)}${ms.gmail_error ? `<br><span class="late">${esc(ms.gmail_error)}</span>` : ''}</div>
    <div class="kv"><span>カレンダー</span><span>${g.calendar ? '許可済み(予定の読み書き)' : g.state === '許可済み' ? 'まだ許可していません。上の [許可し直す] を押して、カレンダーの予定の表示と編集も許可してください' : 'Gmail と一緒に許可します'}</span></div></div>`;
}
function mochiSection() {
  const st = window.Mochi ? Mochi.settings() : {};
  const sw = (key, label, aria) => `<span class="tg"><button class="sw ${st[key] === '0' ? '' : 'on'}" data-msw="${key}" aria-label="${aria}"></button>${label}</span>`;
  return `<div class="sset"><h3>モッチ(段取りさんのキャラクター)</h3>
    <div class="kv"><span>ひとことの吹き出し</span><span>${sw('mochi_bubble', '出す(遅れている締切があるときだけ)', '吹き出しを出す')}</span></div>
    <div class="kv"><span>ひまなときに動く</span><span>${sw('mochi_idle', '動く(跳ねる・歩く・居眠りなど)', 'ひまなときに動く')}</span></div>
    <div class="kv"><span>置き場所</span><span><button class="btn sm" data-mreset>右下に戻す</button></span></div></div>`;
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
    ${await rulesSection()}
    ${await statusSection()}
    ${await mailSection()}
    ${mochiSection()}</div>`;
}


const IC_COMMIT = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="2.6"/><path d="M1.5 8h3.9M10.6 8h3.9"/></svg>';
const IC_LINK ='<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6.5 9.5 9.5 6.5M7 4.5l1-1a2.8 2.8 0 0 1 4 4l-1 1M9 11.5l-1 1a2.8 2.8 0 0 1-4-4l1-1"/></svg>';
const IC_FOLDER = '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 4.5h4l1.2 1.5H14v6.5H2z"/></svg>';
function linkBtn(l, sub) {
  const web = /^https?:\/\//.test(l.target);
  const inner = `${web ? IC_LINK : IC_FOLDER}${esc(l.name)}${sub ? `<em>${esc(sub)}</em>` : ''}`;
  return web ? `<a class="lk" href="${esc(l.target)}" target="_blank" rel="noopener">${inner}</a>` : `<button class="lk" data-lopen="${l.id}">${inner}</button>`;
}
function timeRows(list) {
  return list.length ? list.map((c) => `<div class="tl"><span>${esc(c.start)}</span><span>${kindLabel(c.name, KIND_UNI)} 授業</span></div>`).join('') : '<div class="hint">なし</div>';
}
let KIND_UNI = '#17806a';
function heldRows(list) {
  return (list || []).map((h) => `<div class="tl"><span>${esc(h.start)}</span><span>${esc(h.name)} <span class="mk mk-rep" title="Google カレンダーにつながったら書きます">預かり中</span></span></div>`).join('');
}
// 今日の時間:授業・Google の予定・預かった予定を、時刻順に混ぜる(F12)
function dayRows(classes, events, held) {
  const rows = [
    ...(classes || []).map((c) => [c.start, `<div class="tl"><span>${esc(c.start)}</span><span>${kindLabel(c.name, KIND_UNI)} 授業</span></div>`]),
    ...(events || []).map((e) => [e.start, `<div class="tl"><span>${esc(e.start)}${e.end ? '〜' + esc(e.end) : ''}</span><span>${esc(e.name)}${e.invited ? ' <span class="mk mk-pick">招待</span>' : ''}</span></div>`]),
    ...(held || []).map((h) => [h.start === '終日' ? '00:00' : h.start, heldRows([h])]),
  ].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return rows.length ? rows.map((r) => r[1]).join('') : '<div class="hint">なし</div>';
}
async function topView() {
  const t = await api('GET', '/top');
  S.top = t;
  S.c = { tasks: [...t.overdue, ...t.today_tasks, ...t.week, ...t.nodue] };
  KIND_UNI = (S.kinds || []).find((k) => k.builtin && k.name)?.color || KIND_UNI;
  const lab = (x) => kindLabel(x.label.name, x.label.color);
  const g = t.gauge;
  const pc = g.overall === null ? 0 : g.overall;
  const gline = (n, p, color) => `<div class="gauge"><span>${esc(n)}</span><div class="track"><i style="width:${p ?? 0}%;${color ? `background:${color}` : ''}"></i></div><span>${p === null ? 'タスクなし' : p + '%'}</span></div>`;
  const gauge = `<div class="sec"><button class="gauge gbtn" data-gauge aria-expanded="${S.gOpen ? 'true' : 'false'}" title="押すと、種類ごと・今日と今週にタスクがある授業・会社・開発の進み具合が開きます"><span>全体の進み具合 <span class="gar">${S.gOpen ? '▾' : '▸'}</span></span><div class="track"><i style="width:${pc}%"></i></div><span>${g.overall === null ? 'タスクなし' : pc + '%'}</span></button>
    ${S.gOpen ? `<div class="gdetail"><div class="gsub">種類ごと</div>${g.kinds.map((k) => gline(k.name, k.progress, k.color)).join('')}${g.items.length ? `<div class="gsub">今日・今週にタスクがある授業・会社・開発</div>${g.items.map((i) => gline(i.name, i.progress)).join('')}` : ''}</div>` : ''}</div>`;
  const links = t.links.length ? `<div class="sec"><div class="sh">今日のリンク</div><div class="links">${t.links.map((l) => linkBtn(l, l.container)).join('')}</div></div>` : '';
  const dq = (t.done_questions || []).map((q) => `<div class="ask1">${esc(q.container)}で終わったタスクはある?${q.tasks.map((x) => `<button class="btn sm" data-dqdone="${q.id}" data-task="${x.id}">${esc(x.name)}</button>`).join('')}<button class="btn sm" data-dqno="${q.id}">まだ</button></div>`).join('');
  const notices = t.notices.length || dq ? `<div class="sec"><div class="sh">お知らせ</div>${dq}<div class="note">${t.notices.map((n) => n.kind === 'unsorted' ? `<button data-sort>${esc(n.text)}</button>` : n.kind === 'ask' ? `<button data-go="mail" data-mcat="asks">${esc(n.text)}</button>` : n.kind === 'mail' ? `<button data-go="mail" data-mcat="mails">${esc(n.text)}</button>` : n.kind === 'held' ? `<button data-go="sched">${esc(n.text)}</button>` : n.kind === 'maybe' ? `<button data-maybe>${esc(n.text)}</button>` : `<span class="${n.kind === 'error' ? 'late' : ''}">${esc(n.text)}</span>`).join('')}</div></div>` : '';
  const over = t.overdue.length ? `<div class="sec overdue"><div class="sh">期限切れ</div>${t.overdue.map((x) => taskRow(x, lab(x))).join('')}</div>` : '';
  const sec = (title, list, empty) => `<div class="sec"><div class="sh">${title} <span class="n">${list.length}</span></div>${list.length ? list.map((x) => taskRow(x, lab(x))).join('') : `<div class="hint">${empty}</div>`}</div>`;
  const nothing = !S.c.tasks.length;
  return bar('トップ', `<span class="date">${today()}</span>`) +
    `<div class="tbody"><div class="col">${gauge}${links}${notices}${over}
      <div class="sec"><div class="rowb" style="margin-top:0"><button class="btn" data-addtop>+ タスクを足す</button><span class="hint">1行で打って足す欄(1行入力)は、あとで作ります</span></div></div>
      ${nothing ? emptyState(ILL.desk, 'まだタスクがありません', '「+ タスクを足す」か、「授業・会社・開発」の画面から足せます。') : sec('今日', t.today_tasks, '今日が締切のタスクはありません') + sec('今週', t.week, '今週が締切のタスクはありません') + sec('締切なし', t.nodue, 'なし')}</div>
      <aside class="rcol"><div class="sec"><div class="sh">今日の時間</div>${dayRows(t.classes_today, t.events_today, t.held_today)}</div><div class="sec"><div class="sh">明日の時間</div>${dayRows(t.classes_tomorrow, t.events_tomorrow, t.held_tomorrow)}</div>
      ${t.calendar_on ? '' : '<div class="hint" style="padding:10px 0">Google カレンダーは、設定の「Google」で許可するとここに混ざります。</div>'}</aside></div>`;
}
async function addTaskFromTop() {
  const ov = await api('GET', '/containers');
  const opts = ov.kinds.flatMap((k) => k.items.map((i) => `<option value="${i.id}">${esc(k.name)}:${esc(i.name)}</option>`)).join('');
  taskForm(null, '');
  const f = document.createElement('div');
  f.className = 'field';
  f.innerHTML = `<span>どれのタスク</span><select id="tcid"><option value="${ov.unsorted_id}">未分類(あとで選ぶ)</option>${opts}</select>`;
  $('#layer .modal h3').after(f);
}


async function mailViewOld() {
  const d = await api('GET', '/notices');
  S.notices = d;
  const opts = d.options.map((o) => `<option value="${o.id}">${esc(o.kind)}:${esc(o.name)}</option>`).join('');
  const card = (n) => n.kind === 'window'
    ? `<div class="qcard"><b>${esc(n.body)}</b><div class="s">初めて見た窓の名前です。一度答えれば、次からは聞きません</div>
       <div class="field"><span>覚える文字</span><input id="pat${n.id}" value="${esc(n.pattern)}"></div>
       <div class="hint">窓の名前にこの文字が入っていたら、同じ答えにします。短くすると、広く当てはまります(例:「情報科学演習」)</div>
       <div class="rowb"><select id="sel${n.id}"><option value="">どれの作業?</option>${opts}</select><button class="btn sm pri" data-ans="${n.id}">これにする</button><button class="btn sm" data-ansno="${n.id}">記録しない</button></div></div>`
    : n.kind === 'バイト先の質問'
    ? `<div class="qcard"><b>${esc(n.body)}</b><div class="s">差出人 ${esc(n.sender || '')}。応募サイトの中継アドレスです。一度答えれば、次からは聞きません</div>
       <div class="rowb"><select id="bsel${n.id}"><option value="">新しいバイト先</option>${(d.baito || []).map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join('')}</select>
       <input class="nmin" style="border-color:var(--line2)" id="bnew${n.id}" placeholder="新しいときは名前(○○カフェ)"><button class="btn sm pri" data-bans="${n.id}">これにする</button></div></div>`
    : n.kind === '候補日'
    ? `<div class="qcard"><b>${esc(n.data.text)}</b><div class="s">Claude が読み取った候補日です。相手に返事をして決まったら、その日を押すと予定に入ります</div>
       <div class="rowb">${n.data.dates.map((x, i) => `<button class="btn sm" data-cand="${n.id}" data-ci="${i}">${esc(x.date.slice(5).replace('-', '/'))}(${WEEK[new Date(x.date + 'T00:00').getDay()]}) ${esc(x.start || '')}${x.end ? '〜' + esc(x.end) : ''}</button>`).join('')}
       <button class="btn sm" data-candno="${n.id}">どれも入れない</button></div></div>`
    : n.kind === '自動で完了'
    ? `<div class="qcard"><b>${esc(n.body)}</b><div class="s">ちがうときは、「自動で完了」の欄の [戻す] で未完了に戻せます</div><div class="rowb"><button class="btn sm" data-nok="${n.id}">わかった</button><button class="btn sm" data-undo="${n.task_id}">戻す</button></div></div>`
    : `<div class="qcard"><b>${esc(n.body)}</b></div>`;
  const cats = [['asks', '確認してほしいこと', d.notices.length], ['mails', 'メール', ''], ['auto', '自動で完了', '']];
  const left = `<div class="cats">${cats.map(([k, n, c]) => `<button class="cat ${(S.mcat || 'mails') === k ? 'on' : ''} ${k === 'auto' ? 'sep' : ''}" data-mcat="${k}"><span>${n}</span><span>${c || ''}</span></button>`).join('')}</div>`;
  return bar('連絡') + `<div class="cbody">${left}<div class="list" style="grid-column:2/-1"><div class="col">
    <div class="sec"><div class="sh">確認してほしいこと <span class="n">${d.notices.length}</span></div>
    ${d.notices.length ? d.notices.map(card).join('') : '<div class="hint">今はありません。</div>'}</div>
    <div class="sec"><div class="hint">ここは、段取りさんが自分だけでは決められないことを聞く場所です。メールではなく、段取りさんからの質問とお知らせが入ります。</div></div></div></div></div>`;
}
async function maybeModal() {
  const list = await api('GET', '/maybe-done');
  if (!list.length) { closeModal(); return render(); }
  modal(`<h3>終わっていそうなタスク</h3><div class="hint" style="margin-bottom:8px">Claude がメール・コミット・作業時間を見て、終わっていそうだと考えたものです。終わっていたら [完了] を押してください</div>
    ${list.map((m) => `<div class="mrow"><div class="an"><b>${esc(m.name)}</b><span class="cm">${esc(m.container)} ・ ${esc(m.reason)}</span></div><button class="btn sm pri" data-mbyes="${m.id}">完了</button><button class="btn sm" data-mbno="${m.id}">ちがう</button></div>`).join('')}
    <div class="acts"><button class="btn" data-close>閉じる</button></div>`);
}
function logForm(l) {
  const v = (iso) => (iso ? iso.slice(0, 16) : '');
  modal(`<h3>${l ? '記録を直す' : '記録を足す'}</h3>
    <div class="field"><span>始まり</span><input id="lgs" type="datetime-local" value="${v(l && l.started_at)}"></div>
    <div class="field"><span>終わり</span><input id="lge" type="datetime-local" value="${v(l && l.ended_at)}"></div>
    <div class="field"><span>内容(なくてもよい)</span><input id="lgn" value="${esc(l ? l.note || '' : '')}" placeholder="第2章を書いた"></div>
    <div class="acts">${l ? `<button class="btn danger l" data-logdel="${l.id}">消す</button>` : ''}<button class="btn" data-close>やめる</button><button class="btn pri" data-logsave="${l ? l.id : ''}">${l ? '保存' : '足す'}</button></div>`);
}

const CATN = { 授業: '授業', 奨学金: '奨学金', 試合のチケット: '試合のチケット', 企業: '企業', アルバイト: 'アルバイト', その他: 'その他' };
async function mailView() {
  const sum = await api('GET', '/messages/summary?open=1');
  S.newMail = 0;
  const cat = S.mcat || 'mails';
  const cats = [['asks', '確認してほしいこと', sum.asks], ['mails', 'メール', ''], ['auto', '自動で完了', sum.auto || '']];
  const left = `<div class="cats">${cats.map(([k, n, c]) => `<button class="cat ${cat === k ? 'on' : ''} ${k === 'auto' ? 'sep' : ''}" data-mcat="${k}"><span>${n}</span><span>${c || ''}</span></button>`).join('')}</div>`;
  let mid = '', right = '';
  if (cat === 'asks') {
    const html = await mailViewOld();
    return html;
  } else if (cat === 'auto') {
    const a = await api('GET', `/auto-done${S.autoBefore ? `?before=${encodeURIComponent(S.autoBefore)}` : ''}`);
    const by = { 提出受付: '提出の受付メール', Forms: 'Forms の応答', エントリー受付: 'エントリー受付', コミット: 'コミット' };
    mid = a.items.length ? `<div class="col"><div class="sec"><div class="sh">自動で完了にしたタスク</div>${a.items.map((x) => `<div class="adone"><div class="an"><b>${esc(x.name)}</b><span class="cm">${esc(x.container)} ・ ${esc((x.done_at || '').replace('T', ' ').slice(5, 16))} ・ ${esc(by[x.auto_done_by] || x.auto_done_by)}</span>${x.body ? `<span class="cm src">${esc(x.body.split('もとになったもの: ')[1] || '')}</span>` : ''}</div><button class="btn sm" data-undo="${x.id}">戻す</button></div>`).join('')}
      ${a.more ? `<div class="rowb"><button class="btn sm" data-automore="${esc(a.items[a.items.length - 1].done_at)}">もっと見る</button></div>` : ''}</div>
      <div class="sec"><div class="hint">提出の受付メール・Forms の応答・企業からのエントリー受付・コミットの「完了:」を見つけて、段取りさんが完了にしたタスクです。[戻す] を押すと未完了に戻り、カレンダーの「済」も消えます。</div></div></div>`
      : emptyState(ILL.env, 'まだありません', '提出の受付メールや、コミットの「完了:」を見つけて完了にしたタスクが、ここに並びます。');
  } else {
    const d = await api('GET', '/messages');
    S.mails = d;
    const row = (m) => `<button class="mail ${S.mail === m.id ? 'on' : ''}" data-mail="${m.id}"><div class="f"><span class="mk mk-pick" style="margin:0">${esc(m.container || CATN[m.category] || m.category)}</span><span class="from">${esc(m.sender.split('@')[0])}</span><span>${esc(m.received_at.slice(5, 10).replace('-', '/'))}</span></div><div class="s">${esc(m.subject)}${m.ai_failed ? ' <span class="mk mk-warn">読み取れなかった</span>' : ''}</div></button>`;
    mid = (d.main.length ? d.main.map(row).join('') : '<div class="hint" style="padding:12px 14px">授業・奨学金などのメールは、まだありません。</div>') +
      `<button class="mail" data-mother style="color:var(--sub)"><div class="f"><span>その他の大学のお知らせ ${d.other.length}件 ${S.otherOpen ? '▾' : '▸'}</span></div><div class="s">授業・奨学金・試合のチケットに当てはまらない大学からのメール(学内連絡の一斉配信など)</div></button>` +
      (S.otherOpen ? d.other.map(row).join('') : '');
    if (S.mail) {
      try {
        const m = await api('GET', `/messages/${S.mail}`);
        S.mailDetail = m;
        const body = m.body_gone ? '<p class="hint">本文は90日で消えています。Outlook または Gmail で開いてください。</p>' : `<div class="mbody">${esc(m.body).slice(0, 20000)}</div>`;
        const links = m.links.length ? `<div class="sh" style="margin-top:12px">本文の中のリンク</div><div class="links">${m.links.slice(0, 8).map((u) => `<a class="lk" href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\//, '').slice(0, 40))}</a>`).join('')}</div>` : '';
        const made = m.tasks.length || m.held.length ? `<div class="sh" style="margin-top:12px">このメールから入ったもの</div>${m.tasks.map((t) => `<div class="tl"><span>タスク</span><span>${esc(t.name)} ${esc(t.due_date || '')} ${esc(t.due_time || '')} <button class="link danger" data-mtdel="${t.id}">消す</button></span></div>`).join('')}${m.held.map((h) => `<div class="tl"><span>予定</span><span>${esc(h.title)} ${esc(h.start_at.replace('T', ' '))} <button class="link danger" data-hdel="${h.id}">消す</button></span></div>`).join('')}` : '';
        right = `<div class="reader"><h2>${esc(m.subject)}</h2><div class="meta">${esc(CATN[m.category] || m.category)} ・ ${esc(m.sender)} ・ ${esc(m.received_at.replace('T', ' ').slice(0, 16))}${m.container ? ' ・ ' + esc(m.container) : ''}</div>${body}${links}${made}
          <div class="acts mact"><div><button class="btn sm" data-mresort="${m.id}">振り分けを直す</button><span>このメールは「${esc(m.container || 'その他')}」に振り分けられています。ちがうときに直します。次から、この差出人のメールは直したほうに入ります</span></div>
          <div><button class="btn sm" data-mblock="${esc(m.sender)}">この差出人は取り込まない</button><span>宣伝など、いらない差出人のときに押します。次から、この差出人のメールは段取りさんに入りません。メールそのものは消えず、設定の「止めた差出人」から戻せます</span></div></div></div>`;
      } catch (e) { S.mail = null; }
    }
    if (!right) right = `<div class="reader"><div class="empty" style="padding-top:60px">${ILL.env}<span>メールを選んでください</span></div></div>`;
  }
  return bar('連絡', sum.error ? `<span class="date late">${esc(sum.error)}</span>` : '<span class="date">10分ごとに読みます</span>') +
    `<div class="cbody">${left}<div class="list">${mid}</div>${right}</div>`;
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
    if (d.go) { if (d.mcat) S.mcat = d.mcat; go(d.go); return; }
    if (d.ans) { await api('POST', `/notices/${d.ans}/answer`, { container_id: +$('#sel' + d.ans).value || null, pattern: $('#pat' + d.ans).value }); toast('答えを覚えました'); render(); return; }
    if (d.ansno) { await api('POST', `/notices/${d.ansno}/answer`, { ignore: true, pattern: $('#pat' + d.ansno).value }); toast('この窓は記録しません'); render(); return; }
    if (d.dqdone) { await api('POST', `/done-questions/${d.dqdone}`, { task_id: +d.task }); toast('完了にしました'); render(); return; }
    if (d.dqno) { await api('POST', `/done-questions/${d.dqno}`, {}); render(); return; }
    if (d.logadd !== undefined) { logForm(null); return; }
    if (d.logedit) { logForm(S.logs.find((l) => l.id === +d.logedit)); return; }
    if (d.logsave !== undefined) {
      const data = { started_at: $('#lgs').value, ended_at: $('#lge').value, note: $('#lgn').value };
      if (d.logsave) await api('PATCH', `/work-logs/${d.logsave}`, data); else await api('POST', '/work-logs', { ...data, container_id: S.cont });
      closeModal(); toast(d.logsave ? '直しました' : '足しました'); render(); return;
    }
    if (d.logdel) {
      if (!el.dataset.sure) { el.dataset.sure = '1'; el.textContent = 'ほんとうに消す'; return; }
      await api('DELETE', `/work-logs/${d.logdel}`); closeModal(); toast('消しました'); render(); return;
    }
    if (d.rdel) { await api('DELETE', `/window-rules/${d.rdel}`); toast('消しました。次に見たときにまた聞きます'); render(); return; }
    if (d.msw) { await Mochi.set({ [d.msw]: el.classList.contains('on') ? '0' : '1' }); render(); return; }
    if (d.mreset !== undefined) { await Mochi.resetPos(); toast('モッチを右下に戻しました'); return; }
    if (d.mcat) { S.mcat = d.mcat; S.mail = null; S.autoBefore = null; render(); return; }
    if (d.automore) { S.autoBefore = d.automore; render(); return; }
    if (d.undo) { await api('POST', `/auto-done/${d.undo}/undo`); toast('未完了に戻しました'); render(); return; }
    if (d.nok) { await api('POST', `/notices/${d.nok}/answer`, {}); render(); return; }
    if (d.maybe !== undefined) { await maybeModal(); return; }
    if (d.mbyes || d.mbno) { await api('POST', `/maybe-done/${d.mbyes || d.mbno}`, { done: !!d.mbyes }); toast(d.mbyes ? '完了にしました' : 'このタスクは、しばらく聞きません'); await maybeModal(); return; }
    if (d.mother !== undefined) { S.otherOpen = !S.otherOpen; render(); return; }
    if (d.mail) { S.mail = +d.mail; render(); return; }
    if (d.mresort) {
      const ov = await api('GET', '/containers');
      const opts = ov.kinds.flatMap((k) => k.items.map((i) => `<option value="${i.id}">${esc(k.name)}:${esc(i.name)}</option>`)).join('');
      modal(`<h3>振り分けを直す</h3><div class="hint">このメールと、同じ差出人からこれから届くメールを、選んだところに振り分けます。このメールから入ったタスクも移します。</div>
        <div class="field"><span>振り分け先</span><select id="mrs"><option value="">どれでもない(その他)</option>${opts}</select></div>
        <div class="acts"><button class="btn" data-close>やめる</button><button class="btn pri" data-mresortok="${d.mresort}">直す</button></div>`);
      return;
    }
    if (d.mresortok) { await api('PATCH', `/messages/${d.mresortok}`, { container_id: +$('#mrs').value || null }); closeModal(); toast('振り分けを直しました。次からこの差出人は、直したほうに入ります'); render(); return; }
    if (d.mblock) {
      modal(`<h3>この差出人を取り込まないようにしますか?</h3><div style="font-size:12.5px;line-height:1.7">${esc(d.mblock)}<br>次から、この差出人のメールは段取りさんに入らなくなります。<br>メールそのものは消えません。設定の「止めた差出人」から、いつでも戻せます。</div>
        <div class="acts"><button class="btn" data-close>やめる</button><button class="btn pri" data-mblockok="${esc(d.mblock)}">取り込まない</button></div>`);
      return;
    }
    if (d.mblockok) { await api('POST', '/blocked-senders', { address: d.mblockok }); closeModal(); toast('この差出人を止めました(設定から戻せます)'); return; }
    if (d.mtdel) { await api('DELETE', `/tasks/${d.mtdel}`); toast('消しました。次に読んでも戻しません'); render(); return; }
    if (d.aibadge) {
      const a = await api('GET', `/tasks/${d.aibadge}/ai`);
      modal(`<h3>Claude が読み取りました</h3><div class="hint">もとのメール:${esc(a.subject || '(なし)')}</div><p class="quote">${esc(a.excerpt || '')}</p>
        <div class="hint">まちがっていたら、タスクを直してください。直すか「確認した」を押すと、札が消えます。</div>
        <div class="acts"><button class="btn" data-close>閉じる</button><button class="btn pri" data-aiok="${d.aibadge}">確認した</button></div>`);
      return;
    }
    if (d.aiok) { await api('POST', `/tasks/${d.aiok}/ai-checked`); closeModal(); render(); return; }
    if (d.bdel) { await api('DELETE', `/blocked-senders/${d.bdel}`); toast('外しました'); render(); return; }
    if (d.btadd !== undefined) {
      modal(`<h3>バイト先を足す</h3><div class="field"><span>名前</span><input id="btn0" placeholder="○○カフェ 博多店"></div>
        <div class="field"><span>@ から後ろ(お店から直接届くときだけ)</span><input id="btd0" placeholder="example.co.jp"></div>
        <div class="acts"><button class="btn" data-close>やめる</button><button class="btn pri" data-btsave>足す</button></div>`);
      return;
    }
    if (d.btsave !== undefined) { await api('POST', '/baito', { name: $('#btn0').value, domain: $('#btd0').value }); closeModal(); toast('足しました'); render(); return; }
    if (d.btdel) { await api('DELETE', `/baito/${d.btdel}`); toast('消しました'); render(); return; }
    if (d.bans) {
      const v = $('#bsel' + d.bans).value, nm = $('#bnew' + d.bans).value;
      await api('POST', `/notices/${d.bans}/answer`, v ? { baito_id: +v } : { name: nm });
      toast('覚えました。次から、このアドレスは自動でつけます'); render(); return;
    }
    if (d.cand !== undefined && d.ci !== undefined) { await api('POST', `/notices/${d.cand}/answer`, { index: +d.ci }); toast('予定に入れました'); render(); return; }
    if (d.candno) { await api('POST', `/notices/${d.candno}/answer`, { none: true }); toast('入れずに閉じました'); render(); return; }
    if (d.hdel) { await api('DELETE', `/held-events/${d.hdel}`); toast('消しました。次に読んでも戻しません'); render(); return; }
    if (d.shsave !== undefined) { await api('PATCH', '/settings/mail', { shift_name: $('#shname').value }); toast('保存しました'); render(); return; }
    if (d.domsave !== undefined) { await api('PATCH', '/settings/mail', { university_domain: $('#udom').value }); toast('保存しました。次の読み込みから使います'); render(); return; }
    if (d.gauge !== undefined) { S.gOpen = !S.gOpen; render(); return; }
    if (d.addtop !== undefined) { await addTaskFromTop(); return; }
    if (d.lopen) { await api('POST', `/links/${d.lopen}/open`); toast('開きました'); return; }
    if (d.topen) { await api('POST', `/tasks/${d.topen}/open`); toast('開きました'); return; }
    if (d.ladd !== undefined) {
      modal(`<h3>リンクを足す</h3><div class="field"><span>名前</span><input id="lname" placeholder="学習サイト"></div>
        <div class="field"><span>URL か PC の場所</span><input id="ltarget" placeholder="https://… または C:\\Users\\…"></div>
        <div class="hint">PC のフォルダやファイル(Word の原稿など)の場所も入れられます。押すと、その場所が開きます。</div>
        <div class="acts"><button class="btn" data-close>やめる</button><button class="btn pri" data-lsubmit>足す</button></div>`);
      return;
    }
    if (d.lsubmit !== undefined) { await api('POST', '/links', { container_id: S.cont, name: $('#lname').value, target: $('#ltarget').value }); closeModal(); render(); return; }
    if (d.ldel) { await api('DELETE', `/links/${d.ldel}`); toast('消しました'); render(); return; }
    if (d.lalways !== undefined) { await api('PATCH', `/containers/${S.cont}`, { links_always_top: !el.classList.contains('on') }); render(); return; }
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
      else await api('POST', '/tasks', { ...data, container_id: +($('#tcid') ? $('#tcid').value : d.cid) });
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
    if (d.csave !== undefined) {
      await api('PATCH', `/containers/${S.cont}`, { name: $('#cname').value, kind_id: +$('#ckind').value, ...($('#cdom') ? { company_domain: $('#cdom').value } : {}),
        repo_path: $('#crepo').value, repo_subdir: $('#crsub').value, ...($('#cdesc') ? { own_description: $('#cdesc').value } : {}), ...($('#cstate') ? { dev_state: $('#cstate').value } : {}) });
      toast('保存しました'); render(); return;
    }
    if (d.cmdel) {
      if (!el.dataset.sure) { el.dataset.sure = '1'; el.textContent = 'ほんとうに消す(戻ってきません)'; return; }
      await api('DELETE', `/commits/${d.cmdel}`); toast('消しました'); render(); return;
    }
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
    if (t.dataset.rpat) { await api('PATCH', `/window-rules/${t.dataset.rpat}`, { pattern: t.value }); toast('覚える文字を直しました'); }
    if (t.dataset.kname) { await api('PATCH', `/kinds/${t.dataset.kname}`, { name: t.value }); S.kinds = null; toast('種類の名前を変えました'); }
    if (t.dataset.btname) { await api('PATCH', `/baito/${t.dataset.btname}`, { name: t.value }); toast('直しました'); }
    if (t.dataset.btdom !== undefined) { await api('PATCH', `/baito/${t.dataset.btdom}`, { domain: t.value }); toast('直しました'); }
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

refreshRec();
refreshNewMail();
(function start() {
  const h = location.hash.slice(1);
  if (h.startsWith('inside-')) { S.cont = +h.slice(7); S.screen = 'inside'; }
  else if (VIEWS[h]) S.screen = h;
  render();
})();
