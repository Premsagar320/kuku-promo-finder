# Kuku promo finder (Problem 1)

Finds 20-60 s promo clips (hook in first 3 s, cliffhanger ending, understandable alone) in microdrama screenplays.

## How it works
1. `parse.py`      - plain code: screenplay .txt -> scenes + timed items (dialogue/action/shot/sound).
2. `candidates.py` - plain rules: sliding 20-60 s windows (+ tail-of-episode-N + head-of-episode-N+1 joins),
                     rule score for hook / cliffhanger / standalone, keeps ~10 per episode.
3. `score.py`      - ONE LLM call per episode judges its candidates (hook, cliffhanger, standalone, score, why).
                     Model is swappable in `.env`; results are cached.
4. `run.py`        - combines LLM and rule score, removes overlaps, max 3 per episode, ranks, writes outputs.

## Run
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Create .env with your Gemini API key:
# GEMINI_API_KEY=your_gemini_api_key
# MODEL_NAME=gemini-2.5-flash

# 1. Test parse.py on all files (prints scene counts and total duration per episode):
python parse.py data

# 2. Test run.py on first 3 episodes:
python run.py --input data --out outputs --limit 3

# 3. Full run on all episodes:
python run.py --input data --out outputs

# Optional: rule-based mock mode without calling LLM API
LLM_PROVIDER=mock python run.py --input data --out outputs
```
Swap model: change `MODEL_NAME` (or `LLM_PROVIDER=openai` with `OPENAI_BASE_URL`, `OPENAI_API_KEY`; `pip install openai`).

## Outputs (in `outputs/`)
`promos.csv|json|md` (ranked), `all_scored_candidates.csv` (everything scored, for auditing).
