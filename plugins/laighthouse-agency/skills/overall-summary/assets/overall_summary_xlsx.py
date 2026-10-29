#!/usr/bin/env python3
"""종합 리포트 엑셀(.xlsx) — build_report.py가 HTML과 같은 데이터로 함께 만든다(직접 부르지 않는다).

시트 구성(대행사 기본 레포트 양식 — Summary · By Media · By Date · Mix + 원자료):
  Summary   Total Summary · Monthly Summary(기본 영역 + 목표 영역) · Daily/Weekly Comment
  By Media  Product · Target · Creative(소재 차원이 있을 때) · Placement(노출 위치 데이터가 있을 때, 없으면 '준비 중')
  By Date   Weekly · Daily (나란히)
  Mix       목표 입력값 기준 월별 계획 — 월 예산·CPM·CPC·VTR(파란 글씨)은 값, 예산·예상치는 수식(바꾸면 다시 계산된다)
  Raw       표 데이터 원자 행(일 × 차원) — 필터·피벗용

수치 규칙은 브라우저(assets/overall_summary.js)와 같다:
  - 행 계층·순서: 미디어 → 디멘전(기본 설정), 광고비 큰 순(주·일은 날짜 순). 묶음마다 '{이름} 요약', 맨 아래 총합계.
  - 묶음 행의 CTR·CPM·CPC·CPV·VTR은 원자 지표(광고비·노출·클릭·조회) 합으로 다시 계산한다.
  - 예산·목표(e.*)·소진율·진행율·달성률은 같은 범위 찾기(lookup/targetsOf), Mix 줄·초기값은 같은 MIX_LINES 규칙.
  - 화면의 '외 N개' 접기는 하지 않는다 — 엑셀에는 모든 행을 넣는다. 필터는 전체 월·전 매체(초기 상태)다.

엑셀 작성은 표준 라이브러리(zipfile + SpreadsheetML)만 쓴다 — 호스트에 openpyxl이 없어도 같은 파일이 나오고,
Mix 수식에 계산된 값(캐시)을 함께 넣어 수식을 계산하지 않는 뷰어에서도 숫자가 보인다.
"""
import os
import re
import tempfile
import unicodedata
import zipfile
from datetime import date, datetime, timezone
from functools import lru_cache
from xml.sax.saxutils import escape

FONT = "맑은 고딕"
C_HEAD = "404040"     # 머리글·총합계 (예시: 텍스트 1, 25% 밝게)
C_AREA = "FFC000"     # 기본 영역·목표 영역 띠
C_MEDIA = "DCE6F1"    # 미디어 칸·미디어 요약 행 (예시: 텍스트 2, 90% 밝게)
C_LEAD = "F2F2F2"     # 캠페인명·월 칸, 둘째 단계 요약 행
C_MONTH = "D9D9D9"    # 'N월 요약'
C_NA = "D9D9D9"       # Mix 입력 불가 칸
C_INPUT = "1F4FD8"    # Mix 입력값(파란 글씨)
C_BORDER = "A6A6A6"
F_INT = "#,##0"
F_ACC = '_-* #,##0_-;\\-* #,##0_-;_-* "-"_-;_-@_-'   # Mix: 0은 '-'
F_P2 = "0.00%"
F_P0 = "0%"
F_DATE = "yyyy.m.d"
RATIO_T = {"ctr", "vtr", "cpm", "cpc", "cpv"}


# ── 최소 SpreadsheetML 작성기 ─────────────────────────────────────────────────


@lru_cache(maxsize=None)
def col_letter(c):
    """1 → A, 27 → AA"""
    s = ""
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def ref(r, c):
    return f"{col_letter(c)}{r}"


_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _x(s):
    return escape(_BAD_XML.sub("", str(s)), {'"': "&quot;"})


def text_width(s):
    """표시 폭 — 한글 등 전각 문자는 2칸."""
    s = str(s)
    if s.isascii():
        return len(s)
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(s))


class Styles:
    """스타일 조합(dict) → cellXfs 번호. 같은 조합은 한 번만 등록한다."""

    BUILTIN_FMT = {"General": 0, "#,##0": 3, "0%": 9, "0.00%": 10}

    def __init__(self):
        self.fonts, self.fills, self.borders, self.fmts, self.xfs = [], [], [], {}, []
        self._font(False, None, 10)
        self.fills = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>']
        self.borders = ["<border><left/><right/><top/><bottom/><diagonal/></border>"]
        self.cache = {}
        self.get({})

    def _font(self, bold, color, size):
        xml = (f'<font>{"<b/>" if bold else ""}<sz val="{size}"/>'
               + (f'<color rgb="FF{color}"/>' if color else '<color theme="1"/>') + f'<name val="{FONT}"/><family val="3"/>'
               + '<charset val="129"/></font>')
        if xml not in self.fonts:
            self.fonts.append(xml)
        return self.fonts.index(xml)

    def _fill(self, bg):
        if not bg:
            return 0
        xml = f'<fill><patternFill patternType="solid"><fgColor rgb="FF{bg}"/><bgColor indexed="64"/></patternFill></fill>'
        if xml not in self.fills:
            self.fills.append(xml)
        return self.fills.index(xml)

    def _border(self, on):
        if not on:
            return 0
        side = f'style="thin"><color rgb="FF{C_BORDER}"/>'
        xml = f"<border><left {side}</left><right {side}</right><top {side}</top><bottom {side}</bottom><diagonal/></border>"
        if xml not in self.borders:
            self.borders.append(xml)
        return self.borders.index(xml)

    def _fmt(self, code):
        if not code or code == "General":
            return 0
        if code in self.BUILTIN_FMT:
            return self.BUILTIN_FMT[code]
        return self.fmts.setdefault(code, 164 + len(self.fmts))

    def get(self, st):
        """st: {"b": 굵게, "fc": 글자색, "bg": 배경, "fmt": 숫자 형식, "al": left|center|right, "bd": 테두리, "sz": 크기, "wrap"}"""
        key = tuple(sorted(st.items()))
        if key in self.cache:
            return self.cache[key]
        font = self._font(st.get("b", False), st.get("fc"), st.get("sz", 10))
        fill, border, fmt = self._fill(st.get("bg")), self._border(st.get("bd")), self._fmt(st.get("fmt"))
        al = st.get("al")
        attr = lambda on, name: f' {name}="1"' if on else ""  # noqa: E731
        horiz = f' horizontal="{al}"' if al else ""
        align = f'<alignment{horiz} vertical="center"{attr(st.get("wrap"), "wrapText")}/>'
        xml = (f'<xf numFmtId="{fmt}" fontId="{font}" fillId="{fill}" borderId="{border}" xfId="0"'
               f'{attr(fmt, "applyNumberFormat")}{attr(font, "applyFont")}{attr(fill, "applyFill")}'
               f'{attr(border, "applyBorder")} applyAlignment="1">{align}</xf>')
        self.xfs.append(xml)
        self.cache[key] = len(self.xfs) - 1
        return self.cache[key]

    def xml(self):
        fmts = "".join(f'<numFmt numFmtId="{i}" formatCode="{_x(c)}"/>' for c, i in self.fmts.items())
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                + (f'<numFmts count="{len(self.fmts)}">{fmts}</numFmts>' if self.fmts else "")
                + f'<fonts count="{len(self.fonts)}">{"".join(self.fonts)}</fonts>'
                + f'<fills count="{len(self.fills)}">{"".join(self.fills)}</fills>'
                + f'<borders count="{len(self.borders)}">{"".join(self.borders)}</borders>'
                + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                + f'<cellXfs count="{len(self.xfs)}">{"".join(self.xfs)}</cellXfs>'
                + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                + '</styleSheet>')


