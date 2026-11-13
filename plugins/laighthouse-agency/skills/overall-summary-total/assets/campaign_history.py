#!/usr/bin/env python3
"""캠페인 변경 이력(History) — `list_campaign_change_raw` 원본 행을 사람이 읽는 줄로 바꾼다(build_report.py가 import 한다).

원본은 매체가 준 그대로다(해석·분류·병합 없음):
  - 로그 매체: Google Ads `change_event` · Meta `activities` · TikTok `changelog` — 행 1개 = 매체 로그 1건.
  - 스냅샷 매체: 네이버 검색광고·카카오(모먼트·키워드) — 날마다 받은 캠페인/광고그룹 목록. 같은 대상의 연속한 두 날 값이
    다르면 그날 바뀐 것으로 본다(첫날은 기준이라 변경을 알 수 없다).
이 모듈이 규칙으로 줄을 만든다 — 모델이 원본을 읽거나 문장을 쓰지 않는다.

한 줄 = {"day": "YYYY-MM-DD", "m": 미디어, "lvl": 캠페인|광고그룹|광고|소재, "obj": 대상 이름, "kind": 변경 사항, "detail": 상세}
  - 변경 사항: 생성 · 삭제 · ON · OFF · 예산 증액/감액/변경 · 입찰 변경 · 타겟팅 변경 · 소재 교체 · 이름 변경 · 일정 변경 · 설정 변경
  - 같은 날·같은 대상·같은 변경은 한 줄로 묶는다(상세는 앞 3개 + '외 N건').
  - 매체가 스스로 남긴 기록(검수 상태·자동 타겟 등)과 계정 설정(사용자 권한 등)은 빼고 그 수만 알린다.
  - 대상 이름: 원본에 이름이 없으면(TikTok·Google) 성과 데이터(names: source·campaign_id·ad_group_id·ad_id와 이름)로 찾고,
    그래도 없으면 `ID 123…`으로 둔다.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
# 변경 이력 매체 키 → 미디어 이름(성과 데이터에 그 source가 있으면 그 이름을 쓴다)
SOURCE_LABEL = {"google_ads": "Google", "meta_ads": "Meta", "tiktok_ads": "TikTok", "naver_search_ads": "Naver Search Ads",
                "kakao_moment": "Kakao Moment", "kakao_keyword_ad": "Kakao Keyword"}
# 모델이 부를 스트림 — 스냅샷 매체는 광고·소재 목록을 빼고(행이 아주 많다) 캠페인·광고그룹만 받는다
STREAMS = ["change_event", "activities", "changelog", "campaigns", "campaign_detail", "adgroups", "ad_groups", "ad_group_detail"]
LEVELS = ("캠페인", "광고그룹", "광고", "소재")
MORE = 3   # 묶은 줄의 상세는 앞 3개만 적고 나머지는 '외 N건'


def _json(v):
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _num(v):
    """'20,000 KRW' · 20000 · '₩20,000' → 20000.0 (숫자가 없으면 None)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(v or ""))
    return float(m.group(0).replace(",", "")) if m else None


def _money(v):
    n = _num(v)
    return f"{round(n):,}" if n is not None else str(v)


def budget_kind(old, new):
    o, n = _num(old), _num(new)
    if o is None or n is None or o == n:
        return "예산 변경"
    return "예산 증액" if n > o else "예산 감액"


ON_WORDS = ("enable", "active", "활성", "on", "eligible", "live", "running", "운영", "집행")
OFF_WORDS = ("pause", "disable", "inactive", "비활성", "off", "중지", "stop", "lock", "꺼짐", "archived", "보관")


def on_off(v):
    """상태 값 → ON / OFF / None(알 수 없음). '비활성'을 '활성'보다 먼저 본다."""
    if isinstance(v, bool):
        return "OFF" if v else None
    s = str(v or "").strip().lower()
    if not s:
        return None
    if any(w in s for w in OFF_WORDS):
        return "OFF"
    if any(w in s for w in ON_WORDS):
        return "ON"
    return None


def _snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _path(obj, field):
    """Google 리소스(dict, snake_case 키)에서 changed_fields의 camelCase 경로 값을 꺼낸다."""
    cur = obj
    for seg in field.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(_snake(seg), cur.get(seg, cur.get(_snake(seg) + "_")))
    return cur


def _tail_id(resource):
    """'customers/1/campaigns/123' → '123', 'customers/1/adGroupAds/45~678' → '678'."""
    s = str(resource or "").rstrip("/")
    return s.rsplit("/", 1)[-1].rsplit("~", 1)[-1] if s else ""


