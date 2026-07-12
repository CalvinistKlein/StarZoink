import json
import os
import re
import sys
from datetime import datetime, timedelta

# Add project root to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from md_db import MarkdownDB
from dice import roll_pool, pretty_print_results
from llm_agent import LLMAgent
from rag_engine import RagEngine

GAME_DATA_DIR = os.path.join(BASE_DIR, "GameData")
GAME_INFO_DIR = os.path.join(BASE_DIR, "Game_info")
PLAYER_FILE = os.path.join(GAME_DATA_DIR, "Player Data/Commodore_Nimrod_Heros.md")
HISTORY_FILE = os.path.join(GAME_DATA_DIR, "game_history.json")
CHRONICLE_FILE = os.path.join(GAME_DATA_DIR, "campaign_chronicle.md")

class DungeonOfTheStarsEngine:
    def __init__(self):
        self.llm = LLMAgent(config_path=os.path.join(BASE_DIR, "config.json"))
        self.rag = RagEngine(ollama_url=self.llm.ollama_url)
        self.locations = self._load_locations()
        self.skills_map = self._load_skills_map()
        self.history = self._load_history()
        self.chronicle = self._load_chronicle()
        self.active_player_file = PLAYER_FILE
        # Pre-cache intro
        self.initial_narrative = None

        # Config flag: reflect explicit numeric state from narration into game state.
        # Safe by default (only explicit, in-range statements). Set NARRATION_STATE_PARSE=false
        # in config.json to disable entirely (engine remains source of truth).
        self.auto_parse_stats = self._load_config_flag("NARRATION_STATE_PARSE", True)

    def get_initial_narrative(self):
        if not self.initial_narrative:
            try:
                player_data = MarkdownDB.read_file(self.active_player_file)
                loc_name = player_data["fields"].get("Current Location", "Bridge")
                loc_id = self.get_current_location_id(loc_name)
                loc_data = self.locations.get(loc_id, self.locations.get("bridge"))
                self.initial_narrative = self.llm.generate_initial_intro(loc_data)
            except Exception:
                # Omit errors and let it fallback inside the llm agent
                pass
        return self.initial_narrative

        
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

    def execute_turn(self, player_command, stream_callback=None):
        """Executes a single game loop command."""
        # 1. Regex Guardrail for broad cheat commands
        command_clean = player_command.strip().lower()
        broad_terms = ["win the game", "win game", "skip to end", "destroy rebels instantly", "instantly defeat"]
        if any(term in command_clean for term in broad_terms):
            rejection = "**[TACTICAL ERROR]:** Commodore, strategic operations require execution of localized, immediate directives. Broad skips cannot be executed."
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
        player_data = MarkdownDB.read_file(self.active_player_file)
        
        # 3. Resolve location
        loc_name = player_data["fields"].get("Current Location", "Bridge")
        loc_id = self.get_current_location_id(loc_name)
        loc_data = self.locations.get(loc_id, self.locations.get("bridge"))
        
        # 4. Gather recent history context (last 3 turns) and campaign chronicle
        history_context = {
            "recent_turns": [],
            "campaign_chronicle": self.chronicle
        }
        if self.history:
            for h in self.history[-3:]:
                history_context["recent_turns"].append({
                    "turn": h.get("turn"),
                    "player_command": h.get("player_command"),
                    "dice_roll": h.get("dice_roll"),
                    "state_changes": h.get("state_changes")
                })
        
        # 5. Parse command via LLM Judge
        parsed = self.llm.parse_command(player_command, loc_data, player_data, history_context)
        
        # 6. Check validation
        if not parsed.get("valid", True):
            rejection = f"[TACTICAL REFUSAL] {parsed.get('rejection_reason', 'Cannot execute action.')}"
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

        # 6b. Check if an NPC was detected in the player action
        detected = parsed.get("detected_npc")
        if detected and isinstance(detected, dict):
            name = detected.get("name")
            role = detected.get("role", "Officer")
            faction = detected.get("faction", "Imperial Navy")
            if name:
                # Clean name (spaces to underscores, remove special chars)
                name_clean = re.sub(r"\s+", "_", name.strip())
                # See if we have a file for them
                npc_file = self._find_npc_file(name_clean)
                if not npc_file:
                    # Query Wookieepedia RAG for context
                    lore_context = ""
                    if hasattr(self, "rag") and self.rag:
                        rag_query = name_clean.replace("_", " ")
                        lore_context = self.rag.query_lore(rag_query, n_results=2)
                        
                    # Call LLM to generate character sheet
                    location_name = loc_data.get("name", "Bridge")
                    card_md = self.llm.generate_npc_card(name_clean, role, faction, location_id=location_name, lore_context=lore_context)
                    
                    # Write profile to file
                    npc_dir = os.path.join(GAME_DATA_DIR, "NPC Data")
                    if "officer" in role.lower() or "cmd" in role.lower() or "commander" in role.lower():
                        npc_dir = os.path.join(GAME_DATA_DIR, "Player Data/Command Staff")
                    os.makedirs(npc_dir, exist_ok=True)
                    
                    target_card_path = os.path.join(npc_dir, f"{name_clean}.md")
                    try:
                        with open(target_card_path, "w", encoding="utf-8") as f:
                            f.write(card_md)
                    except Exception as e:
                        print(f"Warning: Failed to save NPC card: {e}")
                        
                    # Register NPC to current location's list
                    self._register_npc_to_location(loc_id, name_clean)
            
        # 7. Check if skill check is required
        roll_results = None
        state_updates = {"fields": {}, "checklists": {}}
        
        skill_check = parsed.get("skill_check") or {}
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
                max_strain = self._sheet_max("System Strain") or 16  # From character sheet base max
                new_strain = min(max_strain, current_strain_int + threats)
                state_updates["fields"]["System Strain"] = str(new_strain)
                
            # If Triumph / Despair, update state updates
            if roll_results["despair"] > 0:
                # Add a state update to damage a subsystem or character
                pass
                
        # 8. Process state updates and mutations
        mutations = parsed.get("engine_mutations") or {}
        
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
        movement = parsed.get("movement") or {}
        if movement.get("transit", False):
            target_id = movement.get("target_location_id")
            if target_id:
                if target_id not in self.locations:
                    target_name = movement.get("target_location_name") or target_id.replace("_", " ").title()
                    # Append new location to Game_info/locations.md
                    new_loc_str = f"\n\n---\n\n## {target_name}\n"
                    new_loc_str += f"*   **Location ID:** `{target_id}`\n"
                    new_loc_str += f"*   **Name:** {target_name}\n"
                    new_loc_str += f"*   **Exits:**\n"
                    # Add current location as exit
                    curr_loc_name = player_data["fields"].get("Current Location", "Bridge")
                    curr_loc_id = self.get_current_location_id(curr_loc_name)
                    if curr_loc_id:
                        new_loc_str += f"    *   `{curr_loc_id}` (via Flight Vector/Transit)\n"
                    new_loc_str += f"*   **Description:** A newly discovered or generated location: {target_name}.\n"
                    new_loc_str += f"*   **NPCs present:** None\n"
                    new_loc_str += f"*   **Interactable Elements:** None\n"
                    
                    loc_file = os.path.join(GAME_INFO_DIR, "locations.md")
                    try:
                        with open(loc_file, "a", encoding="utf-8") as f:
                            f.write(new_loc_str)
                        # Reload locations
                        self.locations = self._load_locations()
                    except Exception as e:
                        print(f"Error dynamically writing location: {e}")
                
                if target_id in self.locations:
                    target_loc = self.locations[target_id]
                    state_updates["fields"]["Current Location"] = target_loc["name"]
                    # Update current location variables for narration
                    loc_data = target_loc
                
        # Apply custom state updates (like opening safes, relocating NPCs, or setting subsystems)
        custom_updates = mutations.get("custom_state_updates", {})
        for k, v in custom_updates.items():
            if "." in k:
                entity_name, field = k.split(".", 1)
                # 1. Check if entity is an NPC
                npc_file = self._find_npc_file(entity_name)
                if npc_file:
                    if "location" in field.lower():
                        target_loc_id = self.get_current_location_id(str(v))
                        self._relocate_npc(entity_name, target_loc_id)
                        MarkdownDB.write_file(npc_file, {"fields": {"Current Location": str(v)}})
                    else:
                        MarkdownDB.write_file(npc_file, {"fields": {field: str(v)}})
                    continue
                # 2. Check if entity is a ship
                ship_file = self._find_ship_file(entity_name)
                if ship_file:
                    if field.startswith("Subsystem Status."):
                        sub_field = field.split(".")[1]
                        MarkdownDB.write_file(ship_file, {"checklists": {sub_field: str(v)}})
                    else:
                        MarkdownDB.write_file(ship_file, {"fields": {field: str(v)}})
            else:
                state_updates["fields"][k] = str(v)
                
        # Write player sheet changes to disk
        # Clamp critical vitals for consistency before persisting
        for _fld, _mx in (("Wounds (Health)", 14), ("System Strain", 16)):
            if _fld in state_updates["fields"]:
                try:
                    _v = int(state_updates["fields"][_fld])
                    state_updates["fields"][_fld] = str(max(0, min(_mx, _v)))
                except Exception:
                    pass
        if "Credits" in state_updates["fields"]:
            try:
                _v = int(state_updates["fields"]["Credits"])
                state_updates["fields"]["Credits"] = str(max(0, _v))
            except Exception:
                pass

        if state_updates["fields"] or state_updates["checklists"]:
            MarkdownDB.write_file(self.active_player_file, state_updates)
            
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
        
        if stream_callback:
            chunks = []
            for tok in self.llm.generate_narration(
                player_command, action_outcome, loc_data, history_context, stream=True
            ):
                chunks.append(tok)
                stream_callback(tok)
            narration = "".join(chunks)
        else:
            narration = self.llm.generate_narration(
                player_command, action_outcome, loc_data, history_context
            )
        
        # 10a. Scan narration for dynamic stats and update files in real-time (optional, config-gated)
        if getattr(self, "auto_parse_stats", True):
            self._parse_narrative_for_stats(narration)
        
        # 10b. Update Campaign Chronicle
        turn_bullet = self.llm.summarize_turn(player_command, narration, state_updates)
        self._save_chronicle(turn_bullet)

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

    def _load_config_flag(self, name, default):
        try:
            cfg_path = os.path.join(BASE_DIR, "config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    cfg = json.load(f)
                if name in cfg:
                    return bool(cfg[name])
        except Exception:
            pass
        return default

    def _sheet_max(self, field_name):
        """Reads the 'Maximum' column for a field from the active player sheet."""
        try:
            with open(self.active_player_file, "r", encoding="utf-8") as f:
                for line in f:
                    if field_name in line and "|" in line:
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 2 and parts[1].replace("**", "").isdigit():
                            return int(parts[1].replace("**", ""))
        except Exception:
            pass
        return None

    def _parse_narrative_for_stats(self, narration):
        """Safely reflect explicit, in-range numeric state statements from the
        narration into game state. Conservative to avoid corrupting state from
        LLM prose hallucinations (narrator is instructed not to mention numbers,
        so this only fires on explicit, deliberate statements)."""
        import re
        ship_file = self._find_ship_file("The_Broken_Sunrise")
        player_file = self.active_player_file

        # Ship Hull Trauma (explicit absolute statements only)
        ship_state = {}
        m = re.search(r"hull\s+(?:trauma|damage)\s+(?:is|at|of|=)?\s*(\d+)", narration, re.IGNORECASE)
        if not m:
            m = re.search(r"hull\s+integrity\s+(?:at|is|of)?\s*(\d+)\s*%", narration, re.IGNORECASE)
            if m:
                num = int(m.group(1))
                ship_state["Hull Trauma"] = str(max(0, min(160, round(160 * (100 - num) / 100))))
        else:
            ship_state["Hull Trauma"] = str(max(0, min(160, int(m.group(1)))))

        # Ship System Strain (explicit absolute statements only)
        m = re.search(r"system\s+strain\s+(?:is|at|of|=)?\s*(\d+)", narration, re.IGNORECASE)
        if m:
            ship_state["System Strain"] = str(max(0, min(80, int(m.group(1)))))

        if ship_state and ship_file and os.path.exists(ship_file):
            try:
                MarkdownDB.write_file(ship_file, {"fields": ship_state})
            except Exception as e:
                print(f"Warning: Failed to reflect ship state: {e}")

        # Player vitals (explicit absolute statements only)
        player_state = {}
        m = re.search(r"wounds?\s+(?:is|at|of|=)?\s*(\d+)", narration, re.IGNORECASE)
        if m:
            player_state["Wounds (Health)"] = str(max(0, min(14, int(m.group(1)))))
        m = re.search(r"strain\s+(?:is|at|of|=)?\s*(\d+)", narration, re.IGNORECASE)
        if m:
            player_state["System Strain"] = str(max(0, min(16, int(m.group(1)))))
        if player_state and player_file and os.path.exists(player_file):
            try:
                MarkdownDB.write_file(player_file, {"fields": player_state})
            except Exception as e:
                print(f"Warning: Failed to reflect player state: {e}")

    def _find_ship_file(self, ship_name):
        """Searches recursively for a ship file by its name."""
        for root, dirs, files in os.walk(GAME_DATA_DIR):
            for file in files:
                if file.replace(".md", "").lower() == ship_name.lower():
                    return os.path.join(root, file)
        return None

    def _load_chronicle(self):
        """Loads campaign_chronicle.md as a text block."""
        if os.path.exists(CHRONICLE_FILE):
            try:
                with open(CHRONICLE_FILE, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass
        return "# Campaign Chronicle\n* Operations commenced aboard Sworinta IV orbit."

    def _save_chronicle(self, new_bullet):
        """Appends a new bullet point to campaign_chronicle.md and updates state."""
        os.makedirs(os.path.dirname(CHRONICLE_FILE), exist_ok=True)
        new_bullet = new_bullet.strip()
        # Strip stray quotes, backticks, or code fences the LLM may wrap around the bullet
        new_bullet = new_bullet.strip("'\"`")
        # Remove duplicate leading bullet markers (e.g. "* * Foo" or "- * Foo")
        new_bullet = re.sub(r'^[\*\-\s]+\*\s*', '* ', new_bullet)
        if new_bullet:
            if not new_bullet.startswith("*"):
                new_bullet = f"* {new_bullet}"
            self.chronicle = self.chronicle.strip() + f"\n{new_bullet}"
            try:
                with open(CHRONICLE_FILE, "w", encoding="utf-8") as f:
                    f.write(self.chronicle + "\n")
            except Exception as e:
                print(f"Warning: Failed to save campaign chronicle: {e}")

    def _find_npc_file(self, npc_name):
        """Searches for an NPC file in the GameData folders using fuzzy/partial name matching."""
        search_clean = npc_name.lower().replace(" ", "").replace("_", "").replace(".", "")
        for folder in ["Player Data/Command Staff", "NPC Data"]:
            dir_path = os.path.join(GAME_DATA_DIR, folder)
            if not os.path.exists(dir_path):
                continue
            for f in os.listdir(dir_path):
                if f.endswith(".md"):
                    f_clean = f.lower().replace(".md", "").replace(" ", "").replace("_", "").replace(".", "")
                    if search_clean in f_clean or f_clean in search_clean:
                        return os.path.join(dir_path, f)
        return None

    def _npc_name_matches(self, n1, n2):
        """Helper to check if two NPC name strings match fuzzily."""
        c1 = n1.lower().replace(" ", "").replace("_", "").replace(".", "")
        c2 = n2.lower().replace(" ", "").replace("_", "").replace(".", "")
        return c1 in c2 or c2 in c1

    def _register_npc_to_location(self, loc_id, npc_name_clean):
        """Appends the NPC to the specified location in Game_info/locations.md."""
        loc_file = os.path.join(GAME_INFO_DIR, "locations.md")
        if not os.path.exists(loc_file):
            return
            
        try:
            with open(loc_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Warning: Failed to read locations file: {e}")
            return
            
        new_lines = []
        in_target_section = False
        npc_added = False
        display_name = npc_name_clean.replace("_", " ")
        
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("## "):
                sec_name = line_str[3:].strip().lower()
                loc = self.locations.get(loc_id)
                if loc and loc["name"].lower() == sec_name:
                    in_target_section = True
                else:
                    in_target_section = False
                    
            if in_target_section and line_str.startswith("*   **NPCs present:**"):
                # Append to NPCs list
                parts = line_str.split("present:**")
                npcs_raw = parts[1].strip()
                npcs = [n.replace("`", "").strip() for n in npcs_raw.split(",") if n.strip()]
                if not any(self._npc_name_matches(n, display_name) for n in npcs):
                    npcs.append(display_name)
                    new_npcs_str = ", ".join(f"`{n}`" for n in npcs)
                    indent = line[:line.find("*")]
                    line = f"{indent}*   **NPCs present:** {new_npcs_str}\n"
                    npc_added = True
                    
            new_lines.append(line)
            
        if npc_added:
            try:
                with open(loc_file, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                # Reload locations registry
                self.locations = self._load_locations()
            except Exception as e:
                print(f"Warning: Failed to write locations file: {e}")

    def _relocate_npc(self, npc_name_clean, new_loc_id):
        """Relocates an NPC from their current location to new_loc_id in Game_info/locations.md."""
        loc_file = os.path.join(GAME_INFO_DIR, "locations.md")
        if not os.path.exists(loc_file):
            return
            
        try:
            with open(loc_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Warning: Failed to read locations file: {e}")
            return
            
        new_lines = []
        display_name = npc_name_clean.replace("_", " ")
        target_loc = self.locations.get(new_loc_id)
        target_sec_name = target_loc["name"].lower() if target_loc else ""
        
        in_target_section = False
        npc_modified = False
        
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("## "):
                sec_name = line_str[3:].strip().lower()
                in_target_section = (sec_name == target_sec_name)
                
            if line_str.startswith("*   **NPCs present:**"):
                parts = line_str.split("present:**")
                npcs_raw = parts[1].strip()
                npcs = [n.replace("`", "").strip() for n in npcs_raw.split(",") if n.strip()]
                
                if in_target_section:
                    if not any(self._npc_name_matches(n, display_name) for n in npcs):
                        npcs.append(display_name)
                        npc_modified = True
                else:
                    if any(self._npc_name_matches(n, display_name) for n in npcs):
                        npcs = [n for n in npcs if not self._npc_name_matches(n, display_name)]
                        npc_modified = True
                        
                new_npcs_str = ", ".join(f"`{n}`" for n in npcs)
                indent = line[:line.find("*")]
                line = f"{indent}*   **NPCs present:** {new_npcs_str}\n" if npcs else f"{indent}*   **NPCs present:** \n"
                
            new_lines.append(line)
            
        if npc_modified:
            try:
                with open(loc_file, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                self.locations = self._load_locations()
            except Exception as e:
                print(f"Warning: Failed to write locations file: {e}")