class Sheet:
    def __init__(self, book, name):
        self.book, self.name = book, name
        self.cells = {}          # (행, 열) → (값, 스타일 번호, 수식)
        self.merges, self.widths, self.fit, self.heights = [], {}, {}, {}
        self.freeze = self.autofilter = None

    def set(self, r, c, v=None, st=None, f=None, fit=True):
        """값 v(숫자·문자·날짜·None), 스타일 st(dict 또는 미리 받은 번호), 수식 f(앞의 '=' 없이 — v는 계산해 둔 값).
        fit: 열 너비 계산에 넣을지."""
        self.cells[(r, c)] = (v, st if isinstance(st, int) else self.book.styles.get(st or {}), f)
        if fit and v is not None and v != "":
            w = (text_width(v) if isinstance(v, str) else 10 if isinstance(v, (date, datetime))
                 else len(f"{v:,.0f}") + 1 if isinstance(v, (int, float)) and abs(v) >= 1 else 5)
            self.fit[c] = max(self.fit.get(c, 0), w)

    def merge(self, r1, c1, r2, c2):
        if (r1, c1) == (r2, c2):
            return
        top = self.cells.get((r1, c1))
        sid = top[1] if top else 0
        for r in range(r1, r2 + 1):   # 병합 범위 안 칸도 같은 스타일(테두리·배경)을 갖게 한다
            for c in range(c1, c2 + 1):
                if (r, c) != (r1, c1):
                    self.cells[(r, c)] = (None, sid, None)
        self.merges.append(f"{ref(r1, c1)}:{ref(r2, c2)}")

    def xml(self, selected):
        rows = {}
        for (r, c), cell in self.cells.items():
            rows.setdefault(r, {})[c] = cell
        out = []
        for r in sorted(rows):
            ht = self.heights.get(r)
            cells = []
            for c in sorted(rows[r]):
                v, sid, f = rows[r][c]
                cells.append(self._cell(ref(r, c), v, sid, f))
            out.append(f'<row r="{r}"' + (f' ht="{ht}" customHeight="1"' if ht else "") + ">" + "".join(cells) + "</row>")
        maxc = max((c for _, c in self.cells), default=1)
        maxr = max((r for r, _ in self.cells), default=1)
        widths = dict(self.widths)
        for c, w in self.fit.items():
            widths.setdefault(c, min(max(w + 2, 7), 60))
        cols = "".join(f'<col min="{c}" max="{c}" width="{w:.1f}" customWidth="1"/>' for c, w in sorted(widths.items()))
        pane = ""
        if self.freeze:
            fr, fc = self.freeze
            top = ref(fr, fc)
            attrs = (f' xSplit="{fc - 1}"' if fc > 1 else "") + (f' ySplit="{fr - 1}"' if fr > 1 else "")
            act = "bottomRight" if fr > 1 and fc > 1 else "bottomLeft" if fr > 1 else "topRight"
            pane = f'<pane{attrs} topLeftCell="{top}" activePane="{act}" state="frozen"/><selection pane="{act}"/>'
        sel = ' tabSelected="1"' if selected else ""
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<dimension ref="A1:{ref(maxr, maxc)}"/>'
                f'<sheetViews><sheetView showGridLines="0"{sel} workbookViewId="0">{pane}'
                '</sheetView></sheetViews><sheetFormatPr defaultRowHeight="16.5"/>'
                + (f"<cols>{cols}</cols>" if cols else "")
                + f'<sheetData>{"".join(out)}</sheetData>'
                + (f'<autoFilter ref="{self.autofilter}"/>' if self.autofilter else "")
                + (f'<mergeCells count="{len(self.merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in self.merges)
                   + "</mergeCells>" if self.merges else "")
                + '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>')

    def _cell(self, at, v, sid, f):
        s = f' s="{sid}"' if sid else ""
        t = type(v)
        if f is None and (t is int or (t is float and v == v and abs(v) != float("inf"))):   # 가장 흔한 칸 — 빠른 길
            return f'<c r="{at}"{s}><v>{v!r}</v></c>'
        if f is None and t is str and v:
            return f'<c r="{at}"{s} t="s"><v>{self.book.string(v)}</v></c>'
        if f is not None:
            fx = f"<f>{_x(f)}</f>"
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf"):
                return f'<c r="{at}"{s}>{fx}<v>{v!r}</v></c>'
            return f'<c r="{at}"{s} t="str">{fx}<v>{_x(v if v is not None else "")}</v></c>'
        if v is None or v == "":
            return f'<c r="{at}"{s}/>'
        if isinstance(v, datetime):
            v = v.date()
        if isinstance(v, date):
            return f'<c r="{at}"{s}><v>{(v - date(1899, 12, 30)).days}</v></c>'
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if v != v or abs(v) == float("inf"):
                return f'<c r="{at}"{s}/>'
            return f'<c r="{at}"{s}><v>{v!r}</v></c>'
        return f'<c r="{at}"{s} t="s"><v>{self.book.string(str(v))}</v></c>'


class Book:
    def __init__(self):
        self.sheets, self.strings, self.styles = [], {}, Styles()

    def sheet(self, name):
        name = re.sub(r"[\[\]:*?/\\]", "_", name)[:31]
        sh = Sheet(self, name)
        self.sheets.append(sh)
        return sh

    def string(self, s):
        return self.strings.setdefault(_BAD_XML.sub("", s), len(self.strings))

    def save(self, path):
        """임시 파일에 쓴 뒤 바꿔 넣는다 — 실패해도 반쯤 쓴 파일이 남지 않는다."""
        sheets_xml = [sh.xml(i == 0) for i, sh in enumerate(self.sheets)]   # 공유 문자열은 시트를 그리며 모인다
        n = len(self.sheets)
        ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
              + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(n))
              + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
              '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
              '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
              '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
              '</Types>')
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                '</Relationships>')
        filt = "".join(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
                       f"'{_x(sh.name)}'!{_abs(sh.autofilter)}</definedName>" for i, sh in enumerate(self.sheets) if sh.autofilter)
        wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
              '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
              '<bookViews><workbookView activeTab="0"/></bookViews><sheets>'
              + "".join(f'<sheet name="{_x(sh.name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, sh in enumerate(self.sheets))
              + "</sheets>" + (f"<definedNames>{filt}</definedNames>" if filt else "")
              + '<calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>')
        wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                             f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(n))
                   + f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   + f'<Relationship Id="rId{n + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
                   + "</Relationships>")
        sst = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(self.strings)}" '
               f'uniqueCount="{len(self.strings)}">'
               + "".join(f'<si><t xml:space="preserve">{_x(s)}</t></si>' for s in self.strings) + "</sst>")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>LaightAI</dc:creator>'
                f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
                f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
        app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
               '<Application>Microsoft Excel</Application></Properties>')
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=folder)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("[Content_Types].xml", ct)
                z.writestr("_rels/.rels", rels)
                z.writestr("docProps/core.xml", core)
                z.writestr("docProps/app.xml", app)
                z.writestr("xl/workbook.xml", wb)
                z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
                z.writestr("xl/styles.xml", self.styles.xml())
                z.writestr("xl/sharedStrings.xml", sst)
                for i, x in enumerate(sheets_xml):
                    z.writestr(f"xl/worksheets/sheet{i + 1}.xml", x)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return path


