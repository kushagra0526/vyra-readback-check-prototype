import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from readcheck.check import check, retake_groups  # noqa: E402
from readcheck.model import placed_words  # noqa: E402
from readcheck.rules import parse  # noqa: E402
from readcheck.synth import REQUESTS, frames_baseline, scenario  # noqa: E402


def run(sc):
    r = check(sc["request"], sc["timeline"], sc["assets"], sc["claim"])
    return {x["rule"] for x in r["failed"] if "stretched by" not in x["detail"]}, r


def test_vyra_published_prompt_parses_and_lists_unchecked():
    rules, unchecked = parse(REQUESTS["rough_cut"])
    names = [r["rule"] for r in rules]
    assert {"max_pause", "retakes", "no_track", "straight_cuts"} <= set(names) and names.count("retakes") == 1
    assert next(r for r in rules if r["rule"] == "max_pause")["max_s"] == 0.5
    assert unchecked == ["Build the rough cut exactly as planned."]


def test_clean_edits_pass():
    for seed in range(1, 6):
        for kind in ("rough_cut", "polish"):
            failed, _ = run(scenario(seed, kind, mutation=None))
            assert failed == set(), (seed, kind, failed)


def test_each_planted_mistake_is_caught():
    for m, kind in [("leave_pause", "rough_cut"), ("first_take", "rough_cut"), ("both_takes", "polish"),
                    ("mid_word", "rough_cut"), ("flash_frame", "rough_cut"), ("black_gap", "polish"),
                    ("transition", "rough_cut"), ("caption_long", "polish"), ("no_duck", "polish"),
                    ("wrong_canvas", "polish"), ("unsafe_caption", "polish"), ("music_added", "rough_cut")]:
        sc = scenario(11, kind, mutation=m)
        failed, _ = run(sc)
        assert sc["expect"] <= failed, (m, failed)
        assert not (failed - sc["expect"] - sc["may_also"]), (m, failed)


def test_caption_drift_after_speed_ramp():
    sc = next(s for s in (scenario(k, "polish", mutation="caption_drift") for k in range(1, 30)) if s["mutation"])
    failed, r = run(sc)
    assert "caption_sync" in failed and any("off" in x["detail"] for x in r["failed"])


def test_speed_maps_source_words_to_timeline():
    sc = scenario(3, "polish", mutation=None)
    tl = sc["timeline"]
    v = tl["tracks"][0]["items"][0]
    v["speed"] = 0.5
    v["end"] = v["start"] + (v["end"] - v["start"]) * 2
    words, _ = placed_words(tl, sc["assets"])
    w = next(x for x in words if x["item"] == v["id"])
    src = sc["assets"]["talk"]["words"][w["k"]]
    assert abs(w["t0"] - (v["start"] + (src["s"] - v["in"]) / 0.5)) < 1e-9


def test_retake_groups_find_restarts():
    sc = scenario(4, "rough_cut", mutation=None)
    words = sc["assets"]["talk"]["words"]
    groups = retake_groups(words)
    truth = {w["line"] for w in words if not w["last"]}
    found = {words[g[0][0]]["line"] for g in groups}
    assert truth == found


def test_frames_baseline_misses_timing_mistakes():
    sc = scenario(11, "rough_cut", mutation="leave_pause")
    assert "max_pause" not in frames_baseline(sc)
