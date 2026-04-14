# audio.py — Audio module (M5)
# Handles: sound loading, event-based playback, BGM, crosshair cursor
# mm.ogg  : main-menu background music (loops)
# btn.ogg : UI button click sound
# bgm.ogg : in-game background music (loops)
# Pause filter: drastic volume drop to simulate muffled "through a wall" effect.

import pygame
import os
from constants import *


class SoundManager:
    """
    Public interface:
        sm.play(event)
        sm.play_menu_bgm()         ← new: starts mm.ogg loop
        sm.stop_menu_bgm()         ← new: stops mm.ogg
        sm.play_bgm()              ← in-game bgm.ogg loop
        sm.stop_bgm()
        sm.play_btn()              ← new: one-shot btn.ogg click
        sm.set_crosshair()
        sm.restore_cursor()
        sm.draw_crosshair(surface)
        sm.set_volume(master)
        sm.set_paused_filter(bool)

    Valid event strings for play():
        "shoot", "player_hurt", "player_death",
        "monster_hurt", "monster_death",
        "player_steps", "monster_step"
    """

    def __init__(self):
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

        self._vol = {
            "shoot":         0.3,
            "player_hurt":   0.7,
            "player_death":  0.5,
            "monster_hurt":  0.25,
            "monster_death": 0.08,
            "player_steps":  0.3,
            "monster_step":  0.1,
        }

        _files = {
            "shoot":         "shoot.ogg",
            "player_hurt":   "player_hurt.ogg",
            "player_death":  "player_death.ogg",
            "monster_hurt":  "monster_hurt.ogg",
            "monster_death": "monster_death.ogg",
            "player_steps":  "player_steps.ogg",
            "monster_step":  "monster_step.ogg",
        }

        self._sounds = {}
        for event, fname in _files.items():
            path = os.path.join(SOUNDS_DIR, fname)
            try:
                self._sounds[event] = pygame.mixer.Sound(path)
            except Exception as e:
                print(f"[Audio] Could not load '{fname}': {e}")

        # Dedicated channels
        self._bgm_channel    = pygame.mixer.Channel(0)  # in-game bgm
        self._menu_channel   = pygame.mixer.Channel(3)  # menu bgm
        self._step_channel_p = pygame.mixer.Channel(1)  # player steps
        self._step_channel_m = pygame.mixer.Channel(2)  # monster steps
        self._btn_channel    = pygame.mixer.Channel(4)  # UI clicks

        # In-game BGM
        bgm_path = os.path.join(SOUNDS_DIR, "bgm.ogg")
        try:
            self._bgm = pygame.mixer.Sound(bgm_path)
        except Exception as e:
            print(f"[Audio] Could not load 'bgm.ogg': {e}")
            self._bgm = None

        # Main-menu BGM (mm.ogg)
        mm_path = os.path.join(SOUNDS_DIR, "mm.ogg")
        try:
            self._mm_bgm = pygame.mixer.Sound(mm_path)
        except Exception as e:
            print(f"[Audio] Could not load 'mm.ogg': {e}")
            self._mm_bgm = None

        # Button click sound (btn.ogg)
        btn_path = os.path.join(SOUNDS_DIR, "btn.ogg")
        try:
            self._btn_snd = pygame.mixer.Sound(btn_path)
        except Exception as e:
            print(f"[Audio] Could not load 'btn.ogg': {e}")
            self._btn_snd = None

        self._crosshair     = None
        self._load_crosshair()

        self._master        = 0.8
        self._paused_filter = False
        self.set_volume(0.8)

    # ── Crosshair ──────────────────────────────────────────────────────

    def _load_crosshair(self):
        path = os.path.join(CURSORS_DIR, "crosshair.png")
        try:
            img = pygame.image.load(path).convert_alpha()
            self._crosshair = pygame.transform.scale(img, (32, 32))
        except Exception as e:
            print(f"[Audio] Could not load crosshair: {e}")

    def set_crosshair(self):
        pygame.mouse.set_visible(False)

    def restore_cursor(self):
        pygame.mouse.set_visible(True)

    def draw_crosshair(self, surface):
        if self._crosshair is None:
            return
        mx, my = pygame.mouse.get_pos()
        cx = mx - self._crosshair.get_width()  // 2
        cy = my - self._crosshair.get_height() // 2
        surface.blit(self._crosshair, (cx, cy))

    # ── Menu BGM ───────────────────────────────────────────────────────

    def play_menu_bgm(self):
        """Start looping mm.ogg on the menu channel."""
        if self._mm_bgm and not self._menu_channel.get_busy():
            self._menu_channel.play(self._mm_bgm, loops=-1)

    def stop_menu_bgm(self):
        self._menu_channel.stop()

    # ── Button click ───────────────────────────────────────────────────

    def play_btn(self):
        """One-shot button click sound."""
        if self._btn_snd:
            filter_mult = 0.12 if self._paused_filter else 1.0
            self._btn_snd.set_volume(self._master * 0.6 * filter_mult)
            self._btn_channel.play(self._btn_snd)

    # ── Pause blur/muffle filter ────────────────────────────────────────

    def set_paused_filter(self, enable: bool):
        if self._paused_filter == enable:
            return
        self._paused_filter = enable
        self._apply_volumes()

    def _apply_volumes(self):
        filter_mult = 0.12 if self._paused_filter else 1.0
        for event, snd in self._sounds.items():
            snd.set_volume(self._master * self._vol.get(event, 1.0) * filter_mult)
        if self._bgm:
            self._bgm_channel.set_volume(self._master * 0.6 * filter_mult)
        if self._mm_bgm:
            self._menu_channel.set_volume(self._master * 0.5 * filter_mult)

    # ── In-game BGM ────────────────────────────────────────────────────

    def play_bgm(self):
        if self._bgm and not self._bgm_channel.get_busy():
            self._bgm_channel.play(self._bgm, loops=-1)

    def stop_bgm(self):
        self._bgm_channel.stop()

    # ── SFX playback ───────────────────────────────────────────────────

    def play(self, event: str):
        snd = self._sounds.get(event)
        if snd is None:
            return
        if event == "player_steps":
            if not self._step_channel_p.get_busy():
                self._step_channel_p.play(snd)
        elif event == "monster_step":
            if not self._step_channel_m.get_busy():
                self._step_channel_m.play(snd)
        else:
            snd.play()

    def stop_steps(self):
        self._step_channel_p.stop()

    # ── Volume ─────────────────────────────────────────────────────────

    def set_volume(self, master: float):
        master = max(0.0, min(1.0, master))
        self._master = master
        self._apply_volumes()
