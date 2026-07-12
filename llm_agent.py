import json
import os
import re
import requests

# Default configuration
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_PARSER_MODEL = "dante_dante159/gary_gigax:latest"
DEFAULT_NARRATOR_MODEL = "dante_dante159/gary_gigax:latest"
DEFAULT_EMBED_MODEL = "nomic-embed-text"

# Forbidden mechanical words that should never leak into narrative prose
_MECH_WORDS = re.compile(
    r"\b(die|dice|d20|d10|d6|roll(?:ed|s|ing)?|triumph|despair|advantage|threat|"
    r"success(?:es)?|failure(?:s)?|crit(?:ical)?|natural 20|1d|2d|3d|4d|8d|12d)\b",
    re.IGNORECASE,
)


class LLMAgent:
    def __init__(self, config_path=None):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.ollama_url = DEFAULT_OLLAMA_URL
        self.parser_model = DEFAULT_PARSER_MODEL
        self.narrator_model = DEFAULT_NARRATOR_MODEL
        self.embed_model = DEFAULT_EMBED_MODEL

        # Auto-discover config.json next to this module if not supplied
        # (prevents silent fallback to hardcoded defaults when LLMAgent()
        #  is instantiated without a config_path).
        if not config_path:
            _here = os.path.dirname(os.path.abspath(__file__))
            for cand in (os.path.join(_here, "config.json"),
                         os.path.join(os.getcwd(), "config.json")):
                if os.path.exists(cand):
                    config_path = cand
                    break

        # Load config.json if present
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                self.api_key = cfg.get("GEMINI_API_KEY", self.api_key)
                url = cfg.get("OLLAMA_URL", self.ollama_url)
                if url and not url.startswith("http://") and not url.startswith("https://"):
                    url = "http://" + url
                self.ollama_url = url
                self.parser_model = cfg.get("PARSER_MODEL", self.parser_model)
                self.narrator_model = cfg.get("NARRATOR_MODEL", self.narrator_model) or self.parser_model
                self.embed_model = cfg.get("EMBED_MODEL", self.embed_model)
            except Exception as e:
                print(f"Warning: Failed to load config.json: {e}")

    # ------------------------------------------------------------------ #
    # Low level providers
    # ------------------------------------------------------------------ #
    def _call_gemini(self, prompt, model="gemini-1.5-flash", system_instruction=None):
        if not self.api_key:
            raise Exception("No GEMINI_API_KEY configured")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        contents = [{"parts": [{"text": prompt}]}]
        data = {"contents": contents}
        if system_instruction:
            data["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        try:
            res = requests.post(url, headers=headers, json=data, timeout=60)
            if res.status_code == 200:
                resp_json = res.json()
                return resp_json["candidates"][0]["content"]["parts"][0]["text"]
            else:
                raise Exception(f"Gemini API returned code {res.status_code}: {res.text[:300]}")
        except Exception as e:
            raise Exception(f"Gemini connection failed: {e}")

    def _call_ollama(self, prompt, model, system_instruction=None, stream=False,
                     num_ctx=8192, num_predict=1536):
        url = f"{self.ollama_url}/api/generate"
        data = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {"num_ctx": num_ctx, "num_predict": num_predict},
        }
        if system_instruction:
            data["system"] = system_instruction

        if stream:
            def _gen():
                try:
                    with requests.post(url, json=data, timeout=(15, 600), stream=True) as res:
                        if res.status_code != 200:
                            raise Exception(f"Ollama returned code {res.status_code}: {res.text[:300]}")
                        for line in res.iter_lines():
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            if "error" in obj:
                                raise Exception(f"Ollama error: {obj['error']}")
                            tok = obj.get("response", "")
                            if tok:
                                yield tok
                            if obj.get("done"):
                                break
                except Exception as e:
                    raise Exception(f"Ollama streaming failed: {e}")
            return _gen()
        else:
            try:
                res = requests.post(url, json=data, timeout=180)
                if res.status_code == 200:
                    return res.json().get("response", "")
                else:
                    raise Exception(f"Ollama returned code {res.status_code}: {res.text[:300]}")
            except Exception as e:
                raise Exception(f"Ollama connection failed: {e}")

    def _is_ollama_running(self):
        try:
            res = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            return res.status_code == 200
        except Exception:
            return False

    def query(self, prompt, system_instruction=None, is_parser=True, stream=False):
        """
        Executes query targeting Gemini -> Ollama.
        Returns a string (stream=False) or a generator of text chunks (stream=True,
        narrator only). Raises ConnectionError if both providers fail.
        """
        errors = []

        # 1. Try Gemini if API key is provided
        if self.api_key:
            try:
                return self._call_gemini(prompt, "gemini-1.5-flash", system_instruction)
            except Exception as e:
                errors.append(f"Gemini failed: {e}")

        # 2. Try Ollama
        if self._is_ollama_running():
            try:
                model = self.parser_model if is_parser else self.narrator_model
                num_predict = 1024 if is_parser else 2048
                if stream and not is_parser:
                    return self._call_ollama(prompt, model, system_instruction,
                                             stream=True, num_predict=num_predict)
                return self._call_ollama(prompt, model, system_instruction,
                                         stream=False, num_predict=num_predict)
            except Exception as e:
                errors.append(f"Ollama failed: {e}")
        else:
            errors.append(f"Ollama is not running at {self.ollama_url}")

        error_msg = (
            "DungeonOfTheStars Engine Connection Failure: No active LLM provider could be reached.\n"
            "Please check that Ollama is running (port 11434) or set the GEMINI_API_KEY environment variable.\n"
            "Details:\n" + "\n".join(f" - {err}" for err in errors)
        )
        raise ConnectionError(error_msg)

    # ------------------------------------------------------------------ #
    # JSON extraction helper (robust against prose / code fences)
    # ------------------------------------------------------------------ #
    def _extract_json(self, text):
        if not text:
            return None
        t = text.strip()
        # Strip markdown code fences if present
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
            t = re.sub(r"\n?```$", "", t)
            t = t.strip()
        # Direct parse
        try:
            return json.loads(t)
        except Exception:
            pass
        # Find first { ... last }
        start = t.find("{")
        end = t.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = t[start:end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------ #
    # Parser
    # ------------------------------------------------------------------ #
    def parse_command(self, command, location_data, player_data, history_data):
        """
        Parses a natural language player command into structured JSON.
        On any failure to obtain valid JSON, returns a safe 'valid=False' dict
        (instead of silently accepting the command).
        """
        system_instruction = (
            "You are the DungeonOfTheStars Parser & Judge. Your job is to translate the user's natural language command "
            "into structured actions while validating that the command is localized, immediate, and reasonable.\n\n"
            "CRITICAL VALIDATION RULES - ABSOLUTE PLAYER AGENCY:\n"
            "- The Commodore has absolute tactical authority and freedom of action. NEVER reject commands like ordering troopers to arrest officers, placing crew in the brig, executing traitors, shooting bridge officers, or making shipwide announcements. Mark these as valid=true and map appropriate engine_mutations (such as changing status to Arrested/KIA or moving NPCs to 'brig').\n"
            "- ONLY reject literally game-breaking meta-commands like 'win the game instantly' or 'magically know where the secret rebel base is without scanning'. Everything else in the game world is permitted!\n"
            "- Capital ships (Star Destroyers) cannot land on planets or enter atmospheric flight. If ordered to land a Star Destroyer, set valid=true but mark it as a hazardous orbital descent where drop-ships/shuttles must be deployed instead, or trigger structural warning alarms.\n"
            "- Accept long-term actions (like hyperdrive travel or background engineering repair tasks) but mark them as valid. "
            "Set appropriate time elapsed (minutes/hours) and list them under background_tasks if they occur in the background.\n"
            "- DYNAMIC TRAVEL & SECTORS: If the player commands the ship or themselves to travel to a new planet, room, orbit, sector, or distress signal that is not listed in the location database, set transit=true, choose a unique snake_case target_location_id (e.g., 'sworinta_v' or 'rebel_outpost'), and provide a clean name in target_location_name (e.g., 'Orbit of Sworinta V' or 'Rebel Comm Outpost'). The system will automatically register and generate it!\n"
            "- FLAGSHIP MOVEMENT & SECTOR TRANSIT: If the player orders the Star Destroyer (The Broken Sunrise) to change sectors or jump to a new orbit/coordinates (e.g., 'move the ship to the Asteroid Field', 'hyperspace jump to Sith Beacon', or 'orbit Sworinta V'), you MUST add a custom state update in engine_mutations: \"custom_state_updates\": {\"The_Broken_Sunrise.Current Sector\": \"New Sector Name\"} (e.g., \"Deep Rim Asteroid Field\", \"Sith Beacon Anomaly\", or \"Sworinta V Orbit\") so the ship's position updates on the tactical map!\n\n"
            "OUTPUT FORMAT:\n"
            "You MUST respond ONLY with a valid JSON block matching this structure:\n"
            "{\n"
            "  \"valid\": true,\n"
            "  \"rejection_reason\": null,\n"
            "  \"action_type\": \"move\" | \"use\" | \"dialogue\" | \"combat\" | \"other\",\n"
            "  \"skill_check\": {\n"
            "    \"required\": false,\n"
            "    \"skill\": \"Computers\" | \"Perception\" | ... | null,\n"
            "    \"difficulty\": 1 (Easy) to 5 (Formidable)\n"
            "  },\n"
            "  \"movement\": {\n"
            "    \"transit\": false,\n"
            "    \"target_location_id\": \"quarters\" | \"hangar\" | ... | null,\n"
            "    \"target_location_name\": \"Name of new location\" | null\n"
            "  },\n"
            "  \"time_elapsed_minutes\": 1,\n"
            "  \"background_tasks\": [],\n"
            "  \"engine_mutations\": {\n"
            "    \"wounds_change\": 0,\n"
            "    \"strain_change\": 0,\n"
            "    \"credits_change\": 0,\n"
            "    \"item_added\": null,\n"
            "    \"item_removed\": null,\n"
            "    \"custom_state_updates\": {}\n"
            "  },\n"
            "  \"detected_npc\": {\n"
            "    \"name\": \"Name_With_Underscores\",\n"
            "    \"role\": \"Role / Job Title\",\n"
            "    \"faction\": \"Faction Name\"\n"
            "  } | null\n"
            "}"
        )

        prompt = (
            f"LOCATION DATA:\n{json.dumps(location_data, indent=2)}\n\n"
            f"PLAYER STATUS:\n{json.dumps(player_data, indent=2)}\n\n"
            f"RECENT HISTORY & CAMPAIGN CHRONICLE:\n{json.dumps(history_data, indent=2)}\n\n"
            f"PLAYER COMMAND:\n\"{command}\"\n\n"
            "Provide the JSON response block below. Ensure it is parseable JSON (no markdown formatting code blocks, just raw JSON)."
        )

        raw = self.query(prompt, system_instruction, is_parser=True)
        parsed = self._extract_json(raw)
        if parsed is None:
            # One retry before giving up
            raw2 = self.query(prompt, system_instruction, is_parser=True)
            parsed = self._extract_json(raw2)

        if parsed is None:
            return {
                "valid": False,
                "rejection_reason": "The command parser returned an unreadable response. Please rephrase your order, Commodore.",
                "action_type": "other",
                "skill_check": {"required": False, "skill": None, "difficulty": 1},
                "movement": {"transit": False, "target_location_id": None, "target_location_name": None},
                "time_elapsed_minutes": 1,
                "background_tasks": [],
                "engine_mutations": {},
                "detected_npc": None,
            }

        # Normalise keys so the engine never hits KeyErrors
        parsed.setdefault("valid", True)
        parsed.setdefault("rejection_reason", None)
        parsed.setdefault("action_type", "other")
        parsed.setdefault("time_elapsed_minutes", 1)
        parsed.setdefault("background_tasks", [])
        sc = parsed.get("skill_check") or {}
        sc.setdefault("required", False)
        sc.setdefault("skill", None)
        sc.setdefault("difficulty", 1)
        parsed["skill_check"] = sc
        mv = parsed.get("movement") or {}
        mv.setdefault("transit", False)
        mv.setdefault("target_location_id", None)
        mv.setdefault("target_location_name", None)
        parsed["movement"] = mv
        em = parsed.get("engine_mutations") or {}
        for k in ("wounds_change", "strain_change", "credits_change", "item_added", "item_removed"):
            em.setdefault(k, 0 if k.endswith("_change") else None)
        em.setdefault("custom_state_updates", {})
        parsed["engine_mutations"] = em
        parsed.setdefault("detected_npc", None)
        return parsed

    # ------------------------------------------------------------------ #
    # Narrator
    # ------------------------------------------------------------------ #
    def generate_narration(self, command, action_result, location_data, history_data, stream=False):
        """
        Generates atmospheric narrative descriptions based on the command outcome.
        Returns a string (stream=False) or a generator of text chunks (stream=True).
        """
        system_instruction = (
            "You are the DungeonOfTheStars Narrator, writing descriptions for a Star Wars themed tactical text adventure.\n"
            "Write narrative prose in a direct, gritty, and tactical style. Keep the tone professional, like an Imperial Navy logs report. Do not use flowery, overly dramatic, or verbose language.\n"
            "Incorporate FFG dice results (Success/Failure, Advantage/Threat, Triumph/Despair) into in-universe outcomes.\n"
            "CRITICAL RULES - DIRECT EXECUTION & DIALOGUE:\n"
            "- DIRECT RESPONSE AND DIALOGUE: Your narrative MUST directly address and answer the player's immediate statement, command, or query. If the player asks a question to Kross or any NPC, that NPC MUST answer directly in dialogue. Never write a generic response that ignores or skips over the dialogue. If the player says something, NPCs must respond directly to what was said.\n"
            "- The Commodore's words, announcements, physical attacks, and orders are ABSOLUTE CANON. Never retcon or ignore them. If the Commodore fires a weapon at someone, do not make the NPC 'calmly step aside' or lecture the Commodore unless a mechanical dice failure occurred. If the Commodore gives an order or makes an announcement, NPCs must react realistically without inventing fake messages from Central Command that contradict the player!\n"
            "- DIALOGUE SPEAKER HEADERS: Whenever any NPC speaks, their dialogue MUST be preceded by an uppercase header on its own line (for example, <COMMANDER VANDAR KROSS> on its own line, followed by the dialogue on the next line: \"Shields holding at eighty percent, sir!\\\").\n"
            "- SECRECY OF THE BEACON: The crew, officers (including Commander Kross), and all external factions believe the signal is an ancient distress call from a derelict warship. Only the Commodore (player) and the Inquisitor know it is an ancient Sith beacon. Ensure all dialogues and crew reactions reflect this secrecy (e.g., crew members speaking about salvaging a derelict warship, while the Inquisitor speaks to you privately or via encrypted channels about the true nature of the Sith artifact).\n"
            "- Never mention Earth or real-world geography/history.\n"
            "- Do not repeat background information or location descriptions if they have not changed. Focus on the action itself and answering the query.\n"
            "- The story characters (and narration) must NEVER roll dice, mention dice, refer to dice, see stats, or mention tabletop mechanics. All dice rolls and rules happen outside the narrative world. Translate the dice outcomes purely into environmental events, mechanical failures, tactical changes, or physical reactions.\n"
            "- Advantage/Threat represent positive/negative side-effects. Triumph is a major boon, Despair is a major complication.\n"
            "Write detailed, thorough, and fully immersive descriptions (3-4 paragraphs or more). Ensure all parts of the action/order are completed and described in detail."
        )
        # Load campaign plot if available to guide acts and narrative branches
        campaign_context = ""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        campaign_file = os.path.join(base_dir, "Game_info/campaign_plot.md")
        if os.path.exists(campaign_file):
            try:
                with open(campaign_file, "r", encoding="utf-8") as f:
                    campaign_context = f.read()
            except Exception:
                pass

        prompt = ""
        if campaign_context:
            prompt += f"CAMPAIGN PLOT GUIDE & ACT OUTLINE:\n{campaign_context}\n\n"

        prompt += (
            f"LOCATION:\n{json.dumps(location_data, indent=2)}\n\n"
            f"COMMAND:\n\"{command}\"\n\n"
            f"ACTION RESULT / STATE MUTATIONS / DICE ROLL:\n{json.dumps(action_result, indent=2)}\n\n"
            f"RECENT HISTORY & CAMPAIGN CHRONICLE:\n{json.dumps(history_data, indent=2)}\n\n"
            "Generate the narrative prose now. Ensure you answer the player's query or resolve their command directly and thoroughly. Do not mention dice, rolls, or numbers."
        )

        return self.query(prompt, system_instruction, is_parser=False, stream=stream).strip() if not stream \
            else self.query(prompt, system_instruction, is_parser=False, stream=True)

    def summarize_turn(self, command, narration, state_changes):
        """
        Generates a single-line bullet point summarizing the narrative consequence
        of the turn to be appended to the Chronicle.
        """
        system_instruction = (
            "You are the Campaign Archivist. Write a single, brief, factual bullet point "
            "summarizing the player's action and the outcome. Focus on plot progression, "
            "NPC interactions, and item discoveries. Do not write atmospheric prose.\n"
            "Format: '* [Brief summary of action and result]'\n"
            "Example: '* Met Chief Engineer Titus Thul in Engineering; learned hyperdrive is offline.'"
        )

        prompt = (
            f"PLAYER ACTION: {command}\n"
            f"NARRATION OUTCOME: {narration}\n"
            f"STATE MUTATIONS: {json.dumps(state_changes)}\n"
            "Provide only the single bullet point starting with '* '."
        )

        try:
            summary = self.query(prompt, system_instruction, is_parser=True)
            return summary.strip()
        except Exception:
            return f"* Action: {command}"

    def generate_npc_card(self, name, role, faction, location_id, lore_context=None):
        """
        Generates a markdown character sheet (Data Card) for a new NPC.
        Incorporates Wookieepedia lore context if available to align stats/traits.
        """
        system_instruction = (
            "You are the Character Sheet Architect for FFG Star Wars RPG. Your job is to generate "
            "a complete, game-compatible character sheet for an NPC based on their name, role, "
            "faction, and any provided Wookieepedia lore context.\n\n"
            "STAT RULES:\n"
            "- Characteristics: Brawn, Agility, Intellect, Cunning, Willpower, Presence. Rank these from 1 to 6. "
            "Most average humans have 2s. Elite officers have 3s or 4s in Intellect/Cunning/Presence. Strong troopers "
            "have 3s or 4s in Brawn/Agility.\n"
            "- Wounds & Strain: Average NPC Wounds: 10-15. Soak: 2-4 (uniform/armor). Defense: 0-2.\n"
            "- Gear: Give them realistic gear based on their role (e.g. blaster pistol, code cylinder, comlink, datapads).\n\n"
            "You must output ONLY the raw Markdown matching this structure precisely (do not wrap in a markdown code block):\n"
            "# Officer/NPC Profile: [Name]\n"
            "## Role: [Role] | Faction: [Faction]\n\n"
            "## I. Live Status (Update During Gameplay)\n\n"
            "| Metric | Maximum | Current Value |\n"
            "| :--- | :---: | :---: |\n"
            "| **Wounds (Health)** | [value] | [ ] |\n"
            "| **System Strain** | [value] | [ ] |\n"
            "| **Soak Value** | [value] | [ ] |\n"
            "| **Defense - Melee** | [value] | [ ] |\n"
            "| **Defense - Ranged** | [value] | [ ] |\n\n"
            "### Duty Status\n"
            "*   **Operational Status:** [X] Active | [ ] Wounded | [ ] KIA\n"
            "*   **Current Location:** [Location ID]\n\n"
            "---\n\n"
            "## II. Characteristics\n\n"
            "*   **Brawn (BR):** [value]\n"
            "*   **Agility (AG):** [value]\n"
            "*   **Intellect (INT):** [value]\n"
            "*   **Cunning (CUN):** [value]\n"
            "*   **Willpower (WIL):** [value]\n"
            "*   **Presence (PR):** [value]\n\n"
            "---\n\n"
            "## III. Skills Profile\n\n"
            "*   [Skill Name 1] ([Characteristic Shorthand]): [ ] Rank [value]\n"
            "*   [Skill Name 2] ([Characteristic Shorthand]): [ ] Rank [value]\n\n"
            "---\n\n"
            "## IV. Gear & Inventory\n\n"
            "*   [Item 1]\n"
            "*   [Item 2]\n"
        )

        prompt = (
            f"NPC NAME: {name}\n"
            f"ROLE: {role}\n"
            f"FACTION: {faction}\n"
            f"LOCATION ID: {location_id}\n"
        )
        if lore_context:
            prompt += f"WOOKIEEPEDIA LORE CONTEXT:\n{lore_context}\n"

        prompt += "\nGenerate the raw markdown character sheet now."

        try:
            card_content = self.query(prompt, system_instruction, is_parser=False)
            return card_content.strip()
        except Exception as e:
            return (
                f"# Officer/NPC Profile: {name.replace('_', ' ')}\n"
                f"## Role: {role} | Faction: {faction}\n\n"
                f"## I. Live Status (Update During Gameplay)\n\n"
                f"| Metric | Maximum | Current Value |\n"
                f"| :--- | :---: | :---: |\n"
                f"| **Wounds (Health)** | 12 | [ ] |\n"
                f"| **System Strain** | 12 | [ ] |\n"
                f"| **Soak Value** | 3 | [ ] |\n"
                f"| **Defense - Melee** | 0 | [ ] |\n"
                f"| **Defense - Ranged** | 0 | [ ] |\n\n"
                f"### Duty Status\n"
                f"*   **Operational Status:** [X] Active | [ ] Wounded | [ ] KIA\n"
                f"*   **Current Location:** {location_id}\n\n"
                f"---\n\n"
                f"## II. Characteristics\n\n"
                f"*   **Brawn (BR):** 2\n"
                f"*   **Agility (AG):** 2\n"
                f"*   **Intellect (INT):** 2\n"
                f"*   **Cunning (CUN):** 2\n"
                f"*   **Willpower (WIL):** 2\n"
                f"*   **Presence (PR):** 2\n"
            )

    def generate_initial_intro(self, location_data):
        """
        Generates a long, highly detailed atmospheric introduction prose for a new game session.
        """
        system_instruction = (
            "You are the DungeonOfTheStars Narrator. Your task is to write a highly detailed, dramatic, and atmospheric "
            "introductory prose (3-5 paragraphs) to start the campaign.\n"
            "Establish a gritty, militaristic, and ominous tone suited for an Imperial Navy commander in the Outer Rim.\n"
            "Do not output any JSON, markdown headers, or suggested actions. Just write the descriptive narrative prose directly."
        )
        campaign_context = ""
        plotbasis_context = ""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        campaign_file = os.path.join(base_dir, "Game_info/campaign_plot.md")
        if os.path.exists(campaign_file):
            try:
                with open(campaign_file, "r", encoding="utf-8") as f:
                    campaign_context = f.read()
            except Exception:
                pass

        plotbasis_file = os.path.join(base_dir, "plotbasis.md")
        if os.path.exists(plotbasis_file):
            try:
                with open(plotbasis_file, "r", encoding="utf-8") as f:
                    plotbasis_context = f.read()
            except Exception:
                pass

        prompt = ""
        if campaign_context:
            prompt += f"CAMPAIGN PLOT GUIDE:\n{campaign_context}\n\n"
        if plotbasis_context:
            prompt += f"PLOT BASIS / SETTING PREMISE:\n{plotbasis_context}\n\n"

        prompt += (
            f"LOCATION DATA:\n{json.dumps(location_data, indent=2)}\n\n"
            "Generate the opening narration now. It must be highly detailed and atmospheric (3-5 paragraphs), describing "
            "the bridge of the Star Destroyer The Broken Sunrise, the toxic green gas giant Sworinta IV masking the ship, "
            "and the weak ping of the ancient Sith beacon resonating from deep space. "
            "CRITICAL PLOT POINT: The crew and officers (including Commander Kross) believe the signal is an ancient "
            "distress call from a derelict warship. Only the Commodore (you) and the assigned Inquisitor know it is a Sith beacon. "
            "Describe the junior sensor officer reporting it as a warship distress call, and the subtle silent reaction/exchange "
            "between you and the Inquisitor who stands in the shadows of the bridge watching you."
        )
        try:
            return self.query(prompt, system_instruction, is_parser=False).strip()
        except Exception as e:
            # Fallback if connection fails
            return (
                "You stand on the command bridge of the Imperial I-class Star Destroyer *The Broken Sunrise*, "
                "staring out through the reinforced viewports into the swirling green depths of Sworinta IV. "
                "The gas giant's intense radiation fields wash over the massive hull, scrambling long-range scans and "
                "cloaking your presence from any prying eyes in the sector. You are the absolute authority here—given the rank of "
                "Commodore by the Emperor himself—commanding this upgraded capital ship with its experimental weapons and Class 1.5 hyperdrive.\n\n"
                "But you are not alone in your command. Standing near the holonet alcove, the silent, cloaked figure of the Imperial Inquisitor "
                "assigned to your vessel watches. Officially, they are here to assist with the recovery of ancient Sith artifacts. Unofficially, "
                "their hand rests near their lightsaber, their cold eyes studying your every command decision.\n\n"
                "A soft tone chiming from the sensor pit breaks the silence. A junior deck officer looks up, nervous. "
                "\"Commodore Heros, sir. We've isolated the transmission. It's a weak, ancient distress call originating from the Deep Rim sector... "
                "preliminary telemetry suggests an old derelict warship signal.\"\n\n"
                "Beside you, the Inquisitor's gaze shifts to meet yours. Beneath their dark hood, a thin, knowing smile forms. "
                "To the crew, this is standard scrap metal and empty distress codes. But to those attuned to the dark side—and to you, "
                "who received the Emperor's private briefings—the signal resonates with a cold, distinct dark-side vibration. The Sith beacon has active power.\n\n"
                "Commander Kross stands nearby, awaiting your command."
            )
