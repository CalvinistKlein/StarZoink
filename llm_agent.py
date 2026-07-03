import json
import os
import re
import requests

# Default configuration
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_PARSER_MODEL = "qwen2.5:3b"
DEFAULT_NARRATOR_MODEL = "qwen2.5:3b"

class LLMAgent:
    def __init__(self, config_path=None):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.ollama_url = DEFAULT_OLLAMA_URL
        self.parser_model = DEFAULT_PARSER_MODEL
        self.narrator_model = DEFAULT_NARRATOR_MODEL
        
        # Load config.json if present
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                    self.api_key = cfg.get("GEMINI_API_KEY", self.api_key)
                    self.ollama_url = cfg.get("OLLAMA_URL", self.ollama_url)
                    self.parser_model = cfg.get("PARSER_MODEL", self.parser_model)
                    self.narrator_model = cfg.get("NARRATOR_MODEL", self.narrator_model)
            except Exception as e:
                print(f"Warning: Failed to load config.json: {e}")

    def _call_gemini(self, prompt, model="gemini-1.5-flash", system_instruction=None):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        
        contents = [{"parts": [{"text": prompt}]}]
        data = {"contents": contents}
        
        if system_instruction:
            data["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
            
        try:
            res = requests.post(url, headers=headers, json=data, timeout=10)
            if res.status_code == 200:
                resp_json = res.json()
                return resp_json["candidates"][0]["content"]["parts"][0]["text"]
            else:
                raise Exception(f"Gemini API returned code {res.status_code}: {res.text}")
        except Exception as e:
            raise Exception(f"Gemini connection failed: {e}")

    def _call_ollama(self, prompt, model, system_instruction=None):
        url = f"{self.ollama_url}/api/generate"
        
        data = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        
        if system_instruction:
            data["system"] = system_instruction
            
        try:
            res = requests.post(url, json=data, timeout=60)
            if res.status_code == 200:
                return res.json().get("response", "")
            else:
                raise Exception(f"Ollama returned code {res.status_code}")
        except Exception as e:
            raise Exception(f"Ollama connection failed: {e}")

    def _is_ollama_running(self):
        try:
            res = requests.get(f"{self.ollama_url}/api/tags", timeout=1)
            return res.status_code == 200
        except:
            return False

    def query(self, prompt, system_instruction=None, is_parser=True):
        """
        Executes query targeting Gemini -> Ollama. Raises ConnectionError if both fail.
        """
        errors = []

        # 1. Try Gemini if API key is provided
        if self.api_key:
            try:
                model = "gemini-1.5-flash"
                return self._call_gemini(prompt, model, system_instruction)
            except Exception as e:
                errors.append(f"Gemini failed: {e}")
                
        # 2. Try Ollama if running
        if self._is_ollama_running():
            try:
                model = self.parser_model if is_parser else self.narrator_model
                return self._call_ollama(prompt, model, system_instruction)
            except Exception as e:
                errors.append(f"Ollama failed: {e}")
        else:
            errors.append(f"Ollama is not running at {self.ollama_url}")
            
        # Raise error since mock fallback is disabled by user request
        error_msg = (
            "StarZork Engine Connection Failure: No active LLM provider could be reached.\n"
            "Please check that Ollama is running locally (port 11434) or set the GEMINI_API_KEY environment variable.\n"
            "Details:\n" + "\n".join(f" - {err}" for err in errors)
        )
        raise ConnectionError(error_msg)

    def parse_command(self, command, location_data, player_data, history_data):
        """
        Parses a natural language player command.
        Returns a dictionary mapping to the structured JSON schema.
        """
        system_instruction = (
            "You are the StarZork Parser & Judge. Your job is to translate the user's natural language command "
            "into structured actions while validating that the command is localized, immediate, and reasonable.\n\n"
            "CRITICAL VALIDATION RULES:\n"
            "- Reject broad, game-skipping commands like 'win the game', 'destroy the rebels instantly', 'know where the base is', "
            "or 'kill everyone'. Mark these as valid=false, and provide an in-universe rejection reason explaining that such broad "
            "actions are strategic objectives that require operational steps.\n"
            "- Reject physically impossible commands based on the location (e.g., trying to open the safe in quarters while standing on the bridge).\n"
            "- Accept long-term actions (like hyperdrive travel or background engineering repair tasks) but mark them as valid. "
            "Set appropriate time elapsed (minutes/hours) and list them under background_tasks if they occur in the background.\n\n"
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
            "    \"target_location_id\": \"quarters\" | \"hangar\" | ... | null\n"
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
            "  }\n"
            "}"
        )
        
        prompt = (
            f"LOCATION DATA:\n{json.dumps(location_data, indent=2)}\n\n"
            f"PLAYER STATUS:\n{json.dumps(player_data, indent=2)}\n\n"
            f"RECENT HISTORY:\n{json.dumps(history_data, indent=2)}\n\n"
            f"PLAYER COMMAND:\n\"{command}\"\n\n"
            "Provide the JSON response block below. Ensure it is parseable JSON (no markdown formatting code blocks, just raw JSON)."
        )
        
        raw_response = self.query(prompt, system_instruction, is_parser=True)
        
        # Clean response of markdown wraps if any
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(json)?\n", "", cleaned)
            cleaned = re.sub(r"\n```$", "", cleaned)
            cleaned = cleaned.strip()
            
        try:
            return json.loads(cleaned)
        except Exception as e:
            # If JSON parsing fails, return a safe recovery parser dictionary
            return {
                "valid": True,
                "rejection_reason": None,
                "action_type": "other",
                "skill_check": {"required": False, "skill": None, "difficulty": 1},
                "movement": {"transit": False, "target_location_id": None},
                "time_elapsed_minutes": 1,
                "background_tasks": [],
                "engine_mutations": {}
            }

    def generate_narration(self, command, action_result, location_data, history_data):
        """
        Generates atmospheric narrative descriptions based on the command outcome.
        """
        system_instruction = (
            "You are the StarZork Narrator, writing descriptions for a Star Wars themed tactical text adventure.\n"
            "Write narrative prose in a direct, gritty, and tactical style. Keep the tone professional, like an Imperial Navy logs report. Do not use flowery, overly dramatic, or verbose language.\n"
            "Incorporate FFG dice results (Success/Failure, Advantage/Threat, Triumph/Despair) into in-universe outcomes.\n"
            "CRITICAL RULES:\n"
            "- Your narrative MUST directly address and resolve the player's immediate command or query. If the player asks a question, queries a database, or talks to an NPC, you must write the response, dialogue, or information retrieved within your prose.\n"
            "- Do not repeat background information or location descriptions if they have not changed. Focus on the action itself and answering the query.\n"
            "- The story characters (and narration) must NEVER roll dice, mention dice, refer to dice, see stats, or mention tabletop mechanics. All dice rolls and rules happen outside the narrative world. Translate the dice outcomes purely into environmental events, mechanical failures, tactical changes, or physical reactions.\n"
            "- Advantage/Threat represent positive/negative side-effects. Triumph is a major boon, Despair is a major complication.\n"
            "Keep descriptions very concise (1-2 short paragraphs max)."
        )
        
        prompt = (
            f"LOCATION:\n{json.dumps(location_data, indent=2)}\n\n"
            f"COMMAND:\n\"{command}\"\n\n"
            f"ACTION RESULT / STATE MUTATIONS / DICE ROLL:\n{json.dumps(action_result, indent=2)}\n\n"
            f"RECENT HISTORY:\n{json.dumps(history_data, indent=2)}\n\n"
            "Generate the narrative prose now. Ensure you answer the player's query or resolve their command directly and concisely. Do not mention dice, rolls, or numbers."
        )
        
        return self.query(prompt, system_instruction, is_parser=False).strip()