def _abs(rng):
    return ":".join(re.sub(r"([A-Z]+)(\d+)", r"$\1$\2", p) for p in rng.split(":"))


# ── 화면과 같은 계산 (overall_summary.js 포팅) ────────────────────────────────────


def uniq(seq):
    return list(dict.fromkeys(seq))


def agg(rs):
    a = {"cost": 0, "imp": 0, "click": 0, "view": 0}
    for r in rs:
        for k in a:
            a[k] += r[k]
    return a


class Targets:
    """예산·목표(budgets): 정확한 범위가 있으면 그 값, 없으면 더 잘게 받은 범위가 이 행의 단위를 모두 덮을 때만 합
    (비율 목표는 합하지 않는다) — overall_summary.js lookup·targetsOf·progOf와 같다."""

    def __init__(self, budgets, months):
        self.B = budgets or []
        self.month = {m["key"]: m for m in months}

    @staticmethod
    def keyset(b):
        return ",".join(sorted(b["scope"]))

    def lookup(self, mo, fixed, key, rs):
        es = [b for b in self.B if b["mo"] == mo and b["v"].get(key) is not None]
        if not es:
            return None
        fk = sorted(fixed)
        for b in es:
            if self.keyset(b) == ",".join(fk) and all(b["scope"].get(k) == fixed[k] for k in fk):
                return b["v"][key]
        if key in RATIO_T:
            return None
        levels = [s.split(",") if s else [] for s in uniq(self.keyset(b) for b in es)]
        levels = sorted((L for L in levels if len(L) > len(fk) and all(k in L for k in fk)), key=len)
        for L in levels:
            cand = [b for b in es if self.keyset(b) == ",".join(L) and all(b["scope"].get(k) == fixed[k] for k in fk)]
            have = {tuple(b["scope"].get(k) for k in L) for b in cand}
            need = uniq(tuple(r.get(k) for k in L) for r in rs if r["mo"] == mo)
            if need and all(n in have for n in need):
                return sum(b["v"][key] for b in cand)
        return None

    def of(self, rs, fixed):
        if not self.B or not rs:
            return None
        mos = uniq(r["mo"] for r in rs)
        out = {}
        for key in ("cost", "imp", "click", "view", "ctr", "vtr", "cpm", "cpc", "cpv"):
            s = 0
            for mo in mos:
                v = self.lookup(mo, fixed, key, rs)
                if v is None:
                    s = None
                    break
                s += v
            if s is not None and not (key in RATIO_T and len(mos) > 1):
                out[key] = s
        # 비율 목표가 없으면(여러 단위·여러 달을 합친 행 등) 합친 예산·노출·클릭·조회 목표로 계산한다
        for k, n, d, mul in (("ctr", "click", "imp", 100), ("cpm", "cost", "imp", 1000), ("cpc", "cost", "click", 1),
                             ("vtr", "view", "imp", 100), ("cpv", "cost", "view", 1)):
            if out.get(k) is None and out.get(n) and out.get(d):
                out[k] = out[n] / out[d] * mul
        return out

    def prog(self, rs):
        el = tot = 0
        for mo in uniq(r["mo"] for r in rs):
            el += self.month[mo]["elapsed"]
            tot += self.month[mo]["days"]
        return el / tot if tot else None


def _div(n, d, mul=1):
    return n / d * mul if d else None


def _tg(k, scale=1):
    return lambda x: x["tg"][k] / scale if x.get("tg") and x["tg"].get(k) is not None else None


def metric_defs(has):
    """(키, 머리글, 숫자 형식, 값 함수, 영역) — 값 함수는 {"a": 원자 합, "tg": 목표, "prog": 진행율}를 받는다."""
    need_ok = lambda need: all(has.get(n) for n in need)  # noqa: E731
    pivot = [(k, l, f, fn, "b") for k, l, f, fn, need in (
        ("cost", "비용", F_INT, lambda x: x["a"]["cost"], ()),
        ("imp", "노출", F_INT, lambda x: x["a"]["imp"], ("imp",)),
        ("click", "클릭", F_INT, lambda x: x["a"]["click"], ("click",)),
        ("view", "조회", F_INT, lambda x: x["a"]["view"], ("view",)),
        ("cpm", "CPM", F_INT, lambda x: _div(x["a"]["cost"], x["a"]["imp"], 1000), ("imp",)),
        ("cpc", "CPC", F_INT, lambda x: _div(x["a"]["cost"], x["a"]["click"]), ("click",)),
        ("ctr", "CTR", F_P2, lambda x: _div(x["a"]["click"], x["a"]["imp"]), ("imp", "click")),
        ("cpv", "CPV", F_INT, lambda x: _div(x["a"]["cost"], x["a"]["view"]), ("view",)),
        ("vtr", "VTR", F_P0, lambda x: _div(x["a"]["view"], x["a"]["imp"]), ("imp", "view")),
    ) if need_ok(need)]
    cost_tg = lambda x: x["tg"]["cost"] if x.get("tg") and x["tg"].get("cost") else None  # noqa: E731
    sel = [(k, k, f, fn, "s") for k, f, fn, need in (
        ("e.Imps", F_INT, _tg("imp"), ("imp",)),
        ("e.Click", F_INT, _tg("click"), ("click",)),
        ("e.View", F_INT, _tg("view"), ("view",)),
        ("e.CTR", F_P2, _tg("ctr", 100), ("imp", "click")),
        ("e.VTR", F_P0, _tg("vtr", 100), ("imp", "view")),
        ("e.CPM", F_INT, _tg("cpm"), ("imp",)),
        ("e.CPC", F_INT, _tg("cpc"), ("click",)),
        ("e.CPV", F_INT, _tg("cpv"), ("view",)),
        ("노출 달성률", F_P0, lambda x: _div(x["a"]["imp"], x["tg"]["imp"]) if x.get("tg") and x["tg"].get("imp") else None, ("imp",)),
        ("클릭 달성률", F_P0, lambda x: _div(x["a"]["click"], x["tg"]["click"]) if x.get("tg") and x["tg"].get("click") else None, ("click",)),
        ("조회 달성률", F_P0, lambda x: _div(x["a"]["view"], x["tg"]["view"]) if x.get("tg") and x["tg"].get("view") else None, ("view",)),
    ) if need_ok(need)]
    summary = ([("budget", "예산", F_INT, cost_tg, "b")] + pivot
               + [("burn", "소진율", F_P0, lambda x: _div(x["a"]["cost"], cost_tg(x)) if cost_tg(x) else None, "b"),
                  ("prog", "진행율", F_P0, lambda x: x.get("prog"), "b")] + sel)
    return pivot, summary


