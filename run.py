"""run.py - find promos in microdrama screenplays.
usage: python run.py --input <folder with episode-*.txt> --out outputs [--limit N] [--top 20]
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
    standalone = float(r.get("standalone_score", r.get("standalone", 3)) or 3)
    if standalone <= 2:
        sc -= 1.5
    return round(sc, 2)


def overlaps(a, b):
    """Check if candidate a overlaps candidate b in any segment."""
    for s in a["segments"]:
        for t in b["segments"]:
            if s["ep"] == t["ep"] and min(s["end"], t["end"]) - max(s["start"], t["start"]) > 1.0:
                return True
    return False


def main():
    ap = argparse.ArgumentParser(description="Find promo clips in microdrama screenplays.")
    ap.add_argument("--input", required=True, help="Path to folder containing episode-*.txt files")
    ap.add_argument("--out", default="outputs", help="Output directory (default: outputs)")
    ap.add_argument("--limit", type=int, default=None, help="Only process first N episodes (for testing)")
    ap.add_argument("--top", type=int, default=20, help="Number of top promos to keep (default: 20)")
    ap.add_argument("--max-per-episode", type=int, default=3, help="Max promos allowed from a single episode")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    S.CACHE_PATH = os.path.join(a.out, "llm_cache.json")

    eps = load_folder(a.input, a.limit)
    by_num = {e["num"]: e for e in eps}
    print(f"Parsed {len(eps)} episodes; provider={S.PROVIDER} model={S.MODEL}")
    cands = C.build_all(eps)
    print(f"{len(cands)} candidates generated after rule pre-filter (~{len(cands)//len(eps) if eps else 0} per episode)")

    cache = S._cache()
    scored = []
    for n in sorted(by_num):
        mine = [c for c in cands if c["episode"] == n]
        res = S.score_episode(n, mine, by_num, cache)
        for c in mine:
            r = res.get(c["id"])
            if not r:
                continue
            standalone_val = r.get("standalone_score", r.get("standalone", 3))
            c.update({
                "hook": r.get("hook", ""),
                "cliffhanger": r.get("cliffhanger", ""),
                "why": r.get("why", ""),
                "llm_score": r.get("score"),
                "standalone_score": standalone_val,
                "hook_in_first_3s": r.get("hook_in_first_3s"),
            })
            c["score"] = final_score(c, r)
            c["final"] = c["score"]
            scored.append(c)
        print(f"  Episode {n:>2}: scored {len(res)}/{len(mine)}")

    # Rank by score descending
    scored.sort(key=lambda c: -c["score"])

    # Deduplicate overlapping candidates and keep top N
    picked, per_ep = [], {}
    for c in scored:
        # Validate promo duration must strictly be 20-60 seconds
        assert 20.0 <= c["duration"] <= 60.0, f"Promo {c['id']} duration {c['duration']}s out of bounds [20, 60]"
        if per_ep.get(c["episode"], 0) >= a.max_per_episode or any(overlaps(c, p) for p in picked):
            continue
        picked.append(c)
        per_ep[c["episode"]] = per_ep.get(c["episode"], 0) + 1
        if len(picked) >= a.top:
            break

    for i, c in enumerate(picked, 1):
        c["rank"] = i
        c["episodes"] = sorted(list({s["ep"] for s in c["segments"]}))
        # Format segments with timestamps
        c["formatted_segments"] = [
            {
                "ep": s["ep"],
                "start": fmt(s["start"]),
                "end": fmt(s["end"]),
                "start_sec": s["start"],
                "end_sec": s["end"],
            }
            for s in c["segments"]
        ]

    # Write CSV output
    cols = ["rank", "episodes", "segments", "duration", "score", "hook", "cliffhanger", "why",
            "llm_score", "standalone_score", "hook_in_first_3s", "heuristic"]
    with open(os.path.join(a.out, "promos.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in picked:
            ep_str = ", ".join(str(e) for e in c["episodes"])
            w.writerow([
                c["rank"], ep_str, seg_str(c), c["duration"], c["score"],
                c["hook"], c["cliffhanger"], c["why"], c["llm_score"],
                c["standalone_score"], c["hook_in_first_3s"], round(c["heuristic"], 1)
            ])

    # Write JSON output
    with open(os.path.join(a.out, "promos.json"), "w", encoding="utf-8") as f:
        json_data = [
            {
                "rank": c["rank"],
                "episodes": c["episodes"],
                "segments": c["formatted_segments"],
                "duration": c["duration"],
                "score": c["score"],
                "hook": c["hook"],
                "cliffhanger": c["cliffhanger"],
                "why": c["why"],
                "llm_score": c["llm_score"],
                "standalone_score": c["standalone_score"],
                "hook_in_first_3s": c["hook_in_first_3s"],
                "heuristic": round(c["heuristic"], 1),
            }
            for c in picked
        ]
        json.dump(json_data, f, indent=2)

    # Write all scored candidates for auditing
    with open(os.path.join(a.out, "all_scored_candidates.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "segments", "duration", "score", "llm_score", "heuristic", "hook", "cliffhanger", "why"])
        for c in scored:
            w.writerow([c["id"], seg_str(c), c["duration"], c["score"], c["llm_score"], round(c["heuristic"], 1),
                        c["hook"], c["cliffhanger"], c["why"]])

    # Write Markdown report
    with open(os.path.join(a.out, "promos.md"), "w", encoding="utf-8") as f:
        f.write(f"# Ranked Promos ({len(picked)})  provider={S.PROVIDER} model={S.MODEL}\n\n")
        for c in picked:
            ep_str = ", ".join(str(e) for e in c["episodes"])
            f.write(
                f"## #{c['rank']}  {seg_str(c)}  ({c['duration']}s) - Score: {c['score']}\n"
                f"- **Episode(s):** {ep_str}\n"
                f"- **Duration:** {c['duration']}s\n"
                f"- **Hook:** {c['hook']}\n"
                f"- **Cliffhanger:** {c['cliffhanger']}\n"
                f"- **Why:** {c['why']}\n\n"
            )

    print(f"\nWrote {len(picked)} ranked promos to {a.out}/ (promos.csv, promos.json, promos.md)")

    # Print summary
    print("\n" + "=" * 80)
    print(f"PROMO SUMMARY: Top {len(picked)} Selected Promos")
    print("=" * 80)
    for c in picked:
        ep_str = ", ".join(str(e) for e in c["episodes"])
        print(f"#{c['rank']:>2} | Ep {ep_str:<6} | {c['duration']:>4.1f}s | Score: {c['score']:>4.2f} | {seg_str(c)}")
        print(f"    Hook:        {c['hook']}")
        print(f"    Cliffhanger: {c['cliffhanger']}")
        print(f"    Why:         {c['why']}")
        print("-" * 80)


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
