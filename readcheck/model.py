"""Timeline read-back model and source-time mapping.

The read-back is the JSON an agent gets from "view timeline state": canvas, tracks, items with
timeline start/end, source in-point and speed, volume keyframes, caption text and box. This format
is my own, modelled on Vyra's public docs (tracks, items, timing, speed, keyframes, captions).

Every check works in timeline seconds, but speech lives in source seconds. An item maps source
[in, in + (end - start) * speed] onto timeline [start, end], so a word at source s plays at
start + (s - in) / speed.
"""
FPS = 30


def items(tl, kind=None, role=None):
    out = []
    for tr in tl["tracks"]:
        if (kind is None or tr["kind"] == kind) and (role is None or tr.get("role") == role):
            out.extend(dict(it, track=tr["id"]) for it in tr["items"])
    return sorted(out, key=lambda it: it["start"])


def src_span(it):
    return it["in"], it["in"] + (it["end"] - it["start"]) * it.get("speed", 1.0)


def to_tl(it, s):
    return it["start"] + (s - it["in"]) / it.get("speed", 1.0)


def placed_words(tl, assets):
    """Words that play on V1, with timeline times. Also words cut part-way (mid-word cuts)."""
    out, partial = [], []
    for it in items(tl, "video"):
        if it["track"] != "V1":
            continue
        a, b = src_span(it)
        for k, w in enumerate(assets[it["asset"]]["words"]):
            if w["e"] <= a + 1e-6 or w["s"] >= b - 1e-6:
                continue
            row = {"w": w["w"], "k": k, "asset": it["asset"], "item": it["id"],
                   "t0": to_tl(it, max(w["s"], a)), "t1": to_tl(it, min(w["e"], b)), "line": w.get("line")}
            if w["s"] < a - 1e-6 or w["e"] > b + 1e-6:
                cut_at = a if w["s"] < a - 1e-6 else b
                partial.append({**row, "cut_src": cut_at, "at": to_tl(it, cut_at)})
            out.append(row)
    out.sort(key=lambda r: r["t0"])
    return out, partial


def speech_spans(words, join=0.35):
    spans = []
    for w in words:
        if spans and w["t0"] - spans[-1][1] <= join:
            spans[-1][1] = max(spans[-1][1], w["t1"])
        else:
            spans.append([w["t0"], w["t1"]])
    return spans


def gain_at(it, t):
    """Linear interpolation of [[t_timeline, gain], ...] keyframes; flat 'volume' otherwise."""
    kf = it.get("volume_kf")
    if not kf:
        return it.get("volume", 1.0)
    if t <= kf[0][0]:
        return kf[0][1]
    for (t0, g0), (t1, g1) in zip(kf, kf[1:]):
        if t0 <= t <= t1:
            return g0 + (g1 - g0) * (t - t0) / max(t1 - t0, 1e-9)
    return kf[-1][1]


def fmt(t):
    m, s = divmod(max(t, 0.0), 60)
    return f"{int(m)}:{s:05.2f}"
