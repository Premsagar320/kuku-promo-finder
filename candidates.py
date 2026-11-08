"""candidates.py - build candidate promo clips with cheap rules (no AI).

A candidate is a list of segments [{ep, start, end}] whose total length is 20-60 s.
  * single-episode windows: start at a dialogue line / scene start, end at an item end
  * cross-episode joins: tail of episode N + head of episode N+1 (episodes are continuous)
A rule-based "heuristic" score keeps only the most promising ones per episode, so the
LLM (score.py) sees ~10 candidates per episode instead of hundreds.
"""
import re
from parse import fmt

MIN_LEN, MAX_LEN = 20.0, 60.0

HOOK_WORDS = ["slap", "scream", "gasp", "shock", "betray", "secret", "lie", "dead", "kill", "die", "blood",
              "divorce", "pregnan", "wedding", "marry", "married", "duke", "never", "how dare", "get out",
              "who are you", "what did you", "you!", "traitor", "poison", "arrest", "guards", "kneel", "mine",
              "truth", "reveal", "fired", "forgive", "mistake", "enough", "impossible", "heir", "baby"]
CLIFF_WORDS = ["secret", "truth", "who", "why", "dead", "alive", "poison", "arrest", "heir", "baby", "mine",
               "never", "tomorrow", "revenge", "regret", "pay", "ready or not"]
SOUND_CLIFF = ["sting", "ominous", "cliffhanger", "slam", "swell", "gasp", "silence", "drone", "crash"]
WEAK_START = re.compile(r"^(he|she|they|it|that|this|and|but|so|then|him|her|them)\b", re.I)


def has_long_silence(items, max_silence=5.0):
    """Check if there is a gap longer than max_silence between consecutive items."""
    for i in range(len(items) - 1):
        if items[i + 1]["start"] - items[i]["end"] > max_silence:
            return True
    return False


def _dialogue(items):
    return [it for it in items if it["kind"] == "dialogue"]


def hook_score(items, s):
    """How hooky is the first 3 seconds starting at s?"""
    first = [it for it in items if s - 0.01 <= it["start"] < s + 3.0]
    dlg = _dialogue(first)
    txt = " ".join(it["text"] for it in first).lower()
    sc = 0.0
    if dlg:
        sc += 2
        if len(dlg[0]["text"].split()) <= 9:
            sc += 1
        if "!" in dlg[0]["text"] or "?" in dlg[0]["text"]:
            sc += 1
        if WEAK_START.match(dlg[0]["text"].strip()):
            sc -= 1.0      # starts mid-thought -> probably needs context
    sc += min(3, sum(1 for w in HOOK_WORDS if w in txt))
    return sc


def cliff_score(items, e, ep_end):
    """How cliffhanger-like is the cut at time e?"""
    last = [it for it in items if e - 4.0 <= it["end"] <= e + 0.01]
    dlg = _dialogue(last)
    sc = 0.0
    if dlg:
        t = dlg[-1]["text"].strip()
        if t.endswith("?"):
            sc += 2
        elif t.endswith(("—", "-", "...", "…")):
            sc += 2
        elif t.endswith("!"):
            sc += 1
        low = t.lower()
        sc += min(2, sum(1 for w in CLIFF_WORDS if w in low))
    sounds = " ".join(it["text"].lower() for it in last if it["kind"] == "sound")
    if any(w in sounds for w in SOUND_CLIFF):
        sc += 1
    if ep_end - e <= 3.0:
        sc += 2            # clip runs to the end of an episode, which is written as a cliffhanger
    return sc


def fmt_items(items, ep_num, s, e, tag_ep=True):
    out = []
    for it in items:
        if it["start"] < s - 0.01 or it["start"] >= e - 0.01:
            continue
        t = f"[E{ep_num} {fmt(it['start'])}]" if tag_ep else f"[{fmt(it['start'])}]"
        if it["kind"] == "dialogue":
            out.append(f'{t} {it["speaker"]}: "{it["text"]}"')
        elif it["kind"] == "action":
            out.append(f"{t} (action) {it['text']}")
        elif it["kind"] == "sound":
            out.append(f"{t} (sound) {it['text']}")
        else:
            out.append(f"{t} (shot) {it['text'][:140]}")
    return "\n".join(out)


def _seg_items(ep, s, e):
    return [it for it in ep["items"] if s - 0.01 <= it["start"] < e - 0.01]


