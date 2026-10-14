#!/usr/bin/env python3
"""Baut russia.m3u: alle russischen Streams aus iptv-org in einer Gruppe "Russia Neu".

- Quelle: alle streams/*.m3u aus github.com/iptv-org/iptv (nicht nur einer pro Sender)
- Namen in lateinischer Schrift und Logos aus der iptv-org-API
- Streams, deren Server-Adresse nicht mehr existiert (DNS), fliegen raus
"""
import json, re, socket, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

GROUP = "Russia Neu"
API = "https://iptv-org.github.io/api/"

streams_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "iptv/streams")
out_file = Path(sys.argv[2] if len(sys.argv) > 2 else "russia.m3u")

def get_json(name):
    with urllib.request.urlopen(API + name, timeout=120) as r:
        return json.load(r)

channels = {c["id"]: c for c in get_json("channels.json")}
logos = {}
for l in get_json("logos.json"):
    if not l.get("in_use", True):
        continue
    key = (l["channel"], l.get("feed"))
    score = (l.get("format") == "PNG", (l.get("width") or 0))
    if key not in logos or score > logos[key][0]:
        logos[key] = (score, l["url"])

def logo_for(cid, feed):
    for key in ((cid, feed), (cid, None)):
        if key in logos:
            return logos[key][1]
    for (c, _), (_, url) in logos.items():
        if c == cid:
            return url
    return ""

# Alle Einträge aus allen Quelldateien einsammeln
entries, seen = [], set()
for f in sorted(streams_dir.glob("*.m3u")):
    extinf, opts = None, []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            extinf, opts = line, []
        elif line.startswith("#EXTVLCOPT"):
            opts.append(line)
        elif line and not line.startswith("#") and extinf:
            m = re.search(r'tvg-id="([^"]*)"', extinf)
            tvg_id = m.group(1) if m else ""
            cid, _, feed = tvg_id.partition("@")
            is_ru = cid.endswith(".ru") or (not cid and f.stem == "ru")
            if is_ru and line not in seen:
                seen.add(line)
                entries.append(dict(tvg_id=tvg_id, cid=cid, feed=feed or None,
                                    src_name=extinf.rsplit(",", 1)[-1].strip(),
                                    opts=opts, url=line))
            extinf, opts = None, []

# Tote Server-Adressen aussortieren (Domain existiert nicht mehr)
def resolves(host):
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False

hosts = {urlparse(e["url"]).hostname for e in entries}
with ThreadPoolExecutor(32) as ex:
    alive = dict(zip(hosts, ex.map(resolves, hosts)))
before = len(entries)
entries = [e for e in entries if alive.get(urlparse(e["url"]).hostname)]

# Lateinischer Name + Zusatz aus dem Original (Auflösung, [Not 24/7] usw.)
def display_name(e):
    ch = channels.get(e["cid"])
    if not ch:
        return e["src_name"]
    suffix = re.search(r"(\s*[\(\[].*)$", e["src_name"])
    return ch["name"] + (" " + suffix.group(1).strip() if suffix else "")

def resolution(name):
    m = re.search(r"\((\d+)[pi]\)", name)
    return int(m.group(1)) if m else 0

for e in entries:
    e["name"] = display_name(e)
entries.sort(key=lambda e: (e["name"].split(" (")[0].casefold(), -resolution(e["name"]), e["name"]))

lines = ["#EXTM3U"]
for e in entries:
    logo = logo_for(e["cid"], e["feed"]) if e["cid"] else ""
    lines.append(f'#EXTINF:-1 tvg-id="{e["tvg_id"]}" tvg-logo="{logo}" group-title="{GROUP}",{e["name"]}')
    lines.extend(e["opts"])
    lines.append(e["url"])
out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{len(entries)} Streams geschrieben ({before - len(entries)} mit toter Adresse entfernt)")
