import sys, os, time, json

REPO = "/home/hugo/workspace/DungeonOfTheStars"
sys.path.insert(0, REPO)
os.chdir(REPO)

from llm_agent import LLMAgent
from game_engine import DungeonOfTheStarsEngine

eng = DungeonOfTheStarsEngine()
llm = eng.llm
print("OLLAMA base:", llm.ollama_url)

pdf = eng.active_player_file
if os.path.exists(pdf):
    with open(pdf) as f:
        player_data = f.read()
else:
    player_data = "Commodore Nimrod Heros\nWounds (Health): 0/14\nSystem Strain: 0/16\nCredits: 500\nLocation: Bridge"
loc_data = eng.locations.get("bridge") or next(iter(eng.locations.values()))
hist_entries = eng.history[-3:] if eng.history else []
history_context = "\n".join(f"Turn {h.get('turn')}: {h.get('player_command')}" for h in hist_entries) or "(game start)"

# ---------------- PARSER BENCHMARK ----------------
commands = [
    "draw my sidearm and fire at the nearest Sith cultist",
    "move to the cargo hold",
    "scan the room for lifeforms",
    "use the comlink to call the bridge",
    "i want to hack the terminal",
    "tell the crew to stand down",
    "open the blast door with the override code",
    "eat a ration",
]
parser_candidates = [
    "qwen2.5:7b", "mistral:7b", "llama3.1:8b", "qwen2.5:3b", "llama3.2:3b",
    "dante_dante159/gary_gigax:latest",
]

print("\n=== PARSER JSON RELIABILITY (valid = dict w/ command+skill_check+state_changes) ===")
print(f"{'model':40} {'ok':>4} {'tot':>4} {'rate':>6} {'avg_s':>7}")
results = {}
for model in parser_candidates:
    llm.parser_model = model
    ok = 0
    times = []
    for cmd in commands:
        t0 = time.time()
        try:
            p = llm.parse_command(cmd, loc_data, player_data, history_context)
        except Exception as e:
            p = {}
            print(f"  [{model}] EXC: {e}")
        times.append(time.time() - t0)
        if p and isinstance(p, dict) and "valid" in p and "skill_check" in p and "engine_mutations" in p:
            ok += 1
            if ok == 1:
                print(f"    sample: {json.dumps(p, indent=0)[:240]}")
    rate = ok / len(commands)
    avg = sum(times) / len(times)
    results[model] = (ok, len(commands), rate, avg)
    print(f"{model:40} {ok:>4} {len(commands):>4} {rate*100:>5.0f}% {avg:>7.1f}")

best_parser = max(results, key=lambda m: (results[m][2], -results[m][3]))
print("\nBEST PARSER (validity then speed):", best_parser, results[best_parser])

# ---------------- NARRATOR SAMPLE ----------------
action_outcome = {
    "success": True,
    "dice_roll": {"skill": "Shoot", "modifier": 2, "dc": 12, "roll": 15, "is_success": True},
    "dice_roll_str": "Shoot check: rolled 15 vs DC 12 - SUCCESS",
    "state_changes": {"fields": {"System Strain": "1"}},
    "time_elapsed_minutes": 1,
}

narrator_candidates = [
    "dante_dante159/gary_gigax:latest", "llama3.1:8b", "qwen2.5:7b",
    "Librellama/gemma4:e2b-Uncensored", "gemma2:9b",
]

print("\n=== NARRATOR STORYTELLING SAMPLES (command: 'fire at the cultist') ===")
for model in narrator_candidates:
    llm.narrator_model = model
    try:
        toks = []
        for t in llm.generate_narration("fire at the cultist", action_outcome, loc_data, history_context, stream=True):
            toks.append(t)
        text = "".join(toks)
    except Exception as e:
        text = f"[ERROR: {e}]"
    print(f"\n----- {model} -----")
    print(text[:800])
