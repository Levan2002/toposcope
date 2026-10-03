#!/usr/bin/env python3
"""Build the Toposcope peak cells from the cached Overpass responses.

Input : Data/_work/overpass/*.json.gz (written by fetch_osm_peaks.py)
Output: Data/peaks/p_<latIdx>_<lonIdx>.tsv.z, Data/peaks/index.json,
        Data/bundle/peaks_major.tsv.z, Data/_work/peaks_all.tsv (uncompressed,
        used by build_lists.py for matching)

File format (raw DEFLATE, no zlib/gzip header, UTF-8):
  #toposcope-peaks v1 cell=<latIdx>_<lonIdx> count=<n>
  osm_id<TAB>lat<TAB>lon<TAB>ele<TAB>name<TAB>alt_names<TAB>wikidata<TAB>flags
Python 3 stdlib only.
"""
import argparse
import datetime
import glob
import gzip
import hashlib
import json
import math
import os
import re
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(HERE)
CACHE = os.path.join(DATA, "_work", "overpass")
PEAKS = os.path.join(DATA, "peaks")
BUNDLE = os.path.join(DATA, "bundle")
ALT_KEYS = ["en", "de", "fr", "it", "es", "pt", "ja", "ko", "zh"]
ELE_MIN, ELE_MAX = -500, 8900
MAJOR_MAX_BYTES = 4 * 1024 * 1024

_ws = re.compile(r"\s+")
_bad_chars = re.compile(r"[\t\r\n|\x00-\x1f\x7f]")
# names that are only an elevation / spot-height label, e.g. "1234", "1234 m",
# "Pt. 1234", "P. 1.234", "Cota 845", "Kóta 512", "q. 1203", "(1234)"
_num_only = re.compile(
    r"^\(?\s*(?:pt\.?|p\.?|punkt|point|pkt\.?|cota|kóta|kota|quota|q\.?|"
    r"vf\.?|höhe|h\.?|alt\.?|altitude|elev\.?|spot height|trig(?:\s*point)?)?"
    r"\s*[-+]?\d[\d\s.,'’]*\s*(?:m|ft|feet|m\.?\s*ü\.?\s*m\.?|m\.?n\.?m\.?|msnm|"
    r"m\.s\.l\.?m?\.?|masl|m a\.?s\.?l\.?)?\s*\)?$", re.I)
_generic = {"peak", "summit", "top", "hill", "mountain", "gipfel", "pic", "pico",
            "vrh", "szczyt", "unnamed", "no name", "noname", "unknown", "?", "-",
            "fixme", "name", "peak name", "berg", "mont", "monte", "cima", "pik",
            "gora", "гора", "вершина", "山", "峰"}


def clean_name(s):
    if not s:
        return ""
    s = _bad_chars.sub(" ", s)
    s = _ws.sub(" ", s).strip()
    return s


def is_bad_name(s):
    if not s:
        return True
    if _num_only.match(s):
        return True
    if s.lower() in _generic:
        return True
    if not re.search(r"\w", s):
        return True
    return False


def parse_len(v):
    """Parse an OSM length value ('4478', '4478 m', '4,478', '14505 ft',
    '4478,5', '~1200', '1200;1201') -> metres (float) or None."""
    if v is None:
        return None
    s = v.strip().lower()
    if not s:
        return None
    s = s.split(";")[0].strip()
    s = s.replace(" ", "").replace(" ", "").replace("\xa0", " ")
    feet = bool(re.search(r"(ft|feet|foot|')\s*$", s)) or s.endswith("′")
    m = re.search(r"[-+]?\d[\d.,\s]*", s)
    if not m:
        return None
    t = m.group(0).strip().replace(" ", "")
    if "," in t and "." in t:
        # 4,478.5 -> thousands comma ; 4.478,5 -> thousands dot
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        parts = t.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[0].lstrip("+-") != "0":
            t = t.replace(",", "")  # 4,478 thousands separator
        else:
            t = t.replace(",", ".")  # 4478,5 decimal comma
    elif t.count(".") > 1:
        t = t.replace(".", "")  # 1.234.5? treat dots as grouping
    elif "." in t:
        a, b = t.split(".")
        # "4.478" with exactly three decimals and no unit could be a thousands
        # dot (German style); only accept that reading if it is plausible.
        if len(b) == 3 and a.lstrip("+-") not in ("", "0") and float(t) < 10:
            t = a + b
    try:
        x = float(t)
    except ValueError:
        return None
    if feet:
        x *= 0.3048
    return x


