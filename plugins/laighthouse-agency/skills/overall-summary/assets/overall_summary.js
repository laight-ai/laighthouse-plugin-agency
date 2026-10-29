/* 종합 리포트 화면 — build_report.py 가 넣은 REPORT로 목업(종합 리포트)의 기능을 그린다.
 * - Daily/Weekly Comment: 빌더가 만든 문장을 그대로 그린다.
 * - Total/Monthly Summary(필터 미적용): 미디어 → 디멘전 계층, 예산·소진율·진행율 + 목표 영역(e.* 목표·달성률).
 * - 월·미디어 필터 → Product·Target·Placement·Weekly·Daily 표(Placement는 노출 위치 데이터 REPORT.place가 있을 때만).
 * - 모든 표: 묶음 이름 옆 ▼/▶ 접기 + 제목 줄 '펼침 [미디어][…][전체]' 단계 접기, 오른쪽 목차(바로가기·맨 위로).
 * - 디멘전 설정·지표 설정(선택·순서)과 캠페인명은 localStorage에 남긴다.
 * 모양은 report_kit.css + 템플릿 <style>만 정한다(인라인 style 없음).
 * 전역: window.OverallSummary = { mount(report) }
 */
(function () {
  const LS_METRICS = 'overall-summary-metrics';
  const LS_DIMS = 'overall-summary-dims';
  const LS_CAMP = 'overall-summary-camp';
  const LS_MIX = 'overall-summary-mix';
  const MORE = 20;   // '더 보기' 한 번에 더 그리는 항목 수
  const FIRST = level => (level <= 1 ? 10 : 5);   // 묶음마다 처음 그리는 항목 수(광고비 상위) — 단계가 깊을수록 적게

  const n0 = v => Math.round(v).toLocaleString('en-US');
  const pct2 = (n, d) => d ? (n / d * 100).toFixed(2) + '%' : '';
  const pct0 = (n, d) => d ? Math.round(n / d * 100) + '%' : '';
  const uniq = arr => [...new Set(arr)];
  const agg = rs => rs.reduce((a, x) => ({ cost: a.cost + x.cost, imp: a.imp + x.imp, click: a.click + x.click, view: a.view + x.view }),
    { cost: 0, imp: 0, click: 0, view: 0 });
  const RATIO_T = new Set(['ctr', 'vtr', 'cpm', 'cpc', 'cpv']);

  function load(key) { try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) { return {}; } }
  function save(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch (e) { /* 저장 불가 환경 */ } }

  function h(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function placeholder(el) { el.innerHTML = ''; el.appendChild(h('div', 'lh-placeholder', '데이터 준비 중')); }

  /* ── 지표 정의 (목업 PIVOT_M · SUM_M) ── */
  function metricDefs(has) {
    const tgv = (k, f) => x => (x.tg && x.tg[k] != null ? f(x.tg[k]) : '');
    const PIVOT = [
      { k: 'cost', l: '비용', f: x => n0(x.a.cost) },
      { k: 'imp', l: '노출', need: ['imp'], f: x => n0(x.a.imp) },
      { k: 'click', l: '클릭', need: ['click'], f: x => n0(x.a.click) },
      { k: 'view', l: '조회', need: ['view'], f: x => n0(x.a.view) },
      { k: 'cpm', l: 'CPM', need: ['imp'], f: x => x.a.imp ? n0(x.a.cost / x.a.imp * 1000) : '' },
      { k: 'cpc', l: 'CPC', need: ['click'], f: x => x.a.click ? n0(x.a.cost / x.a.click) : '' },
      { k: 'ctr', l: 'CTR', need: ['imp', 'click'], f: x => pct2(x.a.click, x.a.imp) },
      { k: 'cpv', l: 'CPV', need: ['view'], f: x => x.a.view ? n0(x.a.cost / x.a.view) : '' },
      { k: 'vtr', l: 'VTR', need: ['imp', 'view'], f: x => pct0(x.a.view, x.a.imp) },
    ];
    const SEL = [
      { k: 'e.Imps', need: ['imp'], f: tgv('imp', n0) },
      { k: 'e.Click', need: ['click'], f: tgv('click', n0) },
      { k: 'e.View', need: ['view'], f: tgv('view', n0) },
      { k: 'e.CTR', need: ['imp', 'click'], f: tgv('ctr', v => v.toFixed(2) + '%') },
      { k: 'e.VTR', need: ['imp', 'view'], f: tgv('vtr', v => Math.round(v) + '%') },
      { k: 'e.CPM', need: ['imp'], f: tgv('cpm', n0) },
      { k: 'e.CPC', need: ['click'], f: tgv('cpc', n0) },
      { k: 'e.CPV', need: ['view'], f: tgv('cpv', n0) },
      { k: '노출 달성률', need: ['imp'], f: x => (x.tg && x.tg.imp ? pct0(x.a.imp, x.tg.imp) : '') },
      { k: '클릭 달성률', need: ['click'], f: x => (x.tg && x.tg.click ? pct0(x.a.click, x.tg.click) : '') },
      { k: '조회 달성률', need: ['view'], f: x => (x.tg && x.tg.view ? pct0(x.a.view, x.tg.view) : '') },
    ].map(m => ({ ...m, l: m.k, g: 's' }));
    const ok = m => (m.need || []).every(n => has[n]);
    const pivot = PIVOT.filter(ok);
    const sum = [
      { k: 'budget', l: '예산', g: 'b', f: x => (x.tg && x.tg.cost ? n0(x.tg.cost) : '') },
      ...pivot.map(m => ({ ...m, g: 'b' })),
      { k: 'burn', l: '소진율', g: 'b', f: x => (x.tg && x.tg.cost ? pct0(x.a.cost, x.tg.cost) : '') },
      { k: 'prog', l: '진행율', g: 'b', f: x => x.prog || '' },
      ...SEL.filter(ok),
    ];
    return { total: sum, monthly: sum, product: pivot, target: pivot, place: pivot, weekly: pivot, daily: pivot };
  }

  /* ── 엑셀로 보내기: 화면 그대로(접은 상태·켠 지표·순서) 표를 클립보드에 넣는다.
   * 묶음 칸(같은 미디어·상품이라 비워 둔 칸)은 채워서 보내 엑셀에서 바로 필터·피벗이 되게 하고,
   * 병합 칸은 빈 칸으로 펼친다. 텍스트(TSV) + HTML 둘 다 넣어 엑셀·구글 시트 어디에 붙여도 칸이 맞는다. */
  const ICON_SHEET = '<svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true"><rect x="2.5" y="3.5" width="11" height="13" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M2.5 7.5h11M2.5 11.5h11M7 3.5v13" stroke="currentColor" stroke-width="1.2"/><path d="M15.5 8v6.5M13 12l2.5 2.5L18 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const ICON_DONE = '<svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true"><path d="M4 10.5l4 4 8-9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const cellText = c => { const inp = c.querySelector('input'); return ((inp ? inp.value : '') + [...c.querySelectorAll('span')].map(x => x.textContent).join('')).trim(); };
  function tableMatrix(table) {
    const nl = Number(table.dataset.labels) || 0;
    const out = [];
    let last = [];
    table.querySelectorAll('tr').forEach(tr => {
      const head = tr.parentNode.tagName === 'THEAD';
      const fill = !head && !/\btb-(grand|total|msum)\b/.test(tr.className);
      const row = [];
      let summed = false;
      [...tr.children].forEach(c => {
        let v = head ? c.textContent.trim() : cellText(c);
        const col = row.length;
        if (!head && col < nl) {
          if (/ 요약$/.test(v)) summed = true;
          if (v) { last[col] = v; last = last.slice(0, col + 1); }
          else if (fill && !summed && last[col]) v = last[col];   // 위 행과 같은 묶음 → 채운다
        }
        row.push(v);
        for (let k = 1; k < (c.colSpan || 1); k++) row.push('');
      });
      out.push({ head, cells: row });
    });
    return out;
  }
  function toClipboard(m) {
    const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
    const tsv = m.map(r => r.cells.map(v => String(v).replace(/[\t\n]/g, ' ')).join('\t')).join('\n');
    const html = '<table>' + m.map(r => '<tr>' + r.cells.map(v => (r.head ? '<th>' : '<td>') + esc(v) + (r.head ? '</th>' : '</td>')).join('') + '</tr>').join('') + '</table>';
    if (navigator.clipboard && window.ClipboardItem) {
      return navigator.clipboard.write([new ClipboardItem({ 'text/plain': new Blob([tsv], { type: 'text/plain' }), 'text/html': new Blob([html], { type: 'text/html' }) })])
        .catch(() => legacyCopy(tsv));
    }
    return Promise.resolve(legacyCopy(tsv));
  }
  function legacyCopy(tsv) {
    const ta = h('textarea', 'tb-hidden'); ta.value = tsv;
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } finally { ta.remove(); }
  }
  let toastTimer;
  function toast(msg) {
    let t = document.querySelector('.tb-toast');
    if (!t) { t = h('div', 'tb-toast'); t.setAttribute('role', 'status'); document.body.appendChild(t); }
    t.textContent = msg; t.classList.add('is-on');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('is-on'), 2200);
  }
  function copySection(el, title, btn) {
    const table = el.querySelector('table.tb-table');
    if (!table) return;
    const m = tableMatrix(table);
    toClipboard(m).then(() => {
      toast(title + ' 표 ' + m.filter(r => !r.head).length + '행을 담았어요 · 엑셀에서 Ctrl+V');
      if (btn) { btn.innerHTML = ICON_DONE; btn.classList.add('is-done'); setTimeout(() => { btn.innerHTML = ICON_SHEET; btn.classList.remove('is-done'); }, 1600); }
    });
  }
  function copyButton(el, title) {
    const b = h('button', 'tb-xl'); b.type = 'button';
    b.innerHTML = ICON_SHEET;
    b.title = '엑셀로 가져가기 — 보이는 그대로 복사됩니다 (표 위에서 Ctrl+C도 됩니다)';
    b.setAttribute('aria-label', title + ' 표를 엑셀용으로 복사');
    b.addEventListener('click', () => copySection(el, title, b));
    el.dataset.copyTitle = title;
    return b;
  }
  /* 표 위에 마우스를 둔 채 Ctrl/⌘+C — 글자를 고르지 않았으면 그 표 전체를 복사한다 */
  let hovered = null;
  document.addEventListener('mouseover', e => { hovered = e.target.closest ? e.target.closest('section[data-copy-title]') : null; });
  document.addEventListener('keydown', e => {
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 'c' || !hovered) return;
    if (String(window.getSelection() || '') || /INPUT|TEXTAREA/.test((document.activeElement || {}).tagName || '')) return;
    e.preventDefault();
    copySection(hovered, hovered.dataset.copyTitle, hovered.querySelector('.tb-xl'));
  });

  function mount(rep) {
    const root = document.getElementById('overall-summary');
    const months = rep.months;
    const T = rep.table;

    /* 머리말 */
    if (rep.part_label) document.querySelectorAll('.tb-eyebrow').forEach(e => { e.textContent = '종합 리포트 · ' + rep.part_label; });
    document.querySelectorAll('[data-h="period"]').forEach(e => { e.textContent = rep.header.period; });
    document.querySelectorAll('[data-h="media"]').forEach(e => { e.textContent = rep.header.media || '-'; });

    /* Comment */
    const dailyEl = root.querySelector('[data-sec="c-daily"]');
    const weeklyEl = root.querySelector('[data-sec="c-weekly"]');
    if (rep.comment) {
      drawDaily(dailyEl, rep.comment.daily);
      drawWeekly(weeklyEl, rep.comment.weekly);
    } else { placeholder(dailyEl); placeholder(weeklyEl); }

    const placeEl = root.querySelector('[data-sec="place"]');
    const PL = rep.place && rep.place.n ? rep.place : null;
    if (!PL) placePending(placeEl);   // 노출 위치 차원이 없는 브랜드 — 섹션은 두고 이유를 알린다(차원이 생기면 자동으로 채워진다)
    const tableEls = ['total', 'monthly', 'product', 'target', 'weekly', 'daily', 'mix'].map(id => root.querySelector('[data-sec="' + id + '"]'));
    const filterEl = root.querySelector('[data-sec="filter"]');
    if (!T || !T.n) { tableEls.forEach(placeholder); filterEl.remove(); prune(root, rep); buildToc(root); return; }

    /* 표 데이터 펼치기 */
    const DAYS = T.days;
    const expand = X => {   // 열 기반 데이터 → 행 + 값 순서(광고비 큰 순)
      const C = X.cols, DIC = X.dict, keys = ['m', ...X.dims.map(d => d.key)];
      const rows = new Array(X.n);
      for (let i = 0; i < X.n; i++) {
        const dd = X.days[C.d[i]];
        const r = { dk: C.d[i], mo: dd.mo, ws: dd.ws, cost: C.cost[i], imp: C.imp[i], click: C.click[i], view: C.view[i] };
        keys.forEach(k => { r[k] = DIC[k][C[k][i]]; });
        rows[i] = r;
      }
      const rk = {};
      keys.forEach(k => { rk[k] = {}; DIC[k].forEach((v, i) => { rk[k][v] = i; }); });
      return { rows, rank: rk };
    };
    const { rows: DATA, rank } = expand(T);
    const DIC = T.dict;
    const PLX = PL ? expand(PL) : null;
    const wOf = {};
    DAYS.forEach(d => { wOf[d.ws] = d.w; });
    const monthKeys = months.map(m => m.key);
    const monthOf = {};
    months.forEach(m => { monthOf[m.key] = m; });
    const MEDIA = DIC.m.slice();

    const DEFS = metricDefs(T.has);
    const DIMS = T.dims;
    const has = k => DIMS.some(d => d.key === k);
    const DIM_DEF = { total: ['p', 't'], monthly: ['p', 't'], product: ['p'], target: ['p', 't'] };
    Object.keys(DIM_DEF).forEach(id => {
      const on = DIM_DEF[id].filter(has);
      DIM_DEF[id] = on.length ? on : DIMS.slice(0, 1).map(d => d.key);
    });
    // Mix: Media → Ad Type(상품 — 캠페인에 배정된 ELT 구분값) → 타겟팅(광고그룹). Media·Ad Type은 끌 수 없다('고정').
    // 줄은 캠페인 하나(캠페인 열은 보이지 않는다) — 목표(get_target_progress_v2)가 캠페인 단위로 오기 때문.
    const MIX_DIMS = [{ key: 'm', label: 'Media', lock: true }, { key: 'p', label: 'Ad Type', lock: true },
      { key: 't', label: '타겟팅' }].filter(d => d.key === 'm' || has(d.key));
    DIM_DEF.mix = MIX_DIMS.map(d => d.key);
    DEFS.mix = [['b', '예산'], ...months.map(m => [m.key, m.label]), ['imp', 'Exp.Imps'], ['clk', 'Exp.Clicks'], ['view', 'Exp.VIEW'],
      ['ctr', 'Exp.CTR'], ['vtr', 'Exp.VTR'], ['cpm', 'Exp.CPM'], ['cpc', 'Exp.CPC'], ['cpv', 'Exp.CPV']]
      .filter(([k]) => !(['view', 'vtr', 'cpv'].includes(k) && !T.has.view) && !(['clk', 'ctr', 'cpc'].includes(k) && !T.has.click))
      .map(([k, l]) => ({ k, l }));
    const dimsFor = id => (id === 'mix' ? MIX_DIMS : DIMS);
    const defaultCfg = id => DEFS[id].map(m => ({ k: m.k, on: true }));
    const defaultDims = id => { const on = DIM_DEF[id]; return [...on, ...dimsFor(id).map(d => d.key).filter(k => !on.includes(k))].map(k => ({ k, on: on.includes(k) })); };

    /* 예산·목표: 정확한 범위가 있으면 그 값, 없으면 더 잘게 받은 범위가 이 행의 단위를 모두 덮을 때만 합(비율 목표는 합하지 않는다) */
    const B = T.budgets || [];
    const keysetOf = b => Object.keys(b.scope).sort().join(',');
    function lookup(mo, fixed, key, rs) {
      const es = B.filter(b => b.mo === mo && b.v[key] != null);
      if (!es.length) return null;
      const fk = Object.keys(fixed).sort();
      const exact = es.find(b => keysetOf(b) === fk.join(',') && fk.every(k => b.scope[k] === fixed[k]));
      if (exact) return exact.v[key];
      if (RATIO_T.has(key)) return null;
      const levels = uniq(es.map(keysetOf)).map(s => (s ? s.split(',') : []))
        .filter(L => L.length > fk.length && fk.every(k => L.includes(k))).sort((a, b) => a.length - b.length);
      for (const L of levels) {
        const cand = es.filter(b => keysetOf(b) === L.join(',') && fk.every(k => b.scope[k] === fixed[k]));
        const haveKeys = new Set(cand.map(b => L.map(k => b.scope[k]).join('\u0001')));
        const need = uniq(rs.filter(r => r.mo === mo).map(r => L.map(k => r[k]).join('\u0001')));
        if (need.length && need.every(c => haveKeys.has(c))) return cand.reduce((s, b) => s + b.v[key], 0);
      }
      return null;
    }
    function targetsOf(rs, fixed) {
      if (!B.length || !rs.length) return null;
      const mos = uniq(rs.map(r => r.mo));
      const out = {};
      ['cost', 'imp', 'click', 'view', 'ctr', 'vtr', 'cpm', 'cpc', 'cpv'].forEach(key => {
        let s = 0;
        for (const mo of mos) { const v = lookup(mo, fixed, key, rs); if (v == null) { s = null; break; } s += v; }
        if (s != null && !(RATIO_T.has(key) && mos.length > 1)) out[key] = s;
      });
      // 비율 목표가 없으면(여러 단위·여러 달을 합친 행 등) 합친 예산·노출·클릭·조회 목표로 계산한다
      [['ctr', 'click', 'imp', 100], ['cpm', 'cost', 'imp', 1000], ['cpc', 'cost', 'click', 1],
       ['vtr', 'view', 'imp', 100], ['cpv', 'cost', 'view', 1]].forEach(([k, n, d, mul]) => {
        if (out[k] == null && out[n] && out[d]) out[k] = out[n] / out[d] * mul;
      });
      return out;
    }
    function progOf(rs) {
      let el = 0, tot = 0;
      uniq(rs.map(r => r.mo)).forEach(mo => { el += monthOf[mo].elapsed; tot += monthOf[mo].days; });
      return tot ? Math.round(el / tot * 100) + '%' : '';
    }

    /* 상태 */
    const camp = load(LS_CAMP);
    const st = {
      months: monthKeys.slice(), medias: MEDIA.slice(), col: {}, lvl: {}, more: {}, menu: null,
      campName: camp[rep.brand], mcfg: load(LS_METRICS), dcfg: load(LS_DIMS),
    };
    function cfg(id) {
      const saved = st.mcfg[id], def = defaultCfg(id);
      if (!Array.isArray(saved)) return def;
      const known = saved.filter(s => DEFS[id].some(m => m.k === s.k));
      return [...known, ...def.filter(d => !known.some(s => s.k === d.k))];
    }
    function setCfg(id, list) { st.mcfg = { ...st.mcfg, [id]: list }; save(LS_METRICS, st.mcfg); paint(); }
    function visible(id) {
      const list = cfg(id).filter(c => c.on).map(c => DEFS[id].find(m => m.k === c.k));
      return [...list.filter(m => m.g !== 's'), ...list.filter(m => m.g === 's')];
    }
    function dcfg(id) {
      const saved = st.dcfg[id], def = defaultDims(id);
      if (!Array.isArray(saved)) return def;
      const known = saved.filter(s => dimsFor(id).some(d => d.key === s.k))
        .map(s => (dimsFor(id).find(d => d.key === s.k).lock ? { ...s, on: true } : s));
      return [...known, ...def.filter(d => !known.some(s => s.k === d.k))];
    }
    function setDcfg(id, list) { st.dcfg = { ...st.dcfg, [id]: list }; save(LS_DIMS, st.dcfg); paint(); }
    function selDims(id) { return dcfg(id).filter(c => c.on).map(c => { const d = dimsFor(id).find(x => x.key === c.k); return { key: d.key, label: d.label }; }); }
    const isCol = (key, def) => (st.col[key] === undefined ? def : st.col[key]);

    /* 단계 접기 (Claude판 계층 표의 '모두 접기'를 단계별로) — '미디어'를 고르면 미디어 아래를 모두 접고, '전체'는 모두 펼친다.
     * 표마다 따로 기억한다(st.lvl[표] = 펼쳐 둘 단계 수). 고르면 그 표에서 하나씩 접고 편 것(st.col)은 지운다. */
    const lvlOf = id => (st.lvl[id] == null ? Infinity : st.lvl[id]);
    function depthCtl(id, labels, redraw) {
      if (!labels.length) return null;
      const g = h('div', 'tb-depth');
      g.appendChild(h('span', 'tb-depth-k', '펼침'));
      [...labels, '전체'].forEach((l, i) => {
        const lv = i < labels.length ? i : Infinity;
        const b = h('button', 'tb-depth-b' + (lvlOf(id) === lv ? ' is-on' : ''), l); b.type = 'button';
        b.title = lv === Infinity ? '모두 펼치기' : l + ' 단위까지만 보기(아래 단계 접기)';
        b.addEventListener('click', () => {
          st.lvl = { ...st.lvl, [id]: lv };
          st.col = Object.fromEntries(Object.entries(st.col).filter(([k]) => !k.startsWith(id + '|')));
          redraw();
        });
        g.appendChild(b);
      });
      return g;
    }

    document.addEventListener('mousedown', e => {
      if (st.menu && !(e.target.closest && e.target.closest('[data-metric-menu]'))) { st.menu = null; paint(); }
    });

    /* 디멘전·지표 설정 메뉴 (목업 menuVals) */
    function menu(id, kind) {
      const isM = kind === 'm';
      const list = isM ? cfg(id) : dcfg(id);
      const defs = isM ? DEFS[id] : dimsFor(id).map(d => ({ k: d.key, l: d.label, lock: d.lock }));
      const set = L => (isM ? setCfg(id, L) : setDcfg(id, L));
      const key = id + '|' + kind;
      const grp = k => defs.find(m => m.k === k).g || 'b';
      const root = h('div', 'lh-picker tb-menu' + (st.menu === key ? ' is-open' : ''));
      root.setAttribute('data-metric-menu', '1');
      const btn = h('button', 'lh-picker-btn'); btn.type = 'button';
      btn.appendChild(h('span', 'lh-picker-title', isM ? '지표 설정' : '디멘전 설정'));
      btn.appendChild(h('span', 'lh-picker-n', list.filter(c => c.on).length + '/' + list.length));
      btn.appendChild(h('span', 'lh-picker-caret', '▾'));
      btn.addEventListener('click', () => { st.menu = st.menu === key ? null : key; paint(); });
      root.appendChild(btn);
      const panel = h('div', 'lh-picker-panel');
      const top = h('div', 'lh-picker-head');
      top.appendChild(h('span', null, isM ? '지표 선택 · 순서 변경' : id === 'mix' ? '디멘전 선택 · 순서 변경' : '미디어 하위 디멘전 선택 · 순서 변경'));
      const reset = h('button', 'lh-picker-reset', '초기화'); reset.type = 'button';
      reset.addEventListener('click', () => set(isM ? defaultCfg(id) : defaultDims(id)));
      top.appendChild(reset);
      panel.appendChild(top);
      list.forEach((c, i) => {
        const sep = i > 0 && grp(list[i - 1].k) !== grp(c.k);
        const row = h('div', 'lh-picker-item' + (sep ? ' tb-sep' : ''));
        const lab = h('label');
        const def = defs.find(m => m.k === c.k);
        const cb = h('input'); cb.type = 'checkbox'; cb.checked = c.on || !!def.lock; cb.disabled = !!def.lock;
        cb.addEventListener('change', () => set(list.map((x, j) => (j === i ? { ...x, on: cb.checked } : x))));
        lab.appendChild(cb); lab.appendChild(document.createTextNode(' ' + def.l + (def.lock ? ' (고정)' : '')));
        row.appendChild(lab);
        [['↑', -1], ['↓', 1]].forEach(([t, d]) => {
          const j = i + d;
          const mv = h('button', 'lh-picker-mv', t); mv.type = 'button';
          mv.title = d < 0 ? '위로' : '아래로';
          mv.disabled = j < 0 || j >= list.length || grp(list[j].k) !== grp(c.k);
          mv.addEventListener('click', () => { const L = list.slice(); [L[i], L[j]] = [L[j], L[i]]; set(L); });
          row.appendChild(mv);
        });
        panel.appendChild(row);
      });
      root.appendChild(panel);
      return root;
    }

    /* 계층 펼치기 (목업 renderTree) — 행 = {cls, cells:[{t, cls, span, tog, togLabel, pk, edit, value, more}]}
     * 묶음 안 항목이 많으면(실데이터: 쿠팡 광고그룹·네이버 쇼핑 상품 수백 개) 광고비 상위 MORE개만 그리고 나머지는 '외 N개' 한 줄
     * (그 합계)로 접는다 — '더 보기'·'전체'로 펼친다. 주·일처럼 순서가 정해진 단계는 자르지 않는다. 요약·총합계는 항상 전체 기준. */
    function renderTree(rows, dims, o, out, lead) {
      const D = dims.length;
      const rk = o.rank || rank;
      const order = dim => dim.sort || ((a, b) => rk[dim.key][a] - rk[dim.key][b]);
      const walk = (rs, level, path, anc, fixed) => {
        const dim = dims[level];
        const groups = new Map();
        rs.forEach(r => { const k = r[dim.key]; const g = groups.get(k); if (g) g.push(r); else groups.set(k, [r]); });
        const all = [...groups.keys()].sort(order(dim));
        const lim = dim.sort ? all.length : (st.more[path] || FIRST(level));
        const keys = all.slice(0, lim);
        const rest = all.slice(lim);
        const restRow = () => {
          if (!rest.length) return;
          const rrs = rest.flatMap(k => groups.get(k));
          out.push({ cls: 'tb-morerow', cells: [...lead(), ...anc.map(f => f()),
            { t: '외 ' + rest.length.toLocaleString('en-US') + '개', more: path, left: rest.length, shown: lim, cls: 'tb-more', span: D - level },
            ...o.metrics(rrs, '', false, null)] });
        };
        keys.forEach(k => {
          const sub = groups.get(k);
          const label = dim.fmt ? dim.fmt(k) : k;
          const fx = { ...fixed, [dim.key]: k };
          if (level === D - 1) {
            out.push({ cls: 'tb-leafrow', cells: [...lead(), ...anc.map(f => f()), { t: label, cls: o.leafCls(level, dim) }, ...o.metrics(sub, '', true, fx)] });
            return;
          }
          const pk = path + '|' + k;
          const canCol = o.subAt(level);   // 접으면 '요약' 줄만 남는다 — 요약 줄이 있는 단계만 접힌다
          const col = canCol && isCol(pk, o.defCol(level));
          let shown = false;
          const lab = () => { const f = !shown; shown = true; return { t: f ? label : '', tog: f && canCol, col: false, pk, cls: o.groupCls(level) }; };
          if (!col) walk(sub, level + 1, pk, [...anc, lab], fx);
          if (o.subAt(level)) {
            out.push({ cls: 'tb-subrow tb-subrow' + Math.min(level, 2), cells: [...lead(), ...anc.map(f => f()),
              { t: label + ' 요약', tog: col, col: true, pk, cls: o.groupCls(level) + ' tb-c tb-sublabel', span: D - level },
              ...o.metrics(sub, '', false, fx)] });
          }
        });
        restRow();
      };
      walk(rows, 0, o.id, [], {});
    }

    function drawTable(el, opt) {
      el.innerHTML = '';
      const wrap = h('div', 'tb-wrap' + (opt.tall ? ' is-tall' : ''));
      const t = h('table', 'tb-table' + (opt.cls ? ' ' + opt.cls : ''));
      t.dataset.labels = opt.labels || 0;
      const thead = h('thead');
      if (opt.groups) {
        const tr = h('tr', 'tb-grow');
        opt.groups.forEach(g => { const th = h('th', g.cls, g.t); th.colSpan = g.span; tr.appendChild(th); });
        thead.appendChild(tr);
      }
      const tr = h('tr', opt.groups ? 'tb-hrow2' : '');
      opt.heads.forEach(x => tr.appendChild(h('th', x.cls, x.t)));
      thead.appendChild(tr);
      t.appendChild(thead);
      const tb = h('tbody');
      const nl = opt.labels || 0;
      opt.rows.forEach(r => {
        const row = h('tr', r.cls || '');
        let at = 0;
        r.cells.forEach(c => {
          const td = h('td', (c.cls || '') + (at < nl ? ' tb-lab' : ''));   // 이름 칸: 긴 이름은 줄바꿈(폭 상한)
          at += c.span || 1;
          if (c.span > 1) td.colSpan = c.span;
          if (c.edit) {
            const inp = h('input', 'tb-camp'); inp.value = c.value || ''; inp.placeholder = '캠페인명 입력';
            inp.addEventListener('input', () => { st.campName = inp.value; const all = load(LS_CAMP); all[rep.brand] = inp.value; save(LS_CAMP, all); });
            td.appendChild(inp);
          }
          if (c.inp) {   // Mix 입력값: 바꾸고 Enter·포커스 이동 시 반영
            const inp = h('input', 'tb-in' + (c.inp === 'text' ? ' tb-in-text' : ''));
            inp.value = c.value; inp.dataset.fid = c.fid || ''; if (c.inp === 'text') inp.placeholder = '캠페인명';
            inp.addEventListener('change', () => c.onInput(inp.value));
            td.appendChild(inp);
          }
          if (c.more) {   // '외 N개' — 더 보기(+MORE) · 전체
            td.appendChild(h('span', null, c.t));
            [['더 보기', Math.min(MORE, c.left)], ['전체', c.left]].forEach(([lb, n], i) => {
              if (i === 1 && c.left <= MORE) return;
              const b = h('button', 'tb-morebtn', lb); b.type = 'button';
              b.addEventListener('click', () => { st.more = { ...st.more, [c.more]: (st.more[c.more] || c.shown) + n }; opt.redraw(); });
              td.appendChild(b);
            });
            row.appendChild(td);
            return;
          }
          if (c.tog) {   // ▼ 펼친 묶음(누르면 접힘) · ▶ 접힌 묶음(요약 줄 — 누르면 펼침)
            const b = h('button', 'tb-tog', c.col ? '▶' : '▼'); b.type = 'button';
            b.title = c.col ? '펼치기' : '접기';
            b.setAttribute('aria-expanded', String(!c.col));
            b.addEventListener('click', () => { st.col = { ...st.col, [c.pk]: !c.col }; opt.redraw(); });
            td.appendChild(b);
          }
          if (c.t !== '' && c.t != null) td.appendChild(h('span', null, c.t));
          row.appendChild(td);
        });
        tb.appendChild(row);
      });
      t.appendChild(tb);
      wrap.appendChild(t);
      el.appendChild(wrap);
    }

    function head(el, title, sub, menus) {
      const hd = h('div', 'lh-section-head');
      const tt = h('div');
      const h2 = h('h2', null, title + ' ');
      h2.appendChild(h('span', 'lh-muted', sub));
      tt.appendChild(h2);
      hd.appendChild(tt);
      const ms = h('div', 'tb-menus');
      menus.filter(Boolean).forEach(m => ms.appendChild(m));
      ms.appendChild(copyButton(el, title));
      hd.appendChild(ms);
      el.appendChild(hd);
      const body = h('div');
      el.appendChild(body);
      return body;
    }

    /* Total / Monthly Summary (목업 buildSummary — 필터 미적용) */
    function buildSummary(el, kind) {
      el.innerHTML = '';
      const ms = visible(kind);
      const nB = ms.filter(m => m.g === 'b').length, nS = ms.length - nB;
      const edge = i => (i === 0 && nB ? ' tb-edge' : i === nB ? ' tb-edge2' : '');
      const basic = (rs, tg, prog, cls) => {
        const a = agg(rs);
        return ms.map((m, i) => ({ t: m.f({ a, tg, prog }), cls: 'tb-num' + edge(i) + (cls ? ' ' + cls : '') }));
      };
      const dims = [{ key: 'm', label: '미디어' }, ...selDims(kind)];
      const D = dims.length;
      const rows = [];
      const off = kind === 'monthly' ? 1 : 0;   // Monthly는 월이 맨 위 단계
      const block = (lead, mos, id) => {
        const scope = DATA.filter(x => mos.includes(x.mo));
        renderTree(scope, dims, {
          id,
          subAt: l => l === 0 && D > 1,
          defCol: l => l + off >= lvlOf(kind),
          groupCls: l => 'tb-c ' + (l === 0 ? 'tb-sg0' : 'tb-sg1'),
          leafCls: l => 'tb-c' + (l === 0 ? ' tb-b' : ''),
          metrics: (rs, cls, isLeaf, fixed) => {
            const tg = fixed ? targetsOf(rs, fixed) : null;   // '외 N개' 줄은 목표 범위가 없다
            return basic(rs, tg, isLeaf && tg && tg.cost ? progOf(rs) : '', cls);
          },
        }, rows, lead);
        return scope;
      };
      const leadOnce = make => { let shown = false; return () => { const f = !shown; shown = true; return [make(f)]; }; };
      let title, sub, firstHead;
      if (kind === 'total') {
        title = 'Total Summary'; sub = '전체 기간 · 필터 미적용'; firstHead = '캠페인명';
        const name = st.campName != null ? st.campName : rep.brand;
        block(leadOnce(f => ({ t: '', cls: 'tb-lead', edit: f, value: name })), monthKeys, kind);
      } else {
        title = 'Monthly Summary'; sub = '월별 · 필터 미적용'; firstHead = '월';
        months.forEach(mo => {
          const pk = kind + '|' + mo.key;
          const col = isCol(pk, 0 >= lvlOf(kind));   // 달을 접으면 'N월 요약' 줄만 남는다
          const dRows = col ? DATA.filter(x => x.mo === mo.key)
            : block(leadOnce(f => ({ t: f ? mo.label : '', cls: 'tb-lead tb-c', tog: f, col: false, pk })), [mo.key], pk);
          if (!dRows.length) return;
          rows.push({ cls: 'tb-msum', cells: [{ t: mo.label + ' 요약', cls: 'tb-c', span: 1 + D, tog: col, col: true, pk }, ...basic(dRows, targetsOf(dRows, {}), '', '')] });
        });
      }
      rows.push({ cls: 'tb-grand', cells: [{ t: 'Total 요약', cls: 'tb-c', span: 1 + D }, ...basic(DATA, targetsOf(DATA, {}), '', '')] });
      const redraw = () => buildSummary(el, kind);
      const levels = [...(off ? ['월'] : []), ...(D > 1 ? ['미디어'] : [])];
      const body = head(el, title, sub, [depthCtl(kind, levels, redraw), menu(kind, 'd'), menu(kind, 'm')]);
      const groups = [{ t: '기본 영역', span: 1 + D + nB, cls: 'tb-gh' }];
      if (nS) groups.push({ t: '목표 영역', span: nS, cls: 'tb-gh tb-edge2' });
      drawTable(body, {
        cls: 'tb-sum', groups, rows, labels: 1 + D, redraw,
        heads: [firstHead, ...dims.map(d => d.label)].map(t => ({ t, cls: 'tb-c' }))
          .concat(ms.map((m, i) => ({ t: m.l, cls: 'tb-c' + edge(i) }))),
      });
    }

    /* Product·Target·Weekly·Daily (목업 buildPivot — 월·미디어 필터 적용) */
    function buildPivot(el, id, title, rows, fixed, rk) {
      el.innerHTML = '';
      const ms = visible(id);
      const dims = [{ key: 'm', label: '미디어' }, ...(fixed || selDims(id))];
      const D = dims.length, out = [];
      const metricCells = (a, cls) => ms.map((m, i) => ({ t: m.f({ a }), cls: 'tb-num' + (i === 0 ? ' tb-edge' : '') + (cls ? ' ' + cls : '') }));
      renderTree(rows, dims, {
        id, rank: rk,
        subAt: l => l < D - 1,
        defCol: l => l >= lvlOf(id),
        groupCls: l => 'tb-g' + Math.min(l, 2),
        leafCls: (l, dim) => (l === 0 ? 'tb-g0 tb-g0leaf' : 'tb-leaf' + (dim.right ? ' tb-r' : '')),
        metrics: (rs, cls) => metricCells(agg(rs), cls),
      }, out, () => []);
      if (rows.length) out.push({ cls: 'tb-total', cells: [{ t: '총합계', cls: 'tb-c', span: D }, ...metricCells(agg(rows), '')] });
      else out.push({ cells: [{ t: '선택된 필터에 해당하는 데이터가 없습니다.', cls: 'lh-empty', span: D + ms.length }] });
      const redraw = () => buildPivot(el, id, title, rows, fixed, rk);
      const ctl = depthCtl(id, dims.slice(0, -1).map(d => d.label), redraw);
      const body = head(el, title, dims.map(d => d.label).join(' · ') + '별', fixed ? [ctl, menu(id, 'm')] : [ctl, menu(id, 'd'), menu(id, 'm')]);
      drawTable(body, {
        cls: 'tb-pivot', tall: id === 'daily', rows: out, labels: D, redraw,
        heads: dims.map(d => ({ t: d.label, cls: 'tb-c' })).concat(ms.map((m, i) => ({ t: m.l, cls: 'tb-r' + (i === 0 ? ' tb-edge' : '') }))),
      });
    }

    /* 월·미디어 필터 바 */
    function drawFilter() {
      filterEl.innerHTML = '';
      const pills = (label, opts, key) => {
        const g = h('div', 'tb-fgroup');
        g.appendChild(h('span', 'tb-flabel', label));
        opts.forEach(o => {
          const on = st[key].includes(o.v);
          const b = h('button', 'lh-tab' + (on ? ' is-on' : ''), o.l); b.type = 'button';
          b.addEventListener('click', () => { st[key] = on ? st[key].filter(x => x !== o.v) : [...st[key], o.v]; paint(); });
          g.appendChild(b);
        });
        return g;
      };
      filterEl.appendChild(pills('월', months.map(m => ({ v: m.key, l: m.label })), 'months'));
      filterEl.appendChild(h('span', 'tb-fdiv'));
      filterEl.appendChild(pills('미디어', MEDIA.map(m => ({ v: m, l: m })), 'medias'));
      const reset = h('button', 'tb-reset', '필터 초기화'); reset.type = 'button';
      reset.addEventListener('click', () => { st.months = monthKeys.slice(); st.medias = MEDIA.slice(); paint(); });
      filterEl.appendChild(reset);
      const shown = [['product', 'Product'], ['target', 'Target'], ['place', 'Placement'], ['weekly', 'Weekly'], ['daily', 'Daily']]
        .filter(([k]) => (k !== 'place' || PL) && (!(rep.tables && rep.tables.length) || rep.tables.includes(k))).map(([, l]) => l);
      filterEl.appendChild(h('span', 'tb-fnote', shown.join(' · ') + ' 표에 공통 적용'));
    }

    /* Mix (목업 buildMix — 목표 입력값 기준 월별 계획, 필터 미적용)
     * 줄 = 캠페인 하나(미디어·캠페인). Ad Type = 그 캠페인의 상품, 타겟팅 = 그 캠페인의 광고그룹(여럿이면 '·'로 잇는다).
     * 목표(budgets)에만 있고 실적이 없는 캠페인(미포함 캠페인 등)도 줄로 나온다(Ad Type·타겟팅 '-').
     * 입력값 = 월 예산·CPM·CPC·VTR(브라우저에 저장). 초기값 = 캠페인 목표(단가는 없으면 매체 목표), 없으면 0.
     * 그 달에 집행도 예산도 없는 달과 조회가 없는 줄의 VTR은 입력 불가(회색).
     * 예상치: 노출 = 예산/CPM×1000, 클릭 = 예산/CPC, 조회 = 노출×VTR, CTR·CPV는 그 합으로. */
    const mixAll = load(LS_MIX);
    st.mix = { lines: {}, ...(mixAll[rep.brand] || {}) };
    function setMix(fn) { st.mix = fn(st.mix); const all = load(LS_MIX); all[rep.brand] = st.mix; save(LS_MIX, all); paintMix(); }
    const MIX_KEYS = MIX_DIMS.map(d => d.key);
    const byCamp = has('c');
    const joinVals = (rs, k) => {   // 캠페인의 상품·광고그룹 이름 — 많으면 광고비 상위 3개 + '외 N'
      const vs = uniq(rs.map(r => r[k])).sort((a, b) => rank[k][a] - rank[k][b]);
      return vs.length > 3 ? vs.slice(0, 3).join('·') + ' 외 ' + (vs.length - 3) : vs.join('·');
    };
    const MIX_LINES = (() => {
      const lineKeys = byCamp ? ['m', 'c'] : MIX_KEYS;
      const by = new Map();
      DATA.forEach(r => { const id = lineKeys.map(k => r[k]).join('\u0001'); if (!by.has(id)) by.set(id, []); by.get(id).push(r); });
      const lines = [...by.entries()].map(([id, rs]) => {
        const line = { id, rows: rs };
        lineKeys.forEach(k => { line[k] = rs[0][k]; });
        MIX_KEYS.forEach(k => { if (!(k in line)) line[k] = joinVals(rs, k); });
        return line;
      });
      if (byCamp) {   // 목표에만 있는 캠페인
        B.filter(b => b.scope.c && b.scope.m && Object.keys(b.scope).length === 2).forEach(b => {
          const id = b.scope.m + '\u0001' + b.scope.c;
          if (by.has(id)) return;
          by.set(id, []);
          const line = { id, rows: [], m: b.scope.m, c: b.scope.c };
          MIX_KEYS.forEach(k => { if (!(k in line)) line[k] = '-'; });
          lines.push(line);
        });
      }
      // 월 예산: 캠페인 목표(캠페인 차원이 없으면 그 줄 범위, 그다음 매체 — 매체에 줄이 하나뿐일 때만).
      // 단가 목표(CPM·CPC·VTR): 캠페인 → 매체 순.
      const pick = (line, keys) => { const f = {}; keys.forEach(k => { if (k in line) f[k] = line[k]; }); return f; };
      const alone = (line, f) => lines.filter(l => Object.keys(f).every(k => l[k] === f[k])).length === 1;
      lines.forEach(line => {
        const rs = line.rows;
        const scopes = (byCamp ? [pick(line, ['m', 'c']), pick(line, ['m'])] : [pick(line, ['m', 'p', 't']), pick(line, ['m'])])
          .filter((f, i, a) => a.findIndex(g => JSON.stringify(g) === JSON.stringify(f)) === i);
        line.def = { noView: !T.has.view || (rs.length > 0 && !rs.some(r => r.view)) };
        months.forEach(mo => {
          let v = null;
          for (const f of scopes) { if (!alone(line, f)) continue; v = lookup(mo.key, f, 'cost', rs); if (v != null) break; }
          line.def[mo.key] = v != null ? v : rs.some(r => r.mo === mo.key) ? 0 : null;
        });
        ['cpm', 'cpc', 'vtr'].forEach(k => {
          let v = null;
          for (const f of scopes) { for (const mo of months) { v = lookup(mo.key, f, k, rs); if (v != null) break; } if (v != null) break; }
          line.def[k] = v != null ? v : 0;
        });
      });
      return lines;
    })();
    const mixVal = l => {
      const o = st.mix.lines[l.id] || {}, v = {};
      months.forEach(mo => { v[mo.key] = l.def[mo.key] == null ? null : (o[mo.key] != null ? o[mo.key] : l.def[mo.key]); });
      ['cpm', 'cpc'].forEach(k => { v[k] = o[k] != null ? o[k] : l.def[k]; });
      v.vtr = l.def.noView ? null : (o.vtr != null ? o.vtr : l.def.vtr);
      return v;
    };
    const mixCalc = ls => ls.reduce((a, l) => {
      const v = mixVal(l);
      const b = months.reduce((s, mo) => s + (v[mo.key] || 0), 0), imp = v.cpm ? b / v.cpm * 1000 : 0;
      a.b += b; months.forEach(mo => { a[mo.key] += v[mo.key] || 0; });
      a.imp += imp; a.clk += v.cpc ? b / v.cpc : 0;
      if (v.vtr != null) a.view += imp * v.vtr / 100;
      return a;
    }, months.reduce((a, mo) => ({ ...a, [mo.key]: 0 }), { b: 0, imp: 0, clk: 0, view: 0 }));
    const num = s => { const x = String(s).replace(/[^0-9.]/g, ''); return x === '' ? 0 : Number(x); };
    function buildMix(el) {
      el.innerHTML = '';
      const dims = selDims('mix'), D = dims.length;
      const mts = visible('mix');
      // 맨 아래 줄 = 화면 이름(Media·Ad Type·타겟팅)이 같은 캠페인들을 합친 한 줄(예: 7월 캠페인 + 8월 캠페인).
      // 월 예산 칸: 그 달 캠페인이 하나면 그 캠페인에 입력, 여럿이면 합계만(입력 불가). CPM·CPC·VTR 칸: 고치면 줄 안의 캠페인 모두에 적용,
      // 값이 캠페인마다 다르면 합친 예산·예상 노출로 계산한 가중 값을 보여 준다. 예상치는 캠페인(=달)마다 계산해 더한다.
      const setLines = (ids, f) => v => setMix(m => {
        const lines = { ...m.lines };
        ids.forEach(id => { lines[id] = { ...(lines[id] || {}), [f]: num(v) }; });
        return { ...m, lines };
      });
      const metrics = (ls, cls, isLeaf) => {
        const a = mixCalc(ls), vals = isLeaf ? ls.map(mixVal) : null, ids = ls.map(l => l.id), gid = ids.join('\u0002');
        const N = t => ({ t, cls: 'tb-num' + (cls ? ' ' + cls : '') });
        const NA = () => ({ t: '', cls: 'tb-num tb-na' });
        const I = (val, f, suffix, onInput) => ({ inp: 'num', value: suffix ? String(val == null ? '' : val) : n0(val || 0),
          onInput: onInput || setLines(ids, f), fid: gid + '|' + f, t: suffix || '', cls: 'tb-num tb-inp' + (cls ? ' ' + cls : '') });
        const common = f => { const xs = uniq(vals.map(v => v[f])); return xs.length === 1 ? xs[0] : null; };
        const noView = isLeaf && ls.every(l => l.def.noView);
        const wCpm = a.imp ? Math.round(a.b / a.imp * 1000) : 0, wCpc = a.clk ? Math.round(a.b / a.clk) : 0;
        const wVtr = a.imp ? Math.round(a.view / a.imp * 100) : 0;
        const map = {
          b: N(n0(a.b)),
          imp: N(n0(a.imp)), clk: N(n0(a.clk)),
          view: noView ? NA() : N(a.view ? n0(a.view) : ''),
          ctr: N(a.imp ? (a.clk / a.imp * 100).toFixed(2) + '%' : ''),
          vtr: noView ? NA() : isLeaf ? I(common('vtr') != null ? common('vtr') : wVtr, 'vtr', '%') : N(a.imp ? wVtr + '%' : ''),
          cpm: isLeaf ? I(common('cpm') != null ? common('cpm') : wCpm, 'cpm') : N(a.imp ? n0(a.b / a.imp * 1000) : ''),
          cpc: isLeaf ? I(common('cpc') != null ? common('cpc') : wCpc, 'cpc') : N(a.clk ? n0(a.b / a.clk) : ''),
          cpv: noView ? NA() : N(a.view ? n0(a.b / a.view) : ''),
        };
        months.forEach(mo => {
          const on = ls.filter(l => l.def[mo.key] != null);
          if (isLeaf && !on.length) map[mo.key] = NA();
          else if (isLeaf && on.length === 1) map[mo.key] = I(mixVal(on[0])[mo.key], mo.key, null, setLines([on[0].id], mo.key));
          else map[mo.key] = N(a[mo.key] ? n0(a[mo.key]) : '-');
        });
        return mts.map(m => map[m.k]);
      };
      const labelCell = (dim, k, first, leaf) => {
        const cls = 'tb-c tb-mx-' + dim.key + (leaf ? ' tb-mx-leaf' : '');
        return { t: first ? k : '', cls };
      };
      // 정렬: 광고비 큰 순(이어 붙인 이름은 첫 이름 기준), 실적 없는 '-'는 뒤로
      const ord = k => (key => (rank[k][key] != null ? rank[k][key] : rank[k][String(key).split('·')[0]] != null ? rank[k][String(key).split('·')[0]] + 0.5 : 1e9));
      const rows = [];
      const walk = (ls, level, anc, path) => {
        const dim = dims[level];
        const o = ord(dim.key);
        const keys = uniq(ls.map(l => l[dim.key])).sort((a, b) => o(a) - o(b) || String(a).localeCompare(String(b)));
        keys.forEach(k => {
          const sub = ls.filter(l => l[dim.key] === k);
          if (level === D - 1) {
            rows.push({ cls: 'tb-mxrow', cells: [...anc.map(f => f()), labelCell(dim, k, true, true), ...metrics(sub, '', true)] });
            return;
          }
          const pk = path + '|' + k;
          const leafCount = uniq(sub.map(l => dims.slice(level + 1).map(d => l[d.key]).join('|'))).length;
          const hasSub = level === 0 || (leafCount > 1 && keys.length > 1);   // Total 줄이 있는 묶음만 접힌다
          const col = hasSub && isCol(pk, level >= lvlOf('mix'));
          let shown = false;
          const lf = () => { const f = !shown; shown = true; return { ...labelCell(dim, k, f, false), tog: f && hasSub, col: false, pk }; };
          if (!col) walk(sub, level + 1, [...anc, lf], pk);
          if (hasSub) {
            rows.push({ cls: 'tb-mxsub tb-mxsub-' + (level === 0 ? 0 : 1), cells: [...anc.map(f => f()),
              { t: k + ' Total', cls: 'tb-c', span: D - level, tog: col, col: true, pk }, ...metrics(sub, '', false)] });
          }
        });
      };
      walk(MIX_LINES, 0, [], 'mix');
      rows.push({ cls: 'tb-grand', cells: [{ t: 'Grand Total', cls: 'tb-c', span: D }, ...metrics(MIX_LINES, '', false)] });
      const legend = h('span', 'tb-legend');
      legend.appendChild(h('b', null, '0,000'));
      legend.appendChild(document.createTextNode(' 입력값 (' + months.map(m => m.label).join('·') + ' 예산, VTR, CPM, CPC)'));
      const reset = h('button', 'lh-picker-btn', '입력값 초기화'); reset.type = 'button';
      reset.addEventListener('click', () => setMix(() => ({ lines: {} })));
      const body = head(el, 'Mix', '목표 입력값 기준 월별 계획 · 필터 미적용',
        [legend, reset, depthCtl('mix', dims.slice(0, -1).map(d => d.label), paintMix), menu('mix', 'd'), menu('mix', 'm')]);
      drawTable(body, {
        cls: 'tb-mix', rows, labels: D, redraw: paintMix,
        heads: dims.map(d => ({ t: d.label, cls: 'tb-c' })).concat(mts.map(m => ({ t: m.l, cls: 'tb-c' + (monthOf[m.k] ? ' tb-hm' : '') }))),
      });
    }
    function paintMix() {   // 입력 중인 칸의 포커스를 다시 그린 뒤에도 유지한다(Tab으로 다음 칸 이동)
      const a = document.activeElement, fid = a && a.dataset ? a.dataset.fid : null;
      buildMix(mixEl);
      if (fid) { const b = mixEl.querySelector('[data-fid="' + CSS.escape(fid) + '"]'); if (b) { b.focus(); b.select && b.select(); } }
    }

    const [totalEl, monthlyEl, productEl, targetEl, weekEl, dayEl, mixEl] = tableEls;
    const prodDim = has('p') ? [{ key: 'p', label: DIMS.find(d => d.key === 'p').label }] : [];   // 상품 또는 Ad Type
    function paint() {
      paintMix();
      buildSummary(totalEl, 'total');
      buildSummary(monthlyEl, 'monthly');
      drawFilter();
      const rows = DATA.filter(x => st.months.includes(x.mo) && st.medias.includes(x.m));
      buildPivot(productEl, 'product', 'Product', rows);
      buildPivot(targetEl, 'target', 'Target', rows);
      if (PL) {   // Placement: 미디어 → Ad Type(상품) → 노출 위치 — 따로 받은 노출 위치 데이터, 같은 월·미디어 필터
        const prs = PLX.rows.filter(x => st.months.includes(x.mo) && st.medias.includes(x.m));
        buildPivot(placeEl, 'place', 'Placement', prs, PL.dims.map(d => ({ key: d.key, label: d.label })), PLX.rank);
      }
      buildPivot(weekEl, 'weekly', 'Weekly', rows,
        [...prodDim, { key: 'ws', label: 'Week', fmt: k => wOf[k] + '주차', sort: (a, b) => a - b, right: true }]);
      buildPivot(dayEl, 'daily', 'Daily', rows,
        [...prodDim, { key: 'dk', label: '일', fmt: k => DAYS[k].label, sort: (a, b) => a - b }]);
    }
    paint();
    prune(root, rep);
    buildToc(root);
  }

  /* 하위 스킬(overall-summary-comment·total·tables·mix)은 고른 섹션만 남긴다 — rep.part가 없으면 전부.
   * 다른 섹션도 그린 뒤 떼어 낸다(필터를 바꿔 다시 그려도 떼어 낸 섹션은 화면에 없다). */
  const PART_SECS = { comment: ['c-daily', 'c-weekly'], total: ['total', 'monthly'],
                      tables: ['filter', 'product', 'target', 'place', 'weekly', 'daily'], mix: ['mix'] };
  function prune(root, rep) {
    if (!rep.part) return;
    let keep = PART_SECS[rep.part] || [];
    if (rep.part === 'tables' && rep.tables && rep.tables.length) keep = ['filter', ...rep.tables];
    root.querySelectorAll('[data-sec]').forEach(el => {
      if (keep.includes(el.dataset.sec)) return;
      (el.closest('section.lh-section') || el).remove();
    });
  }

  /* 오른쪽 목차: 섹션 제목으로 만든 바로가기 + 지금 보는 섹션 표시 + 맨 위로.
   * 넓은 화면은 제목이 펼쳐진 채, 좁으면 점만 보이고 마우스를 올리면 펼친다(표 폭을 덜 잡아먹게). */
  function buildToc(root) {
    const secs = [...root.querySelectorAll('section.lh-section')].filter(s => s.querySelector('h2'));
    if (!secs.length) return;
    const nav = h('nav', 'tb-toc'); nav.setAttribute('aria-label', '목차');
    nav.appendChild(h('div', 'tb-toc-h', '목차'));
    const items = secs.map((s, i) => {
      s.id = s.id || 'sec-' + (s.dataset.sec || 'c' + i);
      const t = s.querySelector('h2').firstChild.textContent.trim();
      if (s.previousElementSibling && s.previousElementSibling.matches('.tb-filter')) nav.appendChild(h('div', 'tb-toc-div', '세부 성과'));
      const a = h('a', 'tb-toc-a'); a.href = '#' + s.id; a.title = t;
      a.appendChild(h('span', 'tb-toc-dot'));
      a.appendChild(h('span', 'tb-toc-t', t));
      a.addEventListener('click', e => { e.preventDefault(); s.scrollIntoView({ behavior: 'smooth', block: 'start' }); history.replaceState(null, '', '#' + s.id); });
      nav.appendChild(a);
      return a;
    });
    const top = h('button', 'tb-toc-top'); top.type = 'button'; top.title = '맨 위로';
    top.appendChild(h('span', 'tb-toc-dot', '↑'));
    top.appendChild(h('span', 'tb-toc-t', '맨 위로'));
    top.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    nav.appendChild(top);
    document.body.appendChild(nav);
    let raf = 0;
    const spy = () => {
      raf = 0;
      const y = window.innerHeight * 0.3;
      let on = 0;
      secs.forEach((s, i) => { if (s.getBoundingClientRect().top <= y) on = i; });
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) on = secs.length - 1;
      items.forEach((a, i) => a.classList.toggle('is-on', i === on));
    };
    window.addEventListener('scroll', () => { if (!raf) raf = requestAnimationFrame(spy); }, { passive: true });
    spy();
  }

  /* Placement 자리 — 노출 위치 데이터가 없을 때 */
  function placePending(el) {
    el.innerHTML = '';
    const hd = h('div', 'lh-section-head');
    const h2 = h('h2', null, 'Placement ');
    h2.appendChild(h('span', 'lh-muted', '미디어 · 상품 · 노출 위치별'));
    hd.appendChild(h2);
    el.appendChild(hd);
    const box = h('div', 'tb-pending');
    box.appendChild(h('strong', null, '노출 위치 데이터 준비 중'));
    box.appendChild(h('span', null, '이 브랜드 데이터에 노출 위치(placement) 차원이 아직 없습니다. 차원이 추가되면 다음 보고서부터 이 표가 채워집니다.'));
    el.appendChild(box);
  }

  /* Daily Comment: 요약 → 매체별 불릿(급감 광고그룹 하위 불릿) → 맺음 */
  function drawDaily(el, d) {
    el.innerHTML = '';
    el.closest('section').querySelector('[data-meta]').textContent = d.meta;
    const box = h('div', 'tb-comment');
    box.appendChild(h('p', null, d.summary));
    const ul = h('ul', 'tb-ul');
    d.items.forEach(it => {
      const li = h('li');
      li.appendChild(h('strong', null, it.k + ':'));
      li.appendChild(document.createTextNode(' ' + it.v));
      if (it.subs && it.subs.length) {
        const sub = h('ul', 'tb-ul2');
        it.subs.forEach(s => { const x = h('li'); x.appendChild(h('strong', null, s.k + ':')); x.appendChild(document.createTextNode(' ' + s.v)); sub.appendChild(x); });
        li.appendChild(sub);
      }
      ul.appendChild(li);
    });
    box.appendChild(ul);
    box.appendChild(h('p', null, d.closing));
    el.appendChild(box);
  }

  /* Weekly Comment: [소진] · [효율](매체 요약 + 상품 불릿) */
  function drawWeekly(el, w) {
    el.innerHTML = '';
    el.closest('section').querySelector('[data-meta]').textContent = w.meta;
    const box = h('div', 'tb-comment tb-weekly');
    w.sections.forEach(sec => {
      const s = h('div', 'tb-wsec');
      s.appendChild(h('div', 'tb-wh', sec.h));
      s.appendChild(h('p', null, sec.text));
      sec.groups.forEach(g => {
        const gg = h('div', 'tb-wgroup');
        gg.appendChild(h('div', 'tb-wmedia', g.media));
        gg.appendChild(h('p', null, g.summary));
        if (g.bullets.length) {
          const ul = h('ul', 'tb-ul2');
          g.bullets.forEach(b => { const li = h('li'); li.appendChild(h('strong', null, b.k + ':')); li.appendChild(document.createTextNode(' ' + b.v)); ul.appendChild(li); });
          gg.appendChild(ul);
        }
        s.appendChild(gg);
      });
      box.appendChild(s);
    });
    el.appendChild(box);
  }

  window.OverallSummary = { mount };
})();
