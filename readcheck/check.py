"""Check a timeline read-back against the request, the transcript, and the agent's own claims."""
import re

from .model import FPS, fmt, gain_at, items, placed_words, speech_spans
from .rules import parse

# share of the 1080x1920 frame covered by platform UI (approximate public creator guidance)
SAFE = {"tiktok": {"top": 0.08, "bottom": 0.20, "right": 0.12, "left": 0.04},
        "reels": {"top": 0.10, "bottom": 0.18, "right": 0.10, "left": 0.04},
        "shorts": {"top": 0.08, "bottom": 0.16, "right": 0.12, "left": 0.04}}
ASPECT = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:5": (4, 5)}


def _norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def sentences(words, gap=0.7):
    """Split source words into spoken sentences (pause >= gap or sentence-final punctuation)."""
    out, cur = [], []
    for k, w in enumerate(words):
        if cur and (w["s"] - words[k - 1]["e"] >= gap or re.search(r"[.!?—]$|--$", words[k - 1]["w"])):
            out.append(cur)
            cur = []
        cur.append(k)
    if cur:
        out.append(cur)
    return out


def retake_groups(words):
    """Consecutive sentences that restart the same line: same opening or most words shared."""
    sents = sentences(words)
    toks = [[_norm(words[k]["w"]) for k in s] for s in sents]
    groups, i = [], 0
    while i < len(sents):
        g = [i]
        while g[-1] + 1 < len(sents):
            a, b = toks[g[-1]], toks[g[-1] + 1]
            sa, sb = set(a), set(b)
            same_start = len(a) >= 3 and a[:3] == b[:3]
            overlap = len(sa & sb) / max(1, min(len(sa), len(sb)))
            if same_start or overlap >= 0.75:
                g.append(g[-1] + 1)
            else:
                break
        if len(g) > 1:
            groups.append([sents[j] for j in g])
        i = g[-1] + 1
    return groups


