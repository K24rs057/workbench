// モッチ(F22・S7)。右下にいて、押すと吹き出しで話す。サイドバーにも移せる。押したまま動かすと運べる。
// 動きと見た目は UI 試作(版23)と同じ。答えは本体が claude -p で作る(A34)。
(function () {
  const M = { open: false, mode: 'bubble', log: [], busy: false, bub: null, justSaid: false, settings: {}, pos: null, wantFocus: false };
  const W = 58, H = 71;
  const SCREEN_NAMES = { top: 'トップ', sched: '予定', mail: '連絡', cont: '授業・会社・開発の一覧', inside: '授業・会社・開発の中', set: '設定' };
  const IMG = (n) => `/assets/character/dandori-${n}.png`;
  const MOCHI = (cls = '', talk = false) => `<span class="mchar ${cls} ${talk ? 'talking' : ''}"><img class="m-n" src="${IMG('normal')}" alt=""><img class="m-b" src="${IMG('blink')}" alt=""><img class="m-t" src="${IMG('talk')}" alt=""></span>`;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  const q = (s) => document.querySelector(s);
  let idleAt = Date.now();

  async function call(method, path, data) {
    const res = await fetch('/api' + path, { method, headers: data ? { 'Content-Type': 'application/json' } : {}, body: data ? JSON.stringify(data) : undefined });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json.error || 'うまくいきませんでした');
    return json;
  }
  const cur = () => (typeof S !== 'undefined' ? S.screen : 'top');
  const screenName = () => SCREEN_NAMES[cur()] || 'トップ';
  function suggestions() {
    const s = cur();
    if (s === 'inside') return ['このタスクを小さく分けて', 'ここは今週何時間やった?', '使い方を教えて'];
    if (s === 'mail') return ['確認してほしいことって何?', '使い方を教えて'];
    return ['今日はまず何をすればいい?', '今週は何時間作業した?', '使い方を教えて'];
  }

  // ---------- 置き場所 ----------
  const narrow = () => innerWidth <= 760;
  function mascotPos() {
    const nar = narrow();
    const bot = nar ? 62 : 4;
    const p = M.pos || { x: innerWidth - W - 16, y: innerHeight - H - (nar ? 86 : 10) };
    return { x: Math.max(4, Math.min(innerWidth - W - 4, p.x)), y: Math.max(4, Math.min(innerHeight - H - bot, p.y)) };
  }
  function placeNear(el, pos) {
    if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    let below = false, top = pos.y - h - 14;
    if (top < 8) { top = pos.y + H + 14; below = true; }
    top = Math.max(8, Math.min(innerHeight - h - 8, top));
    const left = Math.max(8, Math.min(innerWidth - w - 8, pos.x + 29 - w + 40));
    el.style.left = left + 'px'; el.style.top = top + 'px';
    el.classList.toggle('below', below);
    el.style.setProperty('--tx', Math.max(12, Math.min(w - 24, pos.x + 29 - left - 7)) + 'px');
    el.style.visibility = 'visible';
  }
  function loadPos() {
    const raw = M.settings[narrow() ? 'mochi_pos_narrow' : 'mochi_pos_wide'];
    try { M.pos = raw ? JSON.parse(raw) : null; } catch (e) { M.pos = null; }
  }
  function savePos() {
    call('PATCH', '/mochi', { [narrow() ? 'mochi_pos_narrow' : 'mochi_pos_wide']: M.pos ? JSON.stringify({ x: Math.round(M.pos.x), y: Math.round(M.pos.y) }) : '' }).catch(() => {});
  }

  // ---------- 描く ----------
  const dots = '<span class="dots3"><i></i><i></i><i></i></span>';
  function msgHtml(m) {
    if (m.role === '自分') return `<div class="cm me">${esc(m.text)}</div>`;
    const r = m.run;
    if (r && r.state === '動いている') {  // 終わった手を ✓ で積み上げ、いちばん下に今やっていること(モッチ-3 B)
      const p = r.progress || [];
      return `<div class="cm ai"><div class="prog">${p.slice(0, -1).map((x) => `<span class="past">${esc(x)}</span>`).join('')}<span class="now">${dots}${esc(p.length ? p[p.length - 1] + '…' : '考えています…')}</span></div></div>`;
    }
    let extra = '';
    if (r && (r.done.length || r.undone.length)) {
      extra += `<div class="did"><div class="h">やったこと</div><ul>${r.done.map((x) => `<li>${esc(x)}</li>`).join('')}${r.undone.map((x) => `<li class="und">${esc(x)}(元に戻した)</li>`).join('')}</ul>${r.undoable ? `<button class="link" data-mundo="${r.id}">元に戻す</button>` : ''}</div>`;
    }
    if (r && r.pending.length) {
      extra += r.pending.map((a) => `<div class="okcard"><div class="h">やっていい?</div><div>${esc(a.preview)}</div><div class="row"><button class="btn pri sm" data-mok="${a.id}">する</button><button class="btn sm" data-mno="${a.id}">やめる</button></div></div>`).join('');
    }
    return `<div class="cm ai ${m.state === 'あいさつ' ? 'greet' : ''}">${esc(m.text).replace(/\n/g, '<br>')}${extra}</div>`;
  }
  const running = () => M.log.some((m) => m.run && m.run.state === '動いている');
  let polling = false;
  async function poll() {
    if (polling) return;
    polling = true;
    while (running()) {
      await new Promise((r) => setTimeout(r, 1000));
      try { M.log = await call('GET', '/agent/messages'); } catch (e) { break; }
      M.busy = running(); render();
    }
    polling = false;
    M.busy = false; M.justSaid = true; render();
    setTimeout(() => { M.justSaid = false; render(); }, 1600);
    if (window.render) window.render();  // モッチが変えたものを画面にも出す
  }
  function render() {
    const host = q('#agent');
    if (!host) return;
    const had = q('#agin'), val = had ? had.value : '', foc = had && document.activeElement === had;
    const side = M.open && M.mode === 'side';
    const talk = !!M.bub || M.busy || M.justSaid;
    const logH = (M.log.length ? '' : '<div class="cm ai">なにか手伝う? 頼まれたら、調べて、やって、終わったら報告するよ。<div class="src">消す・予定を足すときは、先に確認するよ。やったことは元に戻せるよ</div></div>') +
      M.log.map(msgHtml).join('') + (M.busy && !running() ? `<div class="cm ai wait">${dots}</div>` : '');
    const sugH = `<div class="csug">${suggestions().map((x) => `<button data-mq="${esc(x)}">${esc(x)}</button>`).join('')}</div>`;
    const inH = '<div class="cin"><input id="agin" placeholder="モッチに話しかける" autocomplete="off" aria-label="モッチに話しかける"><button class="send" data-msend aria-label="送る"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15.5v-11M5.5 9 10 4.5 14.5 9"/></svg></button></div>';
    const newB = M.log.length ? '<button data-mnew>新しく話す</button>' : '';
    const app = q('.app'), sp = q('#agp');
    app.classList.toggle('ag', side);
    sp.hidden = !side;
    sp.innerHTML = side ? `<div class="aghd">${MOCHI('mface', M.busy)}モッチ<span class="sideb">${newB}<button data-mbubble title="モッチの吹き出しに戻す">吹き出しに戻す</button></span></div><div class="agctx">${esc(screenName())}を見ています</div><div class="aglog clog" id="aglog">${logH}</div>${sugH}${inH}` : '';
    const chat = M.open && !side
      ? `<div class="chat" id="chat" role="dialog" aria-label="モッチと話す"><div class="chd"><b>モッチ</b><span class="ctx">${esc(screenName())}を見ています</span><span class="chr">${newB}<button data-mside title="右のサイドバーに移す">サイドバーに移す</button></span></div><div class="clog" id="aglog">${logH}</div>${sugH}${inH}</div>`
      : (!M.open && M.bub ? `<div class="bub" id="bub" role="status"><button data-mbubopen style="text-align:left">${esc(M.bub)}</button><button class="x" data-mbubx aria-label="吹き出しを消す">×</button></div>` : '');
    const pos = mascotPos();
    host.innerHTML = chat + (side ? '' : `<button class="mascot" data-mopen aria-label="モッチと話す(押したまま動かすと運べます)" aria-expanded="${M.open}" title="モッチ(押すと話せます。押したまま動かすと好きな場所に運べます)" style="left:${pos.x}px;top:${pos.y}px">${MOCHI('', talk)}${!M.open && M.log.length ? '<span class="keep" title="話の続きがあります"></span>' : ''}</button>`);
    placeNear(q('#chat'), pos); placeNear(q('#bub'), pos);
    if (M.open) {
      const lg = q('#aglog'); lg.scrollTop = lg.scrollHeight;
      const inp = q('#agin'); inp.value = val;
      if (foc || M.wantFocus) { inp.focus(); M.wantFocus = false; }
    }
  }

  // ---------- 話す ----------
  async function ask(text) {
    text = (text || '').trim();
    if (!text || M.busy || running()) return;
    M.log.push({ role: '自分', text, id: -1 });
    M.busy = true; M.wantFocus = true; render();
    try { M.log = await call('POST', '/agent/ask', { text, screen: screenName() }); }
    catch (e) { M.log.push({ role: 'モッチ', text: e.message, id: -2 }); M.busy = false; render(); return; }
    render();
    poll();
  }
  async function action(id, what) {
    try { M.log = await call('POST', `/agent/actions/${id}/${what}`); } catch (e) { M.log.push({ role: 'モッチ', text: e.message, id: -3 }); }
    render();
    if (what === 'confirm' && window.render) window.render();
  }
  async function undo(runId) {
    try { M.log = await call('POST', `/agent/runs/${runId}/undo`); } catch (e) { M.log.push({ role: 'モッチ', text: e.message, id: -4 }); }
    render();
    if (window.render) window.render();
  }
  async function greet() {  // その日最初に開いたときだけ、今日の段取りを短く話す(S7-7)
    try { M.log = await call('POST', '/agent/greeting'); render(); } catch (e) { /* 本体が止まっているとき */ }
  }

  // ---------- 押したとき ----------
  document.addEventListener('click', async (e) => {
    if (M.open && M.mode !== 'side' && !e.target.closest('.chat,.mascot,.ov,.toast')) { M.open = false; render(); }
    const el = e.target.closest('button');
    if (!el) return;
    const d = el.dataset;
    if (d.mopen !== undefined) {
      if (M.dragged) return;
      M.open = !M.open; M.bub = null; M.wantFocus = M.open; render();
      if (M.open) greet();
      return;
    }
    if (d.mundo) { undo(d.mundo); return; }
    if (d.mq) { ask(d.mq); return; }
    if (d.msend !== undefined) { const i = q('#agin'); const v = i.value; i.value = ''; M.wantFocus = true; ask(v); return; }
    if (d.mok) { action(d.mok, 'confirm'); return; }
    if (d.mno) { action(d.mno, 'cancel'); return; }
    if (d.mnew !== undefined) { M.log = await call('DELETE', '/agent/messages'); M.wantFocus = true; render(); return; }
    if (d.mside !== undefined) { M.mode = 'side'; M.wantFocus = true; render(); return; }
    if (d.mbubble !== undefined) { M.mode = 'bubble'; M.wantFocus = true; render(); return; }
    if (d.mbubx !== undefined) { M.bub = null; render(); return; }
    if (d.mbubopen !== undefined) { M.bub = null; M.open = true; M.wantFocus = true; render(); return; }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && M.open && M.mode !== 'side' && !q('.ov')) { M.open = false; render(); return; }
    if (e.key === 'Enter' && !e.isComposing && e.target.id === 'agin') { const v = e.target.value; e.target.value = ''; M.wantFocus = true; ask(v); }
  });

  // ---------- 運ぶ ----------
  let DG = null;
  document.addEventListener('pointerdown', (e) => {
    const m = e.target.closest('.mascot');
    if (!m || e.button !== 0) return;
    const r = m.getBoundingClientRect();
    DG = { m, sx: e.clientX, sy: e.clientY, ox: e.clientX - r.left, oy: e.clientY - r.top, moved: false };
    m.setPointerCapture(e.pointerId);
  });
  document.addEventListener('pointermove', (e) => {
    if (!DG) return;
    if (!DG.moved) {
      if (Math.hypot(e.clientX - DG.sx, e.clientY - DG.sy) < 5) return;
      DG.moved = true;
      DG.m.classList.remove('hop', 'sway', 'peek', 'stretch', 'doze', 'walk', 'right', 'land');
      DG.m.querySelectorAll('.zz').forEach((z) => z.remove());
      DG.m.classList.add('panic', 'grab');
      DG.m.insertAdjacentHTML('beforeend', '<span class="ah">わわっ</span>');
      q('#agent').classList.add('dragging');
    }
    const x = Math.max(4, Math.min(innerWidth - W - 4, e.clientX - DG.ox));
    const y = Math.max(4, Math.min(innerHeight - H - 4, e.clientY - DG.oy));
    DG.m.style.left = x + 'px'; DG.m.style.top = y + 'px'; DG.x = x; DG.y = y;
  });
  document.addEventListener('pointerup', () => {
    if (!DG) return;
    const d = DG; DG = null;
    if (!d.moved) return;
    M.pos = { x: d.x, y: d.y }; M.dragged = true; setTimeout(() => { M.dragged = false; }, 0);
    idleAt = Date.now();
    q('#agent').classList.remove('dragging');
    savePos(); render();
    const m = q('.mascot');
    if (m) { m.classList.add('land'); setTimeout(() => m.classList.remove('land'), 500); }
  });

  // ---------- ひまなとき ----------
  ['click', 'keydown', 'mousemove'].forEach((ev) => document.addEventListener(ev, () => { idleAt = Date.now(); }, { passive: true }));
  function walk(m) {
    const p = mascotPos();
    let dir = Math.random() < 0.5 ? -1 : 1;
    const dist = 50 + Math.random() * 80;
    if (p.x + dir * dist < 8 || p.x + dir * dist > innerWidth - 66) dir = -dir;
    const to = Math.max(8, Math.min(innerWidth - 66, p.x + dir * dist));
    m.classList.add('walk'); if (dir > 0) m.classList.add('right');
    const t0 = performance.now(), dur = Math.abs(to - p.x) * 18;
    const step = (t) => {
      if (!m.isConnected || DG) { m.classList.remove('walk', 'right'); return; }
      const k = Math.min(1, (t - t0) / dur);
      const x = p.x + (to - p.x) * k;
      m.style.left = x + 'px'; M.pos = { x, y: p.y };
      if (k < 1) setTimeout(() => step(performance.now()), 30); else { m.classList.remove('walk', 'right'); savePos(); }
    };
    step(performance.now());
  }
  setInterval(() => {
    const m = q('.mascot');
    if (!m || M.open || M.bub || m.className !== 'mascot' || M.settings.mochi_idle === '0') return;
    const quiet = Date.now() - idleAt;
    if (quiet < 5000) return;
    const acts = quiet > 40000 ? ['doze', 'doze', 'stretch'] : ['hop', 'sway', 'peek', 'stretch', 'walk', 'walk'];
    const a = acts[Math.floor(Math.random() * acts.length)];
    if (a === 'walk') { walk(m); return; }
    m.classList.add(a);
    if (a === 'doze') m.insertAdjacentHTML('beforeend', '<span class="zz">z</span><span class="zz">z</span>');
    setTimeout(() => { m.classList.remove(a); m.querySelectorAll('.zz').forEach((z) => z.remove()); }, a === 'doze' ? 4200 : 2300);
  }, 6500);

  // ---------- ひとこと(S7-4) ----------
  let hintShownFor = null;
  async function checkHint() {
    try {
      const r = await call('GET', '/mochi');
      M.settings = r.settings;
      if (r.hint && r.hint !== hintShownFor && M.settings.mochi_bubble !== '0' && !M.open) {
        hintShownFor = r.hint; M.bub = r.hint; render();
        setTimeout(() => { M.bub = null; render(); }, 9000);
      }
    } catch (e) { /* 本体が止まっているときは何もしない */ }
  }

  // ---------- 設定から使う ----------
  window.Mochi = {
    settings: () => M.settings,
    async set(values) { const r = await call('PATCH', '/mochi', values); M.settings = r.settings; loadPos(); render(); },
    async resetPos() { M.pos = null; await this.set({ mochi_pos_wide: '', mochi_pos_narrow: '' }); },
    render,
  };

  let lastNarrow = narrow();
  window.addEventListener('resize', () => { if (narrow() !== lastNarrow) { lastNarrow = narrow(); loadPos(); } render(); });

  (async function start() {
    try {
      const r = await call('GET', '/mochi');
      M.settings = r.settings;
      M.log = await call('GET', '/agent/messages');
    } catch (e) { /* 本体が止まっているとき */ }
    loadPos(); render();
    if (running()) { M.busy = true; poll(); }  // 開き直したとき、まだ動いている頼みがあれば続きを待つ
    setTimeout(checkHint, 3500);
    setInterval(checkHint, 10 * 60 * 1000);
  })();
})();