class Names:
    """성과 데이터(names 봉투: source·media·campaign_id/name·ad_group_id/name·ad_id/name)로 ID → (미디어, 이름)."""

    def __init__(self, env):
        self.media = {}
        self.by = {"캠페인": {}, "광고그룹": {}, "광고": {}}
        for r in (env or {}).get("rows") or []:
            src, m = r.get("source"), r.get("media")
            if src and m:
                self.media.setdefault(str(src), str(m))
            for lvl, i, n in (("캠페인", "campaign_id", "campaign_name"), ("광고그룹", "ad_group_id", "ad_group_name"),
                              ("광고", "ad_id", "ad_name")):
                if r.get(i) not in (None, "") and r.get(n):
                    self.by[lvl].setdefault(str(r[i]), str(r[n]))

    def media_of(self, source):
        return self.media.get(source) or SOURCE_LABEL.get(source) or source

    def name(self, lvl, oid):
        if oid in (None, ""):
            return None
        oid = str(oid)
        for k in ([lvl] if lvl in self.by else []) + [k for k in self.by if k != lvl]:
            if oid in self.by[k]:
                return self.by[k][oid]
        return None


# ── 매체별 규칙 ──────────────────────────────────────────────────────────────


GOOGLE_LEVEL = (("ASSET", "소재"), ("AD_GROUP_AD", "광고"), ("AD_GROUP", "광고그룹"), ("CAMPAIGN", "캠페인"), ("AD", "광고"))


def google(row, names):
    ev = row.get("change_event") or row
    rtype = str(ev.get("change_resource_type") or "")
    op = str(ev.get("resource_change_operation") or "")
    lvl = next((v for k, v in GOOGLE_LEVEL if k in rtype), "캠페인")
    if rtype.endswith("_ASSET") and rtype != "ASSET":
        lvl = "소재"
    key = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), rtype.lower())   # AD_GROUP_AD → adGroupAd
    new = (ev.get("new_resource") or {})
    old = (ev.get("old_resource") or {})
    new = next(iter(new.values()), {}) if isinstance(new, dict) and len(new) == 1 else new.get(_snake(key), new)
    old = next(iter(old.values()), {}) if isinstance(old, dict) and len(old) == 1 else old.get(_snake(key), old)
    fields = [f.strip() for f in str(ev.get("changed_fields") or "").split(",") if f.strip()]
    when = str(ev.get("change_date_time") or "")[:10]
    # 대상: 소재는 자기 이름, 그 밖은 광고 → 광고그룹 → 캠페인 순으로 이름이 있는 것
    obj = None
    if lvl == "소재":
        obj = (new or {}).get("name") or (old or {}).get("name")
        if not obj:
            obj = names.name("캠페인", _tail_id(ev.get("campaign"))) or names.name("광고그룹", _tail_id(ev.get("ad_group")))
    else:
        rid = _tail_id(ev.get("change_resource_name"))
        obj = names.name(lvl, rid) or (new or {}).get("name") or (old or {}).get("name")
        if not obj and lvl != "캠페인":
            obj = names.name("광고그룹", _tail_id(ev.get("ad_group"))) or names.name("캠페인", _tail_id(ev.get("campaign")))
        obj = obj or (f"ID {rid}" if rid else None)
    base = {"day": when, "lvl": lvl, "obj": obj or "-"}
    if op == "CREATE":
        return [dict(base, kind="소재 추가" if lvl == "소재" else f"{lvl} 생성", detail="")]
    if op == "REMOVE":
        return [dict(base, kind=f"{lvl} 삭제", detail="")]
    out = []
    rest = []
    for f in fields:
        fl = f.lower()
        o, n = _path(old, f), _path(new, f)
        if fl.endswith("status"):
            s = on_off(n)
            out.append(dict(base, kind=f"{lvl} 삭제" if str(n).upper() == "REMOVED" else f"{lvl} {s}" if s else "상태 변경",
                            detail=f"{o} → {n}" if o or n else ""))
        elif "amount_micros" in _snake(f) or "budget" in fl:
            o2, n2 = (_num(o) or 0) / 1e6, (_num(n) or 0) / 1e6
            out.append(dict(base, kind=budget_kind(o2, n2), detail=f"{_money(o2)} → {_money(n2)}" if (o or n) else ""))
        elif "bid" in fl or "cpa" in fl or "roas" in fl:
            out.append(dict(base, kind="입찰 변경", detail=f"{f}: {o} → {n}"))
        elif fl.endswith("name") and lvl != "소재":
            out.append(dict(base, kind="이름 변경", detail=f"{o} → {n}"))
        elif "date" in fl:
            out.append(dict(base, kind="일정 변경", detail=f"{f}: {o} → {n}"))
        elif "CRITERION" in rtype:
            out.append(dict(base, kind="타겟팅 변경", detail=f))
        elif fl not in ("resource_name", "resourcename", "id"):
            rest.append(f)
    if rest and not out:
        out.append(dict(base, kind="타겟팅 변경" if "CRITERION" in rtype else "설정 변경", detail=", ".join(rest)))
    return out or [dict(base, kind="설정 변경", detail="")]


