#!/usr/bin/env python3
"""Stage 2 of the peak-list build: match list members to OSM peaks and write
Data/bundle/lists.json.

Inputs : Data/_work/lists/members.json (fetch_list_members.py)
         Data/_work/peaks_all.tsv      (build_peaks.py)
Outputs: Data/bundle/lists.json, Data/_work/lists/report.json (+ printed report)
Python 3 stdlib only.
"""
import difflib
import json
import math
import os
import re
import unicodedata
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(HERE)
WORK = os.path.join(DATA, "_work", "lists")

TITLE_LANGS = ["en", "de", "fr", "it", "es", "pt-BR", "ja", "ko", "zh-Hans"]

LISTS = [
    {"id": "colorado-14ers", "region": "US-CO", "expected": 53,
     "source": "Membership: Wikipedia 'List of Colorado fourteeners' (53 ranked summits, >= 14,000 ft with >= 300 ft prominence; the 5 unranked sub-peaks of the commonly cited 58 are not included). Names/IDs: Wikidata (CC0). Positions: OpenStreetMap (ODbL).",
     "title": {"en": "Colorado Fourteeners", "de": "Viertausender (14ers) in Colorado",
               "fr": "Les « fourteeners » du Colorado", "it": "I fourteeners del Colorado",
               "es": "Los catorcemiles de Colorado", "pt-BR": "Os fourteeners do Colorado",
               "ja": "コロラド州のフォーティーナーズ", "ko": "콜로라도 포티너스",
               "zh-Hans": "科罗拉多州14000英尺高峰"}},
    {"id": "california-14ers", "region": "US-CA", "expected": 12,
     "source": "Membership: Wikipedia 'List of California 14,000-foot summits' (ranked summits). Names/IDs: Wikidata (CC0). Positions: OpenStreetMap (ODbL).",
     "title": {"en": "California Fourteeners", "de": "Viertausender (14ers) in Kalifornien",
               "fr": "Les « fourteeners » de Californie", "it": "I fourteeners della California",
               "es": "Los catorcemiles de California", "pt-BR": "Os fourteeners da Califórnia",
               "ja": "カリフォルニア州のフォーティーナーズ", "ko": "캘리포니아 포티너스",
               "zh-Hans": "加利福尼亚州14000英尺高峰"}},
    {"id": "munros", "region": "GB-SCT", "expected": 282,
     "source": "Membership: Wikidata items classified as Munro (P8450 = Q1320721), cross-checked with the SMC list via Wikipedia 'List of Munro mountains'. Heights: DoBIH via that table. Positions: OpenStreetMap (ODbL).",
     "title": {"en": "Scottish Munros", "de": "Munros in Schottland", "fr": "Les Munros d'Écosse",
               "it": "I Munro della Scozia", "es": "Los Munros de Escocia",
               "pt-BR": "Os Munros da Escócia", "ja": "スコットランドのマンロー",
               "ko": "스코틀랜드 먼로", "zh-Hans": "苏格兰芒罗山峰"}},
    {"id": "wainwrights", "region": "GB-ENG", "expected": 214,
     "source": "Membership and heights: the 214 fells of A. Wainwright's Pictorial Guides as tabulated in Wikipedia 'List of Wainwrights' (DoBIH). Names/IDs: Wikidata (CC0). Positions: OpenStreetMap (ODbL), checked against OS grid references.",
     "title": {"en": "The Wainwrights", "de": "Die Wainwrights im Lake District",
               "fr": "Les Wainwrights du Lake District", "it": "I Wainwright del Lake District",
               "es": "Los Wainwrights del Distrito de los Lagos",
               "pt-BR": "Os Wainwrights do Lake District", "ja": "ウェインライト（湖水地方の214峰）",
               "ko": "웨인라이트 (레이크 디스트릭트 214봉)", "zh-Hans": "温赖特214峰（湖区）"}},
    {"id": "alps-4000", "region": "Alps", "expected": 82,
     "source": "Membership and heights: UIAA official list of the 82 Alpine 4000 m summits (1994), as tabulated in Wikipedia 'List of mountains of the Alps over 4000 metres'. Names/IDs: Wikidata (CC0). Positions: OpenStreetMap (ODbL).",
     "title": {"en": "Alpine 4000ers", "de": "Viertausender der Alpen",
               "fr": "Sommets de plus de 4000 m des Alpes", "it": "I 4000 delle Alpi",
               "es": "Los cuatromiles de los Alpes", "pt-BR": "Os quatro mil dos Alpes",
               "ja": "アルプスの4000m峰", "ko": "알프스 4000m 봉우리", "zh-Hans": "阿尔卑斯山4000米高峰"}},
    {"id": "hyakumeizan", "region": "JP", "expected": 100,
     "source": "Membership: Wikidata items part of 100 Famous Japanese Mountains (P361 = Q1156761; Fukada Kyūya, 1964). Positions: highest summit of each mountain from OpenStreetMap (ODbL).",
     "title": {"en": "100 Famous Japanese Mountains", "de": "100 berühmte Berge Japans",
               "fr": "Les 100 montagnes célèbres du Japon", "it": "Le 100 montagne famose del Giappone",
               "es": "Las 100 montañas famosas de Japón", "pt-BR": "As 100 montanhas famosas do Japão",
               "ja": "日本百名山", "ko": "일본 100명산", "zh-Hans": "日本百名山"}},
    {"id": "taiwan-100", "region": "TW", "expected": 100,
     "source": "Membership and heights: Taiwan Top 100 Peaks (台灣百岳) as tabulated in zh.wikipedia '台灣百岳', cross-checked with Wikidata items linked to Q10915621. Names/IDs: Wikidata (CC0). Positions: OpenStreetMap (ODbL).",
     "title": {"en": "Taiwan Top 100 Peaks", "de": "Die 100 Gipfel Taiwans",
               "fr": "Les 100 sommets de Taïwan", "it": "Le 100 vette di Taiwan",
               "es": "Las 100 cumbres de Taiwán", "pt-BR": "Os 100 picos de Taiwan",
               "ja": "台湾百岳", "ko": "타이완 백악", "zh-Hans": "台湾百岳"}},
    {"id": "eight-thousanders", "region": "Himalaya-Karakoram", "expected": 14,
     "source": "Membership: Wikidata items classified as eight-thousander (P8450 = Q185552). Positions: OpenStreetMap (ODbL).",
     "title": {"en": "The Eight-thousanders", "de": "Die Achttausender", "fr": "Les quatorze 8000",
               "it": "Gli Ottomila", "es": "Los ochomiles", "pt-BR": "Os oito mil",
               "ja": "8000メートル峰", "ko": "8000미터급 고봉", "zh-Hans": "八千米级山峰"}},
    {"id": "seven-summits-messner", "region": "World", "expected": 7,
     "source": "Seven Summits, Messner list (Puncak Jaya / Carstensz Pyramid for Australia-Oceania). Wikidata (CC0); positions: OpenStreetMap (ODbL).",
     "title": {"en": "Seven Summits (Carstensz)", "de": "Seven Summits (Carstensz-Pyramide)",
               "fr": "Sept sommets (pyramide Carstensz)", "it": "Sette cime (Piramide Carstensz)",
               "es": "Siete cumbres (Pirámide de Carstensz)", "pt-BR": "Sete Cumes (Pirâmide Carstensz)",
               "ja": "七大陸最高峰（カルステンツ・ピラミッド）", "ko": "세계 7대륙 최고봉 (칼스텐츠 피라미드)",
               "zh-Hans": "七大洲最高峰（查亚峰）"}},
    {"id": "seven-summits-bass", "region": "World", "expected": 7,
     "source": "Seven Summits, Bass list (Mount Kosciuszko for Australia). Wikidata (CC0); positions: OpenStreetMap (ODbL).",
     "title": {"en": "Seven Summits (Kosciuszko)", "de": "Seven Summits (Mount Kosciuszko)",
               "fr": "Sept sommets (mont Kosciuszko)", "it": "Sette cime (Monte Kosciuszko)",
               "es": "Siete cumbres (monte Kosciuszko)", "pt-BR": "Sete Cumes (Monte Kosciuszko)",
               "ja": "七大陸最高峰（コジオスコ山）", "ko": "세계 7대륙 최고봉 (코지어스코산)",
               "zh-Hans": "七大洲最高峰（科修斯科山）"}},
]

