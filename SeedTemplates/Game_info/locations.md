# DungeonOfTheStars Scenario Map: Shadows of Sworinta - The Sith Beacon

This file defines the static room/sector registry for the DungeonOfTheStars scenario. 
Exits are strictly enforced by the game engine, and descriptions are used to guide the LLM Narrator.

---

## 1. Bridge of The Broken Sunrise
*   **Location ID:** `bridge`
*   **Name:** Bridge of The Broken Sunrise
*   **Exits:**
    *   `hangar` (via Command Lift)
    *   `quarters` (via Command Lift)
    *   `commons` (via Command Lift)
*   **Description:** The command deck of the Imperial I-class Star Destroyer *The Broken Sunrise*. Pit crew technicians work at sub-surface console stations, and green tactical displays show Sworinta IV spinning slowly below. The viewport looks out over the nose of the massive wedge-shaped ship.
*   **NPCs present:** `Commander_Vandar_Kross (XO)`, `Lt_Cmdr_Aris_Thorne (Nav Officer)`, `Lt Cmdr Aris Thorne (Nav Officer)`
*   **Interactable Elements:**
    *   `command_console`: Access tactical map, flagship systems, and status reports.
    *   `holonet_transceiver`: Receive messages from the Imperial command or Emperor directly.
    *   `viewport`: Look out at Sworinta IV and the surrounding space sector.

---

## 2. Commodore's Quarters
*   **Location ID:** `quarters`
*   **Name:** Commodore Nimrod Heros' Quarters
*   **Exits:**
    *   `bridge` (via Command Lift)
*   **Description:** A sparse, metallic suite suited for a high-ranking officer. A single view-port looks out into deep space. The room contains a bunk, a desk, and a personal terminal. A locked wall safe sits beside the bed.
*   **NPCs present:** None
*   **Interactable Elements:**
    *   `desk_terminal`: Access private logs and decrypted imperial correspondence.
    *   `wall_safe`: Secure storage container (requires a code or mechanical bypass to open). Contains your personal rank cylinder.
    *   `viewport`: View space surrounding the ship.

---

## 3. Hangar Bay 1
*   **Location ID:** `hangar`
*   **Name:** Hangar Bay 1
*   **Exits:**
    *   `bridge` (via Command Lift)
    *   `orbit` (via launching Lambda Shuttle or TIE Fighter)
*   **Description:** A cavernous hangar deck echoing with the hum of sublight engines and structural machinery. Rows of TIE series starfighters hang from overhead rack gantries. Support crew perform maintenance on shuttles and cargo lifters.
*   **NPCs present:** `Lt_Cmdr_Titus_Thul` (Chief Engineer)
*   **Interactable Elements:**
    *   `lambda_shuttle`: The shuttle *Lambda-01*, resting on the landing pad, ready for departure.
    *   `flight_control_console`: Monitor launch sequences, deck airlock state, and starfighter readiness.
    *   `tie_gantry`: Access ladder leading to suspended TIE Fighter cockpits.

---

## 4. Crew Quarters & Deck Commons
*   **Location ID:** `commons`
*   **Name:** Crew Quarters & Deck Commons
*   **Exits:**
    *   `bridge` (via Command Lift)
*   **Description:** The bustling residential and recreational sector of the Star Destroyer. Off-duty technicians, stormtroopers, and enlisted crew move in regimented, disciplined patterns.
*   **NPCs present:** `Lt_Cmdr_Kaelen_Vance` (Chief Medical Officer / Security Liaison)
*   **Interactable Elements:**
    *   `crew_logs`: Consoles displaying duty schedules, rosters, and security status.
    *   `notice_board`: Imperial propaganda posters and general fleet notices.

---

## 5. Orbit of Sworinta IV
*   **Location ID:** `orbit`
*   **Name:** Orbit of Sworinta IV (Space Sector)
*   **Exits:**
    *   `hangar` (via landing/docking shuttle or fighter)
    *   `surface` (via descending flight vector)
    *   `sith_beacon` (via ship sector transit / navigation)
*   **Description:** The deep space sector surrounding the green gas giant Sworinta IV. The planet emits high-density radiation that scrambles long-range scans but serves as perfect masking for your flagship, *The Broken Sunrise*. No other escort ships are present in your immediate task force.
*   **NPCs present:** None
*   **Interactable Elements:**
    *   `sensor_grid`: Scan the planetary surface, orbit, or coordinate arrays for the Sith beacon.
    *   `ship_comms`: Internal communication channels to coordinate deck crews and fighter wings.

---

## 6. Sworinta IV Surface
*   **Location ID:** `surface`
*   **Name:** Sworinta IV Surface (Planetary Exploration)
*   **Exits:**
    *   `orbit` (via ascending flight vector)
*   **Description:** The stormy, toxic atmosphere of Sworinta IV. Swirling clouds of methane and chlorine gas obscure visibility. No active rebel base or installations are located on this radioactive world's surface.
*   **NPCs present:** None
*   **Interactable Elements:**
    *   `sensor_probe`: Launch scanning probes to scan the surface layers for metal anomalies or energy signatures.

---

## 7. The Sith Beacon
*   **Location ID:** `sith_beacon`
*   **Name:** Anomaly / Distress Call (officially logged as "Derelict Warship")
*   **Exits:**
    *   `orbit` (via ship sector transit / navigation)
*   **Description:** An ancient, long-abandoned space station built directly into the core of an asteroid. To the crew and officers of *The Broken Sunrise*, this is officially logged as a derelict warship emitting an ancient distress call. Only you (the Commodore) and the Inquisitor know its true nature as an ancient Sith beacon resonating with dark-side energy.
*   **NPCs present:** None
*   **Interactable Elements:**
    *   `beacon_docking_ring`: Ancient docking apparatus, barely compatible with Imperial standard shuttle docking collars.
    *   `beacon_power_core`: The pulsating core powering the weak transmissions.
    *   `ancient_archives`: Dark storage containers and consoles containing forgotten information.
