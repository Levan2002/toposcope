#!/usr/bin/env python3
"""Reader test for the Toposcope peak files (mirrors what the app parser does).

Checks, for every cell (or a sample with --sample N) plus the bundle:
  * raw DEFLATE (wbits=-15) decompresses; zlib/gzip headers absent
  * header line '#toposcope-peaks v1 cell=<key> count=<n>' and n == line count
  * 8 tab-separated columns, numeric id, 5-decimal lat/lon inside the cell
  * ele integer in -500..8900 or empty, sorted descending (empties last)
  * alt_names 'k=v|k=v' with allowed keys, wikidata Q-id or empty,
    flags from {v, p<int>}
  * index.json count / bytes / sha256 agree with the files
Also validates bundle/lists.json structure if present.
Python 3 stdlib only. Exit code 1 on any failure.
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(HERE)
ALT = {"en", "de", "fr", "it", "es", "pt", "ja", "ko", "zh"}
HDR = re.compile(r"^#toposcope-peaks v1 cell=(\S+) count=(\d+)$")
NUM5 = re.compile(r"^-?\d+\.\d{5}$")
errors = []


def err(msg):
    errors.append(msg)
    if len(errors) < 30:
        print("FAIL:", msg)


def check_file(path, key, expect=None):
    blob = open(path, "rb").read()
    if blob[:2] in (b"\x78\x01", b"\x78\x9c", b"\x78\xda", b"\x1f\x8b"):
        err("%s: looks like zlib/gzip header, expected raw deflate" % path)
    text = zlib.decompress(blob, -15).decode("utf-8")
    lines = text.split("\n")
    if lines[-1] != "":
        err("%s: missing trailing newline" % path)
    lines = lines[:-1]
    m = HDR.match(lines[0])
    if not m or m.group(1) != key:
        err("%s: bad header %r" % (path, lines[0][:80]))
        return 0
    n = int(m.group(2))
    rows = lines[1:]
    if n != len(rows):
        err("%s: header count %d != %d rows" % (path, n, len(rows)))
    prev = None
    ids = set()
    for i, line in enumerate(rows):
        c = line.split("\t")
        if len(c) != 8:
            err("%s:%d: %d columns" % (path, i + 2, len(c)))
            continue
        oid, lat, lon, ele, name, alt, wd, flags = c
        if not oid.isdigit() or oid in ids:
            err("%s:%d: bad/duplicate id %r" % (path, i + 2, oid))
        ids.add(oid)
        if not NUM5.match(lat) or not NUM5.match(lon):
            err("%s:%d: lat/lon format %r %r" % (path, i + 2, lat, lon))
            continue
        la, lo = float(lat), float(lon)
        if key not in ("major",):
            li, lj = map(int, key.split("_"))
            if not (min(35, int((la + 90) // 5)) == li and min(71, int((lo + 180) // 5)) == lj):
                # 5-decimal rounding can push a point onto the next cell edge
                if not (abs((la + 90) / 5 - round((la + 90) / 5)) < 1e-4
                        or abs((lo + 180) / 5 - round((lo + 180) / 5)) < 1e-4):
                    err("%s:%d: point %s,%s outside cell" % (path, i + 2, lat, lon))
        if ele:
            if not re.match(r"^-?\d+$", ele) or not -500 <= int(ele) <= 8900:
                err("%s:%d: ele %r" % (path, i + 2, ele))
        k = (ele == "", -(int(ele) if ele else 0))
        if prev is not None and k < prev:
            err("%s:%d: not sorted by ele desc" % (path, i + 2))
        prev = k
        if not name.strip() or name != name.strip() or "|" in name:
            err("%s:%d: bad name %r" % (path, i + 2, name))
        if re.fullmatch(r"[\d\s.,]+(m|ft)?", name):
            err("%s:%d: numeric name %r" % (path, i + 2, name))
        if alt:
            for part in alt.split("|"):
                kk, _, vv = part.partition("=")
                if kk not in ALT or not vv or vv == name:
                    err("%s:%d: bad alt %r" % (path, i + 2, part))
        if wd and not re.match(r"^Q[1-9]\d*$", wd):
            err("%s:%d: bad wikidata %r" % (path, i + 2, wd))
        if flags:
            for f in flags.split(","):
                if not (f == "v" or re.match(r"^p\d+$", f)):
                    err("%s:%d: bad flag %r" % (path, i + 2, f))
    if expect is not None:
        if expect["count"] != n:
            err("%s: index count %d != %d" % (path, expect["count"], n))
        if expect["bytes"] != len(blob):
            err("%s: index bytes mismatch" % path)
        if expect["sha256"] != hashlib.sha256(blob).hexdigest():
            err("%s: index sha256 mismatch" % path)
    return n


def check_lists(path):
    d = json.load(open(path, encoding="utf-8"))
    langs = {"en", "de", "fr", "it", "es", "pt-BR", "ja", "ko", "zh-Hans"}
    for L in d:
        for k in ("id", "title", "region", "source", "peaks"):
            if k not in L:
                err("lists.json %s: missing %s" % (L.get("id"), k))
        if set(L["title"]) != langs:
            err("lists.json %s: title langs %s" % (L["id"], sorted(L["title"])))
        for p in L["peaks"]:
            for k in ("name", "local", "lat", "lon", "ele", "wikidata", "osm_id"):
                if k not in p:
                    err("lists.json %s/%s: missing %s" % (L["id"], p.get("name"), k))
            if not (-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180):
                err("lists.json %s/%s: coords" % (L["id"], p["name"]))
        print("  list %-22s %3d peaks" % (L["id"], len(L["peaks"])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="check only N random cells")
    a = ap.parse_args()
    idx = json.load(open(os.path.join(DATA, "peaks", "index.json")))
    assert idx["version"] == 1 and "OpenStreetMap" in idx["source"]
    keys = sorted(idx["cells"])
    files = {f[2:-6] for f in os.listdir(os.path.join(DATA, "peaks")) if f.startswith("p_")}
    if files != set(keys):
        err("index/files mismatch: %d files vs %d index entries" % (len(files), len(keys)))
    if a.sample:
        keys = random.sample(keys, min(a.sample, len(keys)))
    total = 0
    for k in keys:
        total += check_file(os.path.join(DATA, "peaks", "p_%s.tsv.z" % k), k, idx["cells"][k])
    print("checked %d cells, %d peaks" % (len(keys), total))
    nb = check_file(os.path.join(DATA, "bundle", "peaks_major.tsv.z"), "major")
    print("checked bundle peaks_major: %d peaks" % nb)
    lp = os.path.join(DATA, "bundle", "lists.json")
    if os.path.exists(lp):
        check_lists(lp)
    print("OK" if not errors else "%d FAILURES" % len(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
