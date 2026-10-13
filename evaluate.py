"""Mutation benchmark: planted agent mistakes in timeline read-backs.

    python evaluate.py dev        # seeds 1-200, used while building
    python evaluate.py heldout    # seeds in eval/heldout.json, committed before the first held-out run

Per scenario (25% clean, else one planted mistake): did readcheck flag the rule the mistake breaks,
did it flag anything else (false findings), and is the agent's "Done ..." message caught as false?
Baselines: trust the agent's message (catches nothing), and the frames check Vyra suggests
("Capture frames at 0:03, 0:15, and 0:40").
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from readcheck.check import check  # noqa: E402
from readcheck.synth import frames_baseline, scenario  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    seeds = range(1, 201) if which == "dev" else json.loads((HERE / "eval/heldout.json").read_text())["seeds"]
    per = defaultdict(Counter)
    tot = Counter()
    misses = []
    for seed in seeds:
        sc = scenario(seed)
        r = check(sc["request"], sc["timeline"], sc["assets"], sc["claim"])
        failed = {x["rule"] + ("_stretched" if "stretched by" in x["detail"] else "") for x in r["failed"]}
        if "max_pause_stretched" in failed and "max_pause" in sc["expect"]:
            failed.add("max_pause")
        m = sc["mutation"] or "clean"
        per[m]["n"] += 1
        tot["scenarios"] += 1
        if sc["mutation"]:
            caught = sc["expect"] <= failed
            per[m]["caught"] += caught
            per[m]["frames"] += bool(sc["expect"] & frames_baseline(sc))
            tot["planted"] += 1
            tot["caught"] += caught
            tot["frames"] += bool(sc["expect"] & frames_baseline(sc))
            if not caught:
                misses.append({"seed": seed, "mutation": m, "failed": sorted(failed)})
        extra = failed - sc["expect"] - sc["may_also"]
        if extra:
            per[m]["false"] += 1
            tot["false_scen"] += 1
            misses.append({"seed": seed, "mutation": m, "false": sorted(extra),
                           "detail": [x["detail"] for x in r["failed"] if x["rule"] in extra][:3]})
        if not sc["mutation"]:
            tot["clean"] += 1
            tot["clean_flagged"] += bool(failed)
    print(f"\n== {which}: {tot['scenarios']} read-backs, {tot['planted']} with a planted agent mistake, {tot['clean']} clean")
    print(f"   agent said \"Done\" on all of them")
    print(f"   mistakes caught:  readcheck {tot['caught']}/{tot['planted']}  ·  frames at 0:03/0:15/0:40 {tot['frames']}/{tot['planted']}  ·  trusting the message 0/{tot['planted']}")
    print(f"   (stretched-pause findings under a 0.5x intro are real and counted as allowed, not hidden)")
    print(f"   read-backs with any wrong finding: {tot['false_scen']}  (clean ones flagged: {tot['clean_flagged']}/{tot['clean']})")
    print(f"\n   {'mistake':<16}{'n':>4}{'readcheck':>11}{'frames':>8}{'false':>7}")
    for m in sorted(per, key=lambda k: (k == "clean", k)):
        c = per[m]
        print(f"   {m:<16}{c['n']:>4}{c['caught']:>11}{c['frames']:>8}{c['false']:>7}")
    for x in misses[:20]:
        print("   MISS", x)
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / f"out/eval_{which}.json").write_text(json.dumps(
        {"totals": dict(tot), "per_mutation": {k: dict(v) for k, v in per.items()}, "misses": misses}, indent=2))


if __name__ == "__main__":
    main()