def parse_ele(v):
    x = parse_len(v)
    if x is None or math.isnan(x) or x < ELE_MIN or x > ELE_MAX:
        return None
    return int(round(x))


def parse_wikidata(v):
    if not v:
        return ""
    m = re.match(r"\s*(Q[1-9]\d*)\b", v.strip())
    return m.group(1) if m else ""


def cell_of(lat, lon):
    li = min(35, max(0, int(math.floor((lat + 90) / 5))))
    lo = min(71, max(0, int(math.floor((lon + 180) / 5))))
    return li, lo


def _box(name):
    v = name.split("_")[1:5]
    return tuple(float(x) for x in v)


def coverage():
    """Boxes fetched completely, and boxes that were split into quarters."""
    cached, splits = set(), set()
    for fn in os.listdir(CACHE):
        if fn.endswith(".json.gz"):
            cached.add(_box(fn[:-8]))
        elif fn.endswith(".split"):
            splits.add(_box(fn[:-6]))
    return cached, splits


def cell_complete(li, lo, cached, splits):
    cell = (li * 5 - 90.0, lo * 5 - 180.0, li * 5 - 85.0, lo * 5 - 175.0)

    def inter(a, b):
        return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))

    def contains(o, i):
        return o[0] <= i[0] and o[1] <= i[1] and o[2] >= i[2] and o[3] >= i[3]

    def cov(box):
        part = inter(cell, box)
        if part[0] >= part[2] or part[1] >= part[3]:
            return True
        if any(contains(c, part) for c in cached):
            return True
        if box in splits:
            s, w, n, e = box
            ml, mo = (s + n) / 2, (w + e) / 2
            return all(cov(q) for q in [(s, w, ml, mo), (s, mo, ml, e),
                                        (ml, w, n, mo), (ml, mo, n, e)])
        return False

    t = (math.floor(cell[0] / 10) * 10.0, math.floor(cell[1] / 10) * 10.0)
    return cov((t[0], t[1], t[0] + 10.0, t[1] + 10.0))


def load_nodes():
    nodes = {}
    files = sorted(glob.glob(os.path.join(CACHE, "*.json.gz")))
    for fn in files:
        with gzip.open(fn, "rb") as f:
            d = json.loads(f.read())
        for e in d.get("elements", []):
            if e.get("type") != "node" or "lat" not in e:
                continue
            nodes[e["id"]] = e
    return nodes, len(files)


def to_row(e, stats):
    tags = e.get("tags", {})
    name = clean_name(tags.get("name"))
    if is_bad_name(name):
        stats["dropped_name"] += 1
        return None
    lat, lon = round(float(e["lat"]), 5), round(float(e["lon"]), 5)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        stats["dropped_coord"] += 1
        return None
    ele = parse_ele(tags.get("ele"))
    if tags.get("ele") and ele is None:
        stats["ele_unparsed_or_absurd"] += 1
    alts = []
    for k in ALT_KEYS:
        if k == "zh":
            v = tags.get("name:zh-Hans") or tags.get("name:zh")
        else:
            v = tags.get("name:" + k)
        v = clean_name(v)
        if v and v != name and not is_bad_name(v):
            alts.append("%s=%s" % (k, v))
    flags = []
    if tags.get("natural") == "volcano":
        flags.append("v")
    prom = parse_len(tags.get("prominence"))
    if prom is not None and 0 < prom <= ELE_MAX:
        flags.append("p%d" % int(round(prom)))
    return {
        "id": e["id"], "lat": lat, "lon": lon, "ele": ele, "name": name,
        "alt": "|".join(alts), "wd": parse_wikidata(tags.get("wikidata")),
        "flags": ",".join(flags),
    }


def fmt(r):
    return "\t".join([
        str(r["id"]), "%.5f" % r["lat"], "%.5f" % r["lon"],
        "" if r["ele"] is None else str(r["ele"]), r["name"], r["alt"], r["wd"],
        r["flags"]])


def sort_key(r):
    return (r["ele"] is None, -(r["ele"] or 0), r["name"], r["id"])


def deflate(text):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(text.encode("utf-8")) + c.flush()


