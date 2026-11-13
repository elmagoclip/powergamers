"""Coleta o ranking de XP do Olden 74 e gera rank.json com quem mais ganhou XP
nas janelas de 10 min a 24 h. Mantém um histórico compacto (history.json.gz)
com as coletas das últimas 25 horas."""
import gzip, json, os, sys, time, urllib.request, urllib.error

API = "https://olden74.com/api/community/rankings?skill=experience&limit=100&offset={}"
OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
WINDOWS = [10, 30, 60, 180, 360, 720, 1440]  # minutos
KEEP_MS = 25 * 3600 * 1000
TOP = 150
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; powergamers-olden74/1.0)",
        "Accept": "application/json"}


def fetch(off):
    last = None
    for i in range(5):
        try:
            req = urllib.request.Request(API.format(off), headers=HEAD)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # rede, 5xx, Cloudflare
            last = e
            time.sleep(4 + 4 * i)
    raise SystemExit(f"falha ao buscar offset {off}: {last}")


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

    rank = {"updated": now, "chars": len(chars), "snapshots": len(hist),
            "oldest": hist[0]["t"], "windows": windows}
    json.dump(rank, open(os.path.join(OUT, "rank.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    with gzip.open(hist_path, "wt", encoding="utf-8") as f:
        json.dump(hist, f, separators=(",", ":"))
    print(f"ok: {len(chars)} chars, {len(hist)} coletas, janelas {list(windows)}")


if __name__ == "__main__":
    main()
