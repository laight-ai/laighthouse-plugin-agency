/* Copilot 보고서 공용 킷 JS — report_kit.py 가 만든 뷰 모델을 클래스 기반 DOM으로 그린다.
 * 모양은 report_kit.css 만 정한다(인라인 style 없음 — 데이터 색만 CSS 변수 --c 로 넘긴다).
 * 전역: window.LHKit = { init, fmt, delta, kpiGrid, bullets, tabs, trend, barLine, compareTable, groupSummary, selectCards, pickTable,
 *                        creativeCards, creativeTable, placeholder, onCompare }
 */
(function () {
  const K = {};
  let CURRENCY = '₩';
  const ZERO_DEC = ['₩', '¥', '원', 'KRW', 'JPY'];
  const SUFFIX = ['원', 'KRW', 'USD', 'JPY', 'EUR'];
  const CURRENCY_UNITS = ['₩', '$', '€', '£', '¥', '원', 'KRW', 'USD', 'JPY', 'EUR'];
  const cmpListeners = [];
  let cmpKey = null;

  K.init = function (report) {
    if (report && report.currency) CURRENCY = report.currency;
    if (window.Chart) {
      Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans KR', sans-serif";
      Chart.defaults.font.size = 11;
      Chart.defaults.color = '#64748b';
    }
  };

  function h(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function color(e, c) { if (c) e.style.setProperty('--c', c); return e; }
  // 요약 불릿 등: 텍스트는 이스케이프하고 <strong>만 허용한다.
  function rich(e, s) {
    const esc = String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    e.innerHTML = esc.replace(/&lt;(\/?)strong&gt;/g, '<$1strong>');
    return e;
  }

  function money(v, cur) {
    cur = cur || CURRENCY;
    let body;
    if (ZERO_DEC.includes(cur)) {
      const d = Math.abs(v) >= 100 ? 0 : 1;
      body = Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
    } else {
      body = Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return SUFFIX.includes(cur) ? body + cur : cur + body;
  }
  /* report_kit.fmt_metric 과 같은 규칙 */
  K.fmt = function (v, unit) {
    if (v == null || typeof v !== 'number' || Number.isNaN(v)) return '-';
    if (unit === '%') return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%';
    if (CURRENCY_UNITS.includes(unit)) return money(v, unit);
    const body = (Number.isInteger(v) || Math.abs(v) >= 100)
      ? Math.round(v).toLocaleString('en-US')
      : v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return unit ? body + unit : body;
  };
  function axis(v, unit) {
    const a = Math.abs(v);
    const loc = (x, d) => Number(x).toLocaleString('en-US', { maximumFractionDigits: d });
    if (unit === '%') return loc(v, 2) + '%';
    let s;
    if (a >= 1e8) s = loc(v / 1e8, 1) + '억';
    else if (a >= 1e4) s = loc(v / 1e4, 1) + '만';
    else s = loc(v, a < 100 ? 1 : 0);
    if (CURRENCY_UNITS.includes(unit)) return SUFFIX.includes(unit) ? s + unit : unit + s;
    return s;
  }
  /* ── 색칠 기준(고정): 이보다 작은 증감은 색을 칠하지 않는다(값·화살표는 그대로). 보고서에서 고르는 입력란은 두지 않는다.
   * delta = 변화율 %, deltaP = 단위가 %인 지표의 %p 차, pace = MTD 진척도 %p */
  const THR = { delta: 10, deltaP: 1, pace: 10 };
  const thrListeners = [];
  K.thr = THR;
  K.onThreshold = function (fn) { thrListeners.push(fn); };
  K.dirOf = function (x, pp) {
    if (x == null || Number.isNaN(x)) return 'flat';
    return Math.abs(x) < Math.max(pp ? THR.deltaP : THR.delta, 1e-12) ? 'flat' : (x > 0 ? 'up' : 'down');
  };
  /* 진척도: 소진율 - 진행률(%p) → 과속(up)/저소진(warn) */
  K.paceCls = function (diff) { return diff == null ? '' : diff > THR.pace ? 'up' : diff < -THR.pace ? 'warn' : ''; };
  /* 예상 소진율(%) → 100 ± 진척도/2 밖이면 색 */
  K.projCls = function (pr) { return pr == null ? '' : pr > 100 + THR.pace / 2 ? 'up' : pr < 100 - THR.pace / 2 ? 'warn' : ''; };
  /* 목표 대비(%) — CPV 등 낮을수록 좋은 지표: 목표보다 높으면 빨강, 낮으면 초록 */
  K.goalCls = function (gap) { return gap == null ? '' : gap > THR.pace ? 'up' : gap < -THR.pace ? 'good' : ''; };
  /* 예전 템플릿 호환 — 입력란 없이 아무것도 그리지 않는다 */
  K.thresholdBar = function (el) { if (el) el.remove(); };

  /* report_kit.delta 와 같은 규칙 + 증감 숫자 x. 색(dir)은 임계치를 따른다. */
  K.delta = function (cur, base, unit) {
    if (typeof cur !== 'number' || typeof base !== 'number') return { text: '-', dir: 'flat', x: null };
    let x, dec, suf;
    if (unit === '%') { x = cur - base; dec = 2; suf = '%p'; }
    else { if (base === 0) return { text: '-', dir: 'flat', x: null }; x = (cur / base - 1) * 100; dec = 1; suf = '%'; }
    if (Math.abs(x) < 0.5 * Math.pow(10, -dec)) return { text: '– ' + (0).toFixed(dec) + suf, dir: 'flat', x: 0 };
    return { text: (x > 0 ? '▲ +' : '▼ ') + x.toFixed(dec) + suf, dir: K.dirOf(x, unit === '%'), x };
  };

  /* ── 차원 필터: "매체:Google 광고:reels 세일"
   * - 차원:값 = 그 차원 이름에 값이 들어 있으면(부분 일치), 차원:=값 = 정확히 같으면(드롭다운이 넣는 형식)
   * - 같은 차원 여러 개는 OR, 차원끼리는 AND, 나머지 단어는 행 경로 전체에서 찾기
   * - 공백이 있는 차원 이름·값은 따옴표: "캠페인 유형":="여름 세일" */
  const TOKEN_RE = /(?:"[^"]*"|[^\s"])+/g;
  const unq = s => String(s).replace(/^"(.*)"$/, '$1');
  function splitTok(tok) {   // 따옴표 밖의 첫 ':' 에서 나눈다
    let inq = false;
    for (let i = 0; i < tok.length; i++) {
      if (tok[i] === '"') inq = !inq;
      else if (tok[i] === ':' && !inq) return [tok.slice(0, i), tok.slice(i + 1)];
    }
    return null;
  }
  K.queryToken = function (label, value) {   // 드롭다운이 넣는 정확 일치 토큰
    const q = s => (/[\s:"]/.test(s) ? '"' + String(s).replace(/"/g, "'") + '"' : String(s));
    return q(label) + ':=' + q(String(value));
  };
  K.parseQuery = function (q, labels) {
    const out = { free: [], by: {} };
    const norm = s => String(s).trim().toLowerCase();
    const idx = {};
    labels.forEach((l, i) => { idx[norm(l)] = i; });
    (String(q || '').match(TOKEN_RE) || []).forEach(tok => {
      const sp = splitTok(tok);
      const li = sp ? idx[norm(unq(sp[0]))] : null;
      if (sp && li != null) {
        let v = sp[1], exact = false;
        if (v.startsWith('=')) { exact = true; v = v.slice(1); }
        v = norm(unq(v));
        if (v) (out.by[li] = out.by[li] || []).push({ v, exact });
      } else {
        const v = norm(unq(tok));
        if (v) out.free.push(v);
      }
    });
    out.empty = !out.free.length && !Object.keys(out.by).length;
    return out;
  };
  /* values[i] = i번째 차원 값(없으면 null). 조건을 모두 만족하면 true */
  K.matchQuery = function (pq, values) {
    if (!pq || pq.empty) return true;
    for (const i in pq.by) {
      const v = values[i];
      if (v == null) return false;
      const s = String(v).toLowerCase().trim();
      if (!pq.by[i].some(x => (x.exact ? s === x.v : s.includes(x.v)))) return false;
    }
    const all = values.filter(v => v != null).join(' ').toLowerCase();
    return pq.free.every(x => all.includes(x));
  };
  /* 차원별 드롭다운(다중 선택) — 처음엔 값이 모두 체크돼 있고(전체), 체크를 풀어 줄인다. 하나라도 풀면 체크된 값만
   * 검색창에 "차원:=값"으로 채워지고, 다시 모두 체크하면 그 차원 조건이 빠진다. 마지막 하나는 풀 수 없다.
   * dims = [{label, values}] */
  K.dimDropdowns = function (wrapEl, dims, input, maxValues) {
    wrapEl.innerHTML = '';
    wrapEl.classList.add('lh-dd-wrap');
    const syncs = [];
    dims.forEach(d => {
      const vals = Array.from(new Set(d.values.filter(v => v != null))).sort((a, b) => String(a).localeCompare(String(b)));
      if (!vals.length || vals.length > (maxValues || 200)) return;
      const toks = vals.map(v => K.queryToken(d.label, v));
      const box = h('details', 'lh-dd');
      const sum = h('summary');
      box.appendChild(sum);
      const list = h('div', 'lh-dd-list');
      const cbs = vals.map((v, i) => {
        const lab = h('label');
        const cb = h('input'); cb.type = 'checkbox';
        cb.addEventListener('change', () => {
          const on = cbs.filter(c => c.checked);
          if (!on.length) { cb.checked = true; return; }   // 마지막 하나는 남긴다
          const rest = (input.value.match(TOKEN_RE) || []).filter(x => !toks.includes(x));
          input.value = rest.concat(on.length === vals.length ? [] : cbs.map((c, j) => c.checked && toks[j]).filter(Boolean)).join(' ');
          input.dispatchEvent(new Event('input'));
        });
        lab.appendChild(cb);
        lab.appendChild(document.createTextNode(' ' + v));
        list.appendChild(lab);
        return cb;
      });
      const sync = () => {   // 검색창의 정확 일치 토큰 → 체크 상태(이 차원 토큰이 없으면 전체)
        const cur = input.value.match(TOKEN_RE) || [];
        const any = toks.some(x => cur.includes(x));
        cbs.forEach((c, j) => { c.checked = !any || cur.includes(toks[j]); });
        const n = cbs.filter(c => c.checked).length;
        sum.textContent = d.label + (n === vals.length ? ' 전체' : ' ' + n + '/' + vals.length) + ' ▾';
      };
      syncs.push(sync);
      sync();
      box.appendChild(list);
      wrapEl.appendChild(box);
    });
    input.addEventListener('input', () => syncs.forEach(f => f()));
    document.addEventListener('click', e => {
      wrapEl.querySelectorAll('details[open]').forEach(dd => { if (!dd.contains(e.target)) dd.open = false; });
    });
  };

  K.placeholder = function (el) {
    el.innerHTML = '';
    el.appendChild(h('div', 'lh-placeholder', '데이터 준비 중'));
  };

  /* 비교 기준 토글(전일/전주 동요일) — KPI 카드와 비교 표가 함께 바뀐다 */
  K.onCompare = function (fn) { cmpListeners.push(fn); };
  function setCompare(k) { cmpKey = k; cmpListeners.forEach(fn => fn(k)); }

  K.tabs = function (el, items, active, onPick) {
    el.innerHTML = '';
    el.classList.add('lh-tabs');
    const btns = items.map(it => {
      const b = h('button', 'lh-tab' + (it.key === active ? ' is-on' : ''), it.label);
      b.type = 'button';
      b.addEventListener('click', () => {
        btns.forEach(x => x.classList.toggle('is-on', x === b));
        onPick(it.key);
      });
      el.appendChild(b);
      return b;
    });
  };

  K.compareTabs = function (el, items, active) {
    cmpKey = active;
    K.tabs(el, items, active, setCompare);
  };

  /* KPI 그리드. card = {label, value, bar?, sub?, deltas: [{key, label, text, dir}]}
   * 비교 키가 여럿이면 활성 키의 증감이 주 줄, 나머지는 보조 줄. */
  K.kpiGrid = function (el, cards) {
    el.innerHTML = '';
    const grid = h('div', 'lh-kpis' + (cards.length <= 2 ? ' is-wide' : ''));
    el.appendChild(grid);
    const lines = [];
    cards.forEach(c => {
      const card = h('div', 'lh-kpi');
      card.appendChild(h('div', 'lh-kpi-label', c.label));
      if (c.tag) card.appendChild(h('span', 'lh-tag tone-' + (c.tag.tone || 'neutral'), c.tag.label));
      card.appendChild(h('div', 'lh-kpi-value', c.value));
      if (c.bar != null) {
        const bar = h('div', 'lh-bar');
        const fill = h('div', 'lh-bar-fill' + (c.bar_cls ? ' ' + c.bar_cls : ''));
        fill.style.setProperty('--w', Math.max(0, Math.min(1, c.bar)) * 100 + '%');
        bar.appendChild(fill);
        if (c.marker != null) {   // 기간 진행률 세로선
          const mk = h('div', 'lh-bar-marker');
          mk.style.setProperty('--m', Math.max(0, Math.min(1, c.marker)) * 100 + '%');
          bar.appendChild(mk);
        }
        card.appendChild(bar);
      }
      // lines = 카드가 직접 정한 줄들 [{text, cls}] (목표 대비 진척·전월 대비 등). x가 있으면 증감 색을 임계치로 다시 정한다.
      (c.lines || []).forEach(ln => {
        const e = h('div', ln.cls || 'lh-kpi-line', ln.text);
        if (ln.x !== undefined && ln.x !== null && /lh-kpi-delta/.test(ln.cls || '')) {
          e.className = 'lh-kpi-delta ' + K.dirOf(ln.x, ln.pp);
        }
        card.appendChild(e);
      });
      const main = h('div', 'lh-kpi-delta');
      const others = h('div', 'lh-kpi-sub');
      card.appendChild(main);
      card.appendChild(others);
      if (c.sub) card.appendChild(h('div', 'lh-kpi-sub', c.sub));
      grid.appendChild(card);
      lines.push({ c, main, others });
    });
    function paint(k) {
      lines.forEach(({ c, main, others }) => {
        const ds = c.deltas || [];
        const pri = ds.find(d => d.key === k) || ds[0];
        main.textContent = pri ? pri.label + ' 대비 ' + pri.text : '';
        const dir = !pri ? '' : (pri.x === undefined || /^[–-]/.test(pri.text)) ? pri.dir : K.dirOf(pri.x, pri.pp);
        main.className = 'lh-kpi-delta ' + dir;
        others.textContent = ds.filter(d => d !== pri).map(d => d.label + ' 대비 ' + d.text).join(' · ');
      });
    }
    paint(cmpKey);
    K.onCompare(paint);
    K.onThreshold(() => paint(cmpKey));
  };

  /* 요약 불릿. item = {head?, text, tone: red|green|yellow|neutral} */
  K.bullets = function (el, items) {
    el.innerHTML = '';
    const ul = h('ul', 'lh-bullets');
    items.forEach(it => {
      const li = h('li', 'lh-bullet tone-' + (it.tone || 'neutral'));
      li.appendChild(h('span', 'lh-dot'));
      const t = h('span', 'lh-bullet-text');
      if (it.head) { t.appendChild(h('strong', null, it.head)); t.appendChild(document.createTextNode(' ')); }
      const body = h('span');
      rich(body, it.text);
      t.appendChild(body);
      li.appendChild(t);
      ul.appendChild(li);
    });
    el.appendChild(ul);
  };

  const weekendBg = {
    id: 'lhWeekend',
    beforeDraw(ch, _a, opts) {
      const idx = (opts && opts.idx) || [];
      if (!idx.length || !ch.chartArea) return;
      const { ctx, chartArea: a, scales: { x } } = ch;
      const w = ch.data.labels.length > 1 ? x.getPixelForValue(1) - x.getPixelForValue(0) : a.right - a.left;
      ctx.save();
      ctx.fillStyle = '#f8fafc';
      idx.forEach(i => {
        const cx = x.getPixelForValue(i);
        const left = Math.max(a.left, cx - w / 2), right = Math.min(a.right, cx + w / 2);
        ctx.fillRect(left, a.top, right - left, a.bottom - a.top);
      });
      ctx.restore();
    },
  };

  /* 지표 선택 라인 추이. spec = {labels, weekend?, metrics:[meta], default_metric, series:[{name, color,
   * values:{m:[..]}, legend?:{m:"..."}}], legend_toggle?, note?} */
  K.trend = function (el, spec) {
    el.innerHTML = '';
    const bar = h('div', 'lh-toolbar');
    const tabs = h('div');
    const legend = h('div', 'lh-legend');
    if (spec.tab_label) { const tw = h('div', 'lh-labeled'); tw.appendChild(h('span', 'lh-mini-label', spec.tab_label)); tw.appendChild(tabs); bar.appendChild(tw); }
    else bar.appendChild(tabs);
    if (spec.legend_label) { const lw = h('div', 'lh-labeled'); lw.appendChild(h('span', 'lh-mini-label', spec.legend_label)); lw.appendChild(legend); bar.appendChild(lw); }
    else bar.appendChild(legend);
    el.appendChild(bar);
    const box = h('div', 'lh-chart');
    const cv = document.createElement('canvas');
    box.appendChild(cv);
    el.appendChild(box);
    let metric = spec.default_metric || spec.metrics[0].key;
    const unitOf = k => (spec.metrics.find(m => m.key === k) || {}).unit;
    const hidden = new Set();
    const chart = new Chart(cv, {
      type: 'line',
      data: { labels: spec.labels, datasets: [] },
      plugins: [weekendBg],
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false }, lhWeekend: { idx: spec.weekend || [] },
          tooltip: { callbacks: { label: c => c.dataset.label + ': ' + K.fmt(c.parsed.y, unitOf(metric)) } },
        },
        scales: { x: { grid: { display: false } },
                  y: { beginAtZero: true, grid: { color: '#f1f5f9' }, ticks: { callback: v => axis(v, unitOf(metric)) } } },
      },
    });
    let showAll = null;
    if (spec.legend_toggle) {   // 숨긴 계열이 있을 때만 "전체 보기"
      showAll = h('button', 'lh-tab lh-showall', '전체 보기');
      showAll.type = 'button';
      showAll.addEventListener('click', () => { hidden.clear(); draw(); });
    }
    function draw() {
      chart.data.datasets = spec.series.map(s => ({
        label: s.name, data: (s.values[metric] || []).map(v => (v == null ? null : v)), hidden: hidden.has(s.name),
        borderColor: s.color, backgroundColor: s.color, tension: 0.3, pointRadius: 3, borderWidth: 2, spanGaps: true,
      }));
      chart.update();
      legend.innerHTML = '';
      spec.series.forEach(s => {
        const it = color(h(spec.legend_toggle ? 'button' : 'span', 'lh-legend-item' + (hidden.has(s.name) ? ' is-off' : '')), s.color);
        it.appendChild(h('span', 'lh-swatch'));
        it.appendChild(h('span', 'lh-legend-name', s.name));
        const lv = s.legend && s.legend[metric];
        if (lv) it.appendChild(h('span', 'lh-legend-val', lv));
        if (spec.legend_toggle) {
          it.type = 'button';
          it.addEventListener('click', () => { hidden.has(s.name) ? hidden.delete(s.name) : hidden.add(s.name); draw(); });
        }
        legend.appendChild(it);
      });
      if (showAll && hidden.size) legend.appendChild(showAll);
    }
    K.tabs(tabs, spec.metrics.map(m => ({ key: m.key, label: m.label })), metric, k => { metric = k; draw(); });
    draw();
    if (spec.note) el.appendChild(h('p', 'lh-note', spec.note));
  };

  /* 막대 + 선 이중 축. spec = {labels, bar:{label, unit, data, color}, line:{label, unit, data, color}} */
  K.barLine = function (el, spec) {
    el.innerHTML = '';
    const legend = h('div', 'lh-legend');
    [[spec.bar, 'lh-swatch box'], [spec.line, 'lh-swatch']].filter(([s]) => s).forEach(([s, cls]) => {
      const it = color(h('span', 'lh-legend-item'), s.color);
      it.appendChild(h('span', cls));
      it.appendChild(h('span', 'lh-legend-name', s.label));
      legend.appendChild(it);
    });
    el.appendChild(legend);
    const box = h('div', 'lh-chart');
    const cv = document.createElement('canvas');
    box.appendChild(cv);
    el.appendChild(box);
    const line = spec.line;   // 없으면 막대만(Monthly 종합의 월간 전체 광고비 추이)
    const datasets = [{ type: 'bar', label: spec.bar.label, data: spec.bar.data, backgroundColor: spec.bar.color, borderRadius: 4, yAxisID: 'y', order: 2, maxBarThickness: 64 }];
    if (line) datasets.push({ type: 'line', label: line.label, data: line.data, borderColor: line.color, backgroundColor: line.color,
      pointRadius: 3, borderWidth: 2, tension: 0.3, yAxisID: 'y2', order: 1, spanGaps: true });
    const scales = {
      x: { grid: { display: false } },
      y: { beginAtZero: true, grid: { color: '#f1f5f9' }, ticks: { callback: v => axis(v, spec.bar.unit) } },
    };
    if (line) scales.y2 = { position: 'right', grid: { display: false }, ticks: { callback: v => axis(v, line.unit) } };
    new Chart(cv, {
      data: { labels: spec.labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => c.dataset.label + ': ' +
          K.fmt(c.parsed.y, c.datasetIndex === 0 ? spec.bar.unit : line.unit) } } },
        scales,
      },
    });
  };

  /* Weekly Summary. groups = [{title, lead, media:[{name, dot?, desc, bullets:[{label, text, tone}]}]}]
   * 텍스트는 <strong>만 허용. tone(red|yellow|green|neutral)은 라벨 색이다. */
  K.groupSummary = function (el, groups) {
    el.innerHTML = '';
    const wrap = h('div', 'lh-gsum');
    groups.forEach(g => {
      const box = h('div', 'lh-gsum-group');
      box.appendChild(h('h3', 'lh-gsum-title', '[' + g.title + ']'));
      if (g.lead) box.appendChild(rich(h('p', 'lh-gsum-lead'), g.lead));
      (g.media || []).forEach(m => {
        const mb = h('div', 'lh-gsum-media');
        const head = h('div', 'lh-gsum-mhead');
        head.appendChild(color(h('span', 'lh-mdot'), m.dot));
        head.appendChild(h('strong', null, m.name));
        mb.appendChild(head);
        if (m.desc) mb.appendChild(rich(h('p', 'lh-gsum-desc'), m.desc));
        if ((m.bullets || []).length) {
          const ul = h('ul', 'lh-gsum-list');
          m.bullets.forEach(b => {
            const li = h('li');
            if (b.label) li.appendChild(h('strong', 'lh-gsum-label tone-' + (b.tone || 'neutral'), b.label + ':'));
            li.appendChild(rich(h('span'), ' ' + b.text));
            ul.appendChild(li);
          });
          mb.appendChild(ul);
        }
        box.appendChild(mb);
      });
      wrap.appendChild(box);
    });
    el.appendChild(wrap);
  };

  /* 선택형 KPI 카드(브랜드별 월간 성과 요약). spec = {label, options:[이름], cards:{이름: [card]}} */
  K.selectCards = function (el, spec) {
    el.innerHTML = '';
    const bar = h('div', 'lh-select-bar');
    const lab = h('label', 'lh-select-label');
    lab.appendChild(h('span', null, spec.label || '선택'));
    const sel = h('select', 'lh-select');
    spec.options.forEach(o => { const op = h('option', null, o); op.value = o; sel.appendChild(op); });
    lab.appendChild(sel);
    bar.appendChild(lab);
    el.appendChild(bar);
    const body = h('div');
    el.appendChild(body);
    const draw = () => K.kpiGrid(body, spec.cards[sel.value] || []);
    sel.addEventListener('change', draw);
    draw();
  };

  /* 드롭다운 체크 목록 + 순서 바꾸기(목업의 Dimension·지표 메뉴). items = [{key, label}], state = {order:[key], on:Set} */
  const pickers = [];
  // composedPath: 메뉴 안 버튼이 메뉴를 다시 그려 대상이 문서에서 떨어져도 "안쪽 클릭"으로 본다
  document.addEventListener('click', e => { const path = e.composedPath(); pickers.forEach(p => { if (!path.includes(p.root)) p.close(); }); });
  function picker(title, heading, items, state, defaults, onChange) {
    const root = h('div', 'lh-picker');
    const btn = h('button', 'lh-picker-btn'); btn.type = 'button';
    const panel = h('div', 'lh-picker-panel');
    root.appendChild(btn); root.appendChild(panel);
    const label = k => (items.find(x => x.key === k) || {}).label;
    const p = { root, close: () => root.classList.remove('is-open') };
    pickers.push(p);
    btn.addEventListener('click', () => root.classList.toggle('is-open'));
    function draw() {
      const n = state.order.filter(k => state.on.has(k)).length;
      btn.innerHTML = '';
      btn.appendChild(h('span', 'lh-picker-title', title));
      btn.appendChild(h('span', 'lh-picker-n', n + '/' + state.order.length));
      btn.appendChild(h('span', 'lh-picker-caret', '▾'));
      panel.innerHTML = '';
      const top = h('div', 'lh-picker-head');
      top.appendChild(h('span', null, heading));
      const reset = h('button', 'lh-picker-reset', '초기화'); reset.type = 'button';
      reset.addEventListener('click', () => { state.order = defaults.order.slice(); state.on = new Set(defaults.on); draw(); onChange(); });
      top.appendChild(reset);
      panel.appendChild(top);
      state.order.forEach((k, i) => {
        const row = h('div', 'lh-picker-item');
        const lab = h('label');
        const cb = h('input'); cb.type = 'checkbox'; cb.checked = state.on.has(k);
        const locked = cb.checked && n === 1;
        cb.disabled = locked;
        if (locked) lab.title = '최소 1개가 필요합니다';
        cb.addEventListener('change', () => { cb.checked ? state.on.add(k) : state.on.delete(k); draw(); onChange(); });
        lab.appendChild(cb); lab.appendChild(document.createTextNode(' ' + label(k)));
        row.appendChild(lab);
        [['↑', -1], ['↓', 1]].forEach(([t, dir]) => {
          const j = i + dir;
          const mv = h('button', 'lh-picker-mv', t); mv.type = 'button';
          mv.disabled = j < 0 || j >= state.order.length || (state.pin != null && (k === state.pin || state.order[j] === state.pin));
          mv.title = dir < 0 ? '위로' : '아래로';
          mv.addEventListener('click', () => { [state.order[i], state.order[j]] = [state.order[j], state.order[i]]; draw(); onChange(); });
          row.appendChild(mv);
        });
        panel.appendChild(row);
      });
    }
    draw();
    return root;
  }

  /* 선택 표 — Dimension·지표를 골라 그 조합 단위로 묶은 평평한 표(페이지당 10행 + 전체 행).
   * spec = report_kit.pick_section: pivot_data 필드 + {mode: "compare"|"goal", compare?, compares?, goal?, default_metrics,
   *        dots, dot_dims, lower, sort, totals?}
   * - compare: 지표마다 [비교 기간, 기준 기간(아래 증감)], 기준 기간 광고비 순. compares가 여럿이면 비교 기준 탭을 따른다.
   * - totals가 있으면 검색하지 않은 '전체' 행은 서버 총계 그대로.
   * - goal: 지표마다 [월 목표, 실적, 달성률(막대)] — 목표가 없는 지표는 실적만. 첫 차원부터 광고비 순위로 정렬하고,
   *         바로 위 행과 같은 상위 차원 값은 감춘다. 목표는 goal.targets.levels 중 고른 차원(+검색 차원)을 모두 담는
   *         가장 작은 수준에서, 그 행이 덮는 단위들의 목표를 더한다(하나라도 없으면 '–').
   *   goal.full = true(monthly): 모든 지표를 [목표, 실적, 달성률/목표 대비] 3열로 — 목표가 없으면 '-'. 비가산 지표는 목표 대비 차이(%),
   *         첫 차원이 매체이고 차원이 둘 이상이면 매체마다 소계 행. 광고비는 소진율 100% ± THR.pace, 그 외는 100% 이상 초록·90% 이상 주황·미만 빨강.
   * - plain: {cur} — 한 기간 값만 지표당 1열(mtd 상세 성과). 광고비 순.
   * 값 규칙: 원 행 1개 = 서버 값, 여럿 = 가산 지표 합 + CTR·CPM·CPV 다시 계산, 그 밖의 비율 지표 '-'. */
  const PICK_PAGE = 10;
  K.pickTable = function (el, spec) {
    el.innerHTML = '';
    if (!spec.dims || !spec.dims.length) { K.placeholder(el); return; }
    const D = spec.dims, M = spec.metrics, N = spec.period.length, P = spec.periods.length;
    const goal = spec.mode === 'goal' ? spec.goal : null;
    const full = !!(goal && goal.full);
    const plain = spec.mode === 'plain' ? spec.plain : null;
    const cmps = spec.mode === 'compare' && spec.compares;   // 비교 기준이 여럿이면 페이지의 비교 기준 탭을 따른다
    let cmp = spec.mode === 'compare' ? ((cmps && cmps[cmpKey]) || spec.compare) : null;
    const pidx = {};
    spec.periods.forEach((p, i) => { pidx[p] = i; });
    let pc = pidx[goal ? goal.cur : cmp ? cmp.cur : plain.cur], pb = cmp ? pidx[cmp.base] : null;
    const dimLabel = k => D.find(d => d.key === k).label;
    const lower = new Set(spec.lower || []);
    const tv = (goal && goal.targets) || { levels: [], values: {} };
    const hasTarget = {};
    Object.values(tv.values).forEach(lv => Object.values(lv).forEach(t => Object.keys(t).forEach(k => { hasTarget[k] = true; })));

    const dimState = { order: D.map(d => d.key), on: new Set(spec.default_dims) };
    const dimDef = { order: dimState.order.slice(), on: spec.default_dims.slice() };
    const metState = { order: M.map(m => m.key), on: new Set(spec.default_metrics), pin: spec.cost };   // 광고비는 맨 앞에 고정
    const metDef = { order: metState.order.slice(), on: spec.default_metrics.slice() };
    let page = 0;
    let searchPref = spec.search_dim || spec.default_dims[goal ? 0 : spec.default_dims.length - 1];

    const bar = h('div', 'lh-pick-bar');
    const left = h('div', 'lh-pick-left');
    left.appendChild(picker('Dimension', '표시할 Dimension / 순서', D, dimState, dimDef, () => { page = 0; paint(); }));
    left.appendChild(picker('지표', '표시할 지표 / 순서', M.map(m => ({ key: m.key, label: m.label })), metState, metDef, () => { page = 0; paint(); }));
    const sdim = h('select', 'lh-select');
    const q = h('input', 'lh-search'); q.type = 'search';
    left.appendChild(sdim); left.appendChild(q);
    bar.appendChild(left);
    const info = h('span', 'lh-pick-info');
    bar.appendChild(info);
    el.appendChild(bar);
    const wrap = h('div', 'lh-table-wrap');
    const t = h('table', 'lh-table lh-pick' + (goal ? ' lh-pick-goal' : ''));
    wrap.appendChild(t);
    el.appendChild(wrap);
    const pager = h('div', 'lh-pager');
    el.appendChild(pager);

    const valOf = (k, i) => spec.dict[k][spec.codes[k][i]];
    const newAgg = () => ({ s: M.map(() => new Array(P).fill(null)), n: new Array(P).fill(0), first: new Array(P).fill(-1), idx: [] });
    function add(a, i) {
      const p = spec.period[i];
      a.n[p]++; a.idx.push(i);
      if (a.first[p] < 0) a.first[p] = i;
      M.forEach((m, j) => { const v = spec.vals[m.key][i]; if (typeof v === 'number') a.s[j][p] = (a.s[j][p] || 0) + v; });
    }
    function value(a, p) {
      const out = {};
      M.forEach((m, j) => {
        if (p == null || a.n[p] === 0) out[m.key] = null;
        else if (a.n[p] === 1) out[m.key] = spec.vals[m.key][a.first[p]];
        else out[m.key] = m.additive ? a.s[j][p] : null;
      });
      if (p != null && a.n[p] > 1) {
        Object.keys(spec.ratio || {}).forEach(k => {
          const [num, den, mul] = spec.ratio[k];
          const nv = out[num], dv = out[den];
          out[k] = typeof nv === 'number' && typeof dv === 'number' && dv ? nv / dv * mul : null;
        });
      }
      return out;
    }
    // 목표: need = 고른 차원 ∪ 검색 차원을 모두 담는 가장 작은 수준
    function targetOf(a, need) {
      const lv = tv.levels.map((l, i) => ({ l, i })).filter(x => need.every(d => x.l.includes(d)))
        .sort((x, y) => x.l.length - y.l.length)[0];
      if (!lv) return {};
      const units = new Set(a.idx.filter(i => spec.period[i] === pc).map(i => lv.l.map(d => valOf(d, i)).join('\u0001')));
      const vals = tv.values[lv.i] || {};
      const out = {};
      Object.keys(hasTarget).forEach(k => {
        let s = 0;
        for (const u of units) { const v = (vals[u] || {})[k]; if (typeof v !== 'number') return; s += v; }
        if (units.size) out[k] = s;
      });
      return out;
    }
    function rateCls(k, r) {
      if (r == null) return '';
      if (k === spec.cost) return r > 1.05 ? 'up' : r < 0.95 ? 'warn' : '';
      return r >= 0.9995 ? '' : r >= 0.9 ? 'warn' : 'up';
    }
    const spanOf = m => (cmp ? 2 : (hasTarget[m.key] || full) ? 3 : 1);
    function fullCells(tr, m, g, v) {   // goal.full: [목표, 실적, 달성률(막대) | 목표 대비 차이] — 목표가 없으면 '-'
      const has = typeof g === 'number' && g !== 0 && typeof v === 'number';
      tr.appendChild(h('td', 'lh-num lh-base', typeof g === 'number' ? K.fmt(g, m.unit) : '-'));
      if (!m.additive) {
        const diff = has ? (v / g - 1) * 100 : null;
        const cls = diff == null ? '' : (lower.has(m.key) ? diff <= 0.05 : diff >= -0.05) ? 'good' : 'up';
        tr.appendChild(h('td', 'lh-num' + (cls ? ' ' + cls : ''), K.fmt(v, m.unit)));
        tr.appendChild(h('td', 'lh-num lh-group-end' + (cls ? ' ' + cls : ''), diff == null ? '-' : (diff > 0 ? '+' : '') + diff.toFixed(1) + '%'));
        return;
      }
      tr.appendChild(h('td', 'lh-num', K.fmt(v, m.unit)));
      const td = h('td', 'lh-rate lh-group-end');
      if (!has) td.textContent = '-';
      else {
        const r = v / g, t = THR.pace / 100;
        const cls = m.key === spec.cost ? (r > 1 + t ? 'up' : r < 1 - t ? 'warn' : '') : r >= 1 ? 'good' : r >= 0.9 ? 'warn' : 'up';
        const box = h('div', 'lh-cellbar');
        const b = h('div', 'lh-bar');
        const f = h('div', 'lh-bar-fill' + (cls && cls !== 'good' ? ' ' + cls : ''));
        f.style.setProperty('--w', Math.min(r, 1) * 100 + '%');
        b.appendChild(f); box.appendChild(b);
        box.appendChild(h('span', cls, (r * 100).toFixed(1) + '%'));
        td.appendChild(box);
      }
      tr.appendChild(td);
    }
    function cells(tr, a, tg, mets, server) {   // server = 서버 총계 {기간 키: {지표: 값}} (검색 없는 '전체' 행)
      const valAt = p => (server && server[spec.periods[p]]) || value(a, p);
      mets.forEach(m => {
        const cur = valAt(pc);
        if (cmp) {
          const base = valAt(pb);
          tr.appendChild(h('td', 'lh-num lh-base', K.fmt(base[m.key], m.unit)));
          const td = h('td', 'lh-num lh-group-end');
          td.appendChild(h('div', null, K.fmt(cur[m.key], m.unit)));
          const d = K.delta(cur[m.key], base[m.key], m.unit);
          td.appendChild(h('div', 'lh-delta ' + d.dir, '(' + d.text + ')'));
          tr.appendChild(td);
          return;
        }
        if (!hasTarget[m.key] && !full) { tr.appendChild(h('td', 'lh-num lh-group-end', K.fmt(cur[m.key], m.unit))); return; }
        const g = tg[m.key], v = cur[m.key];
        if (full) { fullCells(tr, m, g, v); return; }
        tr.appendChild(h('td', 'lh-num lh-base', g == null ? '–' : K.fmt(g, m.unit)));
        tr.appendChild(h('td', 'lh-num', K.fmt(v, m.unit)));
        const td = h('td', 'lh-rate lh-group-end');
        const r = (typeof g === 'number' && typeof v === 'number' && g && v) ? (lower.has(m.key) ? g / v : v / g) : null;
        if (r == null) td.textContent = '–';
        else {
          const cls = rateCls(m.key, r);
          const box = h('div', 'lh-cellbar');
          const b = h('div', 'lh-bar');
          const f = h('div', 'lh-bar-fill' + (cls ? ' ' + cls : ''));
          f.style.setProperty('--w', Math.min(r, 1) * 100 + '%');
          b.appendChild(f); box.appendChild(b);
          box.appendChild(h('span', cls, (r * 100).toFixed(1) + '%'));
          td.appendChild(box);
        }
        tr.appendChild(td);
      });
    }
    function paint() {
      const sel = dimState.order.filter(k => dimState.on.has(k));
      const mets = metState.order.filter(k => metState.on.has(k)).map(k => M.find(m => m.key === k));
      // 검색 차원 select: 고른 차원만. 사용자가 고른 검색 차원(searchPref)은 기억해 두고, 그 차원이 보일 때 되돌린다(목업과 같음)
      sdim.innerHTML = '';
      sel.forEach(k => { const o = h('option', null, dimLabel(k)); o.value = k; sdim.appendChild(o); });
      sdim.value = sel.includes(searchPref) ? searchPref : sel[goal ? 0 : sel.length - 1];
      q.placeholder = dimLabel(sdim.value) + ' 검색';
      const query = q.value.trim().toLowerCase();
      const groups = new Map(), all = newAgg(), rank = {}, byMedia = new Map();
      const subs = full && sel[0] === 'media' && sel.length > 1;   // 매체 소계 행
      for (let i = 0; i < N; i++) {
        if (query && !String(valOf(sdim.value, i)).toLowerCase().includes(query)) continue;
        add(all, i);
        if (subs) { const mv = valOf('media', i); if (!byMedia.has(mv)) byMedia.set(mv, newAgg()); add(byMedia.get(mv), i); }
        const key = sel.map(k => valOf(k, i)).join('\u0001');
        let g = groups.get(key);
        if (!g) { g = { names: sel.map(k => valOf(k, i)), agg: newAgg() }; groups.set(key, g); }
        add(g.agg, i);
        if (spec.period[i] === pc && spec.cost) sel.forEach(k => {   // 차원 값별 광고비(정렬 순위용)
          const v = valOf(k, i), x = spec.vals[spec.cost][i];
          rank[k] = rank[k] || {};
          rank[k][v] = (rank[k][v] || 0) + (typeof x === 'number' ? x : 0);
        });
      }
      let rows = Array.from(groups.values()).map(g => ({ g, cur: value(g.agg, pc) }));
      const costOf = r => r.cur[spec.cost] || 0;
      if (goal) rows.sort((x, y) => {
        for (let j = 0; j < sel.length; j++) {
          const k = sel[j], a = x.g.names[j], b = y.g.names[j];
          if (a === b) continue;
          return ((rank[k] || {})[b] || 0) - ((rank[k] || {})[a] || 0) || String(a).localeCompare(String(b));
        }
        return 0;
      });
      else rows.sort((x, y) => costOf(y) - costOf(x) || x.g.names.join().localeCompare(y.g.names.join()));
      let items = rows;
      if (subs) {
        items = [];
        rows.forEach((r, i) => {
          items.push(r);
          const mv = r.g.names[0];
          if (i === rows.length - 1 || rows[i + 1].g.names[0] !== mv) items.push({ sub: mv, agg: byMedia.get(mv) });
        });
      }
      const pages = Math.max(1, Math.ceil(items.length / PICK_PAGE));
      page = Math.min(page, pages - 1);
      const shown = items.slice(page * PICK_PAGE, page * PICK_PAGE + PICK_PAGE);
      info.textContent = items.length ? items.length + '개 행 중 ' + (page * PICK_PAGE + 1) + '–' + Math.min((page + 1) * PICK_PAGE, items.length) : '0개 행';

      t.innerHTML = '';
      const thead = h('thead'), r1 = h('tr'), r2 = h('tr');
      sel.forEach(k => { const th = h('th', 'lh-name-col', dimLabel(k)); th.rowSpan = 2; r1.appendChild(th); });
      mets.forEach(m => {
        const span = spanOf(m);
        const th = h('th', 'lh-group', m.label); th.colSpan = span;
        if (span === 1) { th.rowSpan = 2; th.className = 'lh-group-end'; r1.appendChild(th); return; }
        r1.appendChild(th);
        const heads = cmp ? [cmp.base_label, cmp.cur_label]
          : full ? (m.key === spec.cost ? ['월 예산', '집행액', '소진율'] : m.additive ? ['월 목표', '실적', '달성률'] : ['목표', '실적', '목표 대비'])
          : [m.key === spec.cost ? '월 목표 예산' : '월 목표', goal.cur_label + (m.key === spec.cost ? ' 광고비' : ' 실적'),
             m.key === spec.cost ? '소진율' : '달성률'];
        heads.forEach((s, i) => r2.appendChild(h('th', 'lh-sub' + (i === heads.length - 1 ? ' lh-group-end' : ''), s)));
      });
      thead.appendChild(r1); thead.appendChild(r2); t.appendChild(thead);
      const tb = h('tbody');
      const need = sel.slice();
      if (query && !need.includes(sdim.value)) need.push(sdim.value);
      shown.forEach((it, ri) => {
        if (it.sub != null) {
          const tr = h('tr', 'is-subtotal');
          const td = h('td', 'lh-name', it.sub + ' 소계'); td.colSpan = sel.length;
          tr.appendChild(td);
          cells(tr, it.agg, targetOf(it.agg, ['media']), mets);
          tb.appendChild(tr);
          return;
        }
        const g = it.g;
        const tr = h('tr', 'is-row');
        sel.forEach((k, j) => {
          const td = h('td', 'lh-name');
          const prev = ri > 0 && shown[ri - 1].g ? shown[ri - 1].g.names : null;
          const same = goal && prev && j < sel.length - 1 && g.names.slice(0, j + 1).every((v, x) => prev[x] === v);
          if (!same) {
            const dot = spec.dot_dims.includes(k) && spec.dots[g.names[j]];
            if (dot) td.appendChild(color(h('span', 'lh-mdot'), dot));
            td.appendChild(h('span', j === 0 ? 'lh-strong' : null, g.names[j]));
          }
          tr.appendChild(td);
        });
        cells(tr, g.agg, goal ? targetOf(g.agg, need) : {}, mets);
        tb.appendChild(tr);
      });
      if (!rows.length) {
        const tr = h('tr'); const td = h('td', 'lh-empty', '검색 결과가 없습니다.');
        td.colSpan = sel.length + mets.reduce((s, m) => s + spanOf(m), 0);
        tr.appendChild(td); tb.appendChild(tr);
      } else {
        const tr = h('tr', 'is-total');
        const td = h('td', 'lh-name', query ? '검색 결과 합계' : '전체'); td.colSpan = sel.length;
        tr.appendChild(td);
        cells(tr, all, goal ? targetOf(all, query ? [sdim.value] : []) : {}, mets, query ? null : spec.totals);
        tb.appendChild(tr);
      }
      t.appendChild(tb);

      pager.innerHTML = '';
      if (pages > 1) {
        const pb2 = (label, target, on, dis) => {
          const b = h('button', 'lh-pg' + (on ? ' is-on' : ''), label); b.type = 'button'; b.disabled = dis;
          b.addEventListener('click', () => { page = target; paint(); });
          pager.appendChild(b);
        };
        pb2('‹', page - 1, false, page === 0);
        for (let i = 0; i < pages; i++) {
          if (pages > 9 && i > 0 && i < pages - 1 && Math.abs(i - page) > 2) {
            if (i === 1 || i === pages - 2) pager.appendChild(h('span', 'lh-muted', '…'));
            continue;
          }
          pb2(String(i + 1), i, i === page, false);
        }
        pb2('›', page + 1, false, page >= pages - 1);
      }
    }
    sdim.addEventListener('change', () => { searchPref = sdim.value; page = 0; paint(); });
    let timer;
    q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { page = 0; paint(); }, 150); });
    paint();
    if (cmps && Object.keys(cmps).length > 1) K.onCompare(k => {
      cmp = cmps[k] || cmp; pc = pidx[cmp.cur]; pb = pidx[cmp.base]; paint();
    });
    K.onThreshold(paint);
    if (spec.note) el.appendChild(h('p', 'lh-note', spec.note));
  };

  /* 비교 표. spec = {name_cols:["매체","상품"], metrics:[meta], compares:{key:{base_label, cur_label}},
   * rows:[{names:[..], kind:"row|subtotal|total", dot?, cur:{m:v}, base:{key:{m:v}}}], note?} */
  K.compareTable = function (el, spec) {
    el.innerHTML = '';
    const closed = new Set();
    if (spec.collapsible) {   // rows[].group 단위로 하위 행을 접는다(접으면 소계만)
      const bar = h('div', 'lh-toolbar lh-collapse-bar');
      bar.appendChild(h('span', 'lh-muted', spec.collapse_hint || '이름을 누르면 하위 행을 접거나 펼칠 수 있습니다. 접으면 소계만 표시됩니다.'));
      const acts = h('div', 'lh-tabs');
      [['모두 펼치기', () => closed.clear()], ['모두 접기', () => spec.rows.forEach(r => r.group && closed.add(r.group))]].forEach(([l, fn]) => {
        const b = h('button', 'lh-tab', l); b.type = 'button';
        b.addEventListener('click', () => { fn(); paint(cmpKey); });
        acts.appendChild(b);
      });
      bar.appendChild(acts);
      el.appendChild(bar);
    }
    const wrap = h('div', 'lh-table-wrap');
    const t = h('table', 'lh-table lh-compare');
    wrap.appendChild(t);
    el.appendChild(wrap);
    const keys = Object.keys(spec.compares);
    function paint(k) {
      if (!spec.compares[k]) k = keys[0];
      const cmp = spec.compares[k];
      t.innerHTML = '';
      const thead = h('thead');
      const r1 = h('tr'), r2 = h('tr');
      spec.name_cols.forEach(n => { const th = h('th', 'lh-name-col', n); th.rowSpan = 2; r1.appendChild(th); });
      spec.metrics.forEach(m => {
        const th = h('th', 'lh-group', m.label); th.colSpan = 2; r1.appendChild(th);
        r2.appendChild(h('th', 'lh-sub', cmp.base_label));
        r2.appendChild(h('th', 'lh-sub lh-group-end', cmp.cur_label));
      });
      thead.appendChild(r1); thead.appendChild(r2); t.appendChild(thead);
      const tb = h('tbody');
      const seen = new Set();
      spec.rows.forEach(r => {
        const g = r.group, isClosed = g != null && closed.has(g);
        if (isClosed && r.kind === 'row') return;
        const tr = h('tr', 'is-' + r.kind);
        if (g != null && !seen.has(g)) {   // 그룹의 첫 표시 행 = 접기 토글
          seen.add(g);
          const names = r.names.slice();
          names[0] = g;
          r = Object.assign({}, r, { names, toggle: true });
        }
        if (r.kind === 'total') {
          const td = h('td', 'lh-name', r.names[0]); td.colSpan = spec.name_cols.length; tr.appendChild(td);
        } else {
          r.names.forEach((n, i) => {
            const td = h('td', 'lh-name');
            if (n != null) {
              if (i === 0 && r.toggle) {
                const b = h('button', 'lh-caret' + (closed.has(g) ? ' is-closed' : ''), '▾');
                b.type = 'button';
                td.classList.add('lh-toggle');
                td.appendChild(b);
                td.addEventListener('click', () => { closed.has(g) ? closed.delete(g) : closed.add(g); paint(cmpKey); });
              }
              const dot = i === 0 ? (r.toggle ? r.gdot || r.dot : r.dot) : (i === 1 ? r.dot2 : null);
              if (dot) td.appendChild(color(h('span', 'lh-mdot'), dot));
              td.appendChild(h('span', null, n));
            }
            tr.appendChild(td);
          });
        }
        const base = (r.base || {})[k] || {};
        spec.metrics.forEach(m => {
          tr.appendChild(h('td', 'lh-num', K.fmt(base[m.key], m.unit)));
          const td = h('td', 'lh-num lh-group-end');
          td.appendChild(h('div', null, K.fmt(r.cur[m.key], m.unit)));
          const d = K.delta(r.cur[m.key], base[m.key], m.unit);
          td.appendChild(h('div', 'lh-delta ' + d.dir, '(' + d.text + ')'));
          tr.appendChild(td);
        });
        tb.appendChild(tr);
      });
      t.appendChild(tb);
    }
    paint(cmpKey);
    if (keys.length > 1) K.onCompare(paint);
    K.onThreshold(() => paint(cmpKey));
    if (spec.note) el.appendChild(h('p', 'lh-note', spec.note));
  };

  /* 최우수 소재 카드. groups = [{title, desc, cards:[{rank, media, product, dot, name, thumb, metric_label,
   * value, sub}]}] */
  K.creativeCards = function (el, groups) {
    el.innerHTML = '';
    const row = h('div', 'lh-best');
    groups.forEach(g => {
      const col = h('div', 'lh-best-group');
      const head = h('h3', 'lh-best-title', g.title);
      head.appendChild(h('span', 'lh-muted', ' (' + (g.period || '최근 7일') + ')'));
      col.appendChild(head);
      col.appendChild(h('p', 'lh-best-desc', g.desc));
      const cards = h('div', 'lh-best-cards');
      if (!g.cards.length) cards.appendChild(h('div', 'lh-placeholder', '대상 소재 없음'));
      g.cards.forEach(c => {
        const card = h('div', 'lh-ccard');
        const top = h('div', 'lh-ccard-top');
        top.appendChild(h('span', 'lh-rank', String(c.rank)));
        top.appendChild(color(h('span', 'lh-mdot'), c.dot));
        top.appendChild(h('span', 'lh-muted', c.media + ' · ' + c.product));
        card.appendChild(top);
        const th = h('div', 'lh-thumb');
        if (c.thumb) {
          const img = document.createElement('img');
          img.src = c.thumb; img.alt = c.name; img.loading = 'lazy';
          img.onerror = () => { img.remove(); th.appendChild(h('span', 'lh-thumb-empty', '소재 썸네일')); };
          th.appendChild(img);
        } else th.appendChild(h('span', 'lh-thumb-empty', '소재 썸네일'));
        card.appendChild(th);
        card.appendChild(h('div', 'lh-ccard-name', c.name));
        const val = h('div', 'lh-ccard-val');
        val.appendChild(h('span', 'lh-muted', c.metric_label));
        val.appendChild(h('strong', null, c.value));
        card.appendChild(val);
        card.appendChild(h('div', 'lh-ccard-sub', c.sub));
        cards.appendChild(card);
      });
      col.appendChild(cards);
      row.appendChild(col);
    });
    el.appendChild(row);
  };

  /* 소재 누적 성과 표. spec = {metrics:[meta], sort_key, page_size, rows:[{media, product, dot, name, values:{m:v}}]} */
  K.creativeTable = function (el, spec) {
    el.innerHTML = '';
    const bar = h('div', 'lh-toolbar');
    const info = h('span', 'lh-muted', '열 이름을 누르면 정렬됩니다. 전체 ' + spec.rows.length + '개 소재');
    const q = h('input', 'lh-search');
    q.type = 'search'; q.placeholder = '검색 — 예: 매체:Meta 상품:Reach reels';
    const right = h('div', 'lh-filter');
    const dd = h('div');
    right.appendChild(dd); right.appendChild(q);
    bar.appendChild(info); bar.appendChild(right);
    el.appendChild(bar);
    K.dimDropdowns(dd, [{ label: '매체', values: spec.rows.map(r => r.media) }, { label: '상품', values: spec.rows.map(r => r.product) }], q);
    const wrap = h('div', 'lh-table-wrap');
    const t = h('table', 'lh-table lh-creative');
    wrap.appendChild(t);
    el.appendChild(wrap);
    const pager = h('div', 'lh-pager');
    el.appendChild(pager);
    let sortKey = spec.sort_key, dir = -1, page = 0;
    const size = spec.page_size || 10;
    const textCols = [['media', '매체'], ['product', '상품'], ['name', '소재']];
    function rows() {
      const pq = K.parseQuery(q.value, ['매체', '상품', '소재']);
      const list = spec.rows.filter(r => K.matchQuery(pq, [r.media, r.product, r.name]));
      const val = r => (textCols.some(c => c[0] === sortKey) ? r[sortKey] : r.values[sortKey]);
      return list.sort((a, b) => {
        const x = val(a), y = val(b);
        if (x == null) return 1; if (y == null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * dir;
      });
    }
    function paint() {
      const list = rows();
      const pages = Math.max(1, Math.ceil(list.length / size));
      page = Math.min(page, pages - 1);
      t.innerHTML = '';
      const tr = h('tr');
      const head = (key, label, cls) => {
        const th = h('th', cls + (key === sortKey ? ' is-sorted' : ''), label + (key === sortKey ? (dir < 0 ? ' ↓' : ' ↑') : ''));
        th.addEventListener('click', () => { if (sortKey === key) dir = -dir; else { sortKey = key; dir = -1; } paint(); });
        tr.appendChild(th);
      };
      textCols.forEach(([k, l]) => head(k, l, 'lh-name-col'));
      spec.metrics.forEach(m => head(m.key, m.label, 'lh-num'));
      const thead = h('thead'); thead.appendChild(tr); t.appendChild(thead);
      const tb = h('tbody');
      list.slice(page * size, page * size + size).forEach(r => {
        const row = h('tr');
        const md = h('td', 'lh-name');
        md.appendChild(color(h('span', 'lh-mdot'), r.dot));
        md.appendChild(h('span', null, r.media));
        row.appendChild(md);
        row.appendChild(h('td', 'lh-name', r.product));
        row.appendChild(h('td', 'lh-name lh-strong', r.name));
        spec.metrics.forEach(m => row.appendChild(h('td', 'lh-num', K.fmt(r.values[m.key], m.unit))));
        tb.appendChild(row);
      });
      if (!list.length) { const e = h('tr'); const td = h('td', 'lh-empty', '검색 결과가 없습니다'); td.colSpan = 3 + spec.metrics.length; e.appendChild(td); tb.appendChild(e); }
      t.appendChild(tb);
      pager.innerHTML = '';
      const btn = (label, p, on, dis) => {
        const b = h('button', 'lh-pg' + (on ? ' is-on' : ''), label);
        b.type = 'button'; b.disabled = !!dis;
        b.addEventListener('click', () => { page = p; paint(); });
        pager.appendChild(b);
      };
      btn('‹', page - 1, false, page === 0);
      for (let i = 0; i < pages; i++) btn(String(i + 1), i, i === page);
      btn('›', page + 1, false, page >= pages - 1);
    }
    q.addEventListener('input', () => { page = 0; paint(); });
    paint();
    if (spec.note) el.appendChild(h('p', 'lh-note', spec.note));
  };

  /* 분석 카드. items = [{dot, head, tag:{label, tone}, text}] — text는 <strong>만 허용 */
  K.analysisCards = function (el, items) {
    el.innerHTML = '';
    const list = h('div', 'lh-analysis');
    items.forEach(it => {
      const card = h('div', 'lh-analysis-item');
      const top = h('div', 'lh-analysis-head');
      if (it.dot) top.appendChild(color(h('span', 'lh-mdot'), it.dot));
      top.appendChild(h('h3', null, it.head));
      if (it.tag) top.appendChild(h('span', 'lh-tag tone-' + (it.tag.tone || 'neutral'), it.tag.label));
      card.appendChild(top);
      card.appendChild(rich(h('p', 'lh-analysis-text'), it.text));
      list.appendChild(card);
    });
    el.appendChild(list);
  };

  /* 일반 표. spec = {groups?: [{label, span}], columns: [{label, cls?}],
   * rows: [{kind, cells: [{text, cls?, dot?, bar?:{v, cls}, sub?:{text, cls}}]}], note?} */
  K.plainTable = function (el, spec) {
    el.innerHTML = '';
    // 셀에 숫자(pace: 소진율-진행률 %p, prate: 예상 소진율 %, gap: 목표 대비 %)가 있으면 색을 임계치로 정한다
    const clsOf = c => (c.pace !== undefined ? K.paceCls(c.pace) : c.prate !== undefined ? K.projCls(c.prate)
      : c.gap !== undefined ? K.goalCls(c.gap) : null);
    const wrap = h('div', 'lh-table-wrap');
    const t = h('table', 'lh-table lh-plain');
    const thead = h('thead');
    if (spec.groups) {
      const r = h('tr');
      spec.groups.forEach(g => { const th = h('th', g.cls || 'lh-group', g.label); th.colSpan = g.span || 1; if (g.rows) th.rowSpan = g.rows; r.appendChild(th); });
      thead.appendChild(r);
    }
    const r2 = h('tr');
    spec.columns.forEach(c => r2.appendChild(h('th', c.cls || '', c.label)));
    thead.appendChild(r2);
    t.appendChild(thead);
    let tb = h('tbody');
    function paintBody() {
    const nb = h('tbody');
    spec.rows.forEach(r => {
      const tr = h('tr', 'is-' + (r.kind || 'row'));
      r.cells.forEach(c0 => {
        const dyn = clsOf(c0);
        const c = dyn === null ? c0 : Object.assign({}, c0, {
          cls: ((c0.base_cls || '') + ' ' + dyn).trim(),
          bar: c0.bar ? Object.assign({}, c0.bar, { cls: dyn }) : c0.bar,
          sub: c0.sub ? Object.assign({}, c0.sub, { cls: dyn }) : c0.sub,
        });
        const td = h('td', c.cls || '');
        if (c.span) td.colSpan = c.span;
        if (c.dot) td.appendChild(color(h('span', 'lh-mdot'), c.dot));
        if (c.bar) {
          const box = h('div', 'lh-cellbar');
          const bar = h('div', 'lh-bar');
          const fill = h('div', 'lh-bar-fill ' + (c.bar.cls || ''));
          fill.style.setProperty('--w', Math.max(0, Math.min(1, c.bar.v)) * 100 + '%');
          bar.appendChild(fill);
          box.appendChild(bar);
          box.appendChild(h('span', c.bar.cls || '', c.text));
          td.appendChild(box);
        } else if (c.text != null) td.appendChild(h('span', null, c.text));
        if (c.sub) td.appendChild(h('span', 'lh-cell-sub ' + (c.sub.cls || ''), ' ' + c.sub.text));
        tr.appendChild(td);
      });
      nb.appendChild(tr);
    });
    if (tb.parentNode) t.replaceChild(nb, tb); else t.appendChild(nb);
    tb = nb;
    }
    paintBody();
    K.onThreshold(paintBody);
    wrap.appendChild(t);
    el.appendChild(wrap);
    if (spec.note) el.appendChild(h('p', 'lh-note', spec.note));
  };

  /* 계층 표 — Claude/GPT판 공용 킷의 LHKit.treeTable을 그대로 옮겼다(접기 ▶/▼·검색·지표 선택·정렬·더 보기).
   * data = {levels, metrics:[{key,label,unit}], cost, nodes:[[name, cur[], base[], children[]], ...]} */
  const PAGE = 50;
  K.treeTable = function (root, data, opts) {
    if (typeof root === 'string') root = document.getElementById(root);
    if (!root || !data || !data.nodes) return;
    opts = opts || {};
    const L = data.levels.length;
    const M = data.metrics;
    let idSeq = 0;
    function wrap(raw, depth, parent) {
      const n = { id: idSeq++, name: raw[0], cur: raw[1], base: raw[2], depth, parent, kids: [] };
      n.search = (parent ? parent.search + ' ' : '') + String(raw[0]).toLowerCase();
      n.kids = (raw[3] || []).map(k => wrap(k, depth + 1, n));
      return n;
    }
    const roots = data.nodes.map(r => wrap(r, 0, null));
    const costIdx = Math.max(0, M.findIndex(m => m.key === data.cost));
    const state = {
      sortIdx: costIdx, sortDir: -1, query: '',
      visible: new Set(M.map((_, i) => i)),
      open: new Set(), shown: {},
    };

    root.classList.add('lh-tree');
    root.innerHTML = `
      <div class="lh-tree-bar">
        <input type="search" class="lh-tree-search" placeholder="${esc(opts.search_placeholder || ('검색 — 예: ' + data.levels[0] + ':값'))}">
        <div class="lh-tree-dd"></div>
        <div class="lh-tree-cols">
          <button type="button" class="lh-tree-colbtn">지표 선택 (<span class="lh-cnt"></span>/${M.length})</button>
          <div class="lh-tree-colmenu" hidden>
            <div class="lh-tree-colacts"><button type="button" data-act="all">전체 선택</button><button type="button" data-act="none">전체 해제</button></div>
            ${M.map((m, i) => `<label><input type="checkbox" data-i="${i}" checked> ${esc(m.label || m.key)}</label>`).join('')}
          </div>
        </div>
        <div class="lh-tree-acts"><button type="button" data-act="collapse">모두 접기</button></div>
      </div>
      <div class="lh-tree-scroll"><table class="lh-tree-table"><thead></thead><tbody></tbody></table></div>
      <div class="lh-tree-note">${esc(opts.note || '')}</div>`;
    const thead = root.querySelector('thead');
    const tbody = root.querySelector('tbody');
    const search = root.querySelector('.lh-tree-search');
    const menu = root.querySelector('.lh-tree-colmenu');
    const cnt = root.querySelector('.lh-cnt');

    function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

    function sortVal(n) { const v = n.cur[state.sortIdx]; return v == null ? -Infinity : v; }
    function sorted(list) {
      return list.slice().sort((a, b) => {
        const d = (sortVal(a) - sortVal(b)) * state.sortDir;
        return d !== 0 && !Number.isNaN(d) ? d : String(a.name).localeCompare(String(b.name));
      });
    }

    // 검색: "단계:값"(그 단계 이름에서) + 일반 단어(경로 이름 전체에서). 일치 노드 + 조상(펼침) + 자손(보임)
    function pathOf(n) { const p = []; for (let x = n; x; x = x.parent) p[x.depth] = x.name; return p; }
    function matchSet() {
      const pq = K.parseQuery(state.query, data.levels);
      if (pq.empty) return null;
      const need = Math.max(-1, ...Object.keys(pq.by).map(Number));
      const keep = new Set();
      const force = new Set();
      (function walk(list) {
        list.forEach(n => {
          if (n.depth >= need && K.matchQuery(pq, pathOf(n))) {
            keep.add(n.id);
            for (let p = n.parent; p; p = p.parent) { keep.add(p.id); force.add(p.id); }
            (function all(k) { k.forEach(c => { keep.add(c.id); all(c.kids); }); })(n.kids);
            return;   // 자손은 이미 보이게 했다 — 일치로 다시 잡으면 전부 강제로 펼쳐진다(접을 수 없게 됨)
          }
          walk(n.kids);
        });
      })(roots);
      return { keep, force };
    }

    function delta(cur, base, unit) {
      if (cur == null || base == null) return '<div class="lh-d lh-d0">—</div>';
      let raw, sfx;
      if (unit === '%') { raw = cur - base; sfx = '%p'; }
      else { if (base === 0) return '<div class="lh-d lh-d0">—</div>'; raw = (cur - base) / Math.abs(base) * 100; sfx = '%'; }
      const shown = Math.round(raw * 10) / 10;
      if (shown === 0) return `<div class="lh-d lh-d0">0.0${sfx}</div>`;
      const dir = K.dirOf(raw, unit === '%');
      const cls = dir === 'up' ? 'lh-up' : dir === 'down' ? 'lh-down' : 'lh-d0';
      return `<div class="lh-d ${cls}">${raw > 0 ? '▲' : '▼'} ${Math.abs(shown).toFixed(1)}${sfx}</div>`;
    }

    function renderHead() {
      const cols = M.map((m, i) => i).filter(i => state.visible.has(i));
      cnt.textContent = cols.length;
      thead.innerHTML = '<tr>' + data.levels.map(l => `<th class="lh-lv">${esc(l)}</th>`).join('') +
        cols.map(i => {
          const on = state.sortIdx === i;
          const arrow = on ? (state.sortDir < 0 ? '↓' : '↑') : '⇅';
          return `<th class="lh-m${on ? ' lh-sorted' : ''}" data-i="${i}" title="클릭해서 정렬">${esc(M[i].label || M[i].key)} <span class="lh-arrow">${arrow}</span></th>`;
        }).join('') + '</tr>';
      return cols;
    }

    function render() {
      const cols = renderHead();
      const ms = matchSet();
      const rows = [];
      (function walk(list, parentId) {
        let items = sorted(list);
        if (ms) items = items.filter(n => ms.keep.has(n.id));
        const limit = state.shown[parentId] || PAGE;
        items.slice(0, limit).forEach(n => {
          rows.push(rowHtml(n, cols, ms));
          const open = ms ? (ms.force.has(n.id) || state.open.has(n.id)) : state.open.has(n.id);
          if (open && n.kids.length) walk(n.kids, n.id);
        });
        if (items.length > limit) {
          const depth = list[0].depth;
          rows.push(`<tr class="lh-more"><td colspan="${L + cols.length}" style="padding-left:${12 + depth * 16}px"><button type="button" data-more="${parentId}">${items.length - limit}개 더 보기</button></td></tr>`);
        }
      })(roots, 'root');
      tbody.innerHTML = rows.join('') || `<tr><td colspan="${L + cols.length}" class="lh-empty">일치하는 항목이 없습니다.</td></tr>`;
    }

    function rowHtml(n, cols, ms) {
      const open = ms ? (ms.force.has(n.id) || state.open.has(n.id)) : state.open.has(n.id);
      let cells = '';
      for (let lv = 0; lv < L; lv++) {
        if (lv < n.depth) cells += '<td class="lh-lv"></td>';
        else if (lv === n.depth) {
          const tog = n.kids.length
            ? `<button type="button" class="lh-tog" data-id="${n.id}" aria-expanded="${open}">${open ? '▼' : '▶'}</button>`
            : '<span class="lh-tog-sp"></span>';
          cells += `<td class="lh-lv lh-name"><div class="lh-namebox">${tog}<span>${esc(n.name).replace(/([_\-\/])/g, '$1<wbr>')}</span></div></td>`;  // _ - / 뒤에서 먼저 줄바꿈
        } else if (lv === n.depth + 1 && n.kids.length) cells += '<td class="lh-lv lh-all">전체</td>';
        else cells += '<td class="lh-lv"></td>';
      }
      cells += cols.map(i => `<td class="lh-m"><div class="lh-v">${K.fmt(n.cur[i], M[i].unit)}</div>${delta(n.cur[i], n.base[i], M[i].unit)}</td>`).join('');
      return `<tr class="lh-depth${n.depth}">${cells}</tr>`;
    }

    root.addEventListener('click', e => {
      const t = e.target.closest('button, th.lh-m');
      if (!t || !root.contains(t)) return;
      if (t.classList.contains('lh-tog')) {
        const id = Number(t.dataset.id);
        if (state.open.has(id)) state.open.delete(id); else state.open.add(id);
        render();
      } else if (t.matches('th.lh-m')) {
        const i = Number(t.dataset.i);
        if (state.sortIdx === i) state.sortDir = -state.sortDir; else { state.sortIdx = i; state.sortDir = -1; }
        render();
      } else if (t.dataset.more) {
        const k = t.dataset.more === 'root' ? 'root' : Number(t.dataset.more);
        state.shown[k] = (state.shown[k] || PAGE) + PAGE;
        render();
      } else if (t.classList.contains('lh-tree-colbtn')) {
        menu.hidden = !menu.hidden;
      } else if (t.dataset.act === 'all' || t.dataset.act === 'none') {
        const on = t.dataset.act === 'all';
        menu.querySelectorAll('input[type=checkbox]').forEach(cb => {
          cb.checked = on; const i = Number(cb.dataset.i);
          if (on) state.visible.add(i); else state.visible.delete(i);
        });
        render();
      } else if (t.dataset.act === 'collapse') {
        state.open.clear(); render();
      }
    });
    menu.addEventListener('change', e => {
      const cb = e.target; const i = Number(cb.dataset.i);
      if (cb.checked) state.visible.add(i); else state.visible.delete(i);
      render();
    });
    document.addEventListener('click', e => {
      if (!menu.hidden && !e.target.closest('.lh-tree-cols')) menu.hidden = true;
    });
    let timer;
    search.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => { state.query = search.value.trim(); render(); }, 150);
    });
    // 단계별 드롭다운(값이 200개 이하인 단계만)
    const byDepth = data.levels.map(() => new Set());
    (function walk(list) { list.forEach(n => { byDepth[n.depth].add(n.name); walk(n.kids); }); })(roots);
    K.dimDropdowns(root.querySelector('.lh-tree-dd'), data.levels.map((l, i) => ({ label: l, values: Array.from(byDepth[i]) })), search);
    K.onThreshold(render);
    render();
  };

  /* 템플릿 부트스트랩: data-sec 블록마다 렌더러 호출, 데이터 없으면 placeholder */
  K.render = function (report, renderers) {
    K.init(report);
    document.querySelectorAll('[data-sec]').forEach(el => {
      const key = el.getAttribute('data-sec');
      const data = report.sections[key];
      if (data == null || !renderers[key]) { K.placeholder(el); return; }
      try { renderers[key](el, data); } catch (e) { console.error(key, e); K.placeholder(el); }
    });
  };

  window.LHKit = K;
})();