# For items whose Wikidata entity is a massif / volcano group, the summit the
# list means (its highest point) carries a different name in OSM.
SUMMIT_HINTS = {
    "Q39231": ["剣ヶ峰"], "Q905588": ["赤岳"], "Q1157658": ["旭岳"],
    "Q656026": ["奥穂高岳"], "Q733710": ["高岳"], "Q3047571": ["大岳", "八甲田大岳"],
    "Q1319361": ["韓国岳"], "Q6921721": ["中岳"], "Q167951": ["熊野岳"],
    "Q2669374": ["西吾妻山"], "Q3695587": ["三本槍岳"], "Q2639098": ["御前峰"],
    "Q2977103": ["大汝山"], "Q279915": ["本白根山"], "Q415251": ["黒檜山"],
    "Q11608718": ["王ヶ頭"], "Q3695499": ["車山"], "Q3276672": ["万三郎岳"],
    "Q3139461": ["日出ヶ岳"], "Q3695432": ["観音岳"], "Q3133588": ["剣ヶ峰"],
    "Q1754806": ["剣ヶ峰"], "Q2744214": ["天狗岳"], "Q715498": ["剣ヶ峰", "弥山"],
    "Q1754619": ["女体山"], "Q3695989": ["八経ヶ岳", "八剣山"], "Q11545926": ["沖武尊", "武尊山"],
    "Q472705": ["雌阿寒岳"], "Q2620173": ["十勝岳"], "Q3075593": ["八幡平"],
    "Q7296": ["Uhuru Peak", "Kibo"], "Q43105": ["Elbrus", "Эльбрус", "West Summit"],
    "Q17189941": ["Mount Vinson", "Vinson"], "Q1045888": ["Puncak Jaya", "Carstensz Pyramid"],
}
# Hyakumeizan: Wikidata has both 大峰山 (Q3695989) and its top 八経ヶ岳
# (Q11391726) as parts of the list; they are the same entry in Fukada's book.
DROP = {"hyakumeizan": {"Q11391726"}}
# zh.wikipedia's 劍山 row resolves to the Wikidata item for the neighbouring
# 小劍山; match it by name instead.
OVERRIDES = {("taiwan-100", "劍山"): {"qid": None, "name_en": "Jian Mountain"},
             # Wikidata P625 of 合歡山 (Q714379) is the North Peak's position and
             # OSM carries Q714379 on the North Peak and 合歡尖山; the main peak
             # is OSM node 1660542386 (3417 m).
             ("taiwan-100", "合歡山"): {"ref_lat": 24.14261, "ref_lon": 121.27120},
             # Hyakumeizan: Wikidata's English labels name the volcano group /
             # massif; use the mountain names of Fukada's list, and keep
             # same-sounding entries apart.
             ("hyakumeizan", "Q905588"): {"name_en": "Mount Yatsugatake"},
             ("hyakumeizan", "Q656026"): {"name_en": "Mount Hotaka (Hotakadake)"},
             ("hyakumeizan", "Q11545926"): {"name_en": "Mount Hotaka (Hotakayama)"},
             ("hyakumeizan", "Q1157658"): {"name_en": "Mount Daisetsu"},
             ("hyakumeizan", "Q167951"): {"name_en": "Mount Zaō", "local": "蔵王山"},
             ("hyakumeizan", "Q6921721"): {"name_en": "Mount Kujū"},
             ("hyakumeizan", "Q3047571"): {"name_en": "Mount Hakkōda"},
             ("hyakumeizan", "Q1109050"): {"name_en": "Mount Tsurugi (Tsurugidake)"},
             ("hyakumeizan", "Q3695995"): {"name_en": "Mount Tsurugi (Tsurugisan)"},
             ("hyakumeizan", "Q31693466"): {"name_en": "Mount Asahi (Ōasahidake)"},
             ("hyakumeizan", "Q3695989"): {"name_en": "Mount Ōmine"},
             ("hyakumeizan", "Q3075593"): {"name_en": "Mount Hachimantai"},
             ("hyakumeizan", "Q11608718"): {"name_en": "Mount Utsukushigahara"},
             ("hyakumeizan", "Q3695492"): {"name_en": "Mount Ainodake"},
             ("eight-thousanders", "Q187138"): {"name_en": "Gasherbrum I"},
             ("eight-thousanders", "Q16466"): {"name_en": "Annapurna I"}}