META_LEVEL = {"CAMPAIGN_GROUP": "캠페인", "CAMPAIGN": "광고그룹", "ADGROUP": "광고", "AD": "광고", "AD_SET": "광고그룹",
              "CREATIVE": "소재", "AD_CREATIVE": "소재"}


def meta(row, names):
    et = str(row.get("event_type") or "").lower()
    otype = str(row.get("object_type") or "").upper()
    if str(row.get("actor_id") or "") == "0" or not otype or et.startswith(("ad_account", "add_", "remove_user")):
        return None   # 매체가 스스로 남긴 기록·계정 설정
    lvl = META_LEVEL.get(otype, "캠페인")
    try:
        t = datetime.strptime(str(row.get("event_time")), "%Y-%m-%dT%H:%M:%S%z").astimezone(KST)
        day = f"{t:%Y-%m-%d}"
    except ValueError:
        day = None
    obj = row.get("object_name") or names.name(lvl, row.get("object_id")) or f"ID {row.get('object_id')}"
    x = _json(row.get("extra_data"))
    x = x if isinstance(x, dict) else {}
    o, n = x.get("old_value"), x.get("new_value")
    if isinstance(o, dict) or isinstance(n, dict):   # {"old_value": {...}} 모양 — 안의 값만
        o = (o or {}).get("value", o) if isinstance(o, dict) else o
        n = (n or {}).get("value", n) if isinstance(n, dict) else n
    label = str(row.get("translated_event_type") or et)
    base = {"day": day, "lvl": lvl, "obj": obj}
    vals = f"{o} → {n}" if o not in (None, "") or n not in (None, "") else ""
    if "run_status" in et or et.endswith("_status"):
        s = on_off(n)
        return [dict(base, kind=f"{lvl} {s}" if s else "상태 변경", detail=vals)]
    if "budget" in et or "spend_cap" in et:
        return [dict(base, kind=budget_kind(o, n), detail=f"{_money(o)} → {_money(n)}" if vals else "")]
    if "bid" in et:
        return [dict(base, kind="입찰 변경", detail=vals)]
    if "target" in et or "audience" in et:
        return [dict(base, kind="타겟팅 변경", detail=label)]
    if "creative" in et:
        return [dict(base, kind="소재 교체", detail=vals or label)]
    if et.endswith("_name"):
        return [dict(base, kind="이름 변경", detail=vals)]
    if et.startswith("create"):
        return [dict(base, kind=f"{lvl} 생성", detail="")]
    if et.startswith(("delete", "archive")):
        return [dict(base, kind=f"{lvl} 삭제", detail="")]
    if any(w in et for w in ("duration", "schedule", "start_time", "end_time", "run_time")):
        return [dict(base, kind="일정 변경", detail=vals)]
    return [dict(base, kind="설정 변경", detail=label + (f" ({vals})" if vals else ""))]


TIKTOK_LEVEL = {"campaign": "캠페인", "ad group": "광고그룹", "ad": "광고"}


