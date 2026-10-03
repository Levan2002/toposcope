#!/usr/bin/env python3
"""Download all named OSM peak/volcano nodes worldwide via the Overpass API.

Python 3 stdlib only. Results are cached per bounding box in
Data/_work/overpass/ as gzip'd Overpass JSON, so a rerun resumes where it
stopped. Tiles start at 10x10 degrees and are split into quarters whenever the
server reports a timeout / out-of-memory for a tile.

Usage: python3 tools/fetch_osm_peaks.py [--servers URL,URL] [--pause 2]
"""
import argparse
import gzip
import json
import os
import queue
import random
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(HERE)
CACHE = os.path.join(DATA, "_work", "overpass")
UA = "Toposcope-data-pipeline/1.0 (named-peak dataset build; python-urllib)"
DEFAULT_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Several mirrors stall for ~75 s on IPv6 from this network; force IPv4.
_orig_gai = socket.getaddrinfo


def _gai_v4(host, port, family=0, *a, **k):
    return _orig_gai(host, port, socket.AF_INET, *a, **k)


socket.getaddrinfo = _gai_v4
QUERY = ('[out:json][timeout:{t}][maxsize:{m}];'
         'node["natural"~"^(peak|volcano)$"]["name"]({s},{w},{n},{e});'
         'out body qt;')
MIN_SPAN = 0.625
MAXSIZE = 268435456  # 256 MB; large reservations stall in the dispatcher

log_lock = threading.Lock()
stat_lock = threading.Lock()


def bump(stats, key, n):
    with stat_lock:
        stats[key] += n


def log(*a):
    with log_lock:
        print(time.strftime("%H:%M:%S"), *a, flush=True)


def tile_name(t):
    s, w, n, e = t
    return "t_%g_%g_%g_%g" % (s, w, n, e)


def cache_path(t):
    return os.path.join(CACHE, tile_name(t) + ".json.gz")


def split_path(t):
    return os.path.join(CACHE, tile_name(t) + ".split")


def quarters(t):
    s, w, n, e = t
    ml, mo = (s + n) / 2, (w + e) / 2
    return [(s, w, ml, mo), (s, mo, ml, e), (ml, w, n, mo), (ml, mo, n, e)]


class Busy(Exception):
    pass


class TooBig(Exception):
    pass


def fetch(server, t, timeout_s):
    s, w, n, e = t
    q = QUERY.format(t=timeout_s, m=MAXSIZE, s=s, w=w, n=n, e=e)
    body = urllib.parse.urlencode({"data": q}).encode()
    req = urllib.request.Request(server, data=body, headers={
        "User-Agent": UA, "Accept": "application/json, */*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s + 120) as r:
            raw = r.read()
    except urllib.error.HTTPError as ex:
        txt = ex.read()[:2000].decode("utf-8", "replace")
        if ex.code in (429, 502, 503, 504):
            if "timed out" in txt.lower() and "query" in txt.lower():
                raise TooBig(txt[:200])
            raise Busy("HTTP %d %s" % (ex.code, " ".join(txt.split())[-200:]))
        if ex.code == 400:
            raise RuntimeError("HTTP 400 " + txt[-400:])
        raise Busy("HTTP %d" % ex.code)
    except Exception as ex:  # URLError, timeouts, IncompleteRead, resets...
        raise Busy("net %r" % (ex,))
    try:
        d = json.loads(raw)
    except ValueError:
        txt = raw[:3000].decode("utf-8", "replace")
        if "timed out" in txt or "out of memory" in txt.lower():
            raise TooBig(txt[-300:])
        raise Busy("non-json " + " ".join(txt.split())[-300:])
    rem = d.get("remark") or ""
    if rem:
        if "timed out" in rem or "memory" in rem.lower():
            raise TooBig(rem)
        if "runtime error" in rem:
            raise Busy(rem)
    return raw, len(d.get("elements", []))


def worker(server, q, args, stats):
    fails = 0
    while True:
        try:
            t = q.get(timeout=5)
        except queue.Empty:
            if stats["pending"] == 0:
                return
            continue
        if os.path.exists(cache_path(t)):
            bump(stats, "pending", -1)
            continue
        if os.path.exists(split_path(t)):
            for c in quarters(t):
                bump(stats, "pending", 1)
                q.put(c)
            bump(stats, "pending", -1)
            continue
        t0 = time.time()
        try:
            raw, n = fetch(server, t, args.timeout)
        except TooBig as ex:
            span = t[2] - t[0]
            if span / 2 >= MIN_SPAN:
                log("SPLIT", tile_name(t), server.split("/")[2], str(ex)[:120])
                open(split_path(t), "w").write(str(ex)[:500])
                for c in quarters(t):
                    bump(stats, "pending", 1)
                    q.put(c)
                bump(stats, "pending", -1)
            else:
                log("TOO BIG at min span, retrying later", tile_name(t))
                q.put(t)
                time.sleep(30)
            continue
        except Busy as ex:
            fails += 1
            wait = min(180, 10 * (2 ** min(fails, 4))) * (0.75 + random.random() / 2)
            log("BUSY", server.split("/")[2], tile_name(t), str(ex)[:160],
                "-> sleep %.0fs" % wait)
            q.put(t)
            time.sleep(wait)
            continue
        fails = 0
        tmp = cache_path(t) + ".tmp"
        with gzip.open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, cache_path(t))
        bump(stats, "done", 1)
        bump(stats, "elements", n)
        bump(stats, "pending", -1)
        log("OK %-28s %7d nodes %6.1fs %s | done=%d pending=%d total=%d" % (
            tile_name(t), n, time.time() - t0, server.split("/")[2],
            stats["done"], stats["pending"], stats["elements"]))
        time.sleep(args.pause)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--servers", default=",".join(DEFAULT_SERVERS))
    ap.add_argument("--pause", type=float, default=2.0)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--step", type=float, default=10.0)
    ap.add_argument("--tiles", default="",
                    help="only these boxes, 's,w,n,e;s,w,n,e' (priority runs)")
    args = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    tiles = []
    st = args.step
    lat = -90.0
    while lat < 90:
        lon = -180.0
        while lon < 180:
            tiles.append((lat, lon, lat + st, lon + st))
            lon += st
        lat += st
    # Process land-heavy mid latitudes first (just ordering; all tiles run).
    tiles.sort(key=lambda t: abs(t[0] + st / 2 - 35))
    if args.tiles:
        tiles = [tuple(float(v) for v in b.split(",")) for b in args.tiles.split(";") if b]
    q = queue.Queue()
    stats = {"pending": len(tiles), "done": 0, "elements": 0}
    for t in tiles:
        q.put(t)
    servers = [s for s in args.servers.split(",") if s]
    ths = [threading.Thread(target=worker, args=(s, q, args, stats), daemon=True)
           for s in servers]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    log("ALL DONE", stats)


if __name__ == "__main__":
    sys.exit(main())