class Dim:
    def __init__(self, key, label, rank=None, sort=None, fmt=None):
        self.key, self.label, self.rank, self.sort, self.fmt = key, label, rank, sort, fmt or (lambda k: k)

    def order(self, keys):
        if self.sort:
            return sorted(keys, key=self.sort)
        return sorted(keys, key=lambda k: self.rank.get(k, 1e9))


def tree(rs, dims, sub_at, x_of):
    """renderTree(화면 계층 펼치기)와 같은 순서 — 접지 않고 모든 행. 반환 (행 목록, 세로 병합 [(시작, 끝, 단계)]).
    행 = {"kind": leaf|sub, "level", "labels": {단계: 이름}, "x": 값 함수 입력}."""
    out, merges, D = [], [], len(dims)

    def walk(rs, level, fixed):
        dim = dims[level]
        groups = {}
        for r in rs:
            groups.setdefault(r[dim.key], []).append(r)
        for k in dim.order(list(groups)):
            sub, label, fx = groups[k], dim.fmt(k), dict(fixed, **{dim.key: k})
            if level == D - 1:
                out.append({"kind": "leaf", "level": level, "labels": {level: label}, "x": x_of(sub, fx, True)})
                continue
            start = len(out)
            walk(sub, level + 1, fx)
            out[start]["labels"][level] = label
            merges.append((start, len(out) - 1, level))
            if sub_at(level):
                out.append({"kind": "sub", "level": level, "labels": {level: label + " 요약"}, "x": x_of(sub, fx, False)})

    if rs:
        walk(rs, 0, {})
    return out, merges


# ── 표 그리기 ─────────────────────────────────────────────────────────────────


def row_style(kind, level, base=None):
    """행 종류별 칸 모양 — 총합계 = 짙은 회색, N월 요약 = 회색, 미디어 요약 = 연한 남색, 그 아래 요약 = 연한 회색."""
    st = {"bd": True, "al": "center", **(base or {})}
    if kind == "total":
        st.update(bg=C_HEAD, fc="FFFFFF", b=True)
    elif kind == "msum":
        st.update(bg=C_MONTH, b=True)
    elif kind == "sub" and level == 0:
        st.update(bg=C_MEDIA, b=True)
    elif kind == "sub":
        st.update(bg=C_LEAD)
    return st


def label_style(j, D):
    """라벨 칸 — 미디어 = 연한 남색 굵게, 중간 묶음 = 굵게, 맨 아래 단계 = 보통."""
    if j == 0:
        return {"bd": True, "al": "center", "bg": C_MEDIA, "b": True}
    return {"bd": True, "al": "center", "b": True} if j < D - 1 else {"bd": True, "al": "center"}


def head_row(sh, r, c, labels):
    for i, t in enumerate(labels):
        sh.set(r, c + i, t, {"bg": C_HEAD, "fc": "FFFFFF", "b": True, "al": "center", "bd": True, "wrap": True})


def section_title(sh, r, c, text):
    sh.set(r, c, text, {"b": True, "sz": 11}, fit=False)
    sh.heights[r] = 20


def put_tree(sh, r0, c0, out, merges, D, cols, lead_cols=0):
    """tree() 결과를 r0행·c0열(라벨 시작 — 앞에 lead_cols칸이 따로 있으면 그만큼 오른쪽)부터 쓴다. 반환: 다음 행."""
    cl = c0 + lead_cols
    for i, row in enumerate(out):
        r, kind, lv = r0 + i, row["kind"], row["level"]
        for j in range(D):   # 요약 행의 바깥 단계 칸(j < 단계)은 위 묶음 병합 칸이라 라벨 모양
            st = row_style(kind, lv) if kind != "leaf" and j >= lv else label_style(j, D)
            sh.set(r, cl + j, row["labels"].get(j), st)
        for j, (_, _, fmt, fn, _) in enumerate(cols):
            sh.set(r, cl + D + j, fn(row["x"]), row_style(kind, lv, {"al": "right", "fmt": fmt}))
        if kind == "sub" and lv < D - 1:
            sh.merge(r, cl + lv, r, cl + D - 1)
    for s, e, lv in merges:
        if e > s:
            sh.merge(r0 + s, cl + lv, r0 + e, cl + lv)
    return r0 + len(out)


def put_total(sh, r, c, span, x, cols, label, kind="total"):
    st = row_style(kind, 0)
    sh.set(r, c, label, st)
    for j in range(1, span):
        sh.set(r, c + j, None, st)
    if span > 1:
        sh.merge(r, c, r, c + span - 1)
    for j, (_, _, fmt, fn, _) in enumerate(cols):
        sh.set(r, c + span + j, fn(x), row_style(kind, 0, {"al": "right", "fmt": fmt}))


def pivot_block(sh, r, c, title, rs, dims, cols):
    """Product·Target·Placement·Weekly·Daily — 묶음마다 요약, 맨 아래 총합계(화면 buildPivot)."""
    section_title(sh, r, c, title)
    D = len(dims)
    head_row(sh, r + 1, c, [d.label for d in dims] + [lb for _, lb, _, _, _ in cols])
    out, merges = tree(rs, dims, lambda lv: lv < D - 1, lambda sub, fx, leaf: {"a": agg(sub)})
    nxt = put_tree(sh, r + 2, c, out, merges, D, cols)
    if rs:
        put_total(sh, nxt, c, D, {"a": agg(rs)}, cols, "총합계")
    else:
        sh.set(nxt, c, "데이터가 없습니다.", {"fc": "808080"}, fit=False)
    return nxt + 1


# ── 시트 ──────────────────────────────────────────────────────────────────────


class Ctx:
    def __init__(self, report, rows):
        T = report["table"]
        self.report, self.T, self.months, self.has = report, T, report["months"], T["has"]
        self.brand = report["brand"]
        self.dims = T["dims"]
        self.rank = {k: {v: i for i, v in enumerate(vs)} for k, vs in T["dict"].items()}
        self.days = T["days"]
        y, m, d = (int(x) for x in self.days[0]["label"].split("."))
        self.start = date(y, m, d)
        self.rows = []
        for r in rows:
            dk = (r["day"] - self.start).days
            x = dict(r, mo=f"{r['day']:%Y-%m}", dk=dk, ws=self.days[dk]["ws"])
            self.rows.append(x)
        self.week_of = {d["ws"]: d["w"] for d in self.days}
        self.targets = Targets(T.get("budgets"), self.months)
        self.pivot_cols, self.sum_cols = metric_defs(self.has)
        self.label = {d["key"]: d["label"] for d in self.dims}

    def has_dim(self, k):
        return k in self.label

    def dim(self, k, label=None):
        return Dim(k, label or self.label.get(k, "미디어" if k == "m" else k), self.rank.get(k, {}))

    def default_dims(self, want):
        on = [k for k in want if self.has_dim(k)]
        return on or [d["key"] for d in self.dims[:1]]


