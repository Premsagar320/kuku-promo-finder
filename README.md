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
cp .env.example .env        # then put your key in .env
python run.py --input "data/<show folder>" --out outputs            # all episodes
python run.py --input "data/<show folder>" --out outputs --limit 3  # quick test
LLM_PROVIDER=mock python run.py --input "data/<show folder>"        # no key: rules only
```
Swap model: change `MODEL_NAME` (or `LLM_PROVIDER=openai` with `OPENAI_BASE_URL`, `OPENAI_API_KEY`; `pip install openai`).

## Outputs (in `outputs/`)
`promos.csv|json|md` (ranked), `all_scored_candidates.csv` (everything scored, for auditing).
