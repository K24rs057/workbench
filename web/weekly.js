// 週の振り返りの画面(要件 F24、基本設計 S8・Q40)
(function () {
  // 週の振り返り(要件 F24、基本設計 S8・Q40)。数字は本体が数えたもの(/api/weekly)をそのまま出す
  const MOCHI_FACE = '<svg viewBox="0 0 36 36" aria-hidden="true"><path d="M18 9c0-3 2-5 5-5-1 3-3 4-5 5Zm0 0c0-2-2-4-4-4 0 2 2 4 4 4Z" fill="#7cb342"/><ellipse cx="18" cy="22" rx="13" ry="11" fill="#fff" stroke="var(--line2)"/><circle cx="13.5" cy="21" r="1.4" fill="#333"/><circle cx="22.5" cy="21" r="1.4" fill="#333"/><path d="M16 25q2 1.6 4 0" stroke="#333" fill="none" stroke-width="1.2" stroke-linecap="round"/><ellipse cx="10.5" cy="24.5" rx="2" ry="1.2" fill="#f8bbd0"/><ellipse cx="25.5" cy="24.5" rx="2" ry="1.2" fill="#f8bbd0"/></svg>';
  const hm = (m) => (m >= 60 ? `${Math.floor(m / 60)}時間${m % 60 ? (m % 60) + '分' : ''}` : `${m}分`);
  const hshort = (m) => (m ? (m / 60).toFixed(1).replace(/\.0$/, '') + 'h' : '—');
  const mdw = (s) => `${+s.slice(5, 7)}/${+s.slice(8, 10)}(${WEEK[new Date(s + 'T00:00').getDay()]})`;
  function weeklyHtml(d, making) {
    const maxC = Math.max(1, ...d.by_container.map((x) => x.min));
    const maxD = Math.max(1, ...d.by_day.map((x) => x.min));
    const head = `<span class="date snav"><button class="link" data-wk="${d.prev}" aria-label="前の週">‹</button> ${mdw(d.week_start)}〜${mdw(d.week_end)}${d.this_week ? ' <span class="mk mk-pick">今週・途中まで</span>' : ''} <button class="link" data-wk="${d.next || ''}" ${d.next ? '' : 'disabled style="opacity:.3"'} aria-label="次の週">›</button></span>`;
    const nums = `<div class="wnums">
      <div><b>${hm(d.total_min)}</b><span>作業した時間</span></div>
      <div><b>${d.done.length}件</b><span>終わったタスク</span></div>
      <div><b class="${d.late.length ? 'late' : ''}">${d.late.length}件</b><span>締切を過ぎた</span></div>
      <div><b>${d.untouched.length}件</b><span>手つかず</span></div></div>`;
    const bars = d.by_container.length
      ? d.by_container.map((x) => `<div class="hbar"><span title="${esc(x.name)}">${esc(x.name)}</span><span class="tr"><i style="width:${(x.min / maxC) * 100}%;background:${x.color || 'var(--blue)'}"></i></span><span class="v">${hm(x.min)}</span></div>`).join('')
      : '<div class="hint">この週の作業記録はありません</div>';
    const days = `<div class="wdays">${d.by_day.map((x) => `<div><span>${hshort(x.min)}</span><i style="height:${Math.round((x.min / maxD) * 64)}px"></i><em>${WEEK[new Date(x.date + 'T00:00').getDay()]}</em></div>`).join('')}</div>`;
    const list = (xs, f, empty, more = 5) => (xs.length ? xs.slice(0, more).map(f).join('') + (xs.length > more ? `<div class="hint">ほか ${xs.length - more}件</div>` : '') : `<div class="hint">${empty}</div>`);
    const right = `<div class="sh">終わったこと</div>${list(d.done, (x) => `<div class="wli">${esc(x.name)} <span class="cm">${esc(x.container)}</span></div>`, 'ありません')}
      <div class="sh" style="margin-top:12px">遅れたこと</div>${list(d.late, (x) => `<div class="wli"><span class="mk mk-warn">${x.days}日遅れ</span> ${esc(x.name)} <span class="cm">${esc(x.container)}</span></div>`, 'ありません', 8)}
      <div class="sh" style="margin-top:12px">手つかず</div>${list(d.untouched, (x) => `<div class="wli">${esc(x.name)} <span class="cm">${esc(x.container)}</span></div>`, 'ありません')}
      <div class="sh" style="margin-top:12px">来週の山</div>${list(d.next_week, (x) => `<div class="wli"><span class="cm" style="margin:0 6px 0 0">${mdw(x.date)}${x.time ? ' ' + esc(x.time) : ''}</span>${x.kind === 'task' ? '締切 ' : ''}${esc(x.name)}</div>`, 'ありません', 8)}`;
    const mochi = d.comment
      ? `<div class="wmochi"><span class="face">${MOCHI_FACE}</span><div>${esc(d.comment)}</div></div>`
      : making ? `<div class="wmochi"><span class="face">${MOCHI_FACE}</span><div class="hint">モッチがひとことを考えています…</div></div>`
    : `<div class="wmochi"><span class="face">${MOCHI_FACE}</span><div>${d.comment_error ? 'ひとことを作れませんでした。' : d.finished ? '' : 'ひとことは、日曜の夜に作ります。'} <button class="btn sm" data-wkcomment="${d.week_start}">${d.comment_error ? '作り直す' : '今つくる'}</button></div></div>`;
    return `<div class="bar"><h1>振り返り</h1>${head}</div>
      <div class="col wcol">${nums}
        <div class="wgrid"><div><div class="sh">どこに時間を使ったか</div>${bars}<div class="sh" style="margin-top:14px">日ごと</div>${days}</div><div>${right}</div></div>
        ${mochi}
        <div class="hint" style="padding:12px 0">作業記録とタスクから、段取りさんが数えています。モッチのひとことだけ Claude が書きます。</div></div>`;
  }

  async function weeklyView() {
    const d = await api('GET', `/weekly${S.week ? `?week=${S.week}` : ''}`);
    S.week = d.week_start;
    // 終わった週でひとことがまだなら、開いたときに作る(Q40)
    const empty = !d.total_min && !d.done.length && !d.late.length;  // 何もない週(使い始める前)は作らない
    if (d.finished && !empty && !d.comment && !d.comment_error && !S.wkMaking) {
      S.wkMaking = d.week_start;
      api('POST', `/weekly/${d.week_start}/comment`).then(() => { S.wkMaking = null; if (S.screen === 'weekly' && S.week === d.week_start) render(); }).catch(() => { S.wkMaking = null; });
    }
    return weeklyHtml(d, S.wkMaking === d.week_start);
  }
  document.addEventListener('click', async (e) => {
    const el = e.target.closest('button');
    if (!el || S.screen !== 'weekly') return;
    const d = el.dataset;
    try {
      if (d.wk) { S.week = d.wk; render(); return; }
      if (d.wkcomment) { el.textContent = '作っています…'; el.disabled = true; await api('POST', `/weekly/${d.wkcomment}/comment`); render(); return; }
    } catch (err) { toast(err.message); }
  });
  VIEWS.weekly = weeklyView;
  if (S.screen === 'weekly') render();
})();