def title_block(sh, ctx, c=2):
    h = ctx.report["header"]
    sh.set(2, c, f"{ctx.brand} | 종합 리포트", {"b": True, "sz": 14}, fit=False)
    sh.set(3, c, "Digital Campaign Report", {"b": True, "sz": 18}, fit=False)
    sh.set(4, c, f"집계 기간 {h['period']} · 미디어 {h['media'] or '-'}", {"fc": "595959"}, fit=False)
    sh.heights.update({2: 23, 3: 30})
    sh.widths[1] = 3


def sheet_summary(book, ctx):
    sh = book.sheet("Summary")
    title_block(sh, ctx)
    cols = ctx.sum_cols
    nb = sum(1 for c in cols if c[4] == "b")
    dims = [ctx.dim("m")] + [ctx.dim(k) for k in ctx.default_dims(["p", "t"])]
    D = len(dims)
    T = ctx.targets

    def x_of(rs, fixed, leaf):
        tg = T.of(rs, fixed) if fixed is not None else None
        return {"a": agg(rs), "tg": tg, "prog": T.prog(rs) if leaf and tg and tg.get("cost") else None}

    def heads(r, first):
        area = {"bg": C_AREA, "b": True, "al": "center", "bd": True}
        sh.set(r, 2, "기본 영역", area)
        for j in range(3, 2 + 1 + D + nb):
            sh.set(r, j, None, area)
        sh.merge(r, 2, r, 1 + 1 + D + nb)
        if len(cols) > nb:
            s0 = 2 + 1 + D + nb
            sh.set(r, s0, "목표 영역", area)
            for j in range(s0 + 1, s0 + len(cols) - nb):
                sh.set(r, j, None, area)
            sh.merge(r, s0, r, s0 + len(cols) - nb - 1)
        sh.heights[r] = 22
        head_row(sh, r + 1, 2, [first] + [d.label for d in dims] + [lb for _, lb, _, _, _ in cols])

    def block(r, rs, lead, lead_st):
        out, merges = tree(rs, dims, lambda lv: lv == 0 and D > 1, x_of)
        nxt = put_tree(sh, r, 2, out, merges, D, cols, lead_cols=1)
        for i in range(len(out)):
            sh.set(r + i, 2, lead if i == 0 else None, lead_st)
        if len(out) > 1:
            sh.merge(r, 2, nxt - 1, 2)
        return nxt

    # Total Summary — 캠페인명 칸 = 브랜드명(화면 입력란 기본값)
    section_title(sh, 6, 2, "■ Total Summary")
    heads(7, "캠페인명")
    r = block(9, ctx.rows, ctx.brand, {"bg": C_LEAD, "al": "center", "bd": True})
    put_total(sh, r, 2, 1 + D, x_of(ctx.rows, {}, False), cols, "Total 요약")

    # Monthly Summary — 달마다 블록 + 'N월 요약'
    r += 3
    section_title(sh, r, 2, "■ Monthly Summary")
    heads(r + 1, "월")
    r += 3
    for mo in ctx.months:
        rs = [x for x in ctx.rows if x["mo"] == mo["key"]]
        if not rs:
            continue
        r = block(r, rs, mo["label"], {"bg": C_LEAD, "al": "center", "bd": True, "b": True})
        put_total(sh, r, 2, 1 + D, x_of(rs, {}, False), cols, mo["label"] + " 요약", kind="msum")
        r += 1
    put_total(sh, r, 2, 1 + D, x_of(ctx.rows, {}, False), cols, "Total 요약")

    # Daily / Weekly Comment — 빌더가 규칙으로 만든 문장 그대로
    cm = ctx.report.get("comment")
    if cm:
        r += 3
        r = comment_lines(sh, r, cm)
    return sh


def comment_lines(sh, r, cm):
    tx = lambda rr, s, st=None: sh.set(rr, 2, s, st or {}, fit=False)  # noqa: E731
    d, w = cm["daily"], cm["weekly"]
    section_title(sh, r, 2, "■ Daily Comment")
    tx(r + 1, d["meta"], {"fc": "595959"})
    tx(r + 2, d["summary"])
    r += 3
    for it in d["items"]:
        tx(r, f"• {it['k']}: {it['v']}")
        r += 1
        for s in it.get("subs") or []:
            tx(r, f"      – {s['k']}: {s['v']}")
            r += 1
    tx(r, d["closing"])
    r += 3
    section_title(sh, r, 2, "■ Weekly Comment")
    tx(r + 1, w["meta"], {"fc": "595959"})
    r += 2
    for sec in w["sections"]:
        tx(r, f"{sec['h']} {sec['text']}", {"b": True})
        r += 1
        for g in sec["groups"]:
            tx(r, f"• {g['media']}: {g['summary']}")
            r += 1
            for b in g["bullets"]:
                tx(r, f"      – {b['k']}: {b['v']}")
                r += 1
    return r


def decode_place(ctx):
    """report["place"](열 기반) → 행 목록과 Dim들. 없으면 (None, None)."""
    PL = ctx.report.get("place")
    if not PL or not PL.get("n"):
        return None, None
    C, DIC = PL["cols"], PL["dict"]
    keys = ["m"] + [d["key"] for d in PL["dims"]]
    rows = []
    for i in range(PL["n"]):
        r = {k: DIC[k][C[k][i]] for k in keys}
        r.update(cost=C["cost"][i], imp=C["imp"][i], click=C["click"][i], view=C["view"][i])
        rows.append(r)
    rank = {k: {v: i for i, v in enumerate(vs)} for k, vs in DIC.items()}
    dims = [Dim("m", "미디어", rank["m"])] + [Dim(d["key"], d["label"], rank[d["key"]]) for d in PL["dims"]]
    return rows, dims


