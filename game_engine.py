import json
import os
import re
import sys
from datetime import datetime, timedelta

# Add StarZork to path
sys.path.append("/home/calvin/Documents/StarZork")

from md_db import MarkdownDB
from dice import roll_pool, pretty_print_results
from llm_agent import LLMAgent

GAME_DATA_DIR = "/home/calvin/Documents/StarZork/GameData"
GAME_INFO_DIR = "/home/calvin/Documents/StarZork/Game_info"
PLAYER_FILE = os.path.join(GAME_DATA_DIR, "Player Data/Commodore_Nimrod_Heros.md")
HISTORY_FILE = os.path.join(GAME_DATA_DIR, "game_history.json")

class StarZorkEngine:
    def __init__(self):
        self.llm = LLMAgent(config_path="/home/calvin/Documents/StarZork/config.json")
        self.locations = self._load_locations()
        self.skills_map = self._load_skills_map()
        self.history = self._load_history()
        
    def _load_locations(self):
        """Parses Game_info/locations.md into a structured room registry."""
        loc_file = os.path.join(GAME_INFO_DIR, "locations.md")
        if not os.path.exists(loc_file):
            return {}
            
        with open(loc_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Parse locations using sections starting with ##
        locations = {}
        sections = content.split("## ")[1:]
        for sec in sections:
            lines = sec.strip().split("\n")
            name = lines[0].strip()
            loc_id = None
            exits = []
            desc = ""
            npc = []
            interactables = []
            
            # Simple line parsing
            for line in lines[1:]:
                line = line.strip()
                if line.startswith("*   **Location ID:**"):
                    loc_id = line.split("ID:**")[1].replace("`", "").strip()
                elif line.startswith("*   **Exits:**"):
                    # Scan exits in next lines
                    pass
                elif line.startswith("    *   `"):
                    # Exit line, e.g. "    *   `hangar` (via Command Lift)"
                    exit_id = line.split("`")[1].strip()
                    exits.append(exit_id)
                elif line.startswith("*   **Description:**"):
                    desc = line.split("Description:**")[1].strip()
                elif line.startswith("*   **NPCs present:**"):
                    npcs_raw = line.split("present:**")[1].strip()
                    npc = [n.replace("`", "").strip() for n in npcs_raw.split(",") if n.strip()]
                elif line.startswith("    *   `") and ":" in line:
                    # Interactable item
                    parts = line.split(":")
                    item_id = parts[0].replace("`", "").replace("*", "").strip()
                    interactables.append(item_id)
                    
            if loc_id:
                locations[loc_id] = {
                    "id": loc_id,
                    "name": name,
                    "exits": exits,
                    "description": desc,
                    "npcs": npc,
                    "interactables": interactables
                }
        return locations

    def _load_skills_map(self):
        """Loads characteristic mappings from Game_info/skills.md."""
        skills_file = os.path.join(GAME_INFO_DIR, "skills.md")
        if not os.path.exists(skills_file):
            return {}
            
        skills = {}
        with open(skills_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("*   **"):
                    # Format: *   **Computers**: Intellect (INT)
                    match = re.match(r"^\*\s+\*\*([^*]+)\*\*:\s*([^(]+)\(([^)]+)\)", line.strip())
                    if match:
                        skill_name = match.group(1).strip()
                        characteristic = match.group(3).strip()
                        skills[skill_name] = characteristic
        return skills

    def _load_history(self):
        """Loads or initializes game_history.json."""
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    return json.load(f)
            except:
                return []
        return []

    def _save_history(self):
        """Writes current turn history to game_history.json."""
        with open(HISTORY_FILE, "w") as f:
            json.dump(self.history, f, indent=2)

    def get_current_location_id(self, player_location_name):
        """Resolves raw player location string to location ID."""
        name_lower = player_location_name.lower()
        for loc_id, loc in self.locations.items():
            if loc["name"].lower() in name_lower or loc_id in name_lower:
                return loc_id
        return "bridge"  # Default fallback

    def execute_turn(self, player_command):
        """Executes a single game loop command."""
        # 1. Regex Guardrail for broad cheat commands
        command_clean = player_command.strip().lower()
        broad_terms = ["win the game", "win game", "skip to end", "destroy rebels instantly", "instantly defeat"]
        if any(term in command_clean for term in broad_terms):
            rejection = "⚠️ **TACTICAL ERROR:** Commodore, strategic operations require execution of localized, immediate directives. Broad skips cannot be executed."
            # Append block to history without state changes
            self.history.append({
                "turn": len(self.history) + 1,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "player_command": player_command,
                "dice_roll": None,
                "state_changes": [],
                "narrative": rejection
            })
            self._save_history()
            return rejection

        # 2. Read current player state
        player_data = MarkdownDB.read_file(PLAYER_FILE)
        
        # 3. Resolve location
        loc_name = player_data["fields"].get("Current Location", "Bridge")
        loc_id = self.get_current_location_id(loc_name)
        loc_data = self.locations.get(loc_id, self.locations.get("bridge"))
        
        # 4. Gather recent history context (last 3 turns) without raw narrative text to prevent LLM repetition loops
        history_context = []
        if self.history:
            for h in self.history[-3:]:
                history_context.append({
                    "turn": h.get("turn"),
                    "player_command": h.get("player_command"),
                    "dice_roll": h.get("dice_roll"),
                    "state_changes": h.get("state_changes")
                })
        
        # 5. Parse command via LLM Judge
        parsed = self.llm.parse_command(player_command, loc_data, player_data, history_context)
        
        # 6. Check validation
        if not parsed.get("valid", True):
            rejection = f"⚠️ [TACTICAL REFUSAL] {parsed.get('rejection_reason', 'Cannot execute action.')}"
            self.history.append({
                "turn": len(self.history) + 1,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "player_command": player_command,
                "dice_roll": None,
                "state_changes": [],
                "narrative": rejection
            })
            self._save_history()
            return rejection
            
        # 7. Check if skill check is required
        roll_results = None
        state_updates = {"fields": {}, "checklists": {}}
        
        skill_check = parsed.get("skill_check", {})
        if skill_check.get("required", False):
            skill_name = skill_check.get("skill")
            difficulty = skill_check.get("difficulty", 2)
            
            # Retrieve characteristics and ranks
            # E.g. Intellect (INT) -> maps to characteristic "Intellect (INT)"
            char_key = self.skills_map.get(skill_name, "INT")
            
            # Map shorthand to full name on sheet
            char_sheet_map = {
                "BR": "Brawn (BR)",
                "AG": "Agility (AG)",
                "INT": "Intellect (INT)",
                "CUN": "Cunning (CUN)",
                "WIL": "Willpower (WIL)",
                "PR": "Presence (PR)"
            }
            
            char_full_key = char_sheet_map.get(char_key, "Intellect (INT)")
            
            # Get Attribute Score and Skill Rank from character sheet dict
            attr_val = int(player_data["fields"].get(char_full_key, "3"))
            
            # Skill rank is listed under fields like: Computers (INT) -> Rank 2
            # Let's extract rank number from string "Rank 2"
            skill_line_val = player_data["fields"].get(f"{skill_name} ({char_key})", "Rank 0")
            rank_match = re.search(r"Rank\s+(\d+)", skill_line_val)
            skill_rank = int(rank_match.group(1)) if rank_match else 0
            
            # Calculate pool
            yellow = min(attr_val, skill_rank)
            green = abs(attr_val - skill_rank)
            purple = difficulty
            
            pool_str = f"{yellow}p {green}a {purple}d"
            
            # Execute roll programmatically
            roll_results, raw = roll_pool(pool_str)
            
            # Apply mechanical strain if threats generated
            threats = roll_results["threat"]
            if threats > 0:
                current_strain = player_data["fields"].get("System Strain", "0")
                current_strain_int = int(current_strain) if current_strain.isdigit() else 0
                max_strain = 16  # From character sheet base max
                new_strain = min(max_strain, current_strain_int + threats)
                state_updates["fields"]["System Strain"] = str(new_strain)
                
            # If Triumph / Despair, update state updates
            if roll_results["despair"] > 0:
                # Add a state update to damage a subsystem or character
                pass
                
        # 8. Process state updates and mutations
        mutations = parsed.get("engine_mutations", {})
        
        # Check health/wounds modifications
        wounds_change = mutations.get("wounds_change", 0)
        if wounds_change != 0:
            current_wounds = player_data["fields"].get("Wounds (Health)", "0")
            current_wounds_int = int(current_wounds) if current_wounds.isdigit() else 0
            new_wounds = max(0, min(14, current_wounds_int + wounds_change))
            state_updates["fields"]["Wounds (Health)"] = str(new_wounds)
            
        # Check credits modifications
        credits_change = mutations.get("credits_change", 0)
        if credits_change != 0:
            current_credits = player_data["fields"].get("Credits", "1000")
            current_credits_int = int(current_credits) if current_credits.isdigit() else 1000
            new_credits = max(0, current_credits_int + credits_change)
            state_updates["fields"]["Credits"] = str(new_credits)
            
        # Check location movement
        movement = parsed.get("movement", {})
        if movement.get("transit", False):
            target_id = movement.get("target_location_id")
            if target_id in self.locations:
                target_loc = self.locations[target_id]
                state_updates["fields"]["Current Location"] = target_loc["name"]
                # Update current location variables for narration
                loc_data = target_loc
                
        # Apply custom state updates (like opening safes or setting subsystems)
        custom_updates = mutations.get("custom_state_updates", {})
        for k, v in custom_updates.items():
            # If it matches a ship manifest file, update that file
            # For simplicity in demo, we check if key has a dot pointing to a file
            # e.g., "The_Waining_Moon.Hyperdrive": "Offline"
            if "." in k:
                ship_name, field = k.split(".", 1)
                # Find ship file recursively in ShipData
                ship_file = self._find_ship_file(ship_name)
                if ship_file:
                    # Is it a status check?
                    if field.startswith("Subsystem Status."):
                        sub_field = field.split(".")[1]
                        MarkdownDB.write_file(ship_file, {"checklists": {sub_field: v}})
                    else:
                        MarkdownDB.write_file(ship_file, {"fields": {field: v}})
            else:
                # Add to player fields
                state_updates["fields"][k] = str(v)
                
        # Write player sheet changes to disk
        if state_updates["fields"] or state_updates["checklists"]:
            MarkdownDB.write_file(PLAYER_FILE, state_updates)
            
        # 9. Advance Clock / Turn state
        # In history, log time advancement
        time_elapsed = parsed.get("time_elapsed_minutes", 1)
        
        # 10. Generate Narration via LLM Narrator
        action_outcome = {
            "success": True if not roll_results else roll_results["is_success"],
            "dice_roll": roll_results,
            "dice_roll_str": pretty_print_results(roll_results) if roll_results else None,
            "state_changes": state_updates,
            "time_elapsed_minutes": time_elapsed
        }
        
        narration = self.llm.generate_narration(player_command, action_outcome, loc_data, history_context)
        
        # 11. Save to History log
        self.history.append({
            "turn": len(self.history) + 1,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "player_command": player_command,
            "dice_roll": roll_results,
            "state_changes": state_updates,
            "narrative": narration
        })
        self._save_history()
        
        return narration

    def _find_ship_file(self, ship_name):
        """Searches recursively for a ship file by its name."""
        for root, dirs, files in os.walk(GAME_DATA_DIR):
            for file in files:
                if file.replace(".md", "").lower() == ship_name.lower():
                    return os.path.join(root, file)
        return None