def tiktok(row, names, seen_names):
    if "platform" in str(row.get("Source") or "").lower() or str(row.get("Object") or "") == "Review Status":
        return None   # 매체가 남긴 검수 상태 등
    lvl = TIKTOK_LEVEL.get(str(row.get("log_object_type") or "").strip().lower(), "캠페인")
    oid = str(row.get("Object ID") or "")
    obj = names.name(lvl, oid) or seen_names.get(oid) or (f"ID {oid}" if oid else "-")
    cat = str(row.get("Object") or "")
    base = {"day": str(row.get("Time") or "")[:10], "lvl": lvl, "obj": obj}
    acts = _json(row.get("Activity details"))
    out = []
    for a in acts if isinstance(acts, list) else []:
        action = str(a.get("action") or "").strip().lower()
        name = str(a.get("name") or "")
        ba = (a.get("before_after") or [{}])[0] or {}
        o, n = ba.get("before"), ba.get("after")
        vals = f"{o} → {n}" if o not in (None, "") else str(n or "")
        if action == "create":
            out.append(dict(base, kind=f"{lvl} 생성", detail=""))
        elif action == "delete":
            out.append(dict(base, kind=f"{lvl} 삭제", detail=""))
        elif cat == "Creative":
            s = on_off(n)
            out.append(dict(base, kind=f"소재 {s}" if s else "소재 교체", detail=name))
        elif cat == "On/Off Status" or name in ("Campaign", "Ad group", "Ad") and on_off(n):
            s = on_off(n)
            out.append(dict(base, kind=f"{lvl} {s}" if s else "상태 변경", detail=vals))
        elif "budget" in name.lower():
            kind = "예산 변경 예약" if "scheduled" in name.lower() else budget_kind(o, n)
            out.append(dict(base, kind=kind, detail=vals))
        elif name == "Name":
            out.append(dict(base, kind="이름 변경", detail=vals))
        elif cat == "Budget & Schedule" or any(w in name.lower() for w in ("schedule", "time", "date")):
            out.append(dict(base, kind="일정 변경", detail=f"{name}: {vals}"))
        elif "bid" in (cat + name).lower() or "optimiz" in (cat + name).lower():
            out.append(dict(base, kind="입찰 변경", detail=f"{name}: {vals}"))
        elif "target" in (cat + name).lower() or "audience" in (cat + name).lower():
            out.append(dict(base, kind="타겟팅 변경", detail=f"{name}: {vals}" if vals else name))
        else:
            out.append(dict(base, kind="설정 변경", detail=f"{name}: {vals}" if vals else name))
    return out


# 스냅샷 매체(네이버·카카오): 같은 대상의 연속한 날 값 비교
# 대상 ID 키 — 단계마다 자기 ID를 먼저 본다(광고그룹 행에도 부모 캠페인 ID가 들어 있다)
SNAP_ID = {"캠페인": ("nccCampaignId", "campaignId", "id"), "광고그룹": ("nccAdgroupId", "adGroupId", "adgroupId", "id"),
           "광고": ("nccAdId", "adId", "creativeId", "id")}
SNAP_NAME = ("name", "campaignName", "adGroupName", "adgroupName")


def snap_level(stream):
    s = stream.lower()
    return "광고그룹" if "group" in s else "캠페인" if "campaign" in s else "광고"


def snap_field(k):
    kl = k.lower()
    if kl in ("userlock", "config", "onoff", "status", "state") or kl.endswith(("status", "lock")):
        return "status"
    if "budget" in kl:
        return "budget"
    if "bid" in kl:
        return "bid"
    if kl in ("name", "campaignname", "adgroupname"):
        return "name"
    if any(w in kl for w in ("startdate", "enddate", "starttime", "endtime", "schedule")):
        return "schedule"
    return None


def _flat(row, prefix=""):
    out = {}
    for k, v in (row or {}).items():
        if isinstance(v, dict):
            out.update(_flat(v, prefix + k + "."))
        else:
            out[prefix + k] = v
    return out


