/* 미디어믹스 결과 보고서 — laighthouse-web 결과 화면(src/pages/marketing/MediaMixResult.tsx)을 그대로 옮긴 것.
   계산(요약 표 · 증감 · 성과 표기 · 진단 읽기)은 src/lib/mediaMix.ts 와 같고, 문구는 ko 메시지 그대로다.
   요약 수치 → 매체별 표 → 진단(접힘) 순서. 같은 매체를 현재(기준 달 실적) → 제안(최적화) 순서로 나란히 비교하는 것이 핵심이다.

   입력: window.__MM_JOB__ = get_media_mix_job(include_diagnostics=true) 응답 그대로,
   window.__MM_AS_OF__ = 그 응답을 받은 시각(epoch ms).
   node 에서는 계산 함수만 module.exports 로 내보낸다. */
;(function (root) {
  'use strict'

  /* ---------- 계산(lib/mediaMix.ts) ---------- */
  /* 보이는 구분 — 응답에는 초안(draft) 행도 있지만 현재와 제안만 견준다 */
  var KINDS = ['current', 'optimized']
  var isActive = function (s) {
    return s === 'pending' || s === 'running'
  }
  var pad2 = function (n) {
    return String(n).padStart(2, '0')
  }
  var ym = function (d) {
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1)
  }
  function prevMonth(month) {
    var p = month.split('-').map(Number)
    return ym(new Date(p[0], p[1] - 2, 1))
  }
  /* 요청은 제안받을 달(target_month)이고, 기준 달은 그 전월이다 */
  var proposalMonth = function (req) {
    return req.target_month
  }
  var baseMonth = function (req) {
    return prevMonth(req.target_month)
  }
  /* 'YYYY-MM' → 2026년 3월 */
  function monthText(month) {
    var p = month.split('-').map(Number)
    return new Date(p[0], p[1] - 1, 1).toLocaleDateString('ko', { year: 'numeric', month: 'long' })
  }

  /* summary 는 구분 × 매체 합계, media '*' 가 그 구분의 전체 합계다.
     매체 순서 — 제안(optimized) 비용이 큰 순, 같으면 이름순. 매체 색도 이 순서를 따른다 */
  function summaryTable(rows) {
    var byKey = new Map(
      rows.map(function (r) {
        return [r.kind + '\u0000' + r.media, r]
      }),
    )
    var get = function (kind, media) {
      var r = byKey.get(kind + '\u0000' + media)
      return r ? { cost: r.cost, revenue: r.revenue, roas: r.roas == null ? null : r.roas } : null
    }
    var names = Array.from(
      new Set(
        rows
          .filter(function (r) {
            return r.media !== '*'
          })
          .map(function (r) {
            return r.media
          }),
      ),
    )
    var optimizedCost = function (m) {
      var c = get('optimized', m)
      return c ? c.cost : 0
    }
    names.sort(function (a, b) {
      return optimizedCost(b) - optimizedCost(a) || a.localeCompare(b)
    })
    return {
      media: names,
      cell: get,
      total: function (kind) {
        return get(kind, '*')
      },
    }
  }

  /* 증감률(%) — 기준이 0 이거나 없으면 null */
  var changeRate = function (to, from) {
    return to == null || from == null || from === 0 ? null : ((to - from) / Math.abs(from)) * 100
  }

  var won = function (v) {
    return v == null ? '–' : '₩' + Math.round(v).toLocaleString('ko-KR')
  }
  /* ROAS 는 배수(매출 ÷ 비용)로 온다 — 보고서 화면처럼 ×100 한 정수 퍼센트로 보인다 */
  var roasText = function (v) {
    return v == null ? '–' : Math.round(v * 100).toLocaleString('ko-KR') + '%'
  }

  /* 성과 지표(revenue_metric) 표기 — job 의 revenue_unit 으로 가른다.
     money: 매출처럼 금액 — ₩ 와 ROAS(%)
     count: 클릭 · 노출처럼 다른 단위 — 개수에 단위를 붙이고, 효율은 성과 하나당 비용(₩)
     unknown: 단위가 없어 금액인지 모른다 — 단위 없이 숫자, 효율은 성과 ÷ 비용 배수 그대로 */
  var MONEY_UNITS = ['₩', 'KRW', '원']
  function outcomeKind(unit) {
    var u = unit == null ? '' : String(unit).trim()
    return !u ? 'unknown' : MONEY_UNITS.indexOf(u) >= 0 ? 'money' : 'count'
  }
  function outcomeText(v, unit) {
    if (v == null) return '–'
    var kind = outcomeKind(unit)
    if (kind === 'money') return won(v)
    var n = Math.round(v).toLocaleString('ko-KR')
    return kind === 'count' ? n + String(unit).trim() : n
  }
  /* summary.roas 는 성과 ÷ 비용이다 — count 는 뒤집어 성과당 비용으로 본다(낮을수록 좋다) */
  function efficiency(roas, unit) {
    if (roas == null) return null
    return outcomeKind(unit) === 'count' ? (roas > 0 ? 1 / roas : null) : roas
  }
  function efficiencyText(roas, unit) {
    var kind = outcomeKind(unit)
    if (kind === 'money') return roasText(roas)
    var v = efficiency(roas, unit)
    if (v == null) return '–'
    /* 배수는 자릿수가 들쭉날쭉하니 유효숫자 세 자리로 맞춘다 — 0.0100 · 0.00388 · 9.70 */
    return kind === 'count'
      ? won(v)
      : v.toLocaleString('ko-KR', { minimumSignificantDigits: 3, maximumSignificantDigits: 3 })
  }

  /* 진단(diagnostics) — BE 가 dict 로 준다. 모양이 다른 값은 빼고 읽는다 */
  var obj = function (v) {
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
  }
  var numOr = function (v) {
    return typeof v === 'number' && isFinite(v) ? v : null
  }
  var strOr = function (v) {
    return typeof v === 'string' ? v : null
  }
  function readDiagnostics(raw) {
    if (!raw) return null
    var windows = []
    Object.keys(obj(raw.windows)).forEach(function (label) {
      var w = raw.windows[label]
      if (Array.isArray(w) && typeof w[0] === 'string' && typeof w[1] === 'string')
        windows.push({ label: label, start: w[0], end: w[1] })
    })
    var media = Object.keys(obj(raw.media)).map(function (name) {
      var m = obj(raw.media[name])
      var dow = m.dow == null ? null : obj(m.dow)
      return {
        media: name,
        samples: numOr(m.n_samples),
        pinned: Array.isArray(m.pinned) ? m.pinned.length : 0,
        dow: dow && {
          ratio: numOr(dow.ratio),
          significant: typeof dow.significant === 'boolean' ? dow.significant : null,
          bestDay: strOr(dow.best_day),
          worstDay: strOr(dow.worst_day),
          bestVsWorstPct: numOr(dow.best_vs_worst_pct),
        },
      }
    })
    var weights = raw.best_alpha_weights == null ? null : obj(raw.best_alpha_weights)
    var rt = obj(raw.runtime_seconds)
    return {
      windows: windows,
      media: media,
      notes: Array.isArray(raw.notes)
        ? raw.notes.filter(function (n) {
            return typeof n === 'string'
          })
        : [],
      /* weight 모드의 요일별 예산 가중치 — 0 = 월요일 … 6 = 일요일. even 이면 null */
      dowWeights:
        weights &&
        [0, 1, 2, 3, 4, 5, 6].map(function (i) {
          return numOr(weights[String(i)])
        }),
      maxRevenue: numOr(raw.max_revenue),
      /* 계산에 걸린 전체 시간(초). 단계별 시간은 보이지 않는다 */
      runtime: { total: numOr(rt.total_seconds) },
    }
  }

  /* ---------- 증감 표기(report/table.tsx) — 지표와 관계없이 오르면 초록 · 내리면 빨강 ---------- */
  var CHANGE_MARK = { up: '▲', down: '▼', flat: '' }
  var CHANGE_CLASS = { up: 'delta-up', down: 'delta-down', flat: 'delta-flat' }
  function resolveChangeDirection(rate) {
    return !isFinite(rate) || rate === 0 ? 'flat' : rate > 0 ? 'up' : 'down'
  }
  function markChange(direction, value) {
    return direction === 'flat' ? value : CHANGE_MARK[direction] + ' ' + value
  }

  /* ---------- 시간(lib/time.ts · MediaMixParts.tsx) ---------- */
  function fmtDateTime(iso) {
    if (!iso) return '-'
    var d = new Date(iso)
    return (
      d.getFullYear() +
      '-' +
      pad2(d.getMonth() + 1) +
      '-' +
      pad2(d.getDate()) +
      ' ' +
      pad2(d.getHours()) +
      ':' +
      pad2(d.getMinutes())
    )
  }
  function durationText(sec) {
    var m = Math.floor(sec / 60)
    var s = sec % 60
    return m ? m + '분 ' + s + '초' : s + '초'
  }
  /* 대기 · 실행 중이면 지금까지, 끝났으면 끝난 시각까지. 시작하기 전에 끝난 job 은 계산한 시간이 없어 null */
  function elapsedSeconds(job, now) {
    if (!job.started_at && job.finished_at) return null
    var from = Date.parse(job.started_at || job.created_at)
    var to = job.finished_at ? Date.parse(job.finished_at) : isActive(job.status) ? now : from
    return Math.max(0, Math.round((to - from) / 1000))
  }

  /* ---------- 문구(ko) ---------- */
  var KIND_LABEL = { current: '현재(실적)', optimized: '제안(최적화)' }
  /* optimized 매출은 실적이 아니라 GP 예측치다 */
  var REVENUE_LABEL = { current: '매출', optimized: '예상 매출' }
  var STATUS = {
    pending: { label: '대기 중', badge: 'badge-info' },
    running: { label: '계산 중', badge: 'badge-info' },
    succeeded: { label: '완료', badge: 'badge-success' },
    failed: { label: '실패', badge: 'badge-danger' },
    canceled: { label: '취소됨', badge: 'badge-muted' },
  }
  var WINDOW_LABEL = { A: '기준 달', M1: '1개월 전', M2: '2개월 전', M3: '3개월 전', 'PY+1': '작년 제안 달' }
  var WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일']

  /* 성과 지표 표기 — 금액(money)이면 매출 · ROAS, 아니면 지표 이름과 성과당 비용(count) 또는 성과 ÷ 비용(unknown) */
  function outcome(job) {
    var unit = job.revenue_unit
    var kind = outcomeKind(unit)
    var metric = job.request.revenue_metric
    return {
      kind: kind,
      label: function (k) {
        return kind === 'money'
          ? REVENUE_LABEL[k]
          : k === 'current'
            ? metric
            : '예상 ' + metric
      },
      eff: kind === 'money' ? 'ROAS' : kind === 'count' ? metric + '당 비용' : metric + ' ÷ 비용',
      value: function (v) {
        return outcomeText(v, unit)
      },
      effText: function (roas) {
        return efficiencyText(roas, unit)
      },
      effValue: function (roas) {
        return efficiency(roas, unit)
      },
    }
  }

  /* 매체 색 — 매체 순서(제안 비용이 큰 순)대로 토큰 팔레트를 돌려 쓴다 */
  var PALETTE = [
    '--blue-500',
    '--green-500',
    '--amber-500',
    '--purple-500',
    '--red-400',
    '--blue-300',
    '--green-300',
    '--amber-300',
    '--purple-300',
    '--ink-400',
  ]
  var colorVar = function (i) {
    return PALETTE[i % PALETTE.length]
  }

  var api = {
    KINDS: KINDS,
    prevMonth: prevMonth,
    monthText: monthText,
    summaryTable: summaryTable,
    changeRate: changeRate,
    won: won,
    roasText: roasText,
    outcomeKind: outcomeKind,
    outcomeText: outcomeText,
    efficiency: efficiency,
    efficiencyText: efficiencyText,
    readDiagnostics: readDiagnostics,
    resolveChangeDirection: resolveChangeDirection,
    markChange: markChange,
    durationText: durationText,
    elapsedSeconds: elapsedSeconds,
    outcome: outcome,
  }
  if (typeof module === 'object' && module.exports) {
    module.exports = api
    return
  }

  /* ---------- 그리기 ---------- */
  var esc = function (v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    })
  }
  /* lucide 아이콘(FE components/ui/Icon 과 같은 그림 · 굵기 1.8) */
  var ICON_PATHS = {
    alert:
      '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  }
  function icon(name, cls) {
    return (
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
      ' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' +
      (cls ? ' class="' + cls + '"' : '') +
      '>' +
      ICON_PATHS[name] +
      '</svg>'
    )
  }
  function statusBadge(status) {
    var s = STATUS[status] || { label: status, badge: 'badge-muted' }
    return '<span class="badge badge-dot ' + s.badge + '">' + esc(s.label) + '</span>'
  }

  function jobView(job) {
    var req = job.request
    var body
    if (isActive(job.status)) body = progress(job)
    else if (job.status === 'failed')
      body =
        '<div class="banner banner-danger">' +
        icon('alert') +
        '<div class="t-sm"><span class="b-title">계산하지 못했습니다</span><div class="b-body t-xs mt-2">' +
        esc(job.error || '잠시 후 다시 실행해 주세요.') +
        '</div></div></div>'
    else if (job.status === 'canceled')
      body =
        '<div class="banner banner-muted">' +
        icon('info') +
        '<div class="t-sm"><span class="b-title">취소한 계산입니다</span></div></div>'
    else body = result(job)
    return (
      '<div class="page-head"><h1>' +
      esc(monthText(proposalMonth(req))) +
      ' 예산 제안</h1>' +
      statusBadge(job.status) +
      '</div>' +
      '<dl class="dl mb-5">' +
      '<dt>기준 달</dt><dd>' +
      esc(monthText(baseMonth(req))) +
      '</dd>' +
      '<dt>목표 예산</dt><dd class="num">' +
      esc(won(req.target_budget)) +
      ' <span class="fg-3">VAT 제외 Net</span></dd>' +
      '<dt>지표</dt><dd>' +
      esc(req.cost_metric) +
      ' · ' +
      esc(req.revenue_metric) +
      '</dd>' +
      '<dt>요청 시각</dt><dd>' +
      esc(fmtDateTime(job.created_at)) +
      '</dd>' +
      '</dl>' +
      body
    )
  }

  /* 대기 · 계산 중 — 보고서는 응답을 받은 순간의 상태다(FE 처럼 다시 읽지 않는다). 경과 시간도 파일을 연 시각이 아니라
     응답을 받은 시각(window.__MM_AS_OF__, 빌더가 넣는다)까지 센다 */
  function progress(job) {
    var sec = elapsedSeconds(job, root.__MM_AS_OF__ || Date.now()) || 0
    var lead = job.status === 'pending' ? '요청 후 ' : '시작 후 '
    return (
      '<section class="card"><div class="card-body stack gap-3"><div class="row-between"><div class="row gap-2">' +
      '<span class="lock-spinner" aria-hidden="true"></span><span class="t-sm" style="font-weight:600">' +
      (job.status === 'pending' ? '계산 순서를 기다리는 중입니다' : '계산 중입니다') +
      '</span></div></div><p class="fg-3 t-sm">' +
      lead +
      esc(durationText(sec)) +
      ' 지났습니다. 보통 수 분 걸리며, 끝나면 이 화면에 결과가 나옵니다.</p></div></section>'
    )
  }

  function result(job) {
    var table = summaryTable(job.summary || [])
    var diagnostics = readDiagnostics(job.diagnostics)
    var o = outcome(job)
    var warnings = job.warnings || []
    var out = '<div class="stack gap-5">'
    if (warnings.length)
      out +=
        '<div class="banner banner-warning">' +
        icon('alert') +
        '<div class="t-sm"><span class="b-title">확인할 내용</span><ul class="b-body t-xs mt-2 list-disc pl-4 stack gap-1">' +
        warnings
          .map(function (w) {
            return '<li>' + esc(w) + '</li>'
          })
          .join('') +
        '</ul></div></div>'
    out += kpis(job, table, o)
    out +=
      '<section class="card"><div class="card-head"><h2>매체별 요약</h2><span class="fg-3 t-xs">' +
      '비용은 VAT 제외 Net 기준입니다.' +
      '</span></div>' +
      summaryTableView(table, o) +
      '</section>'
    if (diagnostics) out += diagnosticsView(diagnostics, o)
    return out + '</div>'
  }

  /* 요약 수치(총 예산 · 예상 총 매출 · ROAS)에 목표 예산 대비와 기준 달 실적 ROAS 를 곁들인다.
     weight 모드는 제안 비용 합계가 목표 예산보다 적을 수 있다 */
  function kpis(job, table, o) {
    var opt = table.total('optimized')
    var cur = table.total('current')
    var target = job.request.target_budget
    var ofTarget = opt ? (opt.cost / target) * 100 : null
    var roasChange = changeRate(o.effValue(opt && opt.roas), o.effValue(cur && cur.roas))
    var roasDir = roasChange == null ? 'flat' : resolveChangeDirection(Number(roasChange.toFixed(1)))
    var kpi = function (label, value, delta) {
      return (
        '<div class="kpi"><div class="k-label">' +
        esc(label) +
        '</div><div class="k-value num">' +
        esc(value) +
        '</div>' +
        (delta == null ? '' : '<div class="k-delta">' + delta + '</div>') +
        '</div>'
      )
    }
    var mtd = function (text) {
      return '<span class="mtd">' + esc(text) + '</span>'
    }
    return (
      '<div class="kpi-grid">' +
      kpi(
        '제안 예산 합계',
        won(opt && opt.cost),
        mtd('목표 ' + won(target) + ' (Net)') +
          (ofTarget != null && ofTarget < 99.5 ? mtd(ofTarget.toFixed(1) + '% 배분') : ''),
      ) +
      kpi(o.label('optimized'), o.value(opt && opt.revenue), mtd('모델 예측치')) +
      kpi(
        '예상 ' + o.eff,
        o.effText(opt && opt.roas),
        roasChange == null
          ? null
          : '<span class="font-semibold ' +
              CHANGE_CLASS[roasDir] +
              '">' +
              esc(markChange(roasDir, Math.abs(roasChange).toFixed(1) + '%')) +
              '</span>' +
              mtd('기준 달 대비'),
      ) +
      kpi('기준 달 실적 ' + o.eff, o.effText(cur && cur.roas), mtd('비용 ' + won(cur && cur.cost))) +
      '</div>'
    )
  }

  function summaryTableView(table, o) {
    var optTotalCell = table.total('optimized')
    var optTotal = optTotalCell ? optTotalCell.cost : 0
    /* 제안 비용 칸에는 비중(제안 합계 대비)을 아래 줄로 곁들인다 */
    var cells = function (kind, media) {
      var c = media == null ? table.total(kind) : table.cell(kind, media)
      var share =
        kind === 'optimized' && media != null && optTotal > 0 && c
          ? '<div class="cell-sub">비중 ' + ((c.cost / optTotal) * 100).toFixed(1) + '%</div>'
          : ''
      return (
        '<td class="num mm-group-start">' +
        esc(won(c && c.cost)) +
        share +
        '</td><td class="num">' +
        esc(o.value(c && c.revenue)) +
        '</td><td class="num">' +
        esc(o.effText(c && c.roas)) +
        '</td>'
      )
    }
    var head1 = KINDS.map(function (k) {
      return '<th colspan="3" class="mm-group-start">' + esc(KIND_LABEL[k]) + '</th>'
    }).join('')
    var head2 = KINDS.map(function (k) {
      return (
        '<th class="num mm-group-start">비용</th><th class="num">' +
        esc(o.label(k)) +
        '</th><th class="num">' +
        esc(o.eff) +
        '</th>'
      )
    }).join('')
    var body = table.media
      .map(function (m, i) {
        return (
          '<tr><td><span class="row gap-2"><span class="mm-dot" style="background:var(' +
          colorVar(i) +
          ')"></span><span class="cell-title">' +
          esc(m) +
          '</span></span></td>' +
          KINDS.map(function (k) {
            return cells(k, m)
          }).join('') +
          '</tr>'
        )
      })
      .join('')
    var total =
      '<tr class="mm-total"><td>합계</td>' +
      KINDS.map(function (k) {
        return cells(k, null)
      }).join('') +
      '</tr>'
    return (
      '<div class="table-wrap overflow-x-auto"><table class="data-table table-dense mm-summary"><thead><tr><th rowspan="2">매체</th>' +
      head1 +
      '</tr><tr>' +
      head2 +
      '</tr></thead><tbody>' +
      body +
      total +
      '</tbody></table></div>'
    )
  }

  /* 진단 — 분석용이라 접어 둔다. 요일 효과가 유의하지 않은 매체는 차이를 참고용으로만 보여 준다 */
  function diagnosticsView(d, o) {
    var sec = function (v) {
      return v == null ? '–' : durationText(Math.round(v))
    }
    var out =
      '<details class="card mm-diag"><summary class="card-head"><h2>진단</h2>' +
      '<span class="fg-3 t-xs">학습 기간 · 표본 · 요일 효과 · 계산 시간</span>' +
      icon('chevron-down', 'mm-diag-caret') +
      '</summary><div class="card-body stack gap-5">'
    if (d.windows.length)
      out +=
        '<div><h3 class="t-sm mb-2" style="font-weight:600">학습에 쓴 기간</h3><dl class="dl">' +
        d.windows
          .map(function (w) {
            return (
              '<dt>' +
              esc(WINDOW_LABEL[w.label] || w.label) +
              '</dt><dd class="num">' +
              esc(w.start) +
              ' ~ ' +
              esc(w.end) +
              '</dd>'
            )
          })
          .join('') +
        '</dl></div>'
    if (d.media.length)
      out +=
        '<div class="table-wrap overflow-x-auto"><table class="data-table table-dense"><thead><tr><th>매체</th>' +
        '<th class="num">학습 일수</th><th>모델 상태</th><th>요일 효과</th></tr></thead><tbody>' +
        d.media
          .map(function (m) {
            var dow = m.dow
            var effect = ''
            if (!dow) effect = '<span class="fg-3">–</span>'
            else {
              var parts = []
              if (dow.bestDay && dow.worstDay && dow.bestVsWorstPct != null)
                parts.push(
                  '<span>' +
                    esc(dow.bestDay + '요일이 ' + dow.worstDay + '요일보다 약 ' + dow.bestVsWorstPct.toFixed(1) + '% 높음') +
                    '</span>',
                )
              if (dow.ratio != null)
                parts.push('<span class="fg-3">요일 효과 비중 ' + (dow.ratio * 100).toFixed(1) + '%</span>')
              if (dow.significant === false) parts.push('<span class="badge">유의하지 않음 · 참고용</span>')
              effect = '<span class="row gap-2 flex-wrap">' + parts.join('') + '</span>'
            }
            return (
              '<tr><td class="cell-title">' +
              esc(m.media) +
              '</td><td class="num">' +
              (m.samples == null ? '–' : m.samples) +
              '</td><td>' +
              (m.pinned > 0
                ? '<span class="badge badge-warning">경계값 ' + m.pinned + '개 · 신뢰도 낮음</span>'
                : '<span class="fg-3">정상</span>') +
              '</td><td class="t-sm">' +
              effect +
              '</td></tr>'
            )
          })
          .join('') +
        '</tbody></table></div>'
    out += '<dl class="dl">'
    if (d.dowWeights)
      out +=
        '<dt>요일별 예산 가중치</dt><dd class="num">' +
        d.dowWeights
          .map(function (w, i) {
            return WEEKDAYS[i] + ' ' + (w == null ? '–' : w.toFixed(2))
          })
          .join(' · ') +
        '</dd>'
    if (d.maxRevenue != null)
      out +=
        '<dt>' +
        (o.kind === 'money' ? '가중치 기준 예상 총매출' : '가중치 기준 ' + esc(o.label('optimized')) + ' 합계') +
        '</dt><dd class="num">' +
        esc(o.value(d.maxRevenue)) +
        '</dd>'
    out +=
      '<dt>계산 시간</dt><dd class="num">' +
      esc(sec(d.runtime.total)) +
      '</dd>'
    if (d.notes.length)
      out +=
        '<dt>배분 메모</dt><dd><ul class="stack gap-1">' +
        d.notes
          .map(function (n) {
            return '<li>' + esc(n) + '</li>'
          })
          .join('') +
        '</ul></dd>'
    return out + '</dl></div></details>'
  }

  function render(job) {
    var app = document.getElementById('app')
    app.innerHTML = jobView(job)
  }

  render(root.__MM_JOB__)
})(typeof window !== 'undefined' ? window : globalThis)