def _iou(a, b):
    """overlap of two single-episode candidates (by time)"""
    if a["segments"][0]["ep"] != b["segments"][0]["ep"] or len(a["segments"]) > 1 or len(b["segments"]) > 1:
        return 0.0
    a0, a1 = a["segments"][0]["start"], a["segments"][0]["end"]
    b0, b1 = b["segments"][0]["start"], b["segments"][0]["end"]
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = (a1 - a0) + (b1 - b0) - inter
    return inter / union if union else 0.0


def single_episode_candidates(ep, top_k=10):
    items = ep["items"]
    scene_starts = {round(sc["start"], 2) for sc in ep["scenes"]}
    starts = sorted({it["start"] for it in items if it["kind"] == "dialogue" or round(it["start"], 2) in scene_starts})
    ends = sorted({it["end"] for it in items if it["kind"] in ("dialogue", "action", "sound")})
    cands = []
    for s in starts:
        for e in ends:
            d = e - s
            if d < MIN_LEN or d > MAX_LEN:
                continue
            win = _seg_items(ep, s, e)
            if len(_dialogue(win)) < 3:
                continue
            if has_long_silence(win):
                continue
            h = hook_score(items, s)
            c = cliff_score(items, e, ep["duration"])
            bonus = 0.0
            if round(s, 2) in scene_starts:
                bonus += 1          # starting at a scene start gives self-contained context
            if len({it["speaker"] for it in _dialogue(win)}) >= 2:
                bonus += 1
            if 28 <= d <= 50:
                bonus += 0.5
            cands.append({"episode": ep["num"], "segments": [{"ep": ep["num"], "start": s, "end": e}],
                          "heuristic": h + c + bonus, "hook_h": h, "cliff_h": c, "kind": "single"})
    cands.sort(key=lambda x: -x["heuristic"])
    kept = []
    for c in cands:
        if all(_iou(c, k) < 0.5 for k in kept):
            kept.append(c)
        if len(kept) >= top_k:
            break
    return kept


def cross_episode_candidates(ep_a, ep_b, top_k=2):
    """Tail of ep_a (last 15-30s) + head of ep_b (first 15-30s). Total 20-60 s."""
    ia, ib = ep_a["items"], ep_b["items"]
    tails = sorted({it["start"] for it in ia if it["kind"] == "dialogue" and 6 <= ep_a["duration"] - it["start"] <= 30})
    heads = sorted({it["end"] for it in ib if it["kind"] in ("dialogue", "action") and 8 <= it["end"] <= 40})
    cands = []
    for s in tails:
        for e in heads:
            d = (ep_a["duration"] - s) + e
            if d < MIN_LEN or d > MAX_LEN:
                continue
            win_a = _seg_items(ep_a, s, ep_a["duration"])
            win_b = _seg_items(ep_b, 0.0, e)
            if has_long_silence(win_a) or has_long_silence(win_b):
                continue
            h = hook_score(ia, s)
            c = cliff_score(ib, e, ep_b["duration"])
            cands.append({"episode": ep_a["num"],
                          "segments": [{"ep": ep_a["num"], "start": s, "end": ep_a["duration"]},
                                       {"ep": ep_b["num"], "start": 0.0, "end": e}],
                          "heuristic": h + c, "hook_h": h, "cliff_h": c, "kind": "cross"})
    cands.sort(key=lambda x: -x["heuristic"])
    return cands[:top_k]


def build_text(eps_by_num, cand):
    parts = []
    for seg in cand["segments"]:
        ep = eps_by_num[seg["ep"]]
        parts.append(fmt_items(ep["items"], seg["ep"], seg["start"], seg["end"]))
    return "\n--- (cut to next segment) ---\n".join(parts)


def total_len(cand):
    return sum(s["end"] - s["start"] for s in cand["segments"])


def build_all(episodes, top_k=10, cross_k=2):
    by_num = {e["num"]: e for e in episodes}
    nums = sorted(by_num)
    allc = []
    for n in nums:
        cs = single_episode_candidates(by_num[n], top_k)
        if n + 1 in by_num:
            cs += cross_episode_candidates(by_num[n], by_num[n + 1], cross_k)
        for i, c in enumerate(cs):
            c["id"] = f"E{n:03d}-{i:02d}"
            c["duration"] = round(total_len(c), 1)
            c["text"] = build_text(by_num, c)
            assert MIN_LEN - 0.01 <= c["duration"] <= MAX_LEN + 0.01, c
        allc += cs
    return allc


if __name__ == "__main__":
    import sys
    from parse import load_folder
    eps = load_folder(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
    cs = build_all(eps)
    print(len(cs), "candidates")
    for c in cs[:3]:
        print(c["id"], c["duration"], round(c["heuristic"], 1), c["segments"])
        print(c["text"][:600], "\n")
