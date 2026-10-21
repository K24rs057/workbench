// 予定の画面(要件 F19、基本設計 S2)。予定の本体は Google カレンダー。ここでは見る・足す・直す・消す。
(function () {
  const pad = (n) => String(n).padStart(2, '0');
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const parse = (s) => new Date(s + 'T00:00');
  const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
  const md = (s) => `${+s.slice(5, 7)}/${+s.slice(8, 10)}(${WEEK[parse(s).getDay()]})`;
  const GRAY = '#8a8f98';
  const lab = (l) => (l ? kindLabel(l.name, l.color) : '');

  S.sv = S.sv || 'list';
  S.slist = S.slist || isoToday();          // 一覧の始まりの日(今日から2週間)
  S.smonth = S.smonth || isoToday().slice(0, 7);

  function range(month) {
    if (S.sv === 'list' && !month) { const a = parse(S.slist); return [iso(a), iso(addDays(a, 13))]; }
    const first = parse((month || S.smonth) + '-01');
    const start = addDays(first, -first.getDay());
    const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
    return [iso(start), iso(addDays(last, 6 - last.getDay()))];
  }

  const md0 = (s) => `${+s.slice(5, 7)}/${+s.slice(8, 10)}`;
  // 何日も続く予定は、始まりの日は「18:00〜」、終わりの日は「〜01:00」、間の日と終日は「終日」
  const tm = (i) => {
    if (i.type === 'task') return `締切${i.start ? ' ' + esc(i.start) : ''}`;
    if (i.multi && !i.all_day) return i.pos === 'first' ? `${esc(i.start)}〜` : i.pos === 'last' ? `〜${esc(i.end)}` : '終日';
    return i.start ? `${esc(i.start)}${i.end ? '〜' + esc(i.end) : ''}` : '終日';
  };
  const evColor = (i) => (i.label && i.label.color) || 'var(--gcal)';  // 授業・会社・開発に結びつけた予定だけ種類の色(2026-10-21 決定 C)
  const isBar = (i) => i.type === 'event' && (i.all_day || i.multi);

  function row(i) {
    if (i.type === 'task') {
      const del = i.calendar_deleted ? ' <span class="mk mk-warn" title="Google カレンダーで消されました。もう書きません">カレンダーから消されました</span>' : '';
      return `<div class="ev"><span class="tm">${tm(i)}</span>${lab(i.label)}<span style="${i.done ? 'text-decoration:line-through;color:var(--faint)' : ''}">${esc(i.name)}${del}</span><button class="ck ${i.done ? 'on' : ''}" data-done="${i.id}" aria-label="${i.done ? '完了を外す' : '完了にする'}"></button></div>`;
    }
    if (i.type === 'held') {
      const why = i.reason === '重なる予定がある' ? '重なる予定があるため書いていません' : i.reason === 'つながらなかった' ? 'つながったら書きます' : 'カレンダーに書く前です';
      return `<div class="ev"><span class="tm">${tm(i)}</span>${lab(i.label)}<span>${esc(i.name)} <button class="mk mk-rep" data-heldlist title="${why}">預かり中</button></span><span></span></div>`;
    }
    return `<div class="ev"><span class="tm">${tm(i)}</span>${lab(i.label)}<button class="evn" data-evopen="${esc(i.id)}">${esc(i.name)}${i.multi ? `<span class="per">${md0(i.first)}〜${md0(i.last)}</span>` : ''}${i.invited ? ' <span class="mk mk-pick">招待</span>' : ''}${i.location ? `<span class="loc"> ${esc(i.location)}</span>` : ''}</button><span></span></div>`;
  }
  function classRow(c, uni) {
    return `<div class="ev"><span class="tm">${esc(c.start)}〜${esc(c.end)}</span>${kindLabel('大学', uni)}<span>授業 ${c.count}コマ<span class="loc"> ${esc(c.names.join('・'))}</span></span><span></span></div>`;
  }

  const shiftMonth = (m, n) => { const x = parse(m + '-01'); x.setMonth(x.getMonth() + n); return iso(x).slice(0, 7); };
  function navHead() {
    const [a, b] = range();
    return S.sv === 'list'
      ? `<span class="date snav"><button class="link" data-snav="-14" aria-label="前の2週間">‹</button> ${md(a)}〜${md(b)} <button class="link" data-snav="14" aria-label="次の2週間">›</button></span>`
      : `<span class="date snav"><button class="link" data-snav="-1" aria-label="前の月">‹</button> ${S.smonth.slice(0, 4)}年${+S.smonth.slice(5)}月 <button class="link" data-snav="1" aria-label="次の月">›</button></span>`;
  }

  function keepEvents(d) {
    S.sevents = Object.fromEntries(d.days.flatMap((x) => x.items.filter((i) => i.type === 'event').map((i) => [i.id, { ...i, date: i.first || x.date }])));
  }

  // ---------- トップの一番下の月のカレンダー(2026-10-21 本人の依頼) ----------
  async function topCal() {
    S.tmonth = S.tmonth || isoToday().slice(0, 7);
    const m = S.tmonth;
    const [a, b] = range(m);
    const d = await api('GET', `/schedule?from=${a}&to=${b}`);
    S.sd = d;  // 日の小窓・予定の小窓は、予定の画面と同じものを使う
    keepEvents(d);
    setTimeout(() => [-1, 1].forEach((k) => {  // となりの月を先に読んでおく
      const [x, y] = range(shiftMonth(m, k));
      api('GET', `/schedule?from=${x}&to=${y}`).catch(() => {});
    }), 300);
    const uni = d.kinds['大学'] || '#17806a';
    const warn = d.error ? `<div class="hint">${esc(d.error)}。予定は出せません。締切と授業だけ出しています</div>` : '';
    return `<div class="sec topcal"><div class="sh">予定<span class="snav"><button data-tnav="-1" aria-label="前の月">‹</button>${m.slice(0, 4)}年${+m.slice(5)}月<button data-tnav="1" aria-label="次の月">›</button></span><button class="link open" data-topensched>予定の画面で開く ›</button></div>${warn}${monthGrid(d, uni, isoToday(), m)}</div>`;
  }
  window.topCal = topCal;

  async function schedView() {
    const [a, b] = range();
    const d = await api('GET', `/schedule?from=${a}&to=${b}`);
    S.sd = d;
    S.c = { tasks: d.days.flatMap((x) => x.items.filter((i) => i.type === 'task')) };
    keepEvents(d);
    const uni = d.kinds['大学'] || '#17806a';
    const t0 = isoToday();
    const head = navHead();
    if (S.sv === 'month') setTimeout(() => [-1, 1].forEach((k) => {  // となりの月を先に読んでおく(本体が10分覚える)
      const [x, y] = range(shiftMonth(S.smonth, k));
      api('GET', `/schedule?from=${x}&to=${y}`).catch(() => {});
    }), 300);
    const top = `<div class="bar"><h1>予定</h1><span class="seg"><button data-sv="list" class="${S.sv === 'list' ? 'on' : ''}">一覧</button><button data-sv="month" class="${S.sv === 'month' ? 'on' : ''}">月</button></span>${head}<span class="r"><button class="btn sm" data-stoday>今日</button><button class="btn pri" data-evadd="" ${d.connected ? '' : 'disabled title="Google カレンダーにつながっていないため、足せません"'}>+ 予定</button></span></div>`;
    const warn = d.error ? `<div class="band">${esc(d.error)}。予定は出せません。締切と授業だけ出しています</div>` : !d.connected ? '<div class="band">Google カレンダーはまだつながっていません(設定の「Google」)。締切と授業だけ出しています</div>' : '';
    const held = d.held.length ? `<button class="band" data-heldlist>Google に書けなかった予定 ${d.held.length}件 ›</button>` : '';
    let main;
    if (S.sv === 'list') {
      main = d.days.map((x) => {
        const rows = (x.classes ? classRow(x.classes, uni) : '') + x.items.map(row).join('');
        return `<div class="sched-day"><h3 class="${x.date === t0 ? 'today' : ''}">${md(x.date)}${x.date === t0 ? ' 今日' : ''}</h3>${rows || '<div class="none">予定なし</div>'}</div>`;
      }).join('');
    } else {
      main = monthGrid(d, uni, t0);
    }
    const drop = `<div class="shdrop" id="shdrop"><b>シフト表の写真をここに落とす</b><span>Claude が自分のシフトだけを読み取ります。読み取った結果を見てから書き込めます</span>
      <label class="btn sm">写真を選ぶ<input type="file" accept="image/*" id="shfile" hidden></label></div>`;
    return top + `<div class="col" style="padding-top:4px">${syncLine(d.sync, d.connected)}${warn}${held}${main}${d.connected ? drop : ''}
      <div class="hint" style="padding:12px 0">スマホなどで足した予定も、10分ごとに読んで出します。段取りさんが書いた締切は、ここではタスクとして1回だけ出します。</div></div>`;
  }

  // ---------- 月の画面(帯) ----------
  const MAXROWS = 3;
  function monthGrid(d, uni, t0, month = S.smonth) {
    const weeks = [];
    for (let k = 0; k < d.days.length; k += 7) weeks.push(d.days.slice(k, k + 7));
    let html = `<div class="month"><div class="wdh">${['日', '月', '火', '水', '木', '金', '土'].map((w) => `<div class="wd">${w}</div>`).join('')}</div>`;
    for (const wk of weeks) {
      const days = wk.map((x) => x.date);
      const w0 = days[0], w6 = days[6];
      // 帯:この週にかかる終日・続く予定を、早い順・長い順に段へ詰める
      const seen = new Set();
      const spans = [];
      wk.forEach((x) => x.items.filter(isBar).forEach((i) => {
        if (seen.has(i.id)) return;
        seen.add(i.id);
        const a = days.indexOf(i.first < w0 ? w0 : i.first), b = days.indexOf(i.last > w6 ? w6 : i.last);
        spans.push({ i, a: a < 0 ? 0 : a, b: b < 0 ? 6 : b });
      }));
      spans.sort((x, y) => (x.a - y.a) || ((y.b - y.a) - (x.b - x.a)));
      const used = days.map(() => []);
      for (const sp of spans) {
        let lane = 0;
        while ([...Array(sp.b - sp.a + 1).keys()].some((k) => used[sp.a + k][lane])) lane++;
        sp.lane = lane;
        for (let k = sp.a; k <= sp.b; k++) used[k][lane] = true;
      }
      // 1日の予定(締切・授業・時刻のある予定・預かった予定)は、その日の空いた段へ
      const singles = wk.map((x, n) => {
        const list = [
          ...x.items.filter((i) => i.type === 'task').map((i) => ({ i })),
          ...(x.classes ? [{ cls: x.classes }] : []),
          ...x.items.filter((i) => i.type !== 'task' && !isBar(i)).map((i) => ({ i })),
        ];
        return list.map((it) => { let lane = 0; while (used[n][lane]) lane++; used[n][lane] = true; return { ...it, lane }; });
      });
      const row = (lane) => lane + 2;
      let parts = wk.map((x, n) => `<button class="mcell ${x.date.slice(0, 7) !== month ? 'out' : ''} ${x.date === t0 ? 'td' : ''}" style="grid-column:${n + 1}" data-sday="${x.date}"><span>${+x.date.slice(8)}</span></button>`).join('');
      for (const sp of spans) {
        if (sp.lane >= MAXROWS) continue;
        const i = sp.i;
        const cl = i.last > w6, cr = i.first < w0;  // 週をまたぐ帯は、切れ目の角を四角にする
        const t = !i.all_day && i.start ? i.start + ' ' : '';
        parts += `<button class="msp ${cl ? 'cl' : ''} ${cr ? 'cr' : ''}" style="grid-column:${sp.a + 1} / ${sp.b + 2};grid-row:${row(sp.lane)};background:${evColor(i)}" data-evopen="${esc(i.id)}" title="${esc(i.name)}">${esc(t + i.name)}</button>`;
      }
      wk.forEach((x, n) => {
        for (const it of singles[n]) {
          if (it.lane >= MAXROWS) continue;
          const pos = `grid-column:${n + 1};grid-row:${row(it.lane)}`;
          if (it.cls) parts += `<span class="mev" style="${pos}"><i style="background:${uni}"></i>${esc(it.cls.start)} 大学 授業${it.cls.count}</span>`;
          else if (it.i.type === 'task') { const c = (it.i.label || {}).color || GRAY; parts += `<span class="mbar ${it.i.done ? 'mdone' : ''}" style="${pos};color:${c};background:color-mix(in srgb, ${c} 16%, transparent)">締切 ${esc(it.i.name)}</span>`; }
          else if (it.i.type === 'held') parts += `<button class="mev" style="${pos}" data-heldlist><i style="background:var(--amber)"></i>${it.i.start ? esc(it.i.start) + ' ' : ''}${esc(it.i.name)}</button>`;
          else parts += `<button class="mev" style="${pos}" data-evopen="${esc(it.i.id)}"><i style="background:${evColor(it.i)}"></i>${it.i.start ? esc(it.i.start) + ' ' : ''}${esc(it.i.name)}</button>`;
        }
        const hidden = spans.filter((sp) => sp.lane >= MAXROWS && sp.a <= n && n <= sp.b).length + singles[n].filter((it) => it.lane >= MAXROWS).length;
        if (hidden) parts += `<button class="mmore" style="grid-column:${n + 1};grid-row:${row(MAXROWS)}" data-sday="${x.date}">他 ${hidden}件</button>`;
      });
      html += `<div class="mwk">${parts}</div>`;
    }
    return html + '</div>';
  }

  // ---------- Google カレンダーとそろっているか(同期の確かめ) ----------
  function syncLine(sy, connected) {
    if (!connected || !sy) return '';
    const at = sy.at ? sy.at.slice(11, 16) : '';
    if (sy.checking) return '<div class="syncline"><span>Google カレンダーとそろっているかを確かめています…</span></div>';
    if (!sy.bad.length) return `<div class="syncline"><span class="ok">● Google カレンダーとそろっています</span><span>${esc(at)} に確かめました ・ 段取りさんが書いた締切 ${sy.checked}件</span><span class="r"><button class="link" data-synccheck>今すぐ確かめる</button></span></div>`;
    const warn = sy.streak >= 2;
    return `<div class="syncline"><span class="${warn ? 'ng' : ''}">● そろっていない締切が ${sy.bad.length}件あります</span><span>${esc(at)} に確かめました。${warn ? '2回続けて直せませんでした' : '次の見回りで直します'}</span><span class="r"><button class="link" data-syncdiff>どれかを見る</button><button class="link" data-synccheck>今すぐ確かめる</button></span></div>`;
  }

  function contOptions(sel) {
    const ov = S.ovAll || [];
    return `<option value="">なし</option>${ov.map((c) => `<option value="${c.id}" ${c.id === sel ? 'selected' : ''}>${esc(c.kind)}:${esc(c.name)}</option>`).join('')}`;
  }
  async function loadConts() {
    if (S.ovAll) return;
    const n = await api('GET', '/notices');
    S.ovAll = n.options;
  }

  async function evForm(ev, day) {
    await loadConts();
    const ro = ev && !ev.editable;
    const dis = ro ? 'disabled' : '';
    modal(`<h3>${ev ? (ro ? '予定' : '予定を直す') : '予定を足す'}</h3>
      ${ev && ev.multi ? `<div class="hint" style="margin-bottom:8px">${md0(ev.first)}〜${md0(ev.last)} の、何日も続く予定です。日付や時刻は ${ev.link ? `<a href="${esc(ev.link)}" target="_blank" rel="noopener">Google カレンダー</a>` : 'Google カレンダー'}で直してください。ここでは、どの授業・会社・開発の予定かを選べます</div>` : ''}
      ${ev && ev.invited ? `<div class="hint" style="margin-bottom:8px">招待された予定です。ふだんは見るだけです。<span class="tg" style="margin-top:6px"><button class="sw ${ev.edit_allowed ? 'on' : ''}" data-evallow="${esc(ev.id)}" aria-label="直せるようにする"></button>この予定を直せるようにする</span></div>` : ''}
      <div class="field"><span>名前</span><input id="evn" value="${esc(ev ? ev.name : '')}" placeholder="サークル" ${dis}></div>
      <div class="field"><span>日付</span><input id="evd" type="date" value="${esc(ev ? ev.date : day || isoToday())}" ${dis}></div>
      <div class="field"><span>時刻(空なら終日)</span><div class="two"><input id="evs" placeholder="13:00" value="${esc(ev ? ev.start || '' : '')}" ${dis}><input id="eve" placeholder="15:00" value="${esc(ev ? ev.end || '' : '')}" ${dis}></div></div>
      <div class="field"><span>授業・会社・開発</span><select id="evc">${contOptions(ev ? ev.container_id : null)}</select></div>
      <div class="hint">保存すると、その場で Google カレンダーにも書きます。</div>
      <div class="acts">${ev && !ev.invited ? `<button class="btn danger l" data-evdel="${esc(ev.id)}">消す</button>` : ''}<button class="btn" data-close>${ro ? '閉じる' : 'やめる'}</button><button class="btn pri" data-evsave="${ev ? esc(ev.id) : ''}">${ev ? '保存' : '足す'}</button></div>`);
  }

  function dayModal(day) {
    const x = S.sd.days.find((y) => y.date === day);
    const uni = S.sd.kinds['大学'] || '#17806a';
    const rows = x ? (x.classes ? classRow(x.classes, uni) : '') + x.items.map(row).join('') : '';
    modal(`<h3>${md(day)}</h3>${rows || '<div class="none">予定なし</div>'}
      <div class="acts" style="justify-content:space-between"><button class="btn pri" data-evadd="${day}" ${S.sd.connected ? '' : 'disabled'}>+ この日に予定を足す</button><button class="btn" data-close>閉じる</button></div>`);
  }

  function heldModal() {
    const why = { 重なる予定がある: '同じ時間に予定があるため、書いていません', つながらなかった: 'Google につながらなかったため、まだ書いていません。つながったら自動でもう一度書きます' };
    modal(`<h3>Google に書けなかった予定</h3>${S.sd.held.map((h) => `<div class="ev" style="grid-template-columns:minmax(0,1fr) auto">
      <span>${esc(h.name)} <span class="loc">${md(h.start_at.slice(0, 10))} ${esc(h.start_at.slice(11, 16))}</span><div class="hint">${why[h.reason] || h.reason}</div></span>
      <span class="rowb" style="margin:0">${h.reason === '重なる予定がある' ? `<button class="btn sm" data-hforce="${h.id}">それでも書く</button><button class="btn sm" data-hdrop="${h.id}">書かない</button>` : `<button class="btn sm" data-hretry="${h.id}">もう一度書く</button>`}</span></div>`).join('') || '<div class="none">ありません</div>'}
      <div class="acts"><button class="btn" data-close>閉じる</button></div>`);
  }

  // ---------- シフト表の写真(F14、S2-2・S2-2a) ----------
  async function sendPhoto(file) {
    if (!file) return;
    modal(`<h3>シフト表を読み取っています</h3><p class="hint">Claude が写真を読んでいます。1分ほどかかることがあります。</p>`);
    const fd = new FormData();
    fd.append('photo', file);
    try {
      const r = await fetch('/api/shift-photo', { method: 'POST', body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || '読み取れませんでした');
      S.shifts = j.shifts; S.shbaito = j.baito;
      shiftModal();
    } catch (err) {
      modal(`<h3>読み取れませんでした</h3><p>${esc(err.message)}</p><div class="acts"><button class="btn" data-close>閉じる</button><button class="btn" data-shhand>自分で入れる</button><label class="btn pri">もう一度<input type="file" accept="image/*" id="shfile2" hidden></label></div>`);
    }
  }
  function shiftModal() {
    const list = S.shifts || [];
    const pick = S.shbaito && S.shbaito.length > 1
      ? `<div class="field"><span>どのバイト先のシフト?</span><select id="shb"><option value="">選ぶ…</option>${S.shbaito.map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join('')}</select></div>` : '';
    const name = !S.shbaito || !S.shbaito.length ? 'バイト' : S.shbaito.length === 1 ? `バイト(${S.shbaito[0].name})` : 'バイト(選んだバイト先)';
    modal(`<h3>読み取ったシフト</h3>
      <div class="hint" style="margin-bottom:8px">まちがっていたら、その場で直せます。書き込まない日は × で外します。予定の名前は「${esc(name)}」です</div>${pick}
      ${list.length ? list.map((x, i) => `<div class="shrow"><input type="date" value="${esc(x.date)}" data-shd="${i}" aria-label="日付"><input value="${esc(x.start)}" data-shs="${i}" aria-label="始まり" placeholder="17:00"><span>〜</span><input value="${esc(x.end)}" data-she="${i}" aria-label="終わり" placeholder="22:00"><button class="link danger" data-shx="${i}" aria-label="この日を外す">×</button></div>`).join('')
        : '<div class="none">書き込むシフトはありません</div>'}
      <div class="rowb"><button class="btn sm" data-shaddrow>+ 1日足す</button></div>
      <div class="acts"><button class="btn" data-shclose>閉じる</button><button class="btn pri" data-shcommit ${list.length ? '' : 'disabled'}>書き込む</button></div>`);
  }
  function readRows() {
    (S.shifts || []).forEach((x, i) => {
      const g = (a) => { const el = document.querySelector(`[data-${a}="${i}"]`); return el ? el.value.trim() : ''; };
      x.date = g('shd'); x.start = g('shs'); x.end = g('she');
    });
  }
  document.addEventListener('change', (e) => {
    if (S.screen !== 'sched') return;
    if (e.target.id === 'shfile' || e.target.id === 'shfile2') { sendPhoto(e.target.files[0]); e.target.value = ''; }
  });
  document.addEventListener('dragover', (e) => {
    const z = e.target.closest && e.target.closest('#shdrop');
    if (z && S.screen === 'sched') { e.preventDefault(); z.classList.add('on'); }
  });
  document.addEventListener('dragleave', (e) => { const z = e.target.closest && e.target.closest('#shdrop'); if (z) z.classList.remove('on'); });
  document.addEventListener('drop', (e) => {
    const z = e.target.closest && e.target.closest('#shdrop');
    if (!z || S.screen !== 'sched') return;
    e.preventDefault(); z.classList.remove('on');
    sendPhoto(e.dataTransfer.files[0]);
  });

  document.addEventListener('click', async (e) => {
    const el = e.target.closest('button');
    if (!el || S.screen !== 'sched') return;
    const dd = el.dataset;
    try {
      if (dd.shx) { readRows(); S.shifts.splice(+dd.shx, 1); shiftModal(); return; }
      if (dd.shaddrow !== undefined) { readRows(); S.shifts.push({ date: isoToday(), start: '', end: '' }); shiftModal(); return; }
      if (dd.shhand !== undefined) { S.shifts = [{ date: isoToday(), start: '', end: '' }]; S.shbaito = S.shbaito || (await api('GET', '/baito')); shiftModal(); return; }
      if (dd.shclose !== undefined) { S.shifts = null; closeModal(); return; }  // 閉じたら結果は消す
      if (dd.shcommit !== undefined) {
        readRows();
        const b = $('#shb');
        const r = await api('POST', '/shift-photo/commit', { shifts: S.shifts, baito_id: b ? +b.value || null : null });
        S.shifts = null;
        modal(`<h3>書き込みました</h3><p>「${esc(r.summary)}」を ${r.written.length}日、Google カレンダーに書きました。</p>
          ${r.skipped.length ? `<div class="sh">書かなかった日</div>${r.skipped.map((x) => `<div class="ev" style="grid-template-columns:auto minmax(0,1fr)"><span class="tm">${md(x.date)} ${esc(x.start)}〜${esc(x.end)}</span><span class="hint">${esc(x.reason)}</span></div>`).join('')}` : ''}
          <div class="acts"><button class="btn pri" data-close>閉じる</button></div>`);
        render(); return;
      }
    } catch (err) { if ($('#merr')) modalError(err); else toast(err.message); return; }
  });

  document.addEventListener('click', async (e) => {
    const el = e.target.closest('button');
    if (!el) return;
    if (S.screen !== 'sched' && !(S.screen === 'top' && el.closest('.topcal, #layer'))) return;
    const d = el.dataset;
    try {
      if (d.tnav) {
        S.tmonth = shiftMonth(S.tmonth, +d.tnav);
        const box = $('#topcal'); if (!box) return;
        box.classList.add('loading');
        const nav = box.querySelector('.snav');  // 届くのを待たずに、見出しの月だけ先に変える
        if (nav) nav.childNodes[1].textContent = `${S.tmonth.slice(0, 4)}年${+S.tmonth.slice(5)}月`;
        const n = S.tn = (S.tn || 0) + 1;  // 続けて押したら、最後の月だけ出す
        const html = await topCal();
        if (n === S.tn && S.screen === 'top') { box.innerHTML = html; box.classList.remove('loading'); }
        return;
      }
      if (d.topensched !== undefined) { S.sv = 'month'; S.smonth = S.tmonth; go('sched'); return; }
      if (d.sv) { S.sv = d.sv; render(); return; }
      if (d.synccheck !== undefined) {
        el.textContent = '確かめています…'; el.disabled = true;
        const r = await api('POST', '/calendar/check');
        toast(r.bad.length ? `そろっていない締切が ${r.bad.length}件あります` : 'Google カレンダーとそろっています');
        render(); return;
      }
      if (d.syncdiff !== undefined) {
        const sy = S.sd.sync;
        modal(`<h3>そろっていない締切</h3><div class="hint" style="margin-bottom:8px">段取りさんが書いた締切のうち、Google カレンダーと合っていないものです。見回りのたびに直そうとします</div>${sy.bad.map((b) => `<div class="ev" style="grid-template-columns:auto minmax(0,1fr)"><span class="tm">${esc(md0(b.date))}</span><span>${esc(b.name)}<span class="per">${esc(b.why)}</span></span></div>`).join('')}
          <div class="acts"><button class="btn" data-close>閉じる</button></div>`);
        return;
      }
      if (d.stoday !== undefined) { S.slist = isoToday(); S.smonth = isoToday().slice(0, 7); render(); return; }
      if (d.snav) {
        const n = +d.snav;
        if (S.sv === 'list') S.slist = iso(addDays(parse(S.slist), n));
        else S.smonth = shiftMonth(S.smonth, n);
        const nav = el.closest('.snav');  // 届くのを待たずに、見出しだけ先に変えて「読んでいます」にする
        if (nav) nav.outerHTML = navHead() + '<span class="hint">読んでいます…</span>';
        const col = $('#main .col'); if (col) col.classList.add('loading');
        render(); return;
      }
      if (d.sday) { dayModal(d.sday); return; }
      if (d.evadd !== undefined) { await evForm(null, d.evadd); return; }
      if (d.evopen) { await evForm(S.sevents[d.evopen]); return; }
      if (d.evallow) {
        const on = !el.classList.contains('on');
        await api('PATCH', `/events/${encodeURIComponent(d.evallow)}`, { edit_allowed: on });
        closeModal(); toast(on ? 'この予定を直せるようにしました' : 'この予定を見るだけにしました'); render(); return;
      }
      if (d.evsave !== undefined) {
        const data = { name: $('#evn').value, date: $('#evd').value, start: $('#evs').value.trim(), end: $('#eve').value.trim(), container_id: +$('#evc').value || null };
        if (d.evsave) {
          const ev = S.sevents[d.evsave];
          const changed = ev.editable ? data : { container_id: data.container_id };
          await api('PATCH', `/events/${encodeURIComponent(d.evsave)}`, changed);
          toast('直しました(Google カレンダーも直しました)');
        } else {
          await api('POST', '/events', data);
          toast('予定を足しました(Google カレンダーにも書きました)');
        }
        closeModal(); render(); return;
      }
      if (d.evdel) {
        modal(`<h3>この予定を消しますか?</h3><p>「${esc(S.sevents[d.evdel].name)}」を、Google カレンダーからも消します。元には戻せません。</p>
          <div class="acts"><button class="btn" data-close>やめる</button><button class="btn danger" data-evdelok="${esc(d.evdel)}">消す</button></div>`);
        return;
      }
      if (d.evdelok) { await api('DELETE', `/events/${encodeURIComponent(d.evdelok)}`); closeModal(); toast('消しました'); render(); return; }
      if (d.heldlist !== undefined) { heldModal(); return; }
      for (const [k, act, msg] of [['hretry', 'retry', ''], ['hforce', 'force', '書きました'], ['hdrop', 'drop', '書かないことにしました']]) {
        if (d[k]) {
          const r = await api('POST', `/held-events/${d[k]}/${act}`);
          toast(act === 'retry' ? (r.written ? '書きました' : '重なる予定があるため、まだ書いていません') : msg);
          S.sd = await api('GET', `/schedule?from=${range()[0]}&to=${range()[1]}`);
          S.sd.held.length ? heldModal() : closeModal();
          render(); return;
        }
      }
    } catch (err) { if ($('#merr')) modalError(err); else toast(err.message); }
  });

  VIEWS.sched = schedView;
  if (S.screen === 'sched') render();  // 「予定」で開いたとき、app.js が先に仮の画面を描いているので描き直す
})();