def check(request, tl, assets, claim=""):
    rules, unchecked = parse(request)
    words, partial = placed_words(tl, assets)
    vids = [it for it in items(tl, "video") if it["track"] == "V1"]
    caps = items(tl, "caption")
    music = items(tl, "audio", role="music")
    end = max((it["end"] for it in vids), default=0.0)
    res = []

    def add(rule, ok, detail, at=None):
        res.append({"rule": rule["rule"], "ok": ok, "detail": detail, "at": at, "src": rule["src"]})

    for r in rules:
        k = r["rule"]
        if k == "max_pause":
            bad = [(a, b) for a, b in zip(words, words[1:]) if b["t0"] - a["t1"] > r["max_s"] + 1e-6]
            if bad:
                sp = {it["id"]: it.get("speed", 1.0) for it in vids}
                for a, b in bad:
                    note = f" (stretched by {sp[a['item']]:g}x speed)" if a["item"] == b["item"] and sp[a["item"]] < 1 else ""
                    add(r, False, f"{b['t0'] - a['t1']:.2f} s pause between \"{a['w']}\" and \"{b['w']}\"{note}", a["t1"])
            else:
                add(r, True, f"no pause over {r['max_s']} s")
        elif k == "retakes":
            n_bad = 0
            for asset_id, a in assets.items():
                if a.get("kind", "speech") != "speech":
                    continue
                kept = {(w["asset"], w["k"]) for w in words}
                for g in retake_groups(a["words"]):
                    keep_i = len(g) - 1 if r["keep"] == "last" else 0
                    on = [sum((asset_id, kk) in kept for kk in s) / len(s) for s in g]
                    wrong = [j for j, f in enumerate(on) if j != keep_i and f > 0.3]
                    missing = on[keep_i] < 0.8
                    if wrong or missing:
                        n_bad += 1
                        line = " ".join(a["words"][kk]["w"] for kk in g[keep_i])[:60]
                        what = []
                        if wrong:
                            what.append(f"attempt {', '.join(str(j + 1) for j in wrong)} of {len(g)} still in")
                        if missing:
                            what.append(f"the {r['keep']} attempt is {'partly ' if on[keep_i] > 0 else ''}missing")
                        t = next((w["t0"] for w in words if w["asset"] == asset_id and w["k"] in g[wrong[0] if wrong else keep_i]), None)
                        add(r, False, f"\"{line}…\": {'; '.join(what)}", t)
            if not n_bad:
                add(r, True, f"every retake group keeps only the {r['keep']} attempt")
        elif k == "no_track":
            present = caps if r["what"] == "caption" else music
            add(r, not present, f"{len(present)} {r['what']} item(s) on the timeline" if present else f"no {r['what']}")
        elif k == "straight_cuts":
            tr = [it for it in vids if it.get("transition")]
            add(r, not tr, f"{len(tr)} transition(s): " + ", ".join(f"{it['transition']} at {fmt(it['start'])}" for it in tr) if tr else "all straight cuts",
                tr[0]["start"] if tr else None)
        elif k == "caption_words":
            bad = [c for c in caps if not (r["min"] <= len(c["text"].split()) <= r["max"])]
            for c in bad:
                add(r, False, f"{len(c['text'].split())}-word caption \"{c['text']}\"", c["start"])
            if not bad:
                add(r, True, f"all {len(caps)} captions have {r['min']}-{r['max']} words" if caps else "no captions on timeline")
            if not caps:
                res[-1]["ok"] = False
        elif k == "caption_sync":
            bad = 0
            for c in caps:
                spoken = [w for w in words if w["t1"] > c["start"] - 0.5 and w["t0"] < c["end"] + 0.5]
                first = _norm(c["text"].split()[0]) if c["text"].split() else ""
                hit = next((w for w in spoken if _norm(w["w"]) == first), None)
                if hit is None:
                    hit = next((w for w in words if _norm(w["w"]) == first and abs(w["t0"] - c["start"]) < 3.0), None)
                if hit is None or abs(hit["t0"] - c["start"]) > r["tol_s"]:
                    bad += 1
                    off = f"{c['start'] - hit['t0']:+.2f} s off \"{hit['w']}\"" if hit else "word not found nearby"
                    add(r, False, f"caption \"{c['text']}\" at {fmt(c['start'])}: {off}", c["start"])
            if not bad:
                add(r, bool(caps), f"{len(caps)} captions start within {r['tol_s']} s of their words" if caps else "no captions on timeline")
        elif k == "duck":
            spans = speech_spans(words)
            bad = []
            for m in music:
                for a, b in spans:
                    for t in [a + (b - a) * x / 8 for x in range(9)]:
                        if m["start"] <= t <= m["end"] and gain_at(m, t) > r["max_gain"] + 0.01:
                            bad.append((t, gain_at(m, t)))
                            break
            if not music:
                add(r, False, "no music track to duck")
            elif bad:
                for t, g in bad:
                    add(r, False, f"music at {g:.0%} under speech (limit {r['max_gain']:.0%})", t)
            else:
                add(r, True, f"music ≤ {r['max_gain']:.0%} under all {len(spans)} speech spans")
        elif k == "format":
            cw, ch = tl["canvas"]["w"], tl["canvas"]["h"]
            ok = True
            if "aspect" in r:
                aw, ah = ASPECT[r["aspect"]]
                ok &= abs(cw / ch - aw / ah) < 0.01
            if "w" in r:
                ok &= (cw, ch) == (r["w"], r["h"])
            add(r, ok, f"canvas {cw}x{ch}" + ("" if ok else f", asked {r.get('aspect', '')} {r.get('w', '')}{'x' if 'w' in r else ''}{r.get('h', '')}"))
        elif k == "safe_zone":
            z = SAFE[{"reel": "reels", "instagram": "reels", "youtube shorts": "shorts"}.get(r["platform"], r["platform"])] if r["platform"] not in SAFE else SAFE[r["platform"]]
            cw, ch = tl["canvas"]["w"], tl["canvas"]["h"]
            bad = []
            for c in caps + items(tl, "text"):
                x0, y0 = c["x"] - c["w"] / 2, c["y"] - c["h"] / 2
                x1, y1 = x0 + c["w"], y0 + c["h"]
                where = [n for n, hit in (("bottom UI", y1 > ch * (1 - z["bottom"])), ("top UI", y0 < ch * z["top"]),
                                          ("right-side buttons", x1 > cw * (1 - z["right"])), ("left edge", x0 < cw * z["left"])) if hit]
                if where:
                    bad.append((c, where))
            for c, where in bad[:5]:
                add(r, False, f"\"{c['text']}\" overlaps {r['platform']} {', '.join(where)}", c["start"])
            if len(bad) > 5:
                res[-1]["detail"] += f" (+{len(bad) - 5} more)"
            if not bad:
                add(r, True, f"all text inside the {r['platform']} safe zone")
        elif k == "overlay_duration":
            lt = [it for it in items(tl, "text") if it.get("style") == r["kind"]]
            ok = bool(lt) and all(abs((it["end"] - it["start"]) - r["secs"]) <= 0.2 for it in lt)
            add(r, ok, ", ".join(f"{it['end'] - it['start']:.1f} s" for it in lt) or "no lower third found")
        elif k == "mid_word_cut":
            for p in partial:
                add(r, False, f"cut inside \"{p['w']}\"", p["at"])
            if not partial:
                add(r, True, "no cut lands inside a word")
        elif k == "flash_frame":
            fl = [it for it in vids if (it["end"] - it["start"]) * FPS < 3]
            for it in fl:
                add(r, False, f"{(it['end'] - it['start']) * FPS:.0f}-frame clip", it["start"])
            if not fl:
                add(r, True, "no clip shorter than 3 frames")
        elif k == "black_gap":
            gaps = [(a["end"], b["start"]) for a, b in zip(vids, vids[1:]) if b["start"] - a["end"] > 1 / FPS]
            if vids and vids[0]["start"] > 1 / FPS:
                gaps.insert(0, (0.0, vids[0]["start"]))
            for a, b in gaps:
                add(r, False, f"{b - a:.2f} s of black", a)
            if not gaps:
                add(r, True, "picture covers the whole timeline")
        elif k == "caption_text":
            bad = 0
            for c in caps:
                spoken = [_norm(w["w"]) for w in words if w["t1"] > c["start"] - 0.3 and w["t0"] < c["end"] + 0.3]
                ct = [_norm(x) for x in c["text"].split()]
                miss = [x for x in ct if x not in spoken]
                if len(miss) > len(ct) / 3:
                    bad += 1
                    add(r, False, f"caption \"{c['text']}\" doesn't match what's said there", c["start"])
            if not bad:
                add(r, True, "caption text matches the speech under it" if caps else "no captions")
    out = {"rules": rules, "unchecked": unchecked, "results": res, "duration": end,
           "failed": [x for x in res if not x["ok"]]}
    out["claims"] = check_claims(claim, out)
    return out