def snapshots(items, names):
    """[(source, stream, dt, row)] → 변경 줄. 첫날 대상은 기준(변경 없음), 그 뒤 처음 나온 대상은 생성."""
    groups = {}
    for src, stream, dt, row in items:
        flat = _flat(row)
        oid = next((str(flat[k]) for k in SNAP_ID[snap_level(stream)] if flat.get(k) not in (None, "")), None)
        if not oid:
            continue
        groups.setdefault((src, stream), {}).setdefault(oid, []).append((dt, flat))
    out = []
    for (src, stream), objs in groups.items():
        lvl = snap_level(stream)
        first_day = min(dt for snaps in objs.values() for dt, _ in snaps)
        for oid, snaps in objs.items():
            snaps.sort(key=lambda x: x[0])
            nm = lambda f: next((str(f[k]) for k in SNAP_NAME if f.get(k)), None)  # noqa: E731
            obj = names.name(lvl, oid) or nm(snaps[-1][1]) or f"ID {oid}"
            if snaps[0][0] > first_day:
                out.append({"src": src, "day": snaps[0][0], "lvl": lvl, "obj": obj, "kind": f"{lvl} 생성", "detail": ""})
            for (_, a), (dt, b) in zip(snaps, snaps[1:]):
                for k in sorted(set(a) | set(b)):
                    f = snap_field(k.rsplit(".", 1)[-1])
                    o, n = a.get(k), b.get(k)
                    if not f or o == n:
                        continue
                    base = {"src": src, "day": dt, "lvl": lvl, "obj": obj}
                    if f == "status":
                        if k.lower().endswith("lock") and isinstance(n, bool):   # 네이버 userLock: true = 꺼 둠
                            s, o, n = ("OFF" if n else "ON"), ("OFF" if o else "ON"), ("OFF" if n else "ON")
                        else:
                            s = on_off(n)
                        out.append(dict(base, kind=f"{lvl} {s}" if s else "상태 변경", detail=f"{o} → {n}"))
                    elif f == "budget":
                        out.append(dict(base, kind=budget_kind(o, n), detail=f"{_money(o)} → {_money(n)}"))
                    elif f == "bid":
                        out.append(dict(base, kind="입찰 변경", detail=f"{_money(o)} → {_money(n)}"))
                    elif f == "name":
                        out.append(dict(base, kind="이름 변경", detail=f"{o} → {n}"))
                    else:
                        out.append(dict(base, kind="일정 변경", detail=f"{k}: {o} → {n}"))
    return out


# ── 조립 ─────────────────────────────────────────────────────────────────────


def build(items, names_env, start, end):
    """원본 items(list_campaign_change_raw의 items 합) → {"rows": [...], "n": 원본 건수, "skipped": 뺀 건수, "media": [...]}.
    start·end(date): 집계 기간 — 그 밖의 날짜는 버린다."""
    names = Names(names_env)
    rows, skipped, snaps = [], 0, []
    seen_names = {}
    for it in items:   # TikTok 이름 변경 로그의 새 이름 → 그 ID의 이름
        r = it.get("row") or {}
        if it.get("source") == "tiktok_ads" and r.get("Object") == "Settings":
            for a in _json(r.get("Activity details")) or []:
                if isinstance(a, dict) and a.get("name") == "Name":
                    ba = (a.get("before_after") or [{}])[0] or {}
                    if ba.get("after"):
                        seen_names.setdefault(str(r.get("Object ID")), str(ba["after"]))
    for it in items:
        src, stream, row = str(it.get("source") or ""), str(it.get("stream") or ""), it.get("row") or {}
        if src == "google_ads":
            got = google(row, names)
        elif src == "meta_ads":
            got = meta(row, names)
        elif src == "tiktok_ads":
            got = tiktok(row, names, seen_names)
        else:
            snaps.append((src, stream, str(it.get("dt") or "")[:10], row))
            continue
        if got is None:
            skipped += 1
            continue
        for g in got:
            g["src"] = src
            g["day"] = g.get("day") or str(it.get("dt") or "")[:10]
        rows += got
    rows += snapshots(snaps, names)
    keep = []
    for r in rows:
        try:
            d = date.fromisoformat(r["day"])
        except (TypeError, ValueError):
            continue
        if start <= d <= end:
            r["m"] = names.media_of(r.pop("src"))
            keep.append(r)
    merged = {}
    for r in keep:
        if r["lvl"] == "소재":   # 소재는 이름이 대상마다 달라 줄이 길어진다 — 같은 날·같은 변경을 한 줄로, 이름은 상세로
            r["detail"], r["obj"] = r["obj"] if not r["detail"] else f"{r['obj']}: {r['detail']}", ""
        k = (r["day"], r["m"], r["lvl"], r["obj"], r["kind"])
        e = merged.setdefault(k, {**r, "details": [], "count": 0})
        e["count"] += 1
        if r["detail"] and r["detail"] not in e["details"]:
            e["details"].append(r["detail"])
    out = []
    for e in merged.values():
        ds = e.pop("details")
        e["detail"] = ", ".join(ds[:MORE]) + (f" 외 {len(ds) - MORE}건" if len(ds) > MORE else "")
        if e["lvl"] == "소재" and not e["obj"]:
            e["obj"] = f"소재 {e['count']}개"
        out.append(e)
    lv = {v: i for i, v in enumerate(LEVELS)}
    out.sort(key=lambda r: (r["day"], r["m"], lv.get(r["lvl"], 9), r["obj"], r["kind"]))
    return {"rows": out, "n": len(items), "skipped": skipped, "media": list(dict.fromkeys(r["m"] for r in out))}