def sheet_media(book, ctx):
    sh = book.sheet("By Media")
    title_block(sh, ctx)
    cols = ctx.pivot_cols
    r = 6
    sh.set(5, 2, "전체 기간 · 전 매체 (화면의 월·미디어 필터 초기 상태)", {"fc": "595959"}, fit=False)
    m = ctx.dim("m")
    r = pivot_block(sh, r, 2, "■ Product", ctx.rows, [m] + [ctx.dim(k) for k in ctx.default_dims(["p"])], cols) + 2
    r = pivot_block(sh, r, 2, "■ Target", ctx.rows, [m] + [ctx.dim(k) for k in ctx.default_dims(["p", "t"])], cols) + 2
    if ctx.has_dim("cr"):   # 화면 Target 표의 디멘전 설정에서 '소재'를 고른 모양(예시 양식의 Creative)
        cdims = [m] + [ctx.dim(k) for k in ("p", "cr") if ctx.has_dim(k)]
        r = pivot_block(sh, r, 2, "■ Creative", ctx.rows, cdims, cols) + 2
    prow, pdims = decode_place(ctx)
    if prow:
        pivot_block(sh, r, 2, "■ Placement", prow, pdims, cols)
    else:
        section_title(sh, r, 2, "■ Placement")
        sh.set(r + 1, 2, "노출 위치 데이터 준비 중 — 이 브랜드 데이터에 노출 위치(placement) 차원이 아직 없습니다. "
                         "차원이 추가되면 다음 보고서부터 채워집니다.", {"fc": "808080"}, fit=False)
    return sh


def sheet_date(book, ctx):
    sh = book.sheet("By Date")
    title_block(sh, ctx)
    sh.set(5, 2, "전체 기간 · 전 매체 · 주 = ISO 주차(월~일)", {"fc": "595959"}, fit=False)
    cols = ctx.pivot_cols
    prod = [ctx.dim("p")] if ctx.has_dim("p") else []
    week = Dim("ws", "Week", sort=lambda k: k, fmt=lambda k: f"{ctx.week_of[k]}주차")
    day = Dim("dk", "일", sort=lambda k: k, fmt=lambda k: ctx.start.fromordinal(ctx.start.toordinal() + k))
    wd = [ctx.dim("m")] + prod + [week]
    pivot_block(sh, 6, 2, "■ Weekly", ctx.rows, wd, cols)
    c2 = 2 + len(wd) + len(cols) + 2
    pivot_block(sh, 6, c2, "■ Daily", ctx.rows, [ctx.dim("m")] + prod + [day], cols)
    for (r, c), (v, sid, f) in list(sh.cells.items()):   # 일 칸: 날짜 형식
        if isinstance(v, date) and c >= c2:
            st = {"bd": True, "al": "center", "fmt": F_DATE}
            sh.cells[(r, c)] = (v, book.styles.get(st), f)
    sh.widths[c2 - 1] = 3
    return sh


# ── Mix (화면 buildMix — 입력값 초기 상태) ────────────────────────────────────


def mix_lines(ctx):
    """MIX_LINES: 줄 = 캠페인 하나(캠페인 차원이 없으면 미디어 × 상품 × 광고그룹). 목표에만 있는 캠페인도 줄로 나온다.
    def = 월 예산 초기값(캠페인 목표 → 그 매체에 줄이 하나뿐이면 매체 목표) · CPM·CPC·VTR 초기값(캠페인 → 매체)."""
    T, rank = ctx.targets, ctx.rank
    mix_keys = ["m"] + [k for k in ("p", "t") if ctx.has_dim(k)]
    by_camp = ctx.has_dim("c")
    line_keys = ["m", "c"] if by_camp else mix_keys

    def join_vals(rs, k):
        vs = sorted(uniq(r[k] for r in rs), key=lambda v: rank[k].get(v, 1e9))
        return "·".join(vs[:3]) + f" 외 {len(vs) - 3}" if len(vs) > 3 else "·".join(vs)

    by = {}
    for r in ctx.rows:
        by.setdefault("\x01".join(r[k] for k in line_keys), []).append(r)
    lines = []
    for lid, rs in by.items():
        line = {"id": lid, "rows": rs}
        for k in line_keys:
            line[k] = rs[0][k]
        for k in mix_keys:
            if k not in line:
                line[k] = join_vals(rs, k)
        lines.append(line)
    if by_camp:   # 목표에만 있는 캠페인
        for b in T.B:
            sc = b["scope"]
            if sc.get("c") and sc.get("m") and len(sc) == 2:
                lid = sc["m"] + "\x01" + sc["c"]
                if lid in by:
                    continue
                by[lid] = []
                line = {"id": lid, "rows": [], "m": sc["m"], "c": sc["c"]}
                for k in mix_keys:
                    line.setdefault(k, "-")
                lines.append(line)

    def pick(line, keys):
        return {k: line[k] for k in keys if k in line}

    def alone(line, f):
        return sum(1 for l in lines if all(l.get(k) == f[k] for k in f)) == 1

    for line in lines:
        rs = line["rows"]
        scopes = []
        for f in ([pick(line, ["m", "c"]), pick(line, ["m"])] if by_camp else [pick(line, ["m", "p", "t"]), pick(line, ["m"])]):
            if f not in scopes:
                scopes.append(f)
        d = {"noView": not ctx.has.get("view") or (len(rs) > 0 and not any(r["view"] for r in rs))}
        for mo in ctx.months:
            v = None
            for f in scopes:
                if not alone(line, f):
                    continue
                v = T.lookup(mo["key"], f, "cost", rs)
                if v is not None:
                    break
            d[mo["key"]] = v if v is not None else (0 if any(r["mo"] == mo["key"] for r in rs) else None)
        for k in ("cpm", "cpc", "vtr"):
            v = None
            for f in scopes:
                for mo in ctx.months:
                    v = T.lookup(mo["key"], f, k, rs)
                    if v is not None:
                        break
                if v is not None:
                    break
            d[k] = v if v is not None else 0
        line["def"] = d
    return lines, mix_keys


def mix_val(l, months):
    d = l["def"]
    v = {mo["key"]: d[mo["key"]] for mo in months}
    v["cpm"], v["cpc"] = d["cpm"], d["cpc"]
    v["vtr"] = None if d["noView"] else d["vtr"]
    return v


def mix_calc(ls, months):
    a = {"b": 0, "imp": 0, "clk": 0, "view": 0, **{mo["key"]: 0 for mo in months}}
    for l in ls:
        v = mix_val(l, months)
        b = sum(v[mo["key"]] or 0 for mo in months)
        imp = b / v["cpm"] * 1000 if v["cpm"] else 0
        a["b"] += b
        for mo in months:
            a[mo["key"]] += v[mo["key"]] or 0
        a["imp"] += imp
        a["clk"] += b / v["cpc"] if v["cpc"] else 0
        if v["vtr"] is not None:
            a["view"] += imp * v["vtr"] / 100
    return a


def _sum_refs(col, rows):
    """같은 열의 행 번호들 → 'J12:J15,J17' (이어진 행은 범위로)."""
    rows = sorted(rows)
    parts, i = [], 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1] == rows[j] + 1:
            j += 1
        parts.append(f"{col}{rows[i]}" + (f":{col}{rows[j]}" if j > i else ""))
        i = j + 1
    return parts


