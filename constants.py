# constants.py — Shared constants for all modules
# Arena RPG — 5-member project

import os

# --- Screen ---
SCREEN_W = 1280
SCREEN_H = 720
FPS      = 60
TITLE    = "Arena RPG"

# --- Colours (R, G, B) ---
BLACK     = (0,   0,   0)
WHITE     = (255, 255, 255)
RED       = (200, 40,  40)
GREEN     = (40,  180, 80)
YELLOW    = (255, 220, 50)
DARK_GREY = (25,  25,  25)
HUD_BG    = (10,  10,  10)
HUD_TEXT  = (230, 230, 230)

# --- Player colours (CoD Zombies style, indexed by player slot 0-3) ---
PLAYER_COLORS = [
    (255, 255, 255),   # P1 — White
    (80,  140, 255),   # P2 — Blue
    (60,  210, 100),   # P3 — Green
    (255, 210, 50),    # P4 — Yellow
]

# --- Player ---
PLAYER_SPEED    = 220
PLAYER_LIVES    = 3
PLAYER_SHOOT_CD = 0.25
BULLET_SPEED    = 550
BULLET_DAMAGE   = 1
PLAYER_IFRAMES  = 1.0

# --- Enemies ---
ENEMY_BASE_COUNT = 5
ENEMY_INTERVAL   = 10
ENEMY_SPEED      = 110
ENEMY_HEALTH     = 1
ENEMY_DAMAGE     = 1
ENEMY_CONTACT_CD = 1.0
SPAWN_MARGIN     = 60

# --- Animation ---
WALK_ANIM_SPEED = 0.15
DEATH_DURATION  = 0.8

# --- Game states ---
STATE_MENU      = "menu"
STATE_USERNAME  = "username"
STATE_LOBBY     = "lobby"
STATE_PLAYING   = "playing"
STATE_DEAD      = "dead"
STATE_PAUSED    = "paused"

# --- Respawn (LAN) ---
RESPAWN_DELAY   = 30.0   # seconds before a dead LAN player respawns
RESPAWN_LIVES   = 1      # HP on respawn
RESPAWN_IFRAMES = 3.0    # seconds of invulnerability on respawn

# --- Languages ---
LANGUAGES    = ["en", "fr"]
DEFAULT_LANG = "en"

# --- LAN ---
LAN_PORT        = 5555
LAN_MAX_PLAYERS = 4
LAN_TICK_RATE   = 20
LAN_TIMEOUT     = 5.0

# --- Asset paths ---
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR  = os.path.join(BASE_DIR, "assets")
SPRITES_DIR = os.path.join(ASSETS_DIR, "sprites")
SOUNDS_DIR  = os.path.join(ASSETS_DIR, "sounds")
CURSORS_DIR = os.path.join(ASSETS_DIR, "cursors")
LOCALES_DIR = os.path.join(BASE_DIR,  "locales")

# --- Map texture ---
# Drop a 16:9 PNG named "map.png" into the assets/ folder.
# It will be auto-scaled to fill the arena (1280x720).
# If absent, a dark procedural grid is drawn instead.
MAP_IMG_PATH = os.path.join(ASSETS_DIR, "map.png")

# --- Player sprite naming convention ---
PLAYER_SPRITE_SUFFIX = {
    0: "",
    1: "_2",
    2: "_3",
    3: "_4",
}
