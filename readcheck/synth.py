"""Synthetic talking-head projects, correct edits, and planted agent mistakes.

A project is one speech asset (word timestamps, retakes, hesitations) plus a music asset. The
correct edit follows the request; each mistake is planted either in the edit decision list (before
render, so later items ripple like a real edit) or in the rendered read-back. The expected failing
rules come from the planted mistake, never from the checker.
"""
import random

from .model import FPS, items, placed_words, speech_spans

LINES = [
    "so today I'm finally finishing the painting I started last month",
    "the first thing I do is block in the darkest shadows",
    "this brush is way too stiff for the sky so I'm switching",
    "honestly the underpainting is doing most of the work here",
    "I always mix a little blue into the greens",
    "let's speed this part up because it takes forever",
    "okay the light is changing so I have to move fast",
    "this is the part where it starts to look like something",
    "I'm going to leave the edges soft on purpose",
    "and that's it for today let me know what you think",
]
REQUESTS = {
    "rough_cut": ("Build the rough cut exactly as planned. Remove pauses over half a second and every retake. "
                  "Keep the last attempt of each line. No captions, no music, straight cuts. "
                  "Then read the timeline back with start and end times."),
    "polish": ("Remove pauses over half a second and every retake, keeping the last attempt of each line. "
               "Add 3-5 word phrase captions and duck the music to 25% under speech. "
               "Export a 9:16 version for TikTok at 1080x1920."),
}
CLAIM = {
    "rough_cut": "Done. Removed all pauses over 0.5s and every retake, kept the last take of each line. No captions, no music, straight cuts.",
    "polish": "Done. Removed all pauses and every retake, kept the last take, added 3-5 word captions synced to speech, ducked the music to 25%, exported 9:16 1080x1920.",
}
MUTATIONS = {
    "rough_cut": ["leave_pause", "first_take", "both_takes", "mid_word", "flash_frame", "black_gap", "transition",
                  "music_added", "caption_added"],
    "polish": ["leave_pause", "first_take", "both_takes", "mid_word", "flash_frame", "black_gap", "caption_drift",
               "caption_long", "caption_text", "no_duck", "wrong_canvas", "unsafe_caption"],
}
EXPECT = {  # rule that must fail, and other rules that may legitimately fail alongside
    "leave_pause": ({"max_pause"}, set()), "first_take": ({"retakes"}, set()), "both_takes": ({"retakes"}, set()),
    "mid_word": ({"mid_word_cut"}, {"caption_text"}), "flash_frame": ({"flash_frame"}, set()),
    "black_gap": ({"black_gap"}, set()), "transition": ({"straight_cuts"}, set()),
    "music_added": ({"no_track"}, set()), "caption_added": ({"no_track"}, set()),
    "caption_drift": ({"caption_sync"}, {"caption_text"}), "caption_long": ({"caption_words"}, set()),
    "caption_text": ({"caption_text"}, {"caption_sync"}), "no_duck": ({"duck"}, set()),
    "wrong_canvas": ({"format"}, {"safe_zone"}), "unsafe_caption": ({"safe_zone"}, set()),
}


def speech_asset(rng):
    words, t, plan = [], 0.6, []
    for li, line in enumerate(LINES):
        toks = line.split()
        attempts = 1 + (rng.random() < 0.35) + (rng.random() < 0.08)
        for at in range(attempts):
            last = at == attempts - 1
            n = len(toks) if last or rng.random() < 0.4 else rng.randint(3, max(3, len(toks) - 2))
            hes = rng.randint(3, n - 2) if (last and n > 6 and rng.random() < 0.35) else None
            ks = []
            for j in range(n):
                if hes is not None and j == hes:
                    t += rng.uniform(0.65, 1.1)  # hesitation inside the line
                w = toks[j] + ("." if last and j == n - 1 else "—" if not last and j == n - 1 else "")
                d = 0.11 + 0.045 * len(toks[j]) + rng.uniform(-0.03, 0.05)
                words.append({"w": w, "s": round(t, 3), "e": round(t + d, 3), "line": li, "attempt": at, "last": last})
                ks.append(len(words) - 1)
                t += d + (rng.uniform(0.38, 0.48) if rng.random() < 0.08 else rng.uniform(0.04, 0.18))  # some honest near-threshold pauses
            plan.append((li, at, last, ks))
            t += rng.uniform(0.75, 1.6)
    return {"kind": "speech", "duration": round(t + 0.5, 3), "words": words}, plan