def write_file(path, header, rows):
    rows = sorted(rows, key=sort_key)
    body = header + "\n" + "".join(fmt(r) + "\n" for r in rows)
    blob = deflate(body)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)
    return len(blob), hashlib.sha256(blob).hexdigest(), rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--major-wd-min-ele", type=int, default=0,
                    help="minimum ele for wikidata-tagged peaks in the bundle")
    ap.add_argument("--allow-partial", action="store_true",
                    help="also write cells whose source boxes are incomplete")
    args = ap.parse_args()
    os.makedirs(PEAKS, exist_ok=True)
    os.makedirs(BUNDLE, exist_ok=True)
    nodes, nfiles = load_nodes()
    stats = {"raw_nodes": len(nodes), "cache_files": nfiles, "dropped_name": 0,
             "dropped_coord": 0, "ele_unparsed_or_absurd": 0}
    cells = {}
    allrows = []
    for e in nodes.values():
        r = to_row(e, stats)
        if r is None:
            continue
        allrows.append(r)
        cells.setdefault(cell_of(r["lat"], r["lon"]), []).append(r)
    cached, splits = coverage()
    incomplete = sorted(k for k in cells if not cell_complete(k[0], k[1], cached, splits))
    if incomplete and not args.allow_partial:
        print("skipping %d cells whose source tiles are not all downloaded yet" % len(incomplete))
        for k in incomplete:
            del cells[k]
    stats["incomplete_cells_skipped"] = len(incomplete) if not args.allow_partial else 0
    stats["world_complete"] = all(
        cell_complete(a, b, cached, splits) for a in range(36) for b in range(72))
    for old in glob.glob(os.path.join(PEAKS, "p_*.tsv.z")):
        os.remove(old)
    index = {"version": 1,
             "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "source": "© OpenStreetMap contributors, ODbL 1.0",
             "cells": {}}
    total_bytes = 0
    for (li, lo), rows in sorted(cells.items()):
        key = "%d_%d" % (li, lo)
        n, sha, _ = write_file(os.path.join(PEAKS, "p_%s.tsv.z" % key),
                               "#toposcope-peaks v1 cell=%s count=%d" % (key, len(rows)),
                               rows)
        index["cells"][key] = {"count": len(rows), "bytes": n, "sha256": sha}
        total_bytes += n
    with open(os.path.join(PEAKS, "index.json"), "w") as f:
        json.dump(index, f, separators=(",", ":"), sort_keys=False)
        f.write("\n")

    # bundled notable peaks
    thr = args.major_wd_min_ele
    while True:
        major = [r for r in allrows
                 if (r["wd"] and r["ele"] is not None and r["ele"] >= thr)
                 or (r["ele"] is not None and r["ele"] >= 4000)]
        n, sha, _ = write_file(os.path.join(BUNDLE, "peaks_major.tsv.z"),
                               "#toposcope-peaks v1 cell=major count=%d" % len(major),
                               major)
        if n <= MAJOR_MAX_BYTES:
            break
        thr += 250
        print("bundle %d bytes > limit, raising wikidata ele threshold to %d" % (n, thr))
    # uncompressed copy for list matching
    with open(os.path.join(DATA, "_work", "peaks_all.tsv"), "w", encoding="utf-8") as f:
        for r in sorted(allrows, key=sort_key):
            f.write(fmt(r) + "\n")

    largest = max(index["cells"].items(), key=lambda kv: kv[1]["bytes"]) if cells else None
    most = max(index["cells"].items(), key=lambda kv: kv[1]["count"]) if cells else None
    summary = dict(stats)
    summary.update({
        "peaks": len(allrows), "peaks_in_cells": sum(len(v) for v in cells.values()),
        "cells": len(cells),
        "total_compressed_bytes": total_bytes,
        "largest_cell_bytes": largest, "most_peaks_cell": most,
        "with_ele": sum(1 for r in allrows if r["ele"] is not None),
        "with_wikidata": sum(1 for r in allrows if r["wd"]),
        "volcanoes": sum(1 for r in allrows if "v" in r["flags"].split(",")),
        "with_prominence": sum(1 for r in allrows if "p" in r["flags"]),
        "with_alt_names": sum(1 for r in allrows if r["alt"]),
        "major_count": len(major), "major_bytes": n,
        "major_wikidata_min_ele": thr,
    })
    with open(os.path.join(DATA, "_work", "build_summary.json"), "w") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
