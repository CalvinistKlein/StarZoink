import os
import sys
import time
import json
import webbrowser
import threading
import re
import queue
from datetime import datetime
from flask import Flask, request, jsonify, render_template, Response

# Add project root to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from md_db import MarkdownDB
from game_engine import DungeonOfTheStarsEngine
from dice import pretty_print_results

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
engine = None

# Global helper to colorize Rich tags to HTML spans
def colorize_narrative_to_html(text: str) -> str:
    """Applies premium HTML styling to dialogue speakers, highlights body-text names, and highlights actions."""
    # 1. Parse dialogue speech blocks into temporary markup tags
    paragraphs = re.split(r'\n\s*\n', text)
    processed_paragraphs = []
    
    known_speakers = ["KROSS", "THORNE", "VANCE", "THUL", "GORN", "GRORN", "HEROS", "VOSS", "INQUISITOR", "COMMODORE", "OFFICER", "CREW", "TROOPER", "REBEL", "PIRATE", "MUTINEER", "SITH"]
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        dialogue_found = False
        speaker = ""
        speech_body = ""
        
        # A. Try matching bracketed speaker: <SPEAKER> ...
        match_bracket = re.match(r'^<([a-zA-Z0-9\s\-\_\.]+)>:?\s*(.*)$', para, re.DOTALL)
        if match_bracket:
            speaker = match_bracket.group(1).strip()
            speech_body = match_bracket.group(2).strip()
            dialogue_found = True
        else:
            # B. Try matching unbracketed speaker with colon: "COMMANDER VANDAR KROSS: ..."
            match_colon = re.match(r'^([a-zA-Z0-9\s\-\_\.]+):(?:\s+|\n)(.*)$', para, re.DOTALL)
            if match_colon:
                possible_speaker = match_colon.group(1).strip()
                poss_upper = possible_speaker.upper()
                if any(k in poss_upper for k in known_speakers):
                    speaker = possible_speaker
                    speech_body = match_colon.group(2).strip()
                    dialogue_found = True
                    
        if dialogue_found:
            name_upper = speaker.upper()
            if "COMMODORE" in name_upper or "HEROS" in name_upper:
                color_class = "bold-cyan"
                hex_color = "#4fc3f7"
            elif any(k in name_upper for k in ("KROSS", "THORNE", "VANCE", "THUL", "GORN", "GRORN", "OFFICER", "TROOPER", "CREW", "IMPERIAL")):
                color_class = "bold-green"
                hex_color = "#81c784"
            elif any(k in name_upper for k in ("REBEL", "PIRATE", "PRISONER", "SITH", "MUTINEER", "ESCAPE", "INQUISITOR", "VOSS")):
                color_class = "bold-red"
                hex_color = "#ff8a80"
            else:
                color_class = "bold-yellow"
                hex_color = "#ffd54f"
                
            dialogue_html = (
                f"[speech_container hex={hex_color}]"
                f"[speech_speaker class={color_class}]{speaker}[/speech_speaker]"
                f"[speech_text]{speech_body}[/speech_text]"
                f"[/speech_container]"
            )
            processed_paragraphs.append(dialogue_html)
        else:
            processed_paragraphs.append(para)
            
    text = "\n\n".join(processed_paragraphs)

    # 2. Highlight key character names inside the body text safely
    names_to_highlight = [
        (r"\b(Commodore\s+Heros|Commodore\s+Nimrod\s+Heros|Nimrod\s+Heros)\b", "bold cyan"),
        (r"\b(Commander\s+Vandar\s+Kross|Commander\s+Kross|Vandar\s+Kross|Kross)\b", "bold green"),
        (r"\b(Lt\.\s+Cmdr\.\s+Aris\s+Thorne|Lt\.\s+Commander\s+Thorne|Aris\s+Thorne|Thorne)\b", "bold green"),
        (r"\b(Lt\.\s+Cmdr\.\s+Titus\s+Thul|Lt\.\s+Commander\s+Thul|Titus\s+Thul|Thul)\b", "bold green"),
        (r"\b(Lt\.\s+Commander\s+Vance|Lt\.\s+Cmdr\.\s+Vance|Vance)\b", "bold green"),
        (r"\b(Commander\s+Grorn|Squad\s+Gorn|Squad\s+Grorn|Grorn|Gorn)\b", "bold green"),
        (r"\b(Rebel\s+Agent\s+Kira\s+Voss|Kira\s+Voss|Voss)\b", "bold red"),
        (r"\b(Imperial\s+Inquisitor|Inquisitor)\b", "bold red"),
    ]
    
    def highlight_word_safely(src_text, word_regex, color):
        flags = 0
        wr = word_regex
        if wr.startswith('(?i)'):
            flags = re.IGNORECASE
            wr = wr[4:]
        pattern = re.compile(r'(\\[[^\]]+\]|[^\\[\\]\\s]*' + wr + r'[^\\[\\]\\s]*)', flags)
        def replace(match):
            val = match.group(1)
            if val.startswith('['):
                return val
            inner_match = re.search(wr, val, flags)
            if inner_match:
                matched_name = inner_match.group(1)
                return val.replace(matched_name, f"[{color}]{matched_name}[/{color}]")
            return val
        return pattern.sub(replace, src_text)

    for word_regex, color in names_to_highlight:
        text = highlight_word_safely(text, word_regex, color)

    # 3. Highlight locations separately
    locations_to_highlight = [
        (r"(?i)\b(Bridge|Quarters|Hangar|Brig|The\s+Brig|Engineering)\b", "bold orange"),
        (r"(?i)\b(Sworinta\s+IV|Sworinta\s+IV\s+Orbit|Sworinta\s+IV\s+Surface|Deep\s+Space|Orbit|Surface)\b", "bold orange"),
        (r"(?i)\b(Sith\s+Beacon|Derelict\s+Warship|Anomaly\s+/\s+Distress\s+Call)\b", "bold orange"),
    ]
    for loc_regex, color in locations_to_highlight:
        text = highlight_word_safely(text, loc_regex, color)

    # 4. Highlight movement/action phrases
    action_verbs = [
        r"\b(walks|runs|moves|jumps|relocates|travels|flies|heads|goes|arrives|departs)\s+(?:to|towards|into|from|for|at)\b",
        r"\b(relocated\s+to|moved\s+to|traveled\s+to|entered\s+the|exited\s+the|arrived\s+at)\b"
    ]
    for verb_pat in action_verbs:
        text = highlight_word_safely(text, verb_pat, "bold magenta")

    # 5. Escape HTML characters to avoid script/element injection but preserve markdown brackets
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Convert bracket syntax to html spans
    text = re.sub(r'\[bold (\w+)\]', r'<span class="bold-\1">', text)
    text = re.sub(r'\[/bold (\w+)\]', r'</span>', text)
    text = re.sub(r'\[(\w+)\]', r'<span class="\1">', text)
    text = re.sub(r'\[/(\w+)\]', r'</span>', text)

    # 7. Convert markdown bold syntax and header HTML
    text = re.sub(r'\*\*(.*?)\*\*', r'<span class="bold-yellow">\1</span>', text)
    text = re.sub(r'###\s*(.*)', r'<span class="bold-yellow" style="font-size: 1.05rem; text-decoration: underline; display: block; margin-top: 10px; margin-bottom: 5px;">\1</span>', text)

    # 8. Convert our temporary speech container bracket syntax to actual styled HTML divs
    text = re.sub(r'\[speech_container hex=([^\]]+)\]', r'<div class="speech-container" style="--dialogue-color: \1;">', text)
    text = text.replace('[/speech_container]', '</div>')
    text = re.sub(r'\[speech_speaker class=([^\]]+)\]', r'<div class="speech-speaker \1">', text)
    text = text.replace('[/speech_speaker]', '</div>')
    text = text.replace('[speech_text]', '<div class="speech-text">')
    text = text.replace('[/speech_text]', '</div>')

    # 9. Convert newlines to break tags
    text = text.replace('\n', '<br>')
    return text


