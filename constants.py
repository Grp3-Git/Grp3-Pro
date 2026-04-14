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
STATE_MENU     = "menu"
STATE_USERNAME = "username"
STATE_LOBBY    = "lobby"
STATE_PLAYING  = "playing"
STATE_DEAD     = "dead"
STATE_PAUSED   = "paused"

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

# --- Player sprite naming convention ---
# Player 1: Player_idle.png, Player_w-1.png, Player_w-2.png, Player_Dead.png
# Player N: Player_idle_N.png, Player_w-1_N.png, Player_w-2_N.png, Player_Dead_N.png
PLAYER_SPRITE_SUFFIX = {
    0: "",    # slot 0 / player 1 -> no suffix
    1: "_2",
    2: "_3",
    3: "_4",
}
