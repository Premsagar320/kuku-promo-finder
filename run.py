"""run.py - find promos in every episode of a show.
usage: python run.py --input <folder with episode-*.txt> --out outputs [--limit N] [--top 25]
"""
import argparse
import csv
import json
import os

import candidates as C
import score as S
from parse import fmt, load_folder


def seg_str(c):
    return " + ".join(f"Ep{s['ep']} {fmt(s['start'])}-{fmt(s['end'])}" for s in c["segments"])


def final_score(c, r):
    llm = float(r.get("score", 0) or 0)
    h = min(10.0, c["heuristic"] * 10 / 9)          # heuristic roughly 0-9 -> 0-10
    sc = 0.8 * llm + 0.2 * h
    if not r.get("hook_in_first_3s", True):
        sc -= 1.0
    if float(r.get("standalone", 3) or 3) <= 2:
        sc -= 1.5
    return round(sc, 2)


def overlaps(a, b):
    for s in a["segments"]:
        for t in b["segments"]:
            if s["ep"] == t["ep"] and min(s["end"], t["end"]) - max(s["start"], t["start"]) > 1.0:
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--limit", type=int, default=None, help="only first N episodes (for testing)")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--max-per-episode", type=int, default=3)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    S.CACHE_PATH = os.path.join(a.out, "llm_cache.json")

    eps = load_folder(a.input, a.limit)
    by_num = {e["num"]: e for e in eps}
    print(f"parsed {len(eps)} episodes; provider={S.PROVIDER} model={S.MODEL}")
    cands = C.build_all(eps)
    print(f"{len(cands)} candidates after rule pre-filter")

    cache = S._cache()
    scored = []
    for n in sorted(by_num):
        mine = [c for c in cands if c["episode"] == n]
        res = S.score_episode(n, mine, by_num, cache)
        for c in mine:
            r = res.get(c["id"])
            if not r:
                continue
            c.update({"hook": r.get("hook", ""), "cliffhanger": r.get("cliffhanger", ""), "why": r.get("why", ""),
                      "llm_score": r.get("score"), "standalone": r.get("standalone"),
                      "hook_in_first_3s": r.get("hook_in_first_3s")})
            c["final"] = final_score(c, r)
            scored.append(c)
        print(f"  episode {n}: scored {len(res)}/{len(mine)}")

    scored.sort(key=lambda c: -c["final"])
    picked, per_ep = [], {}
    for c in scored:
        if per_ep.get(c["episode"], 0) >= a.max_per_episode or any(overlaps(c, p) for p in picked):
            continue
        picked.append(c)
        per_ep[c["episode"]] = per_ep.get(c["episode"], 0) + 1
        if len(picked) >= a.top:
            break
    for i, c in enumerate(picked, 1):
        c["rank"] = i

    cols = ["rank", "episode", "segments", "duration", "hook", "cliffhanger", "why", "final", "llm_score",
            "standalone", "hook_in_first_3s", "heuristic"]
    with open(os.path.join(a.out, "promos.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in picked:
            w.writerow([c["rank"], c["episode"], seg_str(c), c["duration"], c["hook"], c["cliffhanger"], c["why"],
                        c["final"], c["llm_score"], c["standalone"], c["hook_in_first_3s"], round(c["heuristic"], 1)])
    with open(os.path.join(a.out, "promos.json"), "w", encoding="utf-8") as f:
        json.dump([{k: c[k] for k in ["rank", "episode", "segments", "duration", "hook", "cliffhanger", "why",
                                      "final", "llm_score", "standalone", "hook_in_first_3s", "heuristic"]}
                   for c in picked], f, indent=2)
    with open(os.path.join(a.out, "all_scored_candidates.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "segments", "duration", "final", "llm_score", "heuristic", "hook", "cliffhanger", "why"])
        for c in scored:
            w.writerow([c["id"], seg_str(c), c["duration"], c["final"], c["llm_score"], round(c["heuristic"], 1),
                        c["hook"], c["cliffhanger"], c["why"]])
    with open(os.path.join(a.out, "promos.md"), "w", encoding="utf-8") as f:
        f.write(f"# Ranked promos ({len(picked)})  provider={S.PROVIDER} model={S.MODEL}\n\n")
        for c in picked:
            f.write(f"## #{c['rank']}  {seg_str(c)}  ({c['duration']}s)  score {c['final']}\n"
                    f"- **Hook:** {c['hook']}\n- **Cliffhanger:** {c['cliffhanger']}\n- **Why:** {c['why']}\n\n")
    print(f"\nwrote {len(picked)} ranked promos to {a.out}/ (promos.csv, promos.json, promos.md)")
    for c in picked[:5]:
        print(f"  #{c['rank']} {seg_str(c)} ({c['duration']}s) score {c['final']}")


if __name__ == "__main__":
    main()