def canon(s):
    """Spelling variants that should compare equal (ヶ/ケ/ヵ, 臺/台)."""
    return (s or "").replace("ヶ", "ケ").replace("ヵ", "ケ").replace("臺", "台").strip()


def norm(s):
    s = unicodedata.normalize("NFKD", canon(s))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("ß", "ss").replace("’", "'")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b(mount|mt|monte|mont|piz|pizzo|punta|pointe|pic|pico|cima|"
               r"the|peak|spitze|horn|berg|dent|aiguille|ben|beinn|sgurr|sgùrr|"
               r"pike|fell|crag)\b\.?", " ", s)
    s = re.sub(r"[^\w]+", " ", s)
    return " ".join(s.split())


def sim(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        # fall back to raw comparison (e.g. Japanese names are all \w)
        na, nb = canon(a).lower(), canon(b).lower()
        if not na or not nb:
            return 0.0
    if na == nb:
        return 1.0
    if len(na) >= 3 and len(nb) >= 3 and (na in nb or nb in na):
        return 0.9
    return difflib.SequenceMatcher(None, na, nb).ratio()


def hav(lat1, lon1, lat2, lon2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class PeakIndex:
    def __init__(self, path):
        self.grid = defaultdict(list)
        self.by_wd = defaultdict(list)
        n = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                c = line.rstrip("\n").split("\t")
                p = {"id": int(c[0]), "lat": float(c[1]), "lon": float(c[2]),
                     "ele": int(c[3]) if c[3] else None, "name": c[4],
                     "alt": c[5], "wd": c[6]}
                p["names"] = [p["name"]] + [x.split("=", 1)[1] for x in c[5].split("|") if "=" in x]
                self.grid[(int(math.floor(p["lat"] * 10)), int(math.floor(p["lon"] * 10)))].append(p)
                if p["wd"]:
                    self.by_wd[p["wd"]].append(p)
                n += 1
        self.n = n

    def near(self, lat, lon, radius_m):
        dlat = radius_m / 111000.0
        dlon = radius_m / (111000.0 * max(0.05, math.cos(math.radians(lat))))
        out = []
        for gi in range(int(math.floor((lat - dlat) * 10)), int(math.floor((lat + dlat) * 10)) + 1):
            for gj in range(int(math.floor((lon - dlon) * 10)), int(math.floor((lon + dlon) * 10)) + 1):
                for p in self.grid.get((gi, gj), ()):
                    d = hav(lat, lon, p["lat"], p["lon"])
                    if d <= radius_m:
                        out.append((d, p))
        return out


def member_names(m):
    names = []
    for k in ("name", "sub", "title"):
        if m.get(k):
            names.append(re.sub(r"\s*\(.*?\)\s*$", "", m[k]))
    if not m.get("sub"):
        names += list(m.get("wd", {}).get("labels", {}).values())
    return [n for n in dict.fromkeys(names) if n]


def ref_points(m):
    pts = []
    if m.get("ref_lat") is not None:
        pts.append((m["ref_lat"], m["ref_lon"], "list"))
    for la, lo in m.get("wd", {}).get("coords", []):
        pts.append((la, lo, "wikidata"))
    return pts


def wd_ele(m):
    eles = m.get("wd", {}).get("eles") or []
    return eles[0][0] if eles else None


def match(m, idx, region_bbox, used):
    """Return (osm_peak or None, method, notes). `used` = OSM ids already
    assigned within this list (each summit is used once)."""
    names = member_names(m)
    hints = SUMMIT_HINTS.get(m.get("qid"), [])
    pts = ref_points(m)
    precise = [(a, b) for a, b, src in pts if src == "list"]
    ref_ele = m.get("ref_ele") or wd_ele(m)
    is_sub = bool(m.get("sub"))
    notes = []

    def name_sim(p):
        s = max((sim(a, b) for a in names + hints for b in p["names"]), default=0)
        if hints and any(canon(h) == canon(nm) for h in hints for nm in p["names"]):
            s = max(s, 1.0)
        return s

    def ele_ok(p, tol):
        return ref_ele is None or p["ele"] is None or abs(p["ele"] - ref_ele) <= tol

    def near_pts(radius, points=None):
        out = {}
        for a, b in (points if points is not None else [(x, y) for x, y, _ in pts]):
            for d, p in idx.near(a, b, radius):
                if p["id"] in used:
                    continue
                if p["id"] not in out or d < out[p["id"]][0]:
                    out[p["id"]] = (d, p)
        return list(out.values())

    def best_named(cands, need, ele_tol=None):
        best = None
        for d, p in cands:
            s = name_sim(p)
            if s < need:
                continue
            if ele_tol is not None and not ele_ok(p, ele_tol):
                continue
            ele_pen = 0 if (ref_ele is None or p["ele"] is None) else min(abs(p["ele"] - ref_ele), 300) / 300
            score = s - d / 4000.0 - 0.3 * ele_pen
            if best is None or score > best[0]:
                best = (score, d, p, s)
        return best

    def dmin(p, points):
        return min((hav(a, b, p["lat"], p["lon"]) for a, b in points), default=1e12)

    allpts = [(a, b) for a, b, _ in pts]
    # A0. massif entries: the named highest summit (exact hint name)
    if hints and allpts:
        cands = [(d, p) for d, p in near_pts(15000)
                 if any(canon(h) == canon(nm) for h in hints for nm in p["names"])]
        if cands:
            d, p = max(cands, key=lambda x: ((x[1]["ele"] or -1e9), -x[0]))
            return p, "summit-hint", notes
    # A. OSM node carrying the same wikidata id (not for sub-summits, whose
    #    Wikidata item is the parent mountain)
    if not is_sub and m.get("qid") in idx.by_wd:
        cands = [p for p in idx.by_wd[m["qid"]] if p["id"] not in used]
        if allpts:
            cands = [p for p in cands if dmin(p, allpts) < 8000 and
                     (name_sim(p) >= 0.6 or dmin(p, allpts) < 600 or hints)]
        if precise:
            cands = [p for p in cands if dmin(p, precise) < 1500]
        cands = [p for p in cands if ele_ok(p, 100)]
        if cands:
            p = max(cands, key=lambda p: (p["ele"] or -1e9))
            if hints:
                hb = best_named(near_pts(8000, [(p["lat"], p["lon"])]), 0.99)
                if hb and (hb[2]["ele"] or 0) >= (p["ele"] or 0):
                    return hb[2], "wikidata-tag+summit-hint", notes
            return p, "osm-wikidata-tag", notes
    # B. precise list coordinate (OS grid ref / NGS position): summit at it
    if precise:
        cands = near_pts(400, precise)
        r = best_named(cands, 0.6, 60)
        if r:
            return r[2], "list-coord+name", notes
        cands = [(d, p) for d, p in cands if ref_ele and p["ele"] and abs(p["ele"] - ref_ele) <= 25]
        if cands:
            d, p = min(cands, key=lambda x: x[0])
            notes.append("matched by list coordinate+height (OSM name '%s')" % p["name"])
            return p, "list-coord+height", notes
    # C. name match near reference points
    tol = 30 if is_sub else None
    for radius, need in ((1500, 0.8), (4000, 0.85), (8000, 0.95 if not hints else 0.99)):
        r = best_named(near_pts(radius), need, tol)
        if r:
            return r[2], "name<=%dm" % radius, notes
    # D. exact name further away (coarse Wikidata coordinates, e.g. 白山)
    r = best_named(near_pts(30000), 0.99, 80)
    if r:
        notes.append("exact name %.1f km from reference coordinate" % (r[1] / 1000))
        return r[2], "exact-name<=30km", notes
    # E. nearest peak with matching height
    cands = [(d, p) for d, p in near_pts(600)
             if ref_ele and p["ele"] and abs(p["ele"] - ref_ele) <= (15 if is_sub else 40)]
    if cands:
        d, p = min(cands, key=lambda x: x[0])
        notes.append("matched by position+height only (OSM name '%s')" % p["name"])
        return p, "position+height", notes
    # F. no coordinates at all: search the list's region by name + height
    if not pts and region_bbox:
        s, w, n, e = region_bbox
        best = None
        for (gi, gj), ps in idx.grid.items():
            if not (s * 10 - 1 <= gi <= n * 10 and w * 10 - 1 <= gj <= e * 10):
                continue
            for p in ps:
                if p["id"] in used or not (s <= p["lat"] <= n and w <= p["lon"] <= e):
                    continue
                sc = name_sim(p)
                if sc < 0.85 or not ele_ok(p, 60):
                    continue
                key = (sc, -(abs((p["ele"] or 0) - (ref_ele or 0))))
                if best is None or key > best[0]:
                    best = (key, p)
        if best:
            notes.append("no reference coordinates; matched by name+height in region")
            return best[1], "region-name+height", notes
    return None, "unmatched", notes


REGION_BBOX = {"alps-4000": (43.5, 5.0, 47.5, 14.0), "wainwrights": (54.1, -3.6, 54.8, -2.6),
               "munros": (55.8, -7.0, 58.8, -2.8), "colorado-14ers": (36.9, -108.5, 40.6, -105.0),
               "california-14ers": (35.5, -119.5, 41.6, -117.5),
               "taiwan-100": (21.9, 120.0, 25.4, 122.1)}


def main():
    members = json.load(open(os.path.join(WORK, "members.json"), encoding="utf-8"))["lists"]
    idx = PeakIndex(os.path.join(DATA, "_work", "peaks_all.tsv"))
    print("OSM peaks loaded:", idx.n)
    out, report = [], {}
    for L in LISTS:
        lid = L["id"]
        rows = [m for m in members.get(lid, []) if m.get("qid") not in DROP.get(lid, set())]
        peaks, issues = [], []
        used = set()
        # most specific first: entries with precise list coordinates, then
        # main summits, then sub-summits
        order = sorted(rows, key=lambda m: (m.get("ref_lat") is None, bool(m.get("sub"))))
        for m in order:
            ov = OVERRIDES.get((lid, m.get("name"))) or OVERRIDES.get((lid, m.get("qid")))
            if ov:
                m = dict(m, **ov)
                if "qid" in ov and ov["qid"] is None:
                    m.pop("wd", None)
            p, how, notes = match(m, idx, REGION_BBOX.get(lid), used)
            if p:
                used.add(p["id"])
            labels = m.get("wd", {}).get("labels", {})
            name = m.get("name") if lid not in ("munros", "hyakumeizan", "eight-thousanders") \
                and not lid.startswith("seven") else None
            if lid == "munros" and m.get("wp_name"):
                name = m["wp_name"]  # SMC/DoBIH naming as in the list table
            name = name or labels.get("en") or (p["name"] if p else None) or m.get("title")
            name = re.sub(r"\s*\((mountain|Lake District|Colorado|California|peak)\)$", "", name or "")
            local = None
            if lid == "hyakumeizan":
                local = m.get("local") or labels.get("ja")
            if lid == "taiwan-100":
                local = m.get("name")
                name = labels.get("en") or m.get("name")
            ref_ele = m.get("ref_ele") or wd_ele(m)
            pts = ref_points(m)
            if p:
                lat, lon = p["lat"], p["lon"]
                dist = min((hav(a, b, lat, lon) for a, b, _ in pts), default=None)
                if dist is not None and dist > 1000:
                    notes.append("OSM summit %.0f m from reference coordinate" % dist)
                ele = ref_ele
                # list-table heights (DoBIH, UIAA, NGS, zh.wikipedia) are kept
                # unless >100 m off; Wikidata heights yield to OSM beyond 30 m
                if m.get("ref_ele") is None and p["ele"] is not None:
                    # no list-table height: OSM (mostly from national surveys)
                    # beats Wikidata, which mixes massif and rounded values
                    if ref_ele is not None and abs(p["ele"] - ref_ele) > 30:
                        notes.append("Wikidata ele %s vs OSM ele %s; using OSM" % (ref_ele, p["ele"]))
                    ele = p["ele"]
                elif p["ele"] is not None and ref_ele is not None and abs(p["ele"] - ref_ele) > 100:
                    notes.append("reference ele %s vs OSM ele %s; using OSM" % (ref_ele, p["ele"]))
                    ele = p["ele"]
                elif ele is None:
                    ele = p["ele"]
                if p["ele"] is None:
                    notes.append("OSM node has no ele")
            else:
                if not pts:
                    issues.append({"name": name, "qid": m.get("qid"), "problem": "no coordinates"})
                    continue
                lat, lon = pts[0][0], pts[0][1]
                ele = ref_ele
                notes.append("no OSM match; coordinates from %s" % pts[0][2])
            qid_out = m.get("qid")
            if m.get("sub"):
                qid_out = (p["wd"] or None) if p else None
            if m.get("name_en"):
                name = m["name_en"]
            entry = {"name": name, "local": local if local and local != name else None,
                     "lat": round(lat, 5), "lon": round(lon, 5),
                     "ele": int(round(ele)) if ele is not None else None,
                     "wikidata": qid_out, "osm_id": p["id"] if p else None}
            peaks.append(entry)
            if notes or how not in ("osm-wikidata-tag",):
                issues.append({"name": name, "qid": m.get("qid"), "method": how,
                               "osm": (p["name"], p["ele"]) if p else None, "notes": notes})
        peaks.sort(key=lambda x: -(x["ele"] or 0))
        out.append({"id": lid, "title": L["title"], "region": L["region"],
                    "source": L["source"], "peaks": peaks})
        report[lid] = {"expected": L["expected"], "count": len(peaks),
                       "matched_osm": sum(1 for x in peaks if x["osm_id"]),
                       "issues": issues}
        print("%-22s %3d/%3d peaks, %3d matched to OSM, %d notes" % (
            lid, len(peaks), L["expected"], report[lid]["matched_osm"],
            sum(1 for i in issues if i.get("notes") or i.get("problem"))))
    os.makedirs(os.path.join(DATA, "bundle"), exist_ok=True)
    with open(os.path.join(DATA, "bundle", "lists.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    with open(os.path.join(WORK, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
