"""parse.py - read screenplay .txt files into episodes, scenes and timed items.

Plain code, no AI. Each episode becomes:
  {num, logline, continuity, duration, items:[{kind, speaker, start, end, text, scene}]}
kind is one of: dialogue, action, camera, sound.
"""
import glob
import os
import re

LABEL_RE = re.compile(r"^\*\*(.+?):\*\*\s*$")
RANGE_RE = re.compile(r"Start:\s*\((\d+:\d+(?:\.\d+)?)\)\s*\|\s*End:\s*\((\d+:\d+(?:\.\d+)?)\)")
SCENE_RE = re.compile(r"^SCENE\s+(\d+)")


def to_sec(ts):
    m, s = ts.split(":")
    return int(m) * 60 + float(s)


def fmt(sec):
    sec = max(0, sec)
    return f"{int(sec // 60):02d}:{sec % 60:04.1f}"


def parse_episode(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    ep = {"file": os.path.basename(path), "logline": "", "continuity": "", "items": [], "scenes": []}
    m = re.search(r"episode-(\d+)", os.path.basename(path))
    ep["num"] = int(m.group(1)) if m else 0

    scene = 0
    i = 0
    in_script = False
    while i < len(lines):
        line = lines[i].strip()
        if not in_script:
            if line.startswith("EPISODE LOGLINE:"):
                ep["logline"] = line.split(":", 1)[1].strip()
            elif line.startswith("CONTINUITY NOTES:"):
                ep["continuity"] = line.split(":", 1)[1].strip()
            elif line.startswith("--- SCRIPT START"):
                in_script = True
            i += 1
            continue
        if line.startswith("--- SCRIPT END"):
            break
        sm = SCENE_RE.match(line)
        if sm:
            scene = int(sm.group(1))
            ep["scenes"].append({"scene": scene, "heading": "", "start": 0.0, "end": 0.0})
        elif line.startswith("Scene heading:") and ep["scenes"]:
            ep["scenes"][-1]["heading"] = line.split(":", 1)[1].strip()
        elif line.startswith("Scene start:") and ep["scenes"]:
            ep["scenes"][-1]["start"] = to_sec(line.split(":", 1)[1].strip())
        elif line.startswith("Scene end:") and ep["scenes"]:
            ep["scenes"][-1]["end"] = to_sec(line.split(":", 1)[1].strip())
        else:
            lm = LABEL_RE.match(line)
            if lm and i + 1 < len(lines):
                rm = RANGE_RE.search(lines[i + 1])
                if rm:
                    label = lm.group(1).strip()
                    text_lines = []
                    j = i + 2
                    while j < len(lines) and lines[j].strip() and not LABEL_RE.match(lines[j].strip()) \
                            and not SCENE_RE.match(lines[j].strip()) and not lines[j].startswith("---"):
                        text_lines.append(lines[j].strip())
                        j += 1
                    text = " ".join(text_lines).strip()
                    up = label.upper()
                    if up == "CAMERA":
                        kind, speaker = "camera", ""
                    elif up == "ACTION":
                        kind, speaker = "action", ""
                    elif up.startswith("SOUND FX"):
                        kind, speaker = "sound", ""
                    else:
                        kind = "dialogue"
                        speaker = re.split(r"\s*\(", label)[0].strip()
                        text = text.strip('"').strip("“”")
                    ep["items"].append({"kind": kind, "speaker": speaker, "start": to_sec(rm.group(1)),
                                        "end": to_sec(rm.group(2)), "text": text, "scene": scene})
                    i = j
                    continue
        i += 1

    ep["items"].sort(key=lambda x: (x["start"], x["end"]))
    ep["duration"] = max([it["end"] for it in ep["items"]] + [s["end"] for s in ep["scenes"]] + [0])
    return ep


def load_folder(folder, limit=None):
    files = sorted(glob.glob(os.path.join(folder, "**", "episode-*.txt"), recursive=True))
    if limit:
        files = files[:limit]
    return [parse_episode(p) for p in files]


if __name__ == "__main__":
    import sys
    for e in load_folder(sys.argv[1]):
        n_dlg = sum(1 for it in e["items"] if it["kind"] == "dialogue")
        print(f"Ep {e['num']:>3}  scenes={len(e['scenes'])}  items={len(e['items'])}  dialogue={n_dlg}  duration={e['duration']:.1f}s")