def edl(asset, max_pause=0.5, pad=0.08):
    """Correct decisions: last attempts only, split at pauses over max_pause. Source segments."""
    W = asset["words"]
    keep = [k for k, w in enumerate(W) if w["last"]]
    segs, cur = [], [keep[0]]
    for a, b in zip(keep, keep[1:]):
        if b == a + 1 and W[b]["s"] - W[a]["e"] <= max_pause:
            cur.append(b)
        else:
            segs.append(cur)
            cur = [b]
    segs.append(cur)
    out = []
    for s in segs:
        k0, k1 = s[0], s[-1]
        lo = W[k0]["s"] - min(pad, (W[k0]["s"] - W[k0 - 1]["e"]) / 2 if k0 > 0 else pad)
        hi = W[k1]["e"] + min(pad, (W[k1 + 1]["s"] - W[k1]["e"]) / 2 if k1 + 1 < len(W) else pad)
        out.append({"in": round(lo, 3), "out": round(hi, 3), "speed": 1.0, "ks": s})
    return out


def render(asset, segs, kind, rng, slowmo=False, gap_after=None, transition_at=None):
    tl = {"canvas": {"w": 1080, "h": 1920, "fps": FPS}, "tracks": [{"id": "V1", "kind": "video", "items": []}]}
    t = 0.0
    for i, s in enumerate(segs):
        sp = 0.5 if (slowmo and i == 0) else s.get("speed", 1.0)
        dur = (s["out"] - s["in"]) / sp
        it = {"id": f"v{i + 1}", "asset": "talk", "start": round(t, 3), "end": round(t + dur, 3), "in": s["in"], "speed": sp}
        if transition_at == i:
            it["transition"] = "cross dissolve"
        tl["tracks"][0]["items"].append(it)
        t += dur + (0.25 if gap_after == i else 0.0)
    assets = {"talk": asset, "song": {"kind": "music", "duration": 600.0, "words": []}}
    if kind == "polish":
        add_captions(tl, assets)
        add_music(tl, assets)
    return tl, assets


def add_captions(tl, assets, speed_blind=False):
    words, _ = placed_words(tl, assets)
    if speed_blind:  # captions laid out as if the intro still played at 1x
        v = items(tl, "video")[0]
        blind = lambda t: v["start"] + (t - v["start"]) * v["speed"]
        words = [w if w["item"] != v["id"] else dict(w, t0=blind(w["t0"]), t1=blind(w["t1"])) for w in words]
    caps, chunk = [], []
    for w in words:
        chunk.append(w)
        end_line = w["w"].endswith((".", "—"))
        if len(chunk) == 4 or (end_line and len(chunk) >= 3):
            caps.append(chunk)
            chunk = []
    if chunk:
        if len(chunk) < 3 and caps:
            if len(caps[-1]) + len(chunk) <= 5:
                caps[-1] += chunk
            else:
                moved = caps[-1][-1:]
                caps[-1] = caps[-1][:-1]
                caps.append(moved + chunk)
        else:
            caps.append(chunk)
    tr = {"id": "C1", "kind": "caption", "items": []}
    for i, c in enumerate(caps):
        tr["items"].append({"id": f"cap{i + 1}", "start": round(c[0]["t0"], 3), "end": round(c[-1]["t1"], 3),
                            "text": " ".join(w["w"].strip(".—") for w in c), "x": 540, "y": 1150, "w": 760, "h": 140})
    tl["tracks"].append(tr)


