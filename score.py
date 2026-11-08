"""score.py - ask an LLM to judge the candidate clips of ONE episode in one call.

The model is swappable via .env:
  LLM_PROVIDER = gemini (default) | openai (any OpenAI-compatible API) | mock (no key, rules only)
  MODEL_NAME   = e.g. gemini-2.0-flash
Results are cached in outputs/llm_cache.json so re-runs cost nothing.
"""
import hashlib
import json
import os
import re
import time

from dotenv import load_dotenv

load_dotenv()
PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
MODEL = os.getenv("MODEL_NAME", "gemini-2.0-flash")
SLEEP = float(os.getenv("RATE_SLEEP", "4"))   # seconds between calls (free-tier rate limits)
CACHE_PATH = os.getenv("CACHE_PATH", "outputs/llm_cache.json")

PROMPT = """You are a social-media editor for a vertical microdrama app (like ReelShort / DramaBox).
You pick PROMO clips (20-60 s) that make cold viewers install the app.
A good promo:
 1. HOOK: something in the first 3 seconds makes a scrolling viewer stop (slap, reveal, shocking line, humiliation).
 2. CLIFFHANGER: it cuts at an unresolved moment, so the viewer must know what happens next.
 3. STANDALONE: someone who has never seen the show understands who is fighting about what.
 Penalise clips that open mid-conversation needing earlier context, that end with the conflict resolved,
 or that are just slow talk. Reward clear stakes, a clear villain, and an unresolved last beat.

Show context (episode {ep}): {logline}
Previous episode ended / continuity notes: {prev}

Below are {n} candidate clips from this episode. Timestamps are [E<episode> mm:ss.s].
{blocks}

Return ONLY a JSON list with one object per candidate, in this form:
[{{"id": "<candidate id>", "hook": "<what happens in first 3s, <=20 words>", "hook_in_first_3s": true/false,
   "cliffhanger": "<what is left unresolved at the cut, <=20 words>", "standalone_score": 1-5,
   "score": 1-10, "why": "<one line why it works or not>"}}]
Be strict: most candidates should score 6 or lower. Use only what is written above; do not invent plot."""


def _cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(c):
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(c, f)


def call_llm(prompt):
    """The ONLY place that talks to a model. Swap provider/model here or in .env."""
    if PROVIDER == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel(MODEL, generation_config={"temperature": 0.2,
                                                                "response_mime_type": "application/json"})
        return model.generate_content(prompt).text
    if PROVIDER == "openai":
        from openai import OpenAI
        client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL"), api_key=os.environ["OPENAI_API_KEY"])
        r = client.chat.completions.create(model=MODEL, temperature=0.2,
                                           messages=[{"role": "user", "content": prompt}])
        return r.choices[0].message.content
    raise ValueError(f"unknown LLM_PROVIDER {PROVIDER}")


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start:end + 1])


def mock_scores(cands, by_num):
    """No-API fallback: uses only the rule-based heuristic. Flagged as 'mock' in the output."""
    out = {}
    for c in cands:
        lines = c["text"].splitlines()
        out[c["id"]] = {
            "id": c["id"],
            "hook": lines[0][:120] if lines else "",
            "hook_in_first_3s": c["hook_h"] >= 3,
            "cliffhanger": lines[-1][:120] if lines else "",
            "standalone_score": 3,
            "standalone": 3,
            "score": round(min(10, c["heuristic"] * 0.9), 1),
            "why": "rule-based score only (mock mode)",
        }
    return out


def score_episode(ep_num, cands, by_num, cache):
    """Score all candidates whose primary episode is ep_num. Returns {cand_id: fields}."""
    if not cands:
        return {}
    if PROVIDER == "mock":
        return mock_scores(cands, by_num)

    # First check: can all candidates be resolved from cache?
    id_map = {}
    for v in cache.values():
        if isinstance(v, list):
            for r in v:
                if isinstance(r, dict) and "id" in r:
                    id_map[r["id"]] = r

    if all(c["id"] in id_map for c in cands):
        res = {}
        for c in cands:
            r = dict(id_map[c["id"]])
            r["standalone_score"] = r.get("standalone_score", r.get("standalone", 3))
            res[c["id"]] = r
        return res

    ep = by_num[ep_num]
    prev = by_num.get(ep_num - 1)
    prev_txt = (prev["continuity"] or prev["logline"]) if prev else "(this is the first episode)"
    blocks = "\n\n".join(f"### {c['id']}  ({c['duration']}s)\n{c['text']}" for c in cands)
    prompt = PROMPT.format(ep=ep_num, logline=ep["logline"], prev=prev_txt, n=len(cands), blocks=blocks)
    key = hashlib.sha256((MODEL + prompt).encode()).hexdigest()

    if key in cache:
        rows = cache[key]
    else:
        rows = None
        for attempt in range(4):
            try:
                rows = _extract_json(call_llm(prompt))
                break
            except Exception as ex:   # rate limit or bad JSON: wait and retry
                print(f"  ep {ep_num}: retry {attempt + 1} ({str(ex)[:80]})")
                time.sleep(SLEEP * (attempt + 2))
        if rows is None:
            raise SystemExit(f"ERROR: the LLM call failed 4 times for episode {ep_num}. Check MODEL_NAME / key / quota in .env")
        cache[key] = rows
        _save_cache(cache)
        time.sleep(SLEEP)

    out = {}
    for r in rows:
        if isinstance(r, dict) and "id" in r:
            r["standalone_score"] = r.get("standalone_score", r.get("standalone", 3))
            out[r["id"]] = r
    return out
