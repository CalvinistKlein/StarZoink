# DungeonOfTheStars: Game Framework & Demo Implementation Plan

This document outlines the conceptual design, feasibility analysis, system architecture, and implementation plan for **DungeonOfTheStars**—an LLM-powered text-adventure framework with a Star Wars theme and a modern, high-fidelity terminal UI.

---

## 1. Feasibility Analysis

### A. Local LLM Execution (Dual-Model Strategy)
*   **Feasibility:** **Highly Feasible** with a **Hybrid Engine Architecture** and **Dual-Model Setup**.
*   **Analysis:** 
    *   **The Risk:** Small models have poor logical consistency over long sessions. If the LLM is responsible for tracking inventory, door lock states, and map layout, it *will* hallucinate, lose items, or allow the player to walk through solid walls.
    *   **The Solution:** We must build a **hybrid engine**. The core game state (locations, items, inventory, NPC locations, locked status) will be handled by a deterministic, code-based engine. The LLM's role will be limited to:
        1.  **Semantic Parsing:** Translating player natural language into structured JSON commands. Needs to be **fast** and **reliable**.
        2.  **Creative Narration:** Generating rich, thematic Star Wars prose from engine output. Needs to be **atmospheric and creative**.
    *   **Recommended Runner:** `Ollama` using GGUF format for easy local setup, with fallback to API keys (Gemini, OpenAI, OpenRouter).
*   **Model Selection:**
    *   **Parser Model (default `qwen2.5:3b`):** ~2.5 GB RAM (Q4). Best-in-class JSON adherence at this size. Runs on virtually any hardware including old laptops and Raspberry Pi 5.
    *   **Narrator Model (default `qwen2.5:7b`):** ~4.5 GB RAM (Q4). Noticeably richer, more atmospheric prose. Runs on any machine with 8 GB total RAM.
    *   **Why Qwen 2.5?** Strongest structured output (JSON) compliance of any open model family at every size tier. Handles the "don't invent items/exits" constraint far better than Llama or Mistral at equivalent sizes.
*   **Hardware Compatibility Matrix:**

    | User's Machine | Parser | Narrator | RAM Needed |
    |---------------|--------|----------|-----------|
    | Low-end (4 GB RAM) | `qwen2.5:3b` | `qwen2.5:3b` (same) | ~2.5 GB |
    | Mid-range (8 GB RAM) | `qwen2.5:3b` | `qwen2.5:7b` | ~5 GB |
    | High-end (16+ GB / GPU) | `qwen2.5:3b` | `qwen2.5:14b` | ~10 GB |
    | No Ollama / mobile | Mock parser | Cloud API (Gemini Flash free tier) | 0 |

*   Models are configurable via `config.json` (`PARSER_MODEL`, `NARRATOR_MODEL`) or environment variables (`DUNGEONOFTHESTARS_PARSER_MODEL`, `DUNGEONOFTHESTARS_NARRATOR_MODEL`).


### B. Wookieepedia Knowledge Base Integration
*   **Feasibility:** **Highly Feasible** via **Local Cache & On-Demand API Scraping**.
*   **Analysis:** 
    *   The entire Wookieepedia dataset is massive. A raw text dump is gigabytes of data—far too large to store or parse locally in its entirety for a simple game.
    *   **The Solution:** Implement a **"Scrape-Once, Cache-Forever"** model. We will construct a lightweight python utility (`wookieepedia.py`) that queries the official MediaWiki/Wikia API for Wookieepedia.
    *   When the game references a Star Wars entity, planet, or item (e.g. *"T-16 Skyhopper"*), the engine checks a local cache file (`wookieepedia_cache.json` or a SQLite database).
    *   If it is not present in the cache, the engine fetches the article content from the Wookieepedia API, parses and cleans the text (removing HTML tags/infobox metadata), caches it locally, and feeds the relevant text snippet into the LLM's context.
    *   To allow the demo to run offline or with zero latency, we will pre-scrape and pre-seed the cache with core articles relevant to the demo area (e.g. moisture farms, wampas, imperial outposts, holocrons). This combines the speed and stability of a small footprint with access to the entire Wookieepedia knowledge base!


### C. Rich Terminal UI (btop-style)
*   **Feasibility:** **Highly Feasible**.
*   **Analysis:** 
    *   Using Python with the **`Textual`** or **`Rich`** libraries, we can build a layout with dedicated panels:
        *   A main text log for the narrative.
        *   A sidebar showing player stats, inventory (loaded from file), and controls to launch dynamic, interactive vector/SVG overlays (Sector Map and Ship Schematic).
        *   Visual health bars, shield meters, or item weights represented as text-based progress bars or graphs (similar to `btop`).
        *   A sleek, command-line input box at the bottom.

---

## 2. System Architecture (The "Hybrid" Approach)

The engine separates game logic from language generation:

```
  +------------------+
  |   Player Input   |
  +--------+---------+
           | (Natural Language)
           v
  +------------------+
  |   Terminal UI    |
  +--------+---------+
           |
           v
  +------------------+
  |    LLM Parser    |  <-- Interprets user input (e.g., "pry open mailbox")
  +--------+---------+
           | (Structured JSON command, e.g. {"action": "open", "target": "mailbox"})
           v
  +------------------+      +-------------------+
  |   Game Engine    | ---> |    State Files    | (world.json, inventory.json)
  +--------+---------+      +-------------------+
           | (Raw state outcome, e.g. "Opened mailbox. Leaflet inside.")
           v
  +------------------+      +-------------------+
  |   LLM Narrator   | <--- |   RAG Lore DB     | (Wookieepedia snippets)
  +--------+---------+      +-------------------+
           | (Rich thematic description)
           v
  +------------------+
  |   Terminal UI    |  <-- Renders description & updates btop panels
  +------------------+
```