def sheet_mix(book, ctx):
    sh = book.sheet("Mix")
    months, has = ctx.months, ctx.has
    lines, mix_keys = mix_lines(ctx)
    labels = {"m": "Media", "p": "Ad Type", "t": "타겟팅"}
    dims = [Dim(k, labels[k], ctx.rank.get(k, {})) for k in mix_keys]
    D = len(dims)
    mts = [("b", "예산")] + [(mo["key"], mo["label"]) for mo in months] + [
        ("imp", "Exp.Imps"), ("clk", "Exp.Clicks"), ("view", "Exp.VIEW"), ("ctr", "Exp.CTR"), ("vtr", "Exp.VTR"),
        ("cpm", "Exp.CPM"), ("cpc", "Exp.CPC"), ("cpv", "Exp.CPV")]
    mts = [(k, l) for k, l in mts if not (k in ("view", "vtr", "cpv") and not has.get("view"))
           and not (k in ("clk", "ctr", "cpc") and not has.get("click"))]
    c0 = 2
    col = {k: col_letter(c0 + D + i) for i, (k, _) in enumerate(mts)}
    cidx = {k: c0 + D + i for i, (k, _) in enumerate(mts)}
    mkeys = [mo["key"] for mo in months]

    # 정렬: 광고비 큰 순(이어 붙인 이름은 첫 이름 기준), 실적 없는 '-'는 뒤로
    def order(dim):
        def o(key):
            rk = dim.rank
            if key in rk:
                return rk[key]
            first = str(key).split("·")[0]
            return rk[first] + 0.5 if first in rk else 1e9
        return lambda keys: sorted(keys, key=lambda k: (o(k), str(k)))

    out, merges = [], []

    def walk(ls, level):
        dim = dims[level]
        keys = order(dim)(uniq(l[dim.key] for l in ls))
        leaves = []
        for k in keys:
            sub = [l for l in ls if l[dim.key] == k]
            if level == D - 1:
                out.append({"kind": "leaf", "level": level, "labels": {level: k}, "lines": sub})
                leaves.append(len(out) - 1)
                continue
            leaf_count = len(uniq("|".join(str(l[d.key]) for d in dims[level + 1:]) for l in sub))
            has_sub = level == 0 or (leaf_count > 1 and len(keys) > 1)   # Total 줄이 있는 묶음
            start = len(out)
            got = walk(sub, level + 1)
            out[start]["labels"][level] = k
            merges.append((start, len(out) - 1, level))
            leaves += got
            if has_sub:
                out.append({"kind": "sub", "level": level, "labels": {level: f"{k} Total"}, "lines": sub, "leaves": got})
        return leaves

    all_leaves = walk(lines, 0) if lines else []

    sh.set(2, 2, f"{ctx.brand} Media Mix", {"b": True, "sz": 18}, fit=False)
    sh.heights[2] = 30
    sh.widths[1] = 2
    r0 = 12   # 표 머리글 행 (위 4~9행 = Summary 칸)
    grand_r = r0 + 1 + len(out)
    section_title(sh, r0 - 1, 2, "■ Mix (목표 입력값 기준 월별 계획 · 필터 미적용)")
    head_row(sh, r0, c0, [d.label for d in dims] + [l for _, l in mts])
    sh.heights[r0] = 22

    cache = {}   # (행, 키) → 계산해 둔 값(수식 캐시)
    num = {"al": "right", "bd": True, "fmt": F_ACC}
    na = {"bd": True, "bg": C_NA}
    inp = dict(num, fc=C_INPUT, b=True)

    def put(r, k, v, st, f=None):
        cache[(r, k)] = v if isinstance(v, (int, float)) else 0
        sh.set(r, cidx[k], v, st, f=f)

    def common(vals, f):
        xs = uniq(v[f] for v in vals)
        return xs[0] if len(xs) == 1 else None

    def ratio_cells(r, kind_st, leaf):
        """CTR·CPV(줄) 또는 CTR·VTR·CPM·CPC·CPV(묶음) — 합친 값으로 다시 계산."""
        L = lambda k: f"{col[k]}{r}"  # noqa: E731
        b, imp = cache[(r, "b")], cache[(r, "imp")]
        clk, view = cache.get((r, "clk"), 0), cache.get((r, "view"), 0)
        specs = [("ctr", "clk", "imp", 1, F_P2), ("cpv", "b", "view", 1, F_ACC)]
        if not leaf:
            specs += [("vtr", "view", "imp", 1, F_P0), ("cpm", "b", "imp", 1000, F_ACC), ("cpc", "b", "clk", 1, F_ACC)]
        vals = {"b": b, "imp": imp, "clk": clk, "view": view}
        for k, n, d, mul, fmt in specs:
            if k not in col or d not in col or n not in col:
                continue
            v = vals[n] / vals[d] * mul if vals[d] else ""
            f = f'IF({L(d)}>0,{L(n)}/{L(d)}' + (f"*{mul}" if mul != 1 else "") + ',"")'
            sh.set(r, cidx[k], v, dict(kind_st, fmt=fmt), f=f)

    for i, row in enumerate(out):
        r = r0 + 1 + i
        kind, lv, ls = row["kind"], row["level"], row["lines"]
        for j in range(D):
            st = row_style("sub", lv) if kind == "sub" and j >= lv else label_style(j, D)
            sh.set(r, c0 + j, row["labels"].get(j), st)
        if kind == "sub" and lv < D - 1:
            sh.merge(r, c0 + lv, r, c0 + D - 1)
        if kind == "leaf":
            vals = [mix_val(l, months) for l in ls]
            a = mix_calc(ls, months)
            no_view = all(l["def"]["noView"] for l in ls)
            for mo in months:
                on = [l for l in ls if l["def"][mo["key"]] is not None]
                if not on:
                    put(r, mo["key"], None, na)
                elif len(on) == 1:
                    put(r, mo["key"], mix_val(on[0], months)[mo["key"]], inp)
                else:
                    put(r, mo["key"], a[mo["key"]], num)
            b = sum(cache[(r, k)] for k in mkeys)
            months_ref = ",".join(f"{col[k]}{r}" for k in mkeys)
            put(r, "b", b, num, f=f"SUM({months_ref})")
            # 단가 칸: 줄 안 캠페인 값이 같으면 그 값, 다르면 합친 예산 ÷ 예상치로 계산한 가중 값(예상치가 그대로 맞는다)
            cpm = common(vals, "cpm")
            cpm = cpm if cpm is not None else (a["b"] / a["imp"] * 1000 if a["imp"] else 0)
            put(r, "cpm", cpm, inp)
            imp = b / cpm * 1000 if cpm else 0
            put(r, "imp", imp, num, f=f'IF({col["cpm"]}{r}>0,{col["b"]}{r}/{col["cpm"]}{r}*1000,0)')
            if "cpc" in col:
                cpc = common(vals, "cpc")
                cpc = cpc if cpc is not None else (a["b"] / a["clk"] if a["clk"] else 0)
                put(r, "cpc", cpc, inp)
                put(r, "clk", b / cpc if cpc else 0, num, f=f'IF({col["cpc"]}{r}>0,{col["b"]}{r}/{col["cpc"]}{r},0)')
            if "vtr" in col:
                if no_view:
                    put(r, "vtr", None, na)
                    put(r, "view", None, na)
                else:
                    vtr = common(vals, "vtr")
                    vtr = vtr / 100 if vtr is not None else (a["view"] / a["imp"] if a["imp"] else 0)
                    put(r, "vtr", vtr, dict(inp, fmt=F_P0))
                    put(r, "view", imp * vtr, num, f=f'{col["imp"]}{r}*{col["vtr"]}{r}')
            ratio_cells(r, num, True)
            if "cpv" in col and no_view:
                sh.set(r, cidx["cpv"], None, na)
        row["r"] = r

    def group_row(r, leaf_rows, kind, lv):
        st = row_style(kind, lv, {"al": "right", "fmt": F_ACC})
        for k in ["b"] + mkeys + ["imp", "clk", "view"]:
            if k not in col:
                continue
            parts = _sum_refs(col[k], leaf_rows)
            v = sum(cache.get((x, k), 0) for x in leaf_rows)
            put(r, k, v, st, f=f"SUM({','.join(parts)})" if len(parts) <= 200 else None)
        ratio_cells(r, st, False)

    leaf_r = {i: row["r"] for i, row in enumerate(out)}
    for row in out:
        if row["kind"] == "sub":
            group_row(row["r"], [leaf_r[i] for i in row["leaves"]], "sub", row["level"])
    for s, e, lv in merges:
        if e > s:
            sh.merge(r0 + 1 + s, c0 + lv, r0 + 1 + e, c0 + lv)
    st = row_style("total", 0)
    sh.set(grand_r, c0, "Grand Total", st)
    for j in range(1, D):
        sh.set(grand_r, c0 + j, None, st)
    if D > 1:
        sh.merge(grand_r, c0, grand_r, c0 + D - 1)
    group_row(grand_r, [leaf_r[i] for i in all_leaves], "total", 0)

    # 머리 Summary 칸(예시 양식) — Grand Total 칸을 가리키는 수식
    g = {k: cache.get((grand_r, k), 0) for k in ("b", "imp", "clk", "view")}
    hd = {"bg": C_HEAD, "fc": "FFFFFF", "b": True, "al": "center", "bd": True}
    val = {"b": True, "al": "right", "bd": True, "fmt": F_INT}
    sh.set(4, 2, "Summary", {"b": True, "sz": 11}, fit=False)
    sh.set(5, 2, "Client", hd)
    sh.set(5, 3, ctx.brand, {"b": True, "al": "center", "bd": True}, fit=False)
    rr = 6
    for (n1, k1, v1), (n2, k2, v2) in ((("Budget", "b", g["b"]), ("Period", None, " · ".join(m["label"] for m in months))),
                                       (("Exp.Imps", "imp", g["imp"]), ("Exp.CPM", "cpm", _div(g["b"], g["imp"], 1000))),
                                       (("Exp.Click", "clk", g["clk"]), ("Exp.CPC", "cpc", _div(g["b"], g["clk"]))),
                                       (("Exp.View", "view", g["view"]), ("Exp.CPV", "cpv", _div(g["b"], g["view"])))):
        if k1 not in col:
            continue
        for cc, name, k, v in ((2, n1, k1, v1), (4, n2, k2, v2)):
            if k is not None and k not in col:
                continue
            sh.set(rr, cc, name, hd)
            if k is None:
                sh.set(rr, cc + 1, v, {"b": True, "al": "center", "bd": True}, fit=False)
            else:
                sh.set(rr, cc + 1, v if v is not None else "", val, f=f"{col[k]}{grand_r}", fit=False)
        rr += 1
    sh.set(5, 6, "NOTICE", {"b": True}, fit=False)
    for i, t in enumerate(("- 파란 글씨(월 예산·VTR·CPM·CPC)는 입력값입니다. 바꾸면 예산·예상 노출·클릭·조회가 다시 계산됩니다.",
                           "- 초기값 = 목표(get_target_progress_v2)의 캠페인 목표(없으면 매체 목표), 없으면 0. 회색 칸은 입력 불가입니다.",
                           "- 줄 = 화면 이름(Media · Ad Type · 타겟팅)이 같은 캠페인들의 합입니다. 예산·예상치는 기간 전체 합입니다.")):
        sh.set(6 + i, 6, t, fit=False)
    return sh


