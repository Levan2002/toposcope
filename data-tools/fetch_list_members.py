#!/usr/bin/env python3
"""Stage 1 of the peak-list build: collect list membership + reference facts.

Sources
  * Wikidata (CC0) via query.wikidata.org SPARQL: list membership where
    Wikidata models it (Munros, eight-thousanders, 100 Famous Japanese
    Mountains, Seven Summits), plus labels / coordinates / elevations for
    every member item.
  * Wikipedia list pages, used only to establish which summits belong to a
    list (and as a cross-check of heights / grid references); no prose is
    copied.

Writes Data/_work/lists/members.json (consumed by build_lists.py).
Python 3 stdlib only.
"""
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(HERE)
WORK = os.path.join(DATA, "_work", "lists")
UA = "Toposcope-data-pipeline/1.0 (peak list build; python-urllib)"
LANGS = ["en", "de", "fr", "it", "es", "pt", "ja", "ko", "zh-hans", "zh", "zh-hant", "zh-tw"]


def http_get(url, params=None, accept=None, tries=10):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h),
                                        timeout=120) as r:
                return r.read().decode("utf-8")
        except Exception as ex:  # noqa: BLE001 - retry anything transient
            wait = 65 if "429" in str(ex) else 5 * (2 ** i)
            print("  retry %s in %ds: %s" % (url[:80], wait, ex), file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("failed: " + url)


def cached(name, fn):
    p = os.path.join(WORK, name)
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    txt = fn()
    with open(p, "w", encoding="utf-8") as f:
        f.write(txt)
    return txt


def sparql(q, cache_name):
    txt = cached(cache_name, lambda: http_get(
        "https://query.wikidata.org/sparql", {"query": q},
        accept="application/sparql-results+json"))
    return json.loads(txt)["results"]["bindings"]


def wikitext(title):
    fn = "wp_" + re.sub(r"[^A-Za-z0-9]+", "_", title) + ".wikitext"
    return cached(fn, lambda: (time.sleep(2), http_get(
        "https://en.wikipedia.org/w/index.php",
        {"title": title, "action": "raw"}))[1])


def qid(uri):
    return uri.rsplit("/", 1)[-1]


# ---------------------------------------------------------------- OS grid
def osgrid_to_wgs84(ref):
    """6/8/10-figure OS grid reference (e.g. NY215072) -> (lat, lon) WGS84."""
    ref = ref.replace(" ", "").upper()
    l1 = ord(ref[0]) - ord("A")
    l2 = ord(ref[1]) - ord("A")
    if l1 > 7:
        l1 -= 1
    if l2 > 7:
        l2 -= 1
    e100 = ((l1 - 2) % 5) * 5 + (l2 % 5)
    n100 = (19 - (l1 // 5) * 5) - (l2 // 5)
    digits = ref[2:]
    half = len(digits) // 2
    scale = 10 ** (5 - half)
    E = e100 * 100000 + int(digits[:half]) * scale + scale / 2
    N = n100 * 100000 + int(digits[half:]) * scale + scale / 2
    # inverse transverse Mercator on Airy 1830
    a, b = 6377563.396, 6356256.909
    F0, lat0, lon0 = 0.9996012717, math.radians(49), math.radians(-2)
    N0, E0 = -100000, 400000
    e2 = 1 - (b * b) / (a * a)
    n = (a - b) / (a + b)
    lat, M = lat0, 0
    while True:
        lat = (N - N0 - M) / (a * F0) + lat
        Ma = (1 + n + 5 / 4 * n ** 2 + 5 / 4 * n ** 3) * (lat - lat0)
        Mb = (3 * n + 3 * n ** 2 + 21 / 8 * n ** 3) * math.sin(lat - lat0) * math.cos(lat + lat0)
        Mc = (15 / 8 * n ** 2 + 15 / 8 * n ** 3) * math.sin(2 * (lat - lat0)) * math.cos(2 * (lat + lat0))
        Md = 35 / 24 * n ** 3 * math.sin(3 * (lat - lat0)) * math.cos(3 * (lat + lat0))
        M = b * F0 * (Ma - Mb + Mc - Md)
        if abs(N - N0 - M) < 0.00001:
            break
    s, c = math.sin(lat), math.cos(lat)
    nu = a * F0 / math.sqrt(1 - e2 * s * s)
    rho = a * F0 * (1 - e2) / (1 - e2 * s * s) ** 1.5
    eta2 = nu / rho - 1
    t = math.tan(lat)
    VII = t / (2 * rho * nu)
    VIII = t / (24 * rho * nu ** 3) * (5 + 3 * t * t + eta2 - 9 * t * t * eta2)
    IX = t / (720 * rho * nu ** 5) * (61 + 90 * t * t + 45 * t ** 4)
    X = 1 / (c * nu)
    XI = 1 / (c * 6 * nu ** 3) * (nu / rho + 2 * t * t)
    XII = 1 / (c * 120 * nu ** 5) * (5 + 28 * t * t + 24 * t ** 4)
    XIIA = 1 / (c * 5040 * nu ** 7) * (61 + 662 * t * t + 1320 * t ** 4 + 720 * t ** 6)
    dE = E - E0
    phi = lat - VII * dE ** 2 + VIII * dE ** 4 - IX * dE ** 6
    lam = lon0 + X * dE - XI * dE ** 3 + XII * dE ** 5 - XIIA * dE ** 7
    # OSGB36 -> WGS84 Helmert
    nu = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    x = nu * math.cos(phi) * math.cos(lam)
    y = nu * math.cos(phi) * math.sin(lam)
    z = (1 - e2) * nu * math.sin(phi)
    tx, ty, tz = 446.448, -125.157, 542.060
    s_ = -20.4894e-6
    rx, ry, rz = [math.radians(v / 3600) for v in (0.1502, 0.2470, 0.8421)]
    x2 = tx + (1 + s_) * x - rz * y + ry * z
    y2 = ty + rz * x + (1 + s_) * y - rx * z
    z2 = tz - ry * x + rx * y + (1 + s_) * z
    a2, b2 = 6378137.0, 6356752.314245
    e22 = 1 - (b2 * b2) / (a2 * a2)
    p = math.sqrt(x2 * x2 + y2 * y2)
    phi2 = math.atan2(z2, p * (1 - e22))
    for _ in range(10):
        nu2 = a2 / math.sqrt(1 - e22 * math.sin(phi2) ** 2)
        phi2 = math.atan2(z2 + e22 * nu2 * math.sin(phi2), p)
    return math.degrees(phi2), math.degrees(math.atan2(y2, x2))


# ---------------------------------------------------------------- wikitext
def first_link(cell):
    for m in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]", cell):
        t = m.group(1).strip()
        if t.split(":")[0].lower() in ("file", "image", "category"):
            continue
        return t, (m.group(2) or t).strip()
    return None, None


def num(s):
    s = re.sub(r"<[^>]+>|\{\{[^}]*\}\}", "", s or "")
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s)
    return float(m.group(0).replace(",", "")) if m else None


def table_after(text, heading_regex):
    m = re.search(heading_regex, text)
    start = text.index("{|", m.start() if m else 0)
    end = text.index("\n|}", start)
    return text[start:end]


def rows(table):
    return [r for r in re.split(r"\n\|-[^\n]*", table)[1:] if r.strip()]


def parse_alps(text):
    out = []
    for r in rows(table_after(text, r"==\s*Official list\s*==")):
        lines = [l for l in r.split("\n") if l.startswith("|")]
        if len(lines) < 4:
            continue
        rank = num(lines[0].split("|")[-1])
        title, disp = first_link(lines[2])
        if not title:
            disp = re.sub(r"\{\{[^}]*\}\}|<[^>]+>|^\|", "", lines[2]).strip()
        ele = num(lines[3].split("|")[-1])
        name = re.sub(r"\s*\(.*?\)$", "", disp)
        row = {"rank": int(rank) if rank else None, "title": title,
               "name": name, "ref_ele": ele}
        # sub-summits share their parent's article: "[[Grandes Jorasses]]<br />(Pointe Croz)"
        sm = re.search(r"<br\s*/?>\s*\(([^)]*)\)", re.sub(r"<ref.*", "", lines[2]))
        if sm:
            sub = sm.group(1).split("/")[0].strip()
            row["sub"] = sub
            if re.search(r"summit|twin|gendarm", sub, re.I):
                g = {"eastern summit": "East", "western summit": "West",
                     "central summit": "Central", "gendarm": "Gendarm"}.get(sub.lower(), sub)
                row["name"] = name if name.startswith("Eastern ") else "%s %s" % (name, g)
            else:
                row["name"] = sub
            row["parent"] = name
        out.append(row)
    return out


def parse_mtc(text, heading_regex):
    out = []
    for r in rows(table_after(text, heading_regex)):
        m = re.search(r"\{\{Mountain table cell\|([^|}]+)([^}]*)\}\}", r)
        if not m:
            continue
        title = m.group(1).strip()
        nm = re.search(r"\|name=([^|}]+)", m.group(2))
        e = re.search(r"\{\{epi\|([\d.]+)", r)
        c = re.search(r"\{\{coord\|(-?[\d.]+)\|(-?[\d.]+)", r)
        out.append({"title": title,
                    "name": nm.group(1).strip() if nm else re.sub(r"\s*\(.*?\)$", "", title),
                    "ref_ele": float(e.group(1)) if e else None,
                    "ref_lat": float(c.group(1)) if c else None,
                    "ref_lon": float(c.group(2)) if c else None})
    return out


def parse_dobih(text, heading_regex, name_col, ele_col):
    """Wainwright / Munro tables: '|| a || b ||' rows with an OS grid ref."""
    out = []
    for r in rows(table_after(text, heading_regex)):
        line = " ".join(l for l in r.split("\n") if l.startswith("|"))
        cells = [c.strip() for c in line.lstrip("|").split("||")]
        if len(cells) <= ele_col:
            continue
        title, disp = first_link(cells[name_col])
        g = re.search(r"\b([HNOST][A-HJ-Z])\s?(\d{3,5}\s?\d{3,5})\b", line)
        lat = lon = None
        if g and len(g.group(2).replace(" ", "")) % 2 == 0:
            lat, lon = osgrid_to_wgs84(g.group(1) + g.group(2).replace(" ", ""))
        out.append({"title": title, "name": disp, "ref_ele": num(cells[ele_col]),
                    "ref_lat": lat, "ref_lon": lon,
                    "gridref": g.group(0).replace(" ", "") if g else None})
    return out


def titles_to_qids(titles, wiki="en"):
    res = {}
    titles = [t for t in titles if t]
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        txt = http_get("https://%s.wikipedia.org/w/api.php" % wiki, {
            "action": "query", "titles": "|".join(chunk), "redirects": 1,
            "prop": "pageprops", "ppprop": "wikibase_item", "format": "json"})
        d = json.loads(txt)["query"]
        norm = {x["from"]: x["to"] for x in d.get("normalized", [])}
        redir = {x["from"]: x["to"] for x in d.get("redirects", [])}
        by_title = {p["title"]: p.get("pageprops", {}).get("wikibase_item")
                    for p in d["pages"].values()}
        for t in chunk:
            t2 = norm.get(t, t)
            t2 = redir.get(t2, t2)
            res[t] = by_title.get(t2)
        time.sleep(2)
    return res


def _absorb(out, b, kind, wanted):
    q = qid(b["s"]["value"])
    if q not in wanted:
        return
    d = out.setdefault(q, {"labels": {}})
    if kind == "labels":
        d["labels"][b["lang"]["value"]] = b["label"]["value"]
        return
    if "coord" in b:
        m = re.match(r"Point\((-?[\d.eE-]+) (-?[\d.eE-]+)\)", b["coord"]["value"])
        if m:
            c = (float(m.group(2)), float(m.group(1)))
            if c not in d.setdefault("coords", []):
                d["coords"].append(c)
    if "amount" in b:
        amt = float(b["amount"]["value"])
        unit = qid(b["unit"]["value"])
        if unit == "Q3710":
            amt *= 0.3048
        elif unit != "Q11573":
            return
        pref = b["rank"]["value"].endswith("PreferredRank")
        e = (round(amt, 1), pref)
        if e not in d.setdefault("eles", []):
            d["eles"].append(e)


def wd_details(qids, prefix="wd"):
    """labels + coordinates + elevation (metres) for a set of Q-ids."""
    out = {}
    qids = sorted(set(q for q in qids if q))
    # Reuse every cached detail response (cache files are keyed by a hash of
    # the Q-id chunk), so adding list members only queries the new items.
    seen = set()
    for fn in sorted(os.listdir(WORK)):
        if re.match(r"(wd|tw)_(labels|geo)_.*\.json$", fn):
            for b in json.load(open(os.path.join(WORK, fn)))["results"]["bindings"]:
                seen.add(qid(b["s"]["value"]))
    cached_files = [fn for fn in sorted(os.listdir(WORK))
                    if re.match(r"(wd|tw)_(labels|geo)_.*\.json$", fn)]
    todo = [q for q in qids if q not in seen]
    chunks = [("c", cached_files)] + [("q", todo[i:i + 150]) for i in range(0, len(todo), 150)]
    for kind, chunk in chunks:
        if kind == "c":
            for fn in chunk:
                for b in json.load(open(os.path.join(WORK, fn)))["results"]["bindings"]:
                    _absorb(out, b, fn.split("_")[1], set(qids))
            continue
        i = hashlib.sha1(" ".join(chunk).encode()).hexdigest()[:10]
        values = " ".join("wd:" + q for q in chunk)
        q = """SELECT ?s ?lang ?label WHERE { VALUES ?s { %s }
               ?s rdfs:label ?label . BIND(lang(?label) AS ?lang)
               FILTER(?lang IN (%s)) }""" % (
            values, ",".join('"%s"' % l for l in LANGS))
        for b in sparql(q, "%s_labels_%s.json" % (prefix, i)):
            _absorb(out, b, "labels", set(qids))
        q = """SELECT ?s ?coord ?amount ?unit ?rank WHERE { VALUES ?s { %s }
               OPTIONAL { ?s p:P625 ?cs . ?cs ps:P625 ?coord . ?cs wikibase:rank ?crank .
                          FILTER(?crank != wikibase:DeprecatedRank) }
               OPTIONAL { ?s p:P2044 ?st . ?st psv:P2044 ?v . ?v wikibase:quantityAmount ?amount .
                          ?v wikibase:quantityUnit ?unit . ?st wikibase:rank ?rank .
                          FILTER(?rank != wikibase:DeprecatedRank) } }""" % values
        for b in sparql(q, "%s_geo_%s.json" % (prefix, i)):
            _absorb(out, b, "geo", set(qids))
    for d in out.values():
        if "coords" in d:
            d["coords"] = sorted(set(d["coords"]))
        if "eles" in d:
            d["eles"] = sorted(set(d["eles"]), key=lambda x: (not x[1], -x[0]))
    return out


def parse_taiwan(text):
    """zh.wikipedia 'Taiwan 100 Peaks' table: '|N||[[Title|Name]]' then height."""
    out = []
    for r in rows(table_after(text, r"")):
        m = re.search(r"^\|[^\n]*?\|\s*(\d{1,3})\s*\|\|\s*(\[\[[^\]]+\]\][^\n]*)", r, re.M)
        if not m:
            continue
        title, disp = first_link(m.group(2))
        if not title:
            continue
        rest = r[m.end():]
        e = re.search(r"\|\s*(\d{4}(?:\.\d+)?)", rest)
        out.append({"rank": int(m.group(1)), "title": title,
                    "name": re.sub(r"\s*\(.*?\)$", "", disp),
                    "ref_ele": float(e.group(1)) if e else None})
    return out


def taiwan(lists):
    """Taiwan Top 100 Peaks: zh.wikipedia table for membership, cross-checked
    with Wikidata items 'facet of'/'part of' Q10915621."""
    p = os.path.join(WORK, "wp_zh_taiwan100.wikitext")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(http_get("https://zh.wikipedia.org/w/index.php",
                             {"title": "台灣百岳", "action": "raw"}))
    tw = parse_taiwan(open(p, encoding="utf-8").read())
    tq_path = os.path.join(WORK, "title_qids_zh.json")
    tq = json.load(open(tq_path)) if os.path.exists(tq_path) else {}
    missing = [x["title"] for x in tw if x["title"] not in tq]
    if missing:
        tq.update(titles_to_qids(missing, wiki="zh"))
        json.dump(tq, open(tq_path, "w"), ensure_ascii=False, indent=1)
    for x in tw:
        x["qid"] = tq.get(x["title"])
    q = ("SELECT DISTINCT ?s WHERE { { ?s wdt:P1269 wd:Q10915621 } UNION "
         "{ ?s wdt:P361 wd:Q10915621 } }")
    wdset = {qid(b["s"]["value"]) for b in sparql(q, "m_taiwan100.json")}
    det = wd_details({x["qid"] for x in tw if x.get("qid")}, prefix="tw")
    for x in tw:
        if x.get("qid") in det:
            x["wd"] = det[x["qid"]]
    lists["taiwan-100"] = tw
    return {"wikipedia_rows": len(tw), "wikidata_items": len(wdset),
            "wp_without_qid": [x["name"] for x in tw if not x.get("qid")],
            "wp_not_in_wd": [x["name"] for x in tw if x.get("qid") not in wdset],
            "wd_not_in_wp": sorted(wdset - {x.get("qid") for x in tw})}


def main():
    os.makedirs(WORK, exist_ok=True)
    lists = {}

    # --- Wikidata-modelled lists
    def by_claim(prop, target, cache):
        q = "SELECT DISTINCT ?s WHERE { ?s wdt:%s wd:%s . }" % (prop, target)
        return [{"qid": qid(b["s"]["value"])} for b in sparql(q, cache)]

    lists["munros"] = by_claim("P8450", "Q1320721", "m_munros.json")
    lists["eight-thousanders"] = by_claim("P8450", "Q185552", "m_8000.json")
    lists["hyakumeizan"] = by_claim("P361", "Q1156761", "m_hyakumeizan.json")
    lists["seven-summits-messner"] = [{"qid": q} for q in (
        "Q513", "Q39739", "Q130018", "Q7296", "Q43105", "Q17189941", "Q1045888")]
    lists["seven-summits-bass"] = [{"qid": q} for q in (
        "Q513", "Q39739", "Q130018", "Q7296", "Q43105", "Q17189941", "Q178167")]

    # --- Wikipedia-defined lists (membership only)
    alps = parse_alps(wikitext("List of mountains of the Alps over 4000 metres"))
    co = parse_mtc(wikitext("List of Colorado fourteeners"), r"==\s*Fourteeners\s*==")
    ca = parse_mtc(wikitext("List of California 14,000-foot summits"), r"")
    wa = parse_dobih(wikitext("List of Wainwrights"), r"\{\| class=\"wikitable", 1, 3)
    mu_wp = parse_dobih(wikitext("List of Munro mountains"), r"\{\| class=\"wikitable", 2, 6)
    titles = set()
    for L in (alps, co, ca, wa, mu_wp):
        titles.update(x["title"] for x in L if x.get("title"))
    tq_path = os.path.join(WORK, "title_qids.json")
    tq = json.load(open(tq_path)) if os.path.exists(tq_path) else {}
    missing = [t for t in titles if t not in tq]
    if missing:
        tq.update(titles_to_qids(missing))
        json.dump(tq, open(tq_path, "w"), ensure_ascii=False, indent=1)
    for L in (alps, co, ca, wa, mu_wp):
        for x in L:
            x["qid"] = tq.get(x.get("title"))
    lists["alps-4000"] = alps
    lists["colorado-14ers"] = co
    lists["california-14ers"] = ca
    lists["wainwrights"] = wa

    # Munros: Wikidata membership, enriched with the DoBIH grid ref / height
    # from the Wikipedia table where the item is linked there.
    wd_q_all = {m["qid"] for m in lists["munros"]}
    det_m = wd_details(wd_q_all)

    def km(x, q):
        cs = det_m.get(q, {}).get("coords") or []
        if x.get("ref_lat") is None or not cs:
            return 0.0
        return min(math.hypot((la - x["ref_lat"]) * 111.2,
                              (lo - x["ref_lon"]) * 111.2 * math.cos(math.radians(la)))
                   for la, lo in cs)

    # a Wikipedia link only pairs a row with an item if the positions agree
    # (some rows link to a neighbouring summit's article)
    wp_by_q = {}
    for x in mu_wp:
        if x.get("qid") in wd_q_all and x["qid"] not in wp_by_q and km(x, x["qid"]) < 1.5:
            wp_by_q[x["qid"]] = x
    for m in lists["munros"]:
        w = wp_by_q.get(m["qid"])
        if w:
            m.update({k: w[k] for k in ("title", "ref_ele", "ref_lat",
                                        "ref_lon", "gridref") if w.get(k) is not None})
            m["wp_name"] = w["name"]
    # Wikipedia sometimes links a Munro row to its massif article (e.g.
    # "Liathach - Spidean a' Choire Leith" -> Liathach). Pair the remaining
    # rows with Wikidata items by position (grid ref vs P625, < 1.5 km).
    wd_munro_q = {m["qid"] for m in lists["munros"]}
    paired = {id(x) for x in wp_by_q.values()}
    free_rows = [x for x in mu_wp if id(x) not in paired and x.get("ref_lat")]
    for m in lists["munros"]:
        if m["qid"] in wp_by_q:
            continue
        cs = det_m.get(m["qid"], {}).get("coords") or []
        best = None
        for x in free_rows:
            for la, lo in cs:
                dy = (la - x["ref_lat"]) * 111.2
                dx = (lo - x["ref_lon"]) * 111.2 * math.cos(math.radians(la))
                dkm = math.hypot(dx, dy)
                if dkm < 1.5 and (best is None or dkm < best[0]):
                    best = (dkm, x)
        if best:
            x = best[1]
            free_rows.remove(x)
            wp_by_q[m["qid"]] = x
            m.update({k: x[k] for k in ("ref_ele", "ref_lat", "ref_lon", "gridref")
                      if x.get(k) is not None})
            m["wp_name"] = x["name"]
    munro_check = {"wikipedia_rows": len(mu_wp),
                   "wikidata_items": len(lists["munros"]),
                   "wd_not_in_wp": [m["qid"] for m in lists["munros"] if m["qid"] not in wp_by_q],
                   "wp_rows_unpaired": [x["name"] for x in free_rows]}

    allq = {x["qid"] for L in lists.values() for x in L if x.get("qid")}
    det = wd_details(allq)
    for L in lists.values():
        for x in L:
            if x.get("qid") in det:
                x["wd"] = det[x["qid"]]
    taiwan_check = taiwan(lists)
    json.dump({"lists": lists, "munro_check": munro_check, "taiwan_check": taiwan_check},
              open(os.path.join(WORK, "members.json"), "w"),
              ensure_ascii=False, indent=1)
    for k, L in lists.items():
        print("%-24s %4d members, %d with qid, %d with wd coords" % (
            k, len(L), sum(1 for x in L if x.get("qid")),
            sum(1 for x in L if x.get("wd", {}).get("coords"))))
    print("munro check:", json.dumps(munro_check, ensure_ascii=False)[:600])
    print("taiwan check:", json.dumps(taiwan_check, ensure_ascii=False)[:800])


if __name__ == "__main__":
    main()