### Components:
1.  **State Manager (`world.json`, `inventory.json`):** Tracks rooms, items, NPCs, and coordinates. Every state change is written immediately to disk to allow seamless saving and loading.
2.  **Semantic Parser:** A highly prompt-engineered LLM call that extracts intents (e.g., `verbs: [take], targets: [leaflet]`).
3.  **NPC Manager:** Simulates NPC routines, inventories, and simple schedules. When an NPC is in the same room, they receive an agent prompt summarizing their motivations and recent actions.
4.  **RAG Lore Engine:** Retrieves canonical Star Wars lore snippets on demand to ground descriptions in official canon.

---

## 3. Demo Scope: Classic Zork 1 (West of House)

To validate the framework, the demo will implement the opening sequence of Zork 1 with an LLM backend and Star Wars theme options:

### The Template Scenario:
*   **Location:** "West of House". A clearing in a forest, a white house with a boarded front door, a mailbox.
*   **Items:** A mailbox containing a leaflet.
*   **Goals:**
    1.  Open the mailbox and take the leaflet.
    2.  Read the leaflet (which will contain DungeonOfTheStars intro lore).
    3.  Find a way into the house (finding the open window on the east side).
    4.  Enter the kitchen/living room, find the trapdoor under the rug, and descend into the "underground empire".

### Demo Goals:
*   Verify that the local LLM correctly parses commands like *"pry open the mailbox"* or *"look inside the box"* into the engine's `open mailbox` action.
*   Verify that the inventory file is accurately updated and rendered in a `btop`-style sidebar.
*   Verify that saving and loading works seamlessly, returning the player to their exact location and state.

---

## 4. Phased Implementation Roadmap

### Phase 1: Environment & Local LLM Setup
*   Configure Python project, dependencies (`textual`, `rich`, `langchain`/`ollama`, `chromadb`).
*   Establish interface with a local LLM (defaulting to Ollama with `llama3.2:3b` or `qwen2.5:3b`).

### Phase 2: Core Game Engine & State Files
*   Define JSON schemas for rooms, items, NPCs, and inventories.
*   Build state transitions (`move`, `take`, `drop`, `open`, `inventory`).
*   Implement `save_game()` and `load_game()` functions writing to local JSON files.

### Phase 3: Terminal UI (Textual / Rich)
*   Build the `btop`-style visual framework.
*   Include modals for high-fidelity vector graphics (Sector Map & Ship Schematic), status indicators (location, wounds, strain), inventory lists, and the input console.

### Phase 4: Semantic Command Parser & Narrator
*   Create prompt templates for the local LLM:
    *   **Parser Prompt:** Convert raw input to structured JSON action.
    *   **Narrator Prompt:** Inject current room data, item descriptions, and last action output to output atmospheric prose.
*   Implement command fallback systems for when the LLM generates invalid JSON.

### Phase 5: Wookieepedia Lore Engine
*   Initialize an embedded vector database.
*   Seed it with entries for Zork/DungeonOfTheStars objects (e.g., white house -> old republic scout outpost; grue -> nexu or wampa; leaflet -> holocron fragment).

### Phase 6: Demo Integration
*   Assemble all components into the Zork 1 "West of House" demo.
*   Conduct manual playtesting to check inventory consistency, save/load persistence, and TUI performance.

### Phase 7: Standalone Packaging & Executable Compilation
*   Set up a PyInstaller build script (`build_executable.py`) that packages the Python game and assets (`demo_world.json`, cached lore) into a single binary (`DungeonOfTheStars` or `DungeonOfTheStars.exe`).
*   Incorporate logic to read resources from `sys._MEIPASS` when compiled.

---

## 5. Packaging & Cross-Platform Distribution Plan

### A. Distribution Strategy
To make the game easily distributable to other users, systems, OSs, and hardware configurations:
1.  **Engine Compilation:** We will package the entire application (game TUI, deterministic logic engine, data files) into a single standalone binary using **PyInstaller** (`--onefile` mode).
2.  **Resource Bundling:** Dynamic assets (like the JSON world file `demo_world.json` and the pre-seeded `wookieepedia_cache.json`) will be compiled directly inside the executable. The code will dynamically resolve the resource path depending on whether it is running as source or compiled (`sys._MEIPASS`).
3.  **Decoupling the LLM Layer:** 
    *   *Why?* Packaging a local 3B model (~2-3GB) and hardware-specific neural runtimes (CUDA, Vulkan, Metal, CPU) directly into the game executable would make it massive, slow to start, and highly prone to crashing on unsupported graphics cards.
    *   *The Solution:* Keep the game binary lightweight (approx. 25MB) and support two options for LLM logic:
        *   **Local Runner (Ollama):** Queries the user's locally running Ollama instance on `http://localhost:11434`. (Highly configurable and handles hardware acceleration automatically for the user's specific OS/GPU).
        *   **API Fallback (Cloud):** A setup screen in the game allowing the user to input an API key (e.g. Gemini, OpenAI, or OpenRouter) if they want a zero-setup, zero-install experience. The game will save this key locally in a config file (`config.json`).