def sheet_raw(book, ctx):
    """표 데이터 원자 행(일 × 차원) — 실적이 전부 0인 행은 빌더가 이미 뺐다."""
    sh = book.sheet("Raw")
    keys = [d["key"] for d in ctx.dims]
    atoms = [("cost", "비용")] + [(k, l) for k, l in (("imp", "노출"), ("click", "클릭"), ("view", "조회")) if ctx.has.get(k)]
    head = ["일", "월", "Week", "미디어"] + [ctx.label[k] for k in keys] + [l for _, l in atoms]
    hst = {"bg": C_HEAD, "fc": "FFFFFF", "b": True, "al": "center", "bd": True}
    for j, t in enumerate(head):
        sh.set(1, 1 + j, t, hst)
    mlabel = {m["key"]: m["label"] for m in ctx.months}
    rk = ctx.rank
    rows = sorted(ctx.rows, key=lambda r: (r["dk"], rk["m"].get(r["m"], 0), *(rk[k].get(r[k], 0) for k in keys)))
    g = book.styles.get   # 행이 수만 개라 스타일 번호를 미리 받는다
    sd, sx, sp, sn = g({"fmt": F_DATE, "al": "center"}), g({"al": "center"}), g({}), g({"fmt": F_INT})
    for i, r in enumerate(rows):
        rr, fit = 2 + i, i < 500   # 열 너비는 앞 500행으로 잡는다
        sh.set(rr, 1, r["day"], sd, fit=fit)
        sh.set(rr, 2, mlabel.get(r["mo"], r["mo"]), sx, fit=fit)
        sh.set(rr, 3, f"{ctx.week_of[r['ws']]}주차", sx, fit=fit)
        sh.set(rr, 4, r["m"], sp, fit=fit)
        for j, k in enumerate(keys):
            sh.set(rr, 5 + j, r[k], sp, fit=fit)
        for j, (k, _) in enumerate(atoms):
            sh.set(rr, 5 + len(keys) + j, r[k], sn, fit=fit)
    sh.freeze = (2, 1)
    sh.autofilter = f"A1:{ref(1 + len(rows), len(head))}"
    return sh


SHEETS = {"summary": sheet_summary, "media": sheet_media, "date": sheet_date, "mix": sheet_mix, "raw": sheet_raw}


def write(report, rows, path, sheets=None):
    """빌더의 report·원자 행 → .xlsx. 표 데이터가 없으면 만들지 않는다(None).
    sheets: 담을 시트 키(SHEETS 순서로 쓴다) — 하위 스킬이 그 섹션 시트만 담을 때. 없으면 전부."""
    if not report.get("table") or not report["table"].get("n") or not rows:
        return None
    ctx = Ctx(report, rows)
    book = Book()
    for k, fn in SHEETS.items():
        if sheets is None or k in sheets:
            fn(book, ctx)
    return book.save(path)