CLAIMS = [
    (r"(removed|cut|trimmed) (all |every |the )?(\d+ )?pauses", "max_pause"),
    (r"(removed|cut) (all |every |the )?(\d+ )?retakes|kept the (last|final) (take|attempt)", "retakes"),
    (r"captions? (are |were )?(synced|timed|aligned)|synced captions", "caption_sync"),
    (r"\d+\s*-\s*\d+ word (phrase )?captions", "caption_words"),
    (r"duck(ed)? (the )?music", "duck"),
    (r"(exported|export(ed)? (at|in|as)) (9:16|1080x1920)|9:16", "format"),
    (r"straight cuts|no transitions", "straight_cuts"),
    (r"no (captions|music)", "no_track"),
]


def check_claims(claim, out):
    verdicts = []
    for pat, rule in CLAIMS:
        m = re.search(pat, claim, re.I)
        if not m:
            continue
        rs = [x for x in out["results"] if x["rule"] == rule]
        if not rs:
            verdicts.append({"claim": m.group(0), "rule": rule, "verdict": "NOT CHECKED"})
        else:
            bad = [x for x in rs if not x["ok"]]
            verdicts.append({"claim": m.group(0), "rule": rule, "verdict": "FALSE" if bad else "TRUE",
                             "why": bad[0]["detail"] if bad else rs[0]["detail"]})
    return verdicts