def get_flagship_status():
    """Reads status metrics for The Broken Sunrise."""
    ship_file = os.path.join(BASE_DIR, "GameData/ShipData/The_Broken_Sunrise/The_Broken_Sunrise.md")
    if not os.path.exists(ship_file):
        return {"hull": 0, "hull_max": 160, "strain": 0, "strain_max": 80, "shields": "Fore:3 | Port:2 | Stbd:2 | Aft:2", "hyperdrive": "Nominal", "sublight": "Nominal", "weapons": "Nominal", "sensors": "Nominal"}
    try:
        data = MarkdownDB.read_file(ship_file)
        fields = data.get("fields", {})
        checklists = data.get("checklists", {})
        
        hull_str = str(fields.get("Hull Trauma", "0")).replace("[ ]", "0").strip()
        hull = int(hull_str) if hull_str.isdigit() else 0
        
        strain_str = str(fields.get("System Strain", "0")).replace("[ ]", "0").strip()
        strain = int(strain_str) if strain_str.isdigit() else 0
        
        sf = str(fields.get("Shields - Fore", "3")).replace("[ ]", "3").strip()
        sp = str(fields.get("Shields - Port", "2")).replace("[ ]", "2").strip()
        ss = str(fields.get("Shields - Starboard", "2")).replace("[ ]", "2").strip()
        sa = str(fields.get("Shields - Aft", "2")).replace("[ ]", "2").strip()
        
        def get_stat(name):
            val = checklists.get(name, "Nominal")
            if isinstance(val, dict):
                for k, v in val.items():
                    if v and v != "[ ]" and v != "false" and v != False: return k
            elif isinstance(val, str) and val and val != "[ ]":
                return val
            return "Nominal"
            
        return {
            "hull": hull,
            "hull_max": 160,
            "strain": strain,
            "strain_max": 80,
            "shields": f"Fore:{sf} | Port:{sp} | Stbd:{ss} | Aft:{sa}",
            "hyperdrive": get_stat("Hyperdrive"),
            "sublight": get_stat("Sublight Engines"),
            "weapons": get_stat("Weapons Systems"),
            "sensors": get_stat("Sensors")
        }
    except Exception:
        return {"hull": 0, "hull_max": 160, "strain": 0, "strain_max": 80, "shields": "Fore:3 | Port:2 | Stbd:2 | Aft:2", "hyperdrive": "Nominal", "sublight": "Nominal", "weapons": "Nominal", "sensors": "Nominal"}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/initialize', methods=['POST'])
def initialize():
    global engine
    data = request.json or {}
    choice = int(data.get('choice', 1))
    
    if choice == 2:
        # Restart campaign
        try:
            import shutil
            if os.path.exists(os.path.join(BASE_DIR, "SeedTemplates")):
                shutil.copytree(os.path.join(BASE_DIR, "SeedTemplates/GameData/Player Data"), os.path.join(BASE_DIR, "GameData/Player Data"), dirs_exist_ok=True)
                shutil.copytree(os.path.join(BASE_DIR, "SeedTemplates/GameData/ShipData"), os.path.join(BASE_DIR, "GameData/ShipData"), dirs_exist_ok=True)
                if os.path.exists(os.path.join(BASE_DIR, "SeedTemplates/GameData/NPC Data")):
                    shutil.copytree(os.path.join(BASE_DIR, "SeedTemplates/GameData/NPC Data"), os.path.join(BASE_DIR, "GameData/NPC Data"), dirs_exist_ok=True)
                shutil.copy2(os.path.join(BASE_DIR, "SeedTemplates/Game_info/locations.md"), os.path.join(BASE_DIR, "Game_info/locations.md"))
            
            history_path = os.path.join(BASE_DIR, "GameData/game_history.json")
            chronicle_path = os.path.join(BASE_DIR, "GameData/campaign_chronicle.md")
            with open(history_path, "w", encoding="utf-8") as f:
                f.write("[]\n")
            with open(chronicle_path, "w", encoding="utf-8") as f:
                f.write("# Campaign Chronicle\n* Operations commenced aboard Sworinta IV orbit.\n")
        except Exception as e:
            return jsonify({"status": "error", "message": f"Failed to reset: {e}"}), 500

    try:
        engine = DungeonOfTheStarsEngine()
        # Pre-cache the dynamically generated opening narrative
        engine.get_initial_narrative()
    except Exception as e:
        return jsonify({"status": "error", "message": f"LLM Connection failed: {e}"}), 500
        
    return jsonify({"status": "ok"})


