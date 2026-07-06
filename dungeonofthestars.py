import os
import sys
import time
import json
from datetime import datetime

# Add project root to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.ansi import AnsiDecoder

from md_db import MarkdownDB
from game_engine import DungeonOfTheStarsEngine
from dice import pretty_print_results

console = Console()

def get_progress_bar(current, max_val, color="green", empty_color="grey23"):
    """Generates a retro progress bar representing capacity remaining."""
    width = 10
    if max_val <= 0:
        return "[ ]"
    pct = max(0.0, min(1.0, float(max_val - current) / max_val))
    filled = int(width * pct)
    empty = width - filled
    
    bar = Text("[", style="white")
    bar.append("█" * filled, style=color)
    bar.append("░" * empty, style=empty_color)
    bar.append("]", style="white")
    return bar

def get_fleet_status():
    """Reads status metrics for all capital escort vessels."""
    fleet = []
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ship_data_dir = os.path.join(base_dir, "GameData/ShipData")
    if not os.path.exists(ship_data_dir):
        return fleet
        
    for ship_folder in sorted(os.listdir(ship_data_dir)):
        folder_path = os.path.join(ship_data_dir, ship_folder)
        if os.path.isdir(folder_path):
            ship_file = os.path.join(folder_path, f"{ship_folder}.md")
            if os.path.exists(ship_file):
                try:
                    data = MarkdownDB.read_file(ship_file)
                    
                    # Extract class name from the file header
                    ship_class = "Star Destroyer"
                    with open(ship_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip().startswith("## Class:"):
                                ship_class = line.split("Class:")[1].strip()
                                break
                                
                    # Hull Trauma
                    hull_curr_str = data["fields"].get("Hull Trauma", "").strip()
                    hull_curr = int(hull_curr_str) if (hull_curr_str and hull_curr_str.isdigit()) else 0
                    
                    # Maximum Hull from technical specs
                    hull_max = 100
                    with open(ship_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if "Hull Trauma" in line:
                                parts = [p.strip() for p in line.split("|") if p.strip()]
                                if len(parts) >= 2 and parts[1].isdigit():
                                    hull_max = int(parts[1])
                                break
                    
                    hyperdrive = data["checklists"].get("Hyperdrive", "Nominal")
                    
                    # Format hull display
                    if hull_curr == 0:
                        hull_display = "[bold green]NOMINAL[/bold green]"
                    else:
                        pct = (hull_max - hull_curr) / hull_max
                        if pct > 0.75:
                            color = "green"
                        elif pct > 0.4:
                            color = "yellow"
                        else:
                            color = "red"
                        hull_display = f"[{color}]{hull_max - hull_curr}/{hull_max}[/{color}]"
                        
                    fleet.append({
                        "name": ship_folder.replace("_", " "),
                        "class": ship_class,
                        "hull": hull_display,
                        "hyperdrive": hyperdrive
                    })
                except Exception as e:
                    pass
    return fleet

class DungeonOfTheStarsTUI:
    def __init__(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            self.engine = DungeonOfTheStarsEngine()
        except ConnectionError as e:
            console.print(f"\n[bold red]CRITICAL: LLM Connection Failed[/bold red]")
            console.print(f"[yellow]{e}[/yellow]\n")
            sys.exit(1)
        except Exception as e:
            console.print(f"\n[bold red]CRITICAL: Engine Initialization Failed[/bold red]")
            console.print(f"[red]{e}[/red]\n")
            sys.exit(1)
            
        self.narrative_history = []
        self.in_settings = False
        self._add_initial_narration()

    def _add_initial_narration(self):
        # Read the current player location to establish context
        player_file = os.path.join(self.base_dir, "GameData/Player Data/Commodore_Nimrod_Heros.md")
        data = MarkdownDB.read_file(player_file)
        loc_name = data["fields"].get("Current Location", "Bridge, The Broken Sunrise (Orbiting Sworinta IV)")
        
        initial = (
            f"★ [bold green]TACTICAL DIRECTIVE ACTIVATED[/bold green] ★\n\n"
            f"You are standing on the command deck of the Star Destroyer [bold cyan]The Broken Sunrise[/bold cyan]. "
            f"Below you, the toxic green atmosphere of Sworinta IV churns within a radiation-shielded pocket of the sector. "
            f"Your task force escorts stand in defensive ranks, scanning the radiation shadow for any trace of the hidden Rebel outpost.\n\n"
            f"Commander Kross stands nearby, awaiting your command.\n"
            f"Current Location: [bold green]{loc_name}[/bold green]"
        )
        self.narrative_history.append(Text.from_markup(initial))

    def draw_layout(self):
        # 1. Read player stats dynamically
        player_file = os.path.join(self.base_dir, "GameData/Player Data/Commodore_Nimrod_Heros.md")
        player_data = MarkdownDB.read_file(player_file)
        
        wounds_str = player_data["fields"].get("Wounds (Health)", "0").strip()
        wounds = int(wounds_str) if (wounds_str and wounds_str.isdigit()) else 0
        strain_str = player_data["fields"].get("System Strain", "0").strip()
        strain = int(strain_str) if (strain_str and strain_str.isdigit()) else 0
        
        credits = player_data["fields"].get("Credits", "1000")
        location = player_data["fields"].get("Current Location", "Bridge")
        
        # 2. Build Header Panel
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header_text = Text(f"★ DUNGEONOFTHESTARS TACTICAL INTERFACE  |  {time_str}  |  SECTOR: SWORINTA IV ★", justify="center", style="bold green")
        header_panel = Panel(header_text, style="green")

        # 3. Build Status Panel (Left)
        status_text = Text()
        status_text.append("COMMODORE NIMROD HEROS\n", style="bold cyan")
        status_text.append(f"Location: ", style="bold")
        status_text.append(f"{location}\n", style="green")
        status_text.append(f"Credits:  ", style="bold")
        status_text.append(f"{credits} credits\n\n", style="yellow")
        
        # Progress bars
        status_text.append("Health/Wounds: ", style="bold")
        status_text.append_text(get_progress_bar(wounds, 14, "green"))
        status_text.append(f" {wounds}/14\n")
        
        status_text.append("System Strain: ", style="bold")
        status_text.append_text(get_progress_bar(strain, 16, "cyan"))
        status_text.append(f" {strain}/16\n\n")
        
        # Core Attributes
        status_text.append("Attributes:\n", style="bold underline cyan")
        for attr in ["Brawn (BR)", "Agility (AG)", "Intellect (INT)", "Cunning (CUN)", "Willpower (WIL)", "Presence (PR)"]:
            val = player_data["fields"].get(attr, "3")
            status_text.append(f"  {attr.split(' ')[0]}: ", style="bold")
            status_text.append(f"{val}   ", style="green")
        
        status_panel = Panel(status_text, title="[bold white]Command Profile[/bold white]", border_style="grey50")

        # 4. Build Fleet Panel (Left Bottom)
        fleet_table = Table(expand=True, box=None)
        fleet_table.add_column("Vessel Name", style="bold white", width=16)
        fleet_table.add_column("Class Profile", style="cyan", width=18)
        fleet_table.add_column("Hull Status", style="green")
        fleet_table.add_column("Hyperdrive", style="yellow")
        
        fleet_data = get_fleet_status()
        for ship in fleet_data:
            cls_short = ship["class"].split("(")[0].strip()
            h_style = "bold red" if ship["hyperdrive"].lower() != "nominal" else "yellow"
            fleet_table.add_row(
                ship["name"], 
                cls_short, 
                ship["hull"], 
                Text(ship["hyperdrive"], style=h_style)
            )
            
        fleet_panel = Panel(fleet_table, title="[bold white]Task Force Escort Fleet[/bold white]", border_style="grey50")

        # 5. Build Narration Panel (Right)
        if self.in_settings:
            # Render Settings Panel
            settings_text = Text()
            settings_text.append("★ SYSTEM SETTINGS MANAGER ★\n\n", style="bold green")
            settings_text.append("Modify target parameters directly in the input field below:\n\n", style="italic")
            settings_text.append("Commands:\n", style="bold underline cyan")
            settings_text.append("  /set model <name>   - Change Ollama model (e.g. qwen2.5:3b)\n", style="grey70")
            settings_text.append("  /set url <url>       - Change Ollama server endpoint\n", style="grey70")
            settings_text.append("  /set key <api_key>   - Save Gemini cloud API key\n", style="grey70")
            settings_text.append("  /back or /exit       - Return to tactical operations screen\n\n", style="bold yellow")
            
            settings_text.append("Current System Configurations:\n", style="bold underline cyan")
            
            # Add table inside text flow
            api_key_status = "[green]Configured[/green]" if self.engine.llm.api_key else "[grey50]Not Configured (Cloud Disabled)[/grey50]"
            
            settings_table = Table(box=None, expand=True)
            settings_table.add_column("Setting Param", style="bold cyan", width=22)
            settings_table.add_column("Status / Current Value", style="yellow")
            settings_table.add_row("Model (Parser/Narrator)", self.engine.llm.parser_model)
            settings_table.add_row("Ollama Host URL", self.engine.llm.ollama_url)
            settings_table.add_row("Gemini API Key Status", api_key_status)
            
            narrative_panel = Panel(
                Group(
                    settings_text,
                    settings_table
                ),
                title="[bold yellow]System Configurations Dashboard[/bold yellow]", 
                border_style="yellow"
            )
        else:
            # Standard Narration Panel
            narrative_text = Text()
            for turn_idx, entry in enumerate(self.narrative_history[-3:]):
                if turn_idx > 0:
                    narrative_text.append("\n" + "─" * 40 + "\n\n")
                
                if isinstance(entry, str):
                    narrative_text.append(Text.from_markup(entry))
                else:
                    narrative_text.append(entry)
                
            narrative_panel = Panel(
                narrative_text, 
                title="[bold white]Tactical Log & Narrative Screen[/bold white]", 
                border_style="green"
            )

        # 6. Assemble Layout
        layout = Layout()
        layout.split_column(
            Layout(header_panel, size=3),
            Layout(name="body"),
        )
        
        layout["body"].split_row(
            Layout(name="left", ratio=2),
            Layout(narrative_panel, ratio=3)
        )
        
        layout["left"].split_column(
            Layout(status_panel, ratio=3),
            Layout(fleet_panel, ratio=2)
        )
        
        return layout

    def _handle_save_command(self):
        """Creates a snapshot backup of the current game files to Saves directory."""
        import shutil
        save_dir = os.path.join(self.base_dir, "GameData/Saves/manual_save")
        os.makedirs(save_dir, exist_ok=True)
        
        try:
            player_src = os.path.join(self.base_dir, "GameData/Player Data")
            ship_src = os.path.join(self.base_dir, "GameData/ShipData")
            history_src = os.path.join(self.base_dir, "GameData/game_history.json")
            
            shutil.copytree(player_src, os.path.join(save_dir, "Player Data"), dirs_exist_ok=True)
            shutil.copytree(ship_src, os.path.join(save_dir, "ShipData"), dirs_exist_ok=True)
            if os.path.exists(history_src):
                shutil.copy2(history_src, os.path.join(save_dir, "game_history.json"))
                
            msg = Text.from_markup("💾 [bold green]SYSTEM SAVE COMPLETE:[/bold green] Tactical database backed up to `GameData/Saves/manual_save/`.")
            self.narrative_history.append(msg)
        except Exception as e:
            self.narrative_history.append(Text(f"❌ Failed to backup game state: {e}", style="bold red"))

    def _handle_setting_update(self, command):
        """Updates configs dynamically and saves to config.json."""
        parts = command.split(" ", 2)
        if len(parts) < 3:
            console.print("[red]Format error: Use /set <key> <value>[/red]")
            time.sleep(1.2)
            return
            
        key = parts[1].lower()
        val = parts[2].strip()
        
        config_path = os.path.join(self.base_dir, "config.json")
        cfg = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    cfg = json.load(f)
            except:
                pass
                
        key_map = {
            "model": "PARSER_MODEL",
            "url": "OLLAMA_URL",
            "key": "GEMINI_API_KEY"
        }
        
        cfg_key = key_map.get(key)
        if not cfg_key:
            console.print(f"[red]Unknown configuration: '{key}'. Valid parameters: model, url, key[/red]")
            time.sleep(1.2)
            return
            
        cfg[cfg_key] = val
        if cfg_key == "PARSER_MODEL":
            cfg["NARRATOR_MODEL"] = val
            
        # Write file
        try:
            with open(config_path, "w") as f:
                json.dump(cfg, f, indent=2)
            
            # Sync to live engine
            if cfg_key == "GEMINI_API_KEY":
                self.engine.llm.api_key = val
            elif cfg_key == "OLLAMA_URL":
                self.engine.llm.ollama_url = val
            elif cfg_key == "PARSER_MODEL":
                self.engine.llm.parser_model = val
                self.engine.llm.narrator_model = val
                
            console.print(f"[green]Parameter '{key}' successfully synchronized and updated in config.json![/green]")
        except Exception as e:
            console.print(f"[red]Failed to commit config changes: {e}[/red]")
            
        time.sleep(1.2)

    def loop(self):
        while True:
            # Clear terminal screen
            os.system("clear" if os.name == "posix" else "cls")
            
            # Render TUI dashboard
            layout = self.draw_layout()
            console.print(layout)
            
            # Custom input prompt based on mode
            if self.in_settings:
                console.print("\n[bold yellow]System Settings[/bold yellow] > ", end="")
            else:
                console.print("\n[bold cyan]Commodore NIMROD Heros[/bold cyan] > ", end="")
                
            try:
                command = input()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Tactical interface deactivated. Safe travels, Commodore.[/yellow]\n")
                break
                
            if not command.strip():
                continue
                
            command_clean = command.strip().lower()
            
            # Handle commands in settings mode
            if self.in_settings:
                if command_clean in ("/back", "/exit", "exit", "back"):
                    self.in_settings = False
                    continue
                elif command_clean.startswith("/set "):
                    self._handle_setting_update(command.strip())
                    continue
                else:
                    console.print("[yellow]Invalid settings command. Type /back to exit, or /set <key> <value>[/yellow]")
                    time.sleep(1.2)
                    continue

            # Standard mode checks
            if command_clean in ("exit", "quit"):
                console.print("\n[yellow]Tactical interface deactivated. Safe travels, Commodore.[/yellow]\n")
                break
            elif command_clean == "/settings":
                self.in_settings = True
                continue
            elif command_clean == "/save":
                self._handle_save_command()
                continue
                
            # Process natural language commands
            console.print("[green]Processing tactical instructions...[/green]")
            try:
                narrative_output = self.engine.execute_turn(command.strip())
                
                last_turn = self.engine.history[-1] if self.engine.history else {}
                dice_res = last_turn.get("dice_roll")
                
                turn_desc = Text()
                turn_desc.append(f"> {command}\n", style="bold cyan")
                
                if dice_res:
                    dice_str = pretty_print_results(dice_res)
                    turn_desc.append(Text.from_markup(f"🎲 [bold yellow]DICE CHECK:[/bold yellow] {dice_str}\n\n"))
                    
                turn_desc.append(narrative_output)
                self.narrative_history.append(turn_desc)
            except Exception as e:
                console.print(f"\n[bold red]ERROR OCCURRED DURING EXECUTION:[/bold red]")
                console.print(f"[red]{e}[/red]\n")
                console.print("Press Enter to continue...")
                input()

if __name__ == "__main__":
    tui = DungeonOfTheStarsTUI()
    tui.loop()
