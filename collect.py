"""Coleta o ranking de XP do Olden 74 e gera rank.json com quem mais ganhou XP
nas janelas de 10 min a 24 h. Mantém um histórico compacto (history.json.gz)
com as coletas das últimas 25 horas."""
import gzip, json, os, sys, time, urllib.parse, urllib.request, urllib.error

BASE = "https://olden74.com/api"
API = BASE + "/community/rankings?skill=experience&limit=100&offset={}"
TOWNS = {1: "Thais", 2: "Carlin", 3: "Kazordoon", 4: "Ab'Dendriel", 5: "Edron", 6: "Darashia",
         7: "Venore", 8: "Ankrahmun", 9: "Port Hope", 11: "Rookgaard"}
OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
WINDOWS = [10, 30, 60, 180, 360, 720, 1440]  # minutos
KEEP_MS = 25 * 3600 * 1000
TOP = 150
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; powergamers-olden74/1.0)",
        "Accept": "application/json"}


def get_json(url, tries=5, missing_ok=False):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEAD)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if missing_ok and e.code == 404:
                return None
            last = e
        except Exception as e:  # rede, 5xx, Cloudflare
            last = e
        time.sleep(4 + 4 * i)
    raise RuntimeError(f"falha ao buscar {url}: {last}")


def fetch(off):
    try:
        return get_json(API.format(off))
    except RuntimeError as e:
        raise SystemExit(str(e))


def collect():
    chars, off = {}, 0
    while off is not None:
        j = fetch(off)
        zero = False
        for it in j["items"]:
            if it["value"] > 0:
                chars[str(it["id"])] = [it["value"], it["level"], it["vocation"], it["name"]]
            else:
                zero = True
        off = None if zero else j.get("next")
        time.sleep(0.3)
    return chars


def main():
    os.makedirs(OUT, exist_ok=True)
    hist_path = os.path.join(OUT, "history.json.gz")
    hist = []
    if os.path.exists(hist_path):
        try:
            hist = json.load(gzip.open(hist_path, "rt", encoding="utf-8"))
        except Exception:
            hist = []

    now = int(time.time() * 1000)
    chars = collect()
    hist.append({"t": now, "x": {k: [v[0], v[1]] for k, v in chars.items()}})
    hist = [h for h in hist if h["t"] >= now - KEEP_MS]
    hist.sort(key=lambda h: h["t"])

    latest = hist[-1]
    windows = {}
    for w in WINDOWS:
        tol = (3 if w < 60 else 8) * 60 * 1000
        base = next((h for h in hist if h["t"] >= now - w * 60000 - tol and h is not latest), None)
        if base is None:
            continue
        span = (latest["t"] - base["t"]) / 60000
        if span < 3:
            continue
        rows = []
        for cid, (xp, lvl) in latest["x"].items():
            b = base["x"].get(cid)
            if not b:
                continue
            gain = xp - b[0]
            if gain <= 0:
                continue
            name, voc = chars.get(cid, [0, 0, 0, "?"])[3], chars.get(cid, [0, 0, 0, "?"])[2]
            rows.append([name, voc, lvl, lvl - b[1], gain])
        rows.sort(key=lambda r: -r[4])
        windows[str(w)] = {"from": base["t"], "to": latest["t"], "span": round(span, 1),
                           "active": len(rows), "sum": sum(r[4] for r in rows), "rows": rows[:TOP]}

    write_radar(hist, now)

    rank = {"updated": now, "chars": len(chars), "snapshots": len(hist),
            "oldest": hist[0]["t"], "windows": windows}
    json.dump(rank, open(os.path.join(OUT, "rank.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    with gzip.open(hist_path, "wt", encoding="utf-8") as f:
        json.dump(hist, f, separators=(",", ":"))
    print(f"ok: {len(chars)} chars, {len(hist)} coletas, janelas {list(windows)}")


def gain_since(hist, cid, minutes, now):
    """XP ganho por um char desde a coleta mais próxima de `minutes` atrás."""
    latest = hist[-1]
    tol = 3 * 60 * 1000
    base = next((h for h in hist if h["t"] >= now - minutes * 60000 - tol and h is not latest), None)
    if base is None or cid not in latest["x"] or cid not in base["x"]:
        return None
    return latest["x"][cid][0] - base["x"][cid][0]


def write_radar(hist, now):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "radar.txt")
    if not os.path.exists(path):
        return
    names = [l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")][:40]
    q = urllib.parse.quote
    out = []
    for name in names:
        try:
            c = get_json(f"{BASE}/characters/{q(name)}", tries=3, missing_ok=True)
            if not c:
                out.append({"name": name, "missing": True})
                continue
            deaths = get_json(f"{BASE}/community/deaths?limit=5&char={q(c['name'])}", tries=3) or {}
            kills = get_json(f"{BASE}/community/kills?limit=5&killer={q(c['name'])}", tries=3) or {}
        except RuntimeError as e:
            out.append({"name": name, "error": str(e)[:120]})
            continue
        cid = str(c["id"])
        g = {str(m): gain_since(hist, cid, m, now) for m in (10, 30, 60, 180)}
        out.append({
            "name": c["name"], "level": c["level"], "voc": c["vocation"],
            "town": TOWNS.get(c.get("town_id"), "?"), "guild": c.get("guild_name"),
            "lastlogin": (c.get("lastlogin") or 0) * 1000, "gain": g,
            "deaths": [{"t": d["time"] * 1000, "lvl": d["level"], "by": d["killer"], "p": d["killer_is_player"],
                        "md": d.get("mostdamage"), "mdp": d.get("mostdamage_is_player")} for d in deaths.get("items", [])],
            "frags": [{"t": k["time"] * 1000, "who": k["name"], "lvl": k["level"], "unj": k["unjustified"],
                       "last": k["killer"] == c["name"]} for k in kills.get("items", [])],
        })
        time.sleep(0.3)
    json.dump({"updated": now, "chars": out}, open(os.path.join(OUT, "radar.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"radar: {len(out)} chars")


if __name__ == "__main__":
    main()