@app.route('/api/status', methods=['GET'])
def get_status():
    if not engine:
        return jsonify({"char_name": "Unknown", "location": "Unknown", "credits": 0, "wounds": 0, "max_wounds": 10, "strain": 0, "max_strain": 10, "attributes": {}})
    
    player_file = engine.active_player_file
    player_data = MarkdownDB.read_file(player_file)
    
    # Calculate wounds and strain max values
    max_wounds = 0
    max_strain = 0
    if os.path.exists(player_file):
        try:
            with open(player_file, "r", encoding="utf-8") as f:
                for line in f:
                    if "|" in line and "wounds" in line.lower():
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 2 and parts[1].replace("**", "").replace(" ", "").isdigit():
                            max_wounds = int(parts[1].replace("**", "").replace(" ", ""))
                    elif "|" in line and "strain" in line.lower():
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 2 and parts[1].replace("**", "").replace(" ", "").isdigit():
                            max_strain = int(parts[1].replace("**", "").replace(" ", ""))
        except:
            pass
            
    # Extract char name
    char_name = "Commodore Heros"
    if os.path.exists(player_file):
        try:
            with open(player_file, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line.startswith("#"):
                    char_name = first_line.split(":")[-1].strip() if ":" in first_line else first_line.replace("#", "").strip()
        except:
            pass
            
    # Characteristics fallbacks
    if max_wounds <= 0:
        brawn_str = player_data["fields"].get("Brawn (BR)", "3").strip()
        brawn = int(brawn_str) if brawn_str.isdigit() else 3
        max_wounds = 11 + brawn if "heros" in char_name.lower() else 10 + brawn
        
    if max_strain <= 0:
        will_str = player_data["fields"].get("Willpower (WIL)", "3").strip()
        willpower = int(will_str) if will_str.isdigit() else 3
        max_strain = 12 + willpower if "heros" in char_name.lower() else 10 + willpower
        
    wounds_str = player_data["fields"].get("Wounds (Health)", "0").strip()
    wounds = int(wounds_str) if (wounds_str and wounds_str.isdigit()) else 0
    strain_str = player_data["fields"].get("System Strain", "0").strip()
    strain = int(strain_str) if (strain_str and strain_str.isdigit()) else 0
    
    credits = player_data["fields"].get("Credits", "1000000")
    location = player_data["fields"].get("Current Location", "Bridge")
    
    # Gather attributes
    attributes = {}
    for attr in ["Brawn (BR)", "Agility (AG)", "Intellect (INT)", "Cunning (CUN)", "Willpower (WIL)", "Presence (PR)"]:
        attributes[attr] = player_data["fields"].get(attr, "3")

    ship = get_flagship_status()
    
    return jsonify({
        "char_name": char_name,
        "location": location,
        "credits": credits,
        "wounds": wounds,
        "max_wounds": max_wounds,
        "strain": strain,
        "max_strain": max_strain,
        "attributes": attributes,
        "ship_hull": ship["hull"],
        "ship_max_hull": ship["hull_max"],
        "ship_strain": ship["strain"],
        "ship_max_strain": ship["strain_max"],
        "ship_shields": ship["shields"],
        "ship_hyperdrive": ship["hyperdrive"],
        "ship_sublight": ship["sublight"],
        "ship_weapons": ship["weapons"],
        "ship_sensors": ship["sensors"]
    })


@app.route('/api/history', methods=['GET'])
def get_history():
    if not engine or not engine.history:
        # If history is empty, return initial narration formatted cleanly
        player_file = engine.active_player_file if engine else os.path.join(BASE_DIR, "GameData/Player Data/Commodore_Nimrod_Heros.md")
        loc_name = "Bridge, The Broken Sunrise (Orbiting Sworinta IV)"
        if os.path.exists(player_file):
            try:
                data = MarkdownDB.read_file(player_file)
                loc_name = data["fields"].get("Current Location", loc_name)
            except:
                pass
        initial_narr = engine.get_initial_narrative()
        if not initial_narr:
            initial_narr = (
                f"You are standing on the command deck of the Star Destroyer The Broken Sunrise. "
                f"Below you, the toxic green atmosphere of Sworinta IV churns, its radiation masking your ship's presence from long-range scans. "
                f"In the distance, sensors pick up a weak, echoing ping from an ancient Sith beacon.\n\n"
                f"Commander Kross stands nearby, awaiting your command.\n"
                f"Current Location: {loc_name}"
            )
        return jsonify([{
            "command": None,
            "html": colorize_narrative_to_html(initial_narr)
        }])

    res_history = []
    for h in engine.history:
        res_history.append({
            "command": h.get("player_command"),
            "html": colorize_narrative_to_html(h.get("narrative", ""))
        })
    return jsonify(res_history)


@app.route('/api/command', methods=['POST'])
def run_command():
    if not engine:
        return jsonify({"error": "Engine not initialized"}), 400

    data = request.json or {}
    cmd = data.get('command', '').strip()
    if not cmd:
        return jsonify({"error": "Empty command"}), 400

    # Run the turn in a worker thread and stream narrator tokens to the client
    # over Server-Sent Events for a live, easy-to-follow output stream.
    q = queue.Queue()

    def worker():
        try:
            full = engine.execute_turn(cmd, stream_callback=lambda t: q.put(("token", t)))
            q.put(("done", full))
        except Exception as e:
            q.put(("error", str(e)))

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        while True:
            kind, val = q.get()
            if kind == "token":
                yield f"data: {json.dumps({'token': val})}\n\n"
            elif kind == "error":
                yield f"data: {json.dumps({'error': str(val)})}\n\n"
                break
            elif kind == "done":
                narration = val or ""
                html = colorize_narrative_to_html(narration)
                yield f"event: done\ndata: {json.dumps({'html': html, 'command': cmd})}\n\n"
                break

    return Response(gen(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/map', methods=['GET'])
def get_map():
    if not engine:
        return jsonify({"html": "Engine not initialized"})
        
    player_file = engine.active_player_file
    player_data = MarkdownDB.read_file(player_file)
    location = player_data["fields"].get("Current Location", "Bridge")
    loc_lower = location.lower()
    
    ship_file = os.path.join(BASE_DIR, "GameData/ShipData/The_Broken_Sunrise/The_Broken_Sunrise.md")
    ship_sector = "Orbit of Sworinta IV"
    if os.path.exists(ship_file):
        try:
            ship_data = MarkdownDB.read_file(ship_file)
            ship_sector = ship_data.get("fields", {}).get("Current Sector", "Orbit of Sworinta IV")
        except:
            pass
            
    ship_sector_lower = ship_sector.lower()
    dynamic_planet_svg = ""
    
    # Determine flagship coordinates on map
    if "asteroid" in ship_sector_lower:
        flagship_x, flagship_y = 640, 60
        flagship_label = "The Broken Sunrise (Asteroid Field)"
    elif "beacon" in ship_sector_lower or "anomaly" in ship_sector_lower:
        flagship_x, flagship_y = 620, 250
        flagship_label = "The Broken Sunrise (Sith Beacon)"
    elif "sworinta v" in ship_sector_lower or "sworinta 5" in ship_sector_lower:
        flagship_x, flagship_y = 100, 250
        flagship_label = "The Broken Sunrise (Sworinta V Orbit)"
        dynamic_planet_svg = '''
        <!-- Sworinta V Planet -->
        <circle cx="100" cy="350" r="45" fill="url(#sworintaVGrad)" />
        <circle cx="100" cy="350" r="45" fill="none" stroke="#ba68c8" stroke-width="2" filter="url(#glow)" />
        <text x="100" y="345" fill="#ffffff" font-family="Inter, sans-serif" font-size="11" font-weight="700" text-anchor="middle">SWORINTA V</text>
        <text x="100" y="360" fill="#e1bee7" font-family="Inter, sans-serif" font-size="9" text-anchor="middle">Outpost Sector</text>
        '''
    else:
        # Default Sworinta IV Orbit
        flagship_x, flagship_y = 260, 70
        flagship_label = "The Broken Sunrise (Flagship)"

    # Determine player marker position.
    # KEY DESIGN: The player travels with the ship. The ship's Current Sector is the
    # authoritative source of where the ship (and any on-board player) is located on the
    # tactical map. Player's Current Location is only used to distinguish: (a) internal
    # rooms (on the ship), (b) a planetary surface visit, or (c) "on the ship at its
    # current sector" (all other cases). This prevents desync where the LLM updates only
    # one of the two fields.
    is_internal = any(k in loc_lower for k in ("bridge", "quarters", "commons", "hangar", "brig", "engineering"))
    is_surface = "surface" in loc_lower

    if is_internal:
        # Player is inside the ship — badge anchors to flagship position
        player_marker = f'''
        <g transform="translate({flagship_x}, {flagship_y - 32})">
          <rect x="-70" y="-14" width="140" height="22" rx="11" fill="#004d40" stroke="#00e676" stroke-width="1.5"/>
          <text x="0" y="2" fill="#00e676" font-family="Inter, sans-serif" font-size="11" font-weight="700" text-anchor="middle">YOU ARE ON BOARD</text>
        </g>
        '''
    elif is_surface:
        # Player has gone to a planetary surface (rare — keep hardcoded to Sworinta IV center)
        player_marker = '''
        <g transform="translate(260, 240)">
          <circle cx="0" cy="0" r="110" fill="none" stroke="#00e676" stroke-width="3" stroke-dasharray="6 6">
            <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="10s" repeatCount="indefinite"/>
          </circle>
          <rect x="-75" y="60" width="150" height="24" rx="12" fill="#004d40" stroke="#00e676" stroke-width="1.5"/>
          <text x="0" y="76" fill="#00e676" font-family="Inter, sans-serif" font-size="11" font-weight="700" text-anchor="middle">YOU ARE HERE (SURFACE)</text>
        </g>
        '''
    else:
        # Player is traveling with the ship (at its sector). Always anchor to the
        # flagship's current coordinates so ship and player markers stay in sync.
        player_marker = f'''
        <g transform="translate({flagship_x}, {flagship_y - 32})">
          <circle cx="0" cy="0" r="50" fill="none" stroke="#00e676" stroke-width="2" stroke-dasharray="4 4">
            <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="8s" repeatCount="indefinite"/>
          </circle>
          <rect x="-60" y="-14" width="120" height="22" rx="11" fill="#004d40" stroke="#00e676" stroke-width="1.5"/>
          <text x="0" y="2" fill="#00e676" font-family="Inter, sans-serif" font-size="11" font-weight="700" text-anchor="middle">YOU ARE HERE</text>
        </g>
        '''

    svg = f'''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" style="width: 100%; height: auto; background: #11141c; border-radius: 12px;">
      <defs>
        <radialGradient id="planetGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#42a5f5" />
          <stop offset="70%" stop-color="#1565c0" />
          <stop offset="100%" stop-color="#0d47a1" />
        </radialGradient>
        <radialGradient id="sworintaVGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#ba68c8" />
          <stop offset="70%" stop-color="#7b1fa2" />
          <stop offset="100%" stop-color="#4a148c" />
        </radialGradient>
        <radialGradient id="beaconGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#ff5252" stop-opacity="1" />
          <stop offset="50%" stop-color="#ab47bc" stop-opacity="0.6" />
          <stop offset="100%" stop-color="#ab47bc" stop-opacity="0" />
        </radialGradient>
        <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      <!-- Background Grid -->
      <g stroke="#1b202c" stroke-width="1">
        <line x1="0" y1="90" x2="800" y2="90" />
        <line x1="0" y1="180" x2="800" y2="180" />
        <line x1="0" y1="270" x2="800" y2="270" />
        <line x1="0" y1="360" x2="800" y2="360" />
        <line x1="160" y1="0" x2="160" y2="450" />
        <line x1="320" y1="0" x2="320" y2="450" />
        <line x1="480" y1="0" x2="480" y2="450" />
        <line x1="640" y1="0" x2="640" y2="450" />
      </g>

      <!-- Sector Header -->
      <text x="20" y="30" fill="#90caf9" font-family="Inter, sans-serif" font-size="14" font-weight="700" letter-spacing="1">★ SECTOR - {ship_sector.upper()} TACTICAL MAP</text>

      <!-- Orbital Rings -->
      <circle cx="260" cy="240" r="170" fill="none" stroke="#2c3a50" stroke-width="2" stroke-dasharray="8 6" />
      <circle cx="260" cy="240" r="115" fill="none" stroke="#1e88e5" stroke-width="1" stroke-opacity="0.3" />

      <!-- Sworinta IV Planet -->
      <circle cx="260" cy="240" r="95" fill="url(#planetGrad)" />
      <circle cx="260" cy="240" r="95" fill="none" stroke="#64b5f6" stroke-width="2" filter="url(#glow)" />
      <text x="260" y="235" fill="#ffffff" font-family="Inter, sans-serif" font-size="15" font-weight="700" text-anchor="middle">SWORINTA IV</text>
      <text x="260" y="255" fill="#bbdefb" font-family="Inter, sans-serif" font-size="11" text-anchor="middle">Atmospheric Scans: Turbulent</text>

      <!-- Dynamic Planet if present -->
      {dynamic_planet_svg}

      <!-- Deep Rim Asteroid Field -->
      <g transform="translate(560, 90)">
        <text x="30" y="-15" fill="#b0bec5" font-family="Inter, sans-serif" font-size="12" font-weight="600">Deep Rim Asteroid Field</text>
        <polygon points="10,0 25,5 20,20 0,15" fill="#546e7a" />
        <polygon points="40,10 55,5 65,25 35,30" fill="#455a64" />
        <polygon points="80,-5 95,10 85,25 70,15" fill="#607d8b" />
        <polygon points="120,5 135,-5 145,15 125,20" fill="#546e7a" />
        <polygon points="30,40 45,35 50,55 25,50" fill="#37474f" />
      </g>

      <!-- Deep Rim Anomaly / Sith Beacon -->
      <g transform="translate(620, 310)">
        <circle cx="0" cy="0" r="35" fill="url(#beaconGrad)" />
        <circle cx="0" cy="0" r="8" fill="#ff5252" filter="url(#glow)" />
        <circle cx="0" cy="0" r="20" fill="none" stroke="#ab47bc" stroke-width="1.5" stroke-dasharray="4 4">
          <animate attributeName="r" values="8;30;8" dur="3s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="1;0;1" dur="3s" repeatCount="indefinite" />
        </circle>
        <text x="0" y="45" fill="#e1bee7" font-family="Inter, sans-serif" font-size="12" font-weight="600" text-anchor="middle">Sith Beacon / Anomaly</text>
      </g>

      <!-- Flagship: The Broken Sunrise -->
      <g transform="translate({flagship_x}, {flagship_y})">
        <polygon points="0,-18 -14,18 14,18" fill="#cfd8dc" stroke="#90caf9" stroke-width="2" filter="url(#glow)" />
        <text x="25" y="5" fill="#90caf9" font-family="Inter, sans-serif" font-size="13" font-weight="700">{flagship_label}</text>
      </g>

      <!-- Active Player Marker -->
      {player_marker}
    </svg>
    '''
    return jsonify({"html": svg})


@app.route('/api/ship', methods=['GET'])
def get_ship():
    if not engine:
        return jsonify({"side_html": "Engine not initialized", "top_html": "Engine not initialized"})
        
    player_file = engine.active_player_file
    player_data = MarkdownDB.read_file(player_file)
    location = player_data["fields"].get("Current Location", "Bridge")
    loc_lower = location.lower()
    
    is_bridge = "bridge" in loc_lower
    is_quarters = "quarter" in loc_lower or "common" in loc_lower or "crew" in loc_lower or "officer" in loc_lower
    is_hangar = "hangar" in loc_lower or "bay" in loc_lower or "tie" in loc_lower
    is_engineering = "engineering" in loc_lower or "reactor" in loc_lower or "core" in loc_lower or "engine" in loc_lower
    is_brig = "brig" in loc_lower or "cell" in loc_lower
    
    if not (is_quarters or is_hangar or is_engineering or is_brig):
        is_bridge = True
        
    def get_marker(active, x, y, label):
        if not active:
            return ""
        return f'''
        <g transform="translate({x}, {y})">
          <circle cx="0" cy="0" r="8" fill="#00e676" filter="url(#glow)">
            <animate attributeName="r" values="6;12;6" dur="1.5s" repeatCount="indefinite"/>
            <animate attributeName="opacity" values="1;0.4;1" dur="1.5s" repeatCount="indefinite"/>
          </circle>
          <rect x="15" y="-12" width="120" height="24" rx="12" fill="#004d40" stroke="#00e676" stroke-width="1.5"/>
          <text x="75" y="4" fill="#00e676" font-family="Inter, sans-serif" font-size="11" font-weight="700" text-anchor="middle">{label}</text>
        </g>
        '''

    side_svg = f'''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" style="width: 100%; height: auto; background: #0c0f16; border-radius: 12px;">
      <defs>
        <!-- Hull Gradients -->
        <linearGradient id="hullGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#374151" />
          <stop offset="50%" stop-color="#1f2937" />
          <stop offset="100%" stop-color="#111827" />
        </linearGradient>
        <linearGradient id="superGrad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#4b5563" />
          <stop offset="100%" stop-color="#1f2937" />
        </linearGradient>
        <!-- Engine Glow -->
        <radialGradient id="engineGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#00e5ff" stop-opacity="1" />
          <stop offset="30%" stop-color="#00b0ff" stop-opacity="0.8" />
          <stop offset="100%" stop-color="#00b0ff" stop-opacity="0" />
        </radialGradient>
        <!-- Reactor Glow -->
        <radialGradient id="reactorGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#e0f7fa" stop-opacity="1" />
          <stop offset="40%" stop-color="#00e5ff" stop-opacity="0.7" />
          <stop offset="100%" stop-color="#00e5ff" stop-opacity="0" />
        </radialGradient>
        <!-- Glow Filter -->
        <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="5" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      <!-- Title -->
      <text x="20" y="30" fill="#90caf9" font-family="Inter, sans-serif" font-size="14" font-weight="700" letter-spacing="1">★ THE BROKEN SUNRISE - IMPERIAL I-CLASS STAR DESTROYER (SIDE CUTAWAY)</text>

      <!-- Background Grid -->
      <g stroke="#1b202c" stroke-width="1" opacity="0.4">
        <line x1="0" y1="100" x2="800" y2="100" />
        <line x1="0" y1="200" x2="800" y2="200" />
        <line x1="0" y1="300" x2="800" y2="300" />
        <line x1="200" y1="0" x2="200" y2="450" />
        <line x1="400" y1="0" x2="400" y2="450" />
        <line x1="600" y1="0" x2="600" y2="450" />
      </g>

      <!-- ================= DETAILED STAR DESTROYER GEOMETRY ================= -->
      
      <!-- Hangar Bay Interior Glow (visible in ventral cutout) -->
      <polygon points="280,266 380,266 400,285 270,282" fill="#006064" opacity="0.4" filter="url(#glow)" />
      
      <!-- Ventral Solar Ionization Reactor Dome (Protrusion under ship) -->
      <path d="M 450,290 C 470,335 530,335 550,280" fill="url(#superGrad)" stroke="#4b5563" stroke-width="2" />
      <circle cx="500" cy="305" r="16" fill="url(#reactorGlow)" filter="url(#glow)" />
      <circle cx="500" cy="305" r="8" fill="#ffffff" />

      <!-- Main Wedge Hull (Base Plate & Nose) -->
      <polygon points="80,250 700,165 700,290 520,305 80,250" fill="url(#hullGrad)" stroke="#4b5563" stroke-width="2" />
      
      <!-- Middle Trench Detail Layer (ISD horizontal belt) -->
      <path d="M 80,250 L 700,227" stroke="#111827" stroke-width="4" />
      <path d="M 80,250 L 700,227" stroke="#4b5563" stroke-width="1" />

      <!-- Ventral Hangar Bay Cutout (Belly Notch) -->
      <polygon points="260,277 290,265 390,265 410,295" fill="#0c0f16" stroke="#4b5563" stroke-width="2" />

      <!-- Stepped Superstructure Terraces (Dorsal Decks) -->
      <polygon points="380,205 450,195 450,180 500,180 500,165 560,165 560,150 620,150 625,166 700,175 700,228 380,228" fill="url(#superGrad)" stroke="#4b5563" stroke-width="1.5" />
      
      <!-- Command Tower Neck -->
      <polygon points="575,150 580,105 615,105 620,150" fill="url(#superGrad)" stroke="#374151" stroke-width="1.5" />

      <!-- Bridge T-Structure (Command Deck) -->
      <polygon points="560,105 550,85 645,85 635,105" fill="#374151" stroke="#90caf9" stroke-width="2" />
      <!-- Bridge Viewports (Glowing green stripe) -->
      <polygon points="565,95 558,89 637,89 630,95" fill="#00e676" opacity="0.8" filter="url(#glow)" />

      <!-- Shield Generator Domes (On top of Tower) -->
      <!-- Left Dome & Neck -->
      <line x1="575" y1="85" x2="575" y2="72" stroke="#4b5563" stroke-width="3" />
      <circle cx="575" cy="68" r="8" fill="#ffe082" stroke="#ffa000" stroke-width="1.5" filter="url(#glow)" />
      <!-- Right Dome & Neck -->
      <line x1="620" y1="85" x2="620" y2="72" stroke="#4b5563" stroke-width="3" />
      <circle cx="620" cy="68" r="8" fill="#ffe082" stroke="#ffa000" stroke-width="1.5" filter="url(#glow)" />

      <!-- Glowing Engine Exhausts (Ventral/Aft Nozzles) -->
      <!-- Auxiliary Engine Top -->
      <polygon points="700,180 725,185 725,198 700,203" fill="#00b0ff" stroke="#00e5ff" stroke-width="1" />
      <circle cx="725" cy="191.5" r="10" fill="url(#engineGlow)" filter="url(#glow)" />
      
      <!-- Main Engine Top -->
      <polygon points="700,205 730,210 730,230 700,235" fill="#00b0ff" stroke="#00e5ff" stroke-width="1" />
      <circle cx="730" cy="220" r="15" fill="url(#engineGlow)" filter="url(#glow)" />
      
      <!-- Main Engine Middle -->
      <polygon points="700,238 732,243 732,263 700,268" fill="#00b0ff" stroke="#00e5ff" stroke-width="1" />
      <circle cx="732" cy="253" r="15" fill="url(#engineGlow)" filter="url(#glow)" />

      <!-- Main Engine Bottom -->
      <polygon points="700,270 730,275 730,295 700,300" fill="#00b0ff" stroke="#00e5ff" stroke-width="1" />
      <circle cx="730" cy="285" r="15" fill="url(#engineGlow)" filter="url(#glow)" />

      <!-- Hull Panel Details (Overlay Lines for Scale) -->
      <line x1="180" y1="240" x2="240" y2="280" stroke="#4b5563" stroke-width="0.7" opacity="0.5" />
      <line x1="320" y1="220" x2="350" y2="260" stroke="#4b5563" stroke-width="0.7" opacity="0.5" />
      <line x1="500" y1="180" x2="520" y2="228" stroke="#4b5563" stroke-width="0.7" opacity="0.5" />
      <line x1="600" y1="165" x2="630" y2="228" stroke="#4b5563" stroke-width="0.7" opacity="0.5" />

      <!-- ================= COMPARTMENTS & PLAYER MARKERS ================= -->
      
      <!-- DECK 1: Command Bridge (In Tower Structure) -->
      {get_marker(is_bridge, 595, 95, "YOU ARE HERE")}

      <!-- DECK 2: Commodore & Officer Quarters (Upper Superstructure) -->
      {get_marker(is_quarters, 510, 160, "YOU ARE HERE")}

      <!-- DECK 3: The Brig & Security (Mid Superstructure/Hull) -->
      {get_marker(is_brig, 410, 205, "YOU ARE HERE")}

      <!-- DECK 4: Main Hangar Bay (Lower Ventral Cutout) -->
      {get_marker(is_hangar, 310, 250, "YOU ARE HERE")}

      <!-- DECK 5: Main Engineering & Reactor (Aft Section near Engines) -->
      {get_marker(is_engineering, 570, 250, "YOU ARE HERE")}
    </svg>
    '''

    top_svg = f'''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" style="width: 100%; height: auto; background: #0c0f16; border-radius: 12px;">
      <defs>
        <!-- Top view Gradients -->
        <linearGradient id="hullGradTop" x1="0%" y1="50%" x2="100%" y2="50%">
          <stop offset="0%" stop-color="#374151" />
          <stop offset="80%" stop-color="#1f2937" />
          <stop offset="100%" stop-color="#111827" />
        </linearGradient>
        <radialGradient id="engineGlowTop" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#00e5ff" stop-opacity="1" />
          <stop offset="30%" stop-color="#00b0ff" stop-opacity="0.8" />
          <stop offset="100%" stop-color="#00b0ff" stop-opacity="0" />
        </radialGradient>
        <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="5" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      <!-- Title -->
      <text x="20" y="30" fill="#90caf9" font-family="Inter, sans-serif" font-size="14" font-weight="700" letter-spacing="1">★ THE BROKEN SUNRISE - IMPERIAL I-CLASS STAR DESTROYER (TOP LAYOUT)</text>

      <!-- Background Grid -->
      <g stroke="#1b202c" stroke-width="1" opacity="0.4">
        <line x1="0" y1="100" x2="800" y2="100" />
        <line x1="0" y1="200" x2="800" y2="200" />
        <line x1="0" y1="300" x2="800" y2="300" />
        <line x1="200" y1="0" x2="200" y2="450" />
        <line x1="400" y1="0" x2="400" y2="450" />
        <line x1="600" y1="0" x2="600" y2="450" />
      </g>

      <!-- ================= DETAILED STAR DESTROYER TOP GEOMETRY ================= -->
      
      <!-- Main Wedge Hull (Top View ISD Silhouette) -->
      <polygon points="60,225 700,75 700,375" fill="url(#hullGradTop)" stroke="#4b5563" stroke-width="2.5" />
      
      <!-- Centerline Ridge (Spine of the ship) -->
      <line x1="60" y1="225" x2="700" y2="225" stroke="#4b5563" stroke-width="2" />
      <line x1="60" y1="225" x2="700" y2="225" stroke="#111827" stroke-width="0.7" />

      <!-- Glowing Engine Exhausts (Rear nozzles) -->
      <!-- Outer Left Engine -->
      <circle cx="710" cy="150" r="12" fill="url(#engineGlowTop)" filter="url(#glow)" />
      <circle cx="710" cy="150" r="6" fill="#ffffff" />
      <!-- Main Left Engine -->
      <circle cx="712" cy="190" r="16" fill="url(#engineGlowTop)" filter="url(#glow)" />
      <circle cx="712" cy="190" r="8" fill="#ffffff" />
      <!-- Main Center Engine -->
      <circle cx="715" cy="225" r="18" fill="url(#engineGlowTop)" filter="url(#glow)" />
      <circle cx="715" cy="225" r="9" fill="#ffffff" />
      <!-- Main Right Engine -->
      <circle cx="712" cy="260" r="16" fill="url(#engineGlowTop)" filter="url(#glow)" />
      <circle cx="712" cy="260" r="8" fill="#ffffff" />
      <!-- Outer Right Engine -->
      <circle cx="710" cy="300" r="12" fill="url(#engineGlowTop)" filter="url(#glow)" />
      <circle cx="710" cy="300" r="6" fill="#ffffff" />

      <!-- Command Superstructure (Stepped Terraces from Top) -->
      <polygon points="400,225 560,150 680,150 680,300 560,300" fill="#2d3648" stroke="#4b5563" stroke-width="1.5" />
      
      <!-- Bridge Tower Superstructure (T-Shape Tower Deck) -->
      <polygon points="580,225 610,180 670,180 670,270 610,270" fill="#1f2937" stroke="#4b5563" stroke-width="1.5" />
      <rect x="635" y="140" width="30" height="170" rx="4" fill="#374151" stroke="#90caf9" stroke-width="1.5" />
      
      <!-- Shield Generator Domes (Top View) -->
      <circle cx="650" cy="135" r="10" fill="#ffe082" stroke="#ffa000" stroke-width="1.5" filter="url(#glow)" />
      <circle cx="650" cy="315" r="10" fill="#ffe082" stroke="#ffa000" stroke-width="1.5" filter="url(#glow)" />

      <!-- Bridge Marker placement -->
      {get_marker(is_bridge, 640, 225, "YOU ARE HERE")}

      <!-- Officer & Crew Quarters / Commons -->
      <rect x="500" y="180" width="90" height="90" rx="6" fill="#1e2430" stroke="#64b5f6" stroke-width="1.5" />
      <text x="545" y="225" fill="#bbdefb" font-family="Inter, sans-serif" font-size="11" font-weight="600" text-anchor="middle" transform="rotate(-90 545 225)">QUARTERS</text>
      {get_marker(is_quarters, 535, 225, "YOU ARE HERE")}

      <!-- Main Hangar Bay Layout (Forward section) -->
      <rect x="290" y="170" width="120" height="110" rx="6" fill="#1a202c" stroke="#42a5f5" stroke-width="1.5" />
      <text x="350" y="225" fill="#90caf9" font-family="Inter, sans-serif" font-size="11" font-weight="700" text-anchor="middle" transform="rotate(-90 350 225)">HANGAR BAY</text>
      {get_marker(is_hangar, 340, 225, "YOU ARE HERE")}

      <!-- The Brig (Port Side) -->
      <rect x="440" y="90" width="80" height="50" rx="6" fill="#1e2430" stroke="#e57373" stroke-width="1.5" />
      <text x="480" y="118" fill="#ef9a9a" font-family="Inter, sans-serif" font-size="10" font-weight="600" text-anchor="middle">THE BRIG</text>
      {get_marker(is_brig, 470, 115, "YOU ARE HERE")}

      <!-- Main Engineering & Reactor (Aft center) -->
      <rect x="580" y="200" width="80" height="50" rx="6" fill="#1e2430" stroke="#ffa726" stroke-width="1.5" />
      {get_marker(is_engineering, 610, 225, "YOU ARE HERE")}
    </svg>
    '''

    return jsonify({
        "side_html": side_svg,
        "top_html": top_svg
    })


@app.route('/api/settings', methods=['GET', 'POST'])
def get_set_settings():
    config_path = os.path.join(BASE_DIR, "config.json")
    
    if request.method == 'POST':
        data = request.json or {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except:
            cfg = {}
            
        cfg["OLLAMA_URL"] = data.get("OLLAMA_URL", cfg.get("OLLAMA_URL", "127.0.0.1:11434"))
        cfg["PARSER_MODEL"] = data.get("PARSER_MODEL", cfg.get("PARSER_MODEL", ""))
        cfg["NARRATOR_MODEL"] = data.get("NARRATOR_MODEL", cfg.get("NARRATOR_MODEL", cfg.get("PARSER_MODEL", "")))
        cfg["SHOW_DICE_CHECKS"] = bool(data.get("SHOW_DICE_CHECKS", cfg.get("SHOW_DICE_CHECKS", False)))
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            
        # Re-initialize engine models with updated configs (live, no restart needed)
        if engine:
            try:
                engine.llm.ollama_url = cfg["OLLAMA_URL"]
                engine.llm.parser_model = cfg["PARSER_MODEL"]
                engine.llm.narrator_model = cfg["NARRATOR_MODEL"] or cfg["PARSER_MODEL"]
                if hasattr(engine, "rag") and engine.rag is not None:
                    engine.rag.ollama_url = cfg["OLLAMA_URL"]
            except Exception as e:
                print(f"Warning: failed to apply live model change: {e}")
        return jsonify({"status": "ok"})

    # GET request
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except:
        cfg = {"OLLAMA_URL": "127.0.0.1:11434", "PARSER_MODEL": "dante_dante159/gary_gigax:latest", "NARRATOR_MODEL": "dante_dante159/gary_gigax:latest", "SHOW_DICE_CHECKS": False}
        
    return jsonify(cfg)


@app.route('/api/save', methods=['POST'])
def manual_save():
    # Execute turn automatically saves everything, but we can verify it
    if engine:
        try:
            engine._save_history()
            return jsonify({"status": "ok", "message": "💾 SYSTEM BACKUP COMPLETE: Campaign progress persistent in GameData."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "error", "message": "Engine not running"}), 400


def open_browser():
    time.sleep(1.5)
    webbrowser.open_new_tab("http://127.0.0.1:5000")


if __name__ == '__main__':
    print("★ Launching StarZork Flagship Tactical Web Server on port 5000 ★")
    print("Press Ctrl+C to stop.")
    
    # Start browser auto-open in a daemon thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run server (bound to all interfaces so it is reachable over Tailscale/LAN)
    app.run(host="0.0.0.0", port=5000, debug=False)
