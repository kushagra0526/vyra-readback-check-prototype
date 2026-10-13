"""One agent edit with several realistic mistakes -> out/report.html, out/report.json

    python demo.py

The agent got Vyra's published polish prompt, slowed the intro to 0.5x, said "Done", and its
read-back hides: a 0.9 s pause left in, captions not moved after the slow-mo, the music not ducked
under one line, and a caption under TikTok's bottom UI.
"""
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from readcheck.check import check  # noqa: E402
from readcheck.model import fmt, gain_at, items, placed_words, speech_spans  # noqa: E402
from readcheck.synth import add_captions, frames_baseline, scenario  # noqa: E402

e = html.escape


def build():
    seed = next(s for s in range(1, 200) if scenario(s, "polish", mutation="leave_pause")["slowmo"]
                and scenario(s, "polish", mutation="leave_pause")["mutation"] == "leave_pause"
                and scenario(s, "polish", mutation="caption_drift")["mutation"] == "caption_drift")
    sc = scenario(seed, "polish", mutation="leave_pause")
    tl, assets = sc["timeline"], sc["assets"]
    tl["tracks"] = [tr for tr in tl["tracks"] if tr["kind"] != "caption"]
    add_captions(tl, assets, speed_blind=True)          # captions laid out before the slow-mo
    tl["tracks"].insert(1, tl["tracks"].pop())
    kf = next(tr for tr in tl["tracks"] if tr.get("role") == "music")["items"][0]["volume_kf"]
    lows = [j for j, (t, g) in enumerate(kf) if g < 0.5]
    for j in lows[6:8]:                                  # one span of speech with music at full
        kf[j][1] = 1.0
    caps = next(tr for tr in tl["tracks"] if tr["kind"] == "caption")["items"]
    caps[len(caps) // 2]["y"] = 1690                     # one caption under the bottom UI
    return sc


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sc = build()
    r = check(sc["request"], sc["timeline"], sc["assets"], sc["claim"])
    fr = frames_baseline(sc)
    print(f"\n== Request:\n   {sc['request']}\n\n== Agent: {sc['claim']}\n")
    print("== readcheck")
    for x in r["results"]:
        if not x["ok"]:
            print(f"   ✗ {x['rule']:<13} {fmt(x['at']) if x['at'] is not None else '':>8}  {x['detail']}")
    print("   passed: " + ", ".join(sorted({x['rule'] for x in r['results'] if x['ok']} - {x['rule'] for x in r['failed']})))
    print(f"   not checked: {r['unchecked'] or 'nothing'}")
    print("\n== Agent's claims")
    for c in r["claims"]:
        print(f"   {c['verdict']:<6} \"{c['claim']}\"  {c.get('why', '')}")
    print(f"\n== Frames at 0:03 / 0:15 / 0:40 would show: {sorted(fr) or 'nothing wrong'}")
    ev = {w: json.loads((HERE / f'out/eval_{w}.json').read_text())["totals"] for w in ("dev", "heldout")
          if (HERE / f'out/eval_{w}.json').exists()}
    (HERE / "out/report.json").write_text(json.dumps({"request": sc["request"], "claim": sc["claim"], "check": r,
                                                      "frames_baseline": sorted(fr), "eval": ev}, indent=2, default=str))
    (HERE / "out/report.html").write_text(render(sc, r, fr, ev), encoding="utf-8")
    print("\nwrote out/report.html, out/report.json")


def strip(sc, r):
    tl, assets = sc["timeline"], sc["assets"]
    dur = max(it["end"] for it in items(tl, "video"))
    W, X0 = 1040, 70
    sx = lambda t: X0 + t / dur * W
    out = []
    for it in items(tl, "video"):
        col = "#7aa7d9" if it.get("speed", 1) == 1 else "#b48ad9"
        out.append(f'<rect x="{sx(it["start"]):.1f}" y="20" width="{max(1, sx(it["end"]) - sx(it["start"]) - 1):.1f}" height="34" fill="{col}" rx="3"/>')
    for c in items(tl, "caption"):
        out.append(f'<rect x="{sx(c["start"]):.1f}" y="62" width="{max(1, sx(c["end"]) - sx(c["start"]) - 1):.1f}" height="16" fill="#e2c46b" rx="2"/>')
    words, _ = placed_words(tl, assets)
    for a, b in speech_spans(words):
        out.append(f'<rect x="{sx(a):.1f}" y="86" width="{max(1, sx(b) - sx(a)):.1f}" height="8" fill="#9fc79f"/>')
    m = items(tl, "audio", role="music")[0]
    pts = " ".join(f"{sx(t):.1f},{150 - gain_at(m, t) * 44:.1f}" for t in [k * dur / 600 for k in range(601)])
    out.append(f'<polyline points="{pts}" fill="none" stroke="#c98a5a" stroke-width="1.6"/>')
    out.append(f'<line x1="{X0}" x2="{X0 + W}" y1="{150 - 0.25 * 44:.1f}" y2="{150 - 0.25 * 44:.1f}" stroke="#c98a5a" stroke-dasharray="3 3" opacity=".6"/>')
    for x in r["failed"]:
        if x["at"] is not None:
            out.append(f'<line x1="{sx(x["at"]):.1f}" x2="{sx(x["at"]):.1f}" y1="10" y2="156" stroke="#d6453a" stroke-width="2"/>'
                       f'<circle cx="{sx(x["at"]):.1f}" cy="10" r="5" fill="#d6453a"/>')
    labels = [("V1", 41), ("captions", 74), ("speech", 93), ("music", 132)]
    out += [f'<text x="{X0 - 8}" y="{y}" text-anchor="end" class="lab">{n}</text>' for n, y in labels]
    for k in range(0, int(dur) + 1, 5):
        out.append(f'<text x="{sx(k):.1f}" y="172" text-anchor="middle" class="tick">{k}s</text>')
    return f'<svg viewBox="0 0 1130 180" width="100%">{"".join(out)}</svg>'


def render(sc, r, fr, ev):
    rows = "".join(f'<tr class="bad"><td>✗</td><td>{e(x["rule"])}</td><td>{fmt(x["at"]) if x["at"] is not None else ""}</td><td>{e(x["detail"])}</td></tr>'
                   for x in r["failed"])
    passed = sorted({x["rule"] for x in r["results"] if x["ok"]} - {x["rule"] for x in r["failed"]})
    claims = "".join(f'<tr><td class="{"f" if c["verdict"] == "FALSE" else "t"}">{c["verdict"]}</td><td>“{e(c["claim"])}”</td><td>{e(c.get("why", ""))}</td></tr>'
                     for c in r["claims"])
    evrows = "".join(f"<tr><td>{'held-out (seeds frozen in git first)' if k == 'heldout' else 'dev'}</td><td>{v['scenarios']}</td><td>{v['planted']}</td>"
                     f"<td class='t'>{v['caught']}/{v['planted']}</td><td>{v['frames']}/{v['planted']}</td><td>0/{v['planted']}</td><td>{v['false_scen'] if 'false_scen' in v else 0}</td></tr>"
                     for k, v in ev.items())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Timeline read-back check</title><style>
:root{{--bg:#f5f4f0;--fg:#1e201d;--mut:#676a63;--card:#fff;--line:#e3e1d9;--bad:#b4402f;--ok:#2f7a4f}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:26px 16px 60px}}h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:18px;margin:28px 0 10px}}.sub,.mut{{color:var(--mut)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}.q{{border-left:4px solid #8aa6c9;padding-left:12px}}.said{{border-left:4px solid var(--ok);padding-left:12px;color:var(--ok)}}
table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{border-top:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}}tr.bad td{{color:var(--bad)}}
td.f{{color:var(--bad);font-weight:700}}td.t{{color:var(--ok);font-weight:700}}.lab{{font-size:12px;fill:var(--mut)}}.tick{{font-size:10.5px;fill:var(--mut)}}
</style></head><body><main>
<h1>The agent said "Done." Was it?</h1>
<div class="sub">Timeline read-back checked against the request and the transcript. Synthetic footage. Unofficial prototype by Kushagra Pratap Singh, not affiliated with Vyra.</div>
<div class="grid" style="margin-top:16px"><div class="card"><b>Request</b> <span class="mut">(Vyra's published polish prompt)</span><p class="q">{e(sc['request'])}</p></div>
<div class="card"><b>Agent</b><p class="said">{e(sc['claim'])}</p><div class="mut">Its edit also slowed the intro to 0.5x (purple).</div></div></div>
<h2>Timeline read-back</h2><div class="card">{strip(sc, r)}<div class="mut">Red markers = failed checks. Dashed line = 25% music.</div></div>
<h2>readcheck: {len(r['failed'])} problems</h2><div class="card"><table>{rows}</table>
<div class="mut" style="margin-top:8px">Passed: {', '.join(passed)}. Not checked: {e(', '.join(r['unchecked'])) or 'nothing'}.</div></div>
<div class="grid"><div><h2>The agent's claims</h2><div class="card"><table>{claims}</table></div></div>
<div><h2>"Capture frames at 0:03, 0:15, 0:40"</h2><div class="card">Would show: <b>{', '.join(sorted(fr)) or 'nothing wrong'}</b>. Pauses, takes, caption timing and ducking don't show in three stills.</div></div></div>
<h2>Mutation benchmark</h2><div class="card" style="overflow-x:auto"><table><tr><th>set</th><th>read-backs</th><th>with a planted mistake</th><th>readcheck caught</th><th>3 frames caught</th><th>trusting "Done"</th><th>wrong findings</th></tr>{evrows}</table></div>
</main></body></html>"""


if __name__ == "__main__":
    main()