def add_music(tl, assets, gain=0.25):
    words, _ = placed_words(tl, assets)
    end = max(it["end"] for it in items(tl, "video"))
    kf = [[0.0, 1.0]]
    for a, b in speech_spans(words):
        kf += [[round(max(a - 0.2, kf[-1][0]), 3), 1.0], [round(max(a - 0.05, kf[-1][0]), 3), gain],
               [round(b + 0.05, 3), gain], [round(b + 0.2, 3), 1.0]]
    tl["tracks"].append({"id": "A2", "kind": "audio", "role": "music",
                         "items": [{"id": "m1", "asset": "song", "start": 0.0, "end": end, "in": 0.0, "volume_kf": kf}]})


def scenario(seed, kind=None, mutation="random", benign=None):
    rng = random.Random(seed)
    kind = kind or rng.choice(["rough_cut", "polish"])
    asset, plan = speech_asset(rng)
    segs = edl(asset)
    if mutation == "random":
        mutation = None if rng.random() < 0.25 else rng.choice(MUTATIONS[kind])
    slowmo = kind == "polish" and (mutation == "caption_drift" or rng.random() < 0.3)
    W = asset["words"]
    gap_after = transition_at = None
    retakes = [p for p in plan if not p[2]]
    if mutation in ("first_take", "both_takes") and not retakes:
        mutation = "leave_pause"
    if mutation == "leave_pause":
        cands = [i for i in range(len(segs) - 1) if segs[i + 1]["ks"][0] == segs[i]["ks"][-1] + 1]
        if not cands:
            mutation = "mid_word"
        else:
            i = rng.choice(cands)
            segs[i] = {"in": segs[i]["in"], "out": segs[i + 1]["out"], "speed": 1.0, "ks": segs[i]["ks"] + segs[i + 1]["ks"]}
            del segs[i + 1]
    if mutation in ("first_take", "both_takes"):
        li, at, _, ks = rng.choice(retakes)
        last_ks = next(p[3] for p in plan if p[0] == li and p[2])
        first = {"in": round(W[ks[0]]["s"] - 0.06, 3), "out": round(W[ks[-1]]["e"] + 0.06, 3), "speed": 1.0, "ks": ks}
        pos = next(i for i, s in enumerate(segs) if s["ks"][0] in last_ks)
        if mutation == "first_take":
            segs = [s for s in segs if not set(s["ks"]) & set(last_ks)]
            segs.insert(pos, first)
        else:
            segs.insert(pos, first)
    if mutation == "mid_word":
        i = rng.randrange(len(segs))
        lw = W[segs[i]["ks"][-1]]
        segs[i] = dict(segs[i], out=round(lw["s"] + (lw["e"] - lw["s"]) * 0.45, 3))
    if mutation == "flash_frame":
        i = rng.randrange(len(segs) - 1)
        a = segs[i]["out"]
        silent = W[segs[i]["ks"][-1] + 1]["s"] - 0.02 if segs[i]["ks"][-1] + 1 < len(W) else a + 0.2
        if silent - a > 0.1:
            segs.insert(i + 1, {"in": round(a + 0.01, 3), "out": round(a + 0.01 + 2 / FPS, 3), "speed": 1.0, "ks": []})
        else:
            mutation = "black_gap"
    if mutation == "black_gap":
        gap_after = rng.randrange(len(segs) - 1)
    if mutation == "transition":
        transition_at = rng.randrange(1, len(segs))
    tl, assets = render(asset, segs, kind, rng, slowmo=slowmo, gap_after=gap_after, transition_at=transition_at)
    caps = next((tr for tr in tl["tracks"] if tr["kind"] == "caption"), None)
    if mutation == "caption_drift":
        before = {c["text"]: (c["start"], c["end"]) for c in caps["items"]}
        tl["tracks"] = [tr for tr in tl["tracks"] if tr["kind"] != "caption"]
        add_captions(tl, assets, speed_blind=True)
        tl["tracks"].insert(1, tl["tracks"].pop())
        drift = max(max(abs(c["start"] - before.get(c["text"], (c["start"], c["end"]))[0]),
                        abs(c["end"] - before.get(c["text"], (c["start"], c["end"]))[1])) for c in tl["tracks"][1]["items"])
        if drift < 0.2:  # the slowed intro was too short to move any caption: not a real mistake
            mutation = None
    if mutation == "caption_long" and caps:
        i = rng.randrange(len(caps["items"]) - 1)
        a, b = caps["items"][i], caps["items"].pop(i + 1)
        a["text"] += " " + b["text"]
        a["end"] = b["end"]
    if mutation == "caption_text" and caps:
        cut = [w["w"].strip(".—") for w in W if not w["last"]] or ["um", "so", "wait"]
        c = rng.choice(caps["items"])
        start = rng.randrange(max(1, len(cut) - 4))
        c["text"] = " ".join(cut[start:start + len(c["text"].split())])
        if not cut[start:]:
            c["text"] = "this was cut out"
    if mutation == "no_duck":
        m = items(tl, "audio", role="music")[0]
        kf = next(tr for tr in tl["tracks"] if tr.get("role") == "music")["items"][0]["volume_kf"]
        lows = [j for j, (t, g) in enumerate(kf) if g < 0.5]
        j = rng.choice(lows[: max(2, len(lows) // 2)] if len(lows) > 2 else lows)
        j = j - (j % 2 == 1 and kf[j - 1][1] < 0.5)
        for q in range(len(kf)):
            if kf[q][1] < 0.5 and abs(q - j) <= 1:
                kf[q][1] = 1.0
    if mutation == "wrong_canvas":
        tl["canvas"] = {"w": 1920, "h": 1080, "fps": FPS}
    if mutation == "unsafe_caption" and caps:
        for c in rng.sample(caps["items"], k=max(1, len(caps["items"]) // 4)):
            c["y"] = 1690
    if mutation == "music_added":
        add_music(tl, assets, gain=1.0)
    if mutation == "caption_added":
        add_captions(tl, assets)
    exp, ok_extra = EXPECT.get(mutation, (set(), set()))
    if slowmo:  # a 0.5x intro really does stretch a 0.45 s pause past 0.5 s on the timeline
        ok_extra = ok_extra | {"max_pause_stretched"}
    return {"seed": seed, "kind": kind, "mutation": mutation, "slowmo": slowmo, "request": REQUESTS[kind],
            "claim": CLAIM[kind], "timeline": tl, "assets": assets, "expect": exp, "may_also": ok_extra}


def frames_baseline(sc, times=(3.0, 15.0, 40.0)):
    """What 'capture frames at 0:03, 0:15 and 0:40' can show: canvas size, text position, black,
    a transition in progress, an extra caption or a flash frame landing exactly on a sampled time."""
    tl = sc["timeline"]
    found = set()
    vids = items(tl, "video")
    caps = items(tl, "caption")
    if sc["kind"] == "polish" and (tl["canvas"]["w"], tl["canvas"]["h"]) != (1080, 1920):
        found.add("format")
    for t in times:
        on = [c for c in caps if c["start"] <= t <= c["end"]]
        if sc["kind"] == "rough_cut" and on:
            found.add("no_track")
        if sc["kind"] == "polish" and any(c["y"] + c["h"] / 2 > 1920 * 0.8 for c in on):
            found.add("safe_zone")
        v = [it for it in vids if it["start"] <= t <= it["end"]]
        if not v and t < (vids[-1]["end"] if vids else 0):
            found.add("black_gap")
        if any(it.get("transition") and abs(t - it["start"]) < 0.5 for it in v):
            found.add("straight_cuts")
        if any((it["end"] - it["start"]) * FPS < 3 for it in v):
            found.add("flash_frame")
    return found
