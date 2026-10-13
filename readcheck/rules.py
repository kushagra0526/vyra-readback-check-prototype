"""Turn the user's edit request into checkable rules.

Patterns follow the prompts Vyra publishes on https://usevyra.com/mcp. A sentence that matches
nothing becomes NOT CHECKED, listed in the report, never silently passed. Hygiene rules (mid-word
cuts, flash frames, black gaps, caption text = speech) always run.
"""
import re

PLATFORM = r"(tiktok|reels?|instagram|shorts|youtube shorts)"
SKIP = re.compile(r"\b(read the timeline back|tell me when|wait for my ok|then show me|summari[sz]e)\b", re.I)


def _secs(s):
    s = s.lower().strip()
    if "half a second" in s:
        return 0.5
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ms|milliseconds?)", s)
    if m:
        return float(m.group(1)) / 1000
    m = re.search(r"(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?)?\b", s)
    return float(m.group(1)) if m else None


def parse(request):
    rules, unchecked = [], []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", request.strip()):
        s = sent.strip()
        if not s:
            continue
        got = []
        m = re.search(r"pauses? (?:over|longer than|above|more than|of more than)\s+(half a second|[\d.]+\s*(?:ms|milliseconds?|s|sec|secs|seconds?))", s, re.I)
        if m:
            got.append({"rule": "max_pause", "max_s": _secs(m.group(1)), "src": s})
        if re.search(r"\b(every|all|the) retakes?\b|\bremove retakes\b", s, re.I) or re.search(r"keep(?:ing)? the (last|final|first) (attempt|take)", s, re.I):
            keep = re.search(r"keep(?:ing)? the (last|final|first) (attempt|take)", s, re.I)
            got.append({"rule": "retakes", "keep": (keep.group(1).lower() if keep else "last").replace("final", "last"), "src": s})
        if re.search(r"\bno captions?\b", s, re.I):
            got.append({"rule": "no_track", "what": "caption", "src": s})
        if re.search(r"\bno music\b", s, re.I):
            got.append({"rule": "no_track", "what": "music", "src": s})
        if re.search(r"\bstraight cuts\b|\bno transitions\b", s, re.I):
            got.append({"rule": "straight_cuts", "src": s})
        m = re.search(r"(\d+)\s*(?:-|to|–)\s*(\d+)[\s-]*word (?:phrase )?captions", s, re.I)
        if m:
            got.append({"rule": "caption_words", "min": int(m.group(1)), "max": int(m.group(2)), "src": s})
            got.append({"rule": "caption_sync", "tol_s": 0.15, "src": s})
        elif re.search(r"\b(word[- ]by[- ]word|add|with) captions\b", s, re.I):
            got.append({"rule": "caption_sync", "tol_s": 0.15, "src": s})
        m = re.search(r"duck (?:the )?music (?:down )?to (\d+)\s*%(?: under (?:the )?(?:speech|voice|dialogue))?", s, re.I)
        if m:
            got.append({"rule": "duck", "max_gain": int(m.group(1)) / 100, "src": s})
        m = re.search(r"\b(9:16|16:9|1:1|4:5)\b", s)
        r = re.search(r"\b(\d{3,4})\s*[x×]\s*(\d{3,4})\b", s)
        if m or r:
            fr = {"rule": "format", "src": s}
            if m:
                fr["aspect"] = m.group(1)
            if r:
                fr["w"], fr["h"] = int(r.group(1)), int(r.group(2))
            got.append(fr)
        p = re.search(r"\bfor " + PLATFORM + r"\b|\b" + PLATFORM + r" (?:version|export|cut)\b", s, re.I)
        if p:
            got.append({"rule": "safe_zone", "platform": (p.group(1) or p.group(2)).lower(), "src": s})
        m = re.search(r"lower third.*?for (\d+(?:\.\d+)?) seconds?", s, re.I)
        if m:
            got.append({"rule": "overlay_duration", "kind": "lower_third", "secs": float(m.group(1)), "src": s})
        if got:
            rules.extend(got)
        elif not SKIP.search(s):
            unchecked.append(s)
    seen, uniq = set(), []
    for r in rules:  # "remove every retake" + "keep the last attempt" are one rule
        key = (r["rule"],) + tuple(sorted((k, str(v)) for k, v in r.items() if k != "src"))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    rules = uniq
    # 9:16 export for vertical platforms implies the platform safe zone
    if any(r["rule"] == "format" and r.get("aspect") == "9:16" for r in rules) and not any(r["rule"] == "safe_zone" for r in rules):
        rules.append({"rule": "safe_zone", "platform": "tiktok", "src": "(implied by 9:16)"})
    for h in ("mid_word_cut", "flash_frame", "black_gap", "caption_text"):
        rules.append({"rule": h, "src": "(always)"})
    return rules, unchecked
