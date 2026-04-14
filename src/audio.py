# audio.py — Audio module (M5)
# Handles: sound loading, event-based playback, BGM, custom crosshair cursor
# NEW: blur/lowpass filter effect for pause state

import pygame
import os
from constants import *


class SoundManager:
    """
    Public interface used by main.py:
        sm = SoundManager()
        sm.play(event)
        sm.play_bgm()
        sm.stop_bgm()
        sm.set_crosshair()
        sm.restore_cursor()
        sm.draw_crosshair(surface)
        sm.set_volume(master)          # 0.0 – 1.0
        sm.set_paused_filter(enable)   # muffled / blurred sound when paused

    Valid event strings:
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

        self._bgm_channel   = pygame.mixer.Channel(0)
        self._step_channel_p = pygame.mixer.Channel(1)
        self._step_channel_m = pygame.mixer.Channel(2)

        bgm_path = os.path.join(SOUNDS_DIR, "bgm.ogg")
        try:
            self._bgm = pygame.mixer.Sound(bgm_path)
        except Exception as e:
            print(f"[Audio] Could not load 'bgm.ogg': {e}")
            self._bgm = None

        self._crosshair   = None
        self._load_crosshair()

        self._master       = 0.8
        self._paused_filter = False
        self.set_volume(0.8)

    # ------------------------------------------------------------------ #
    #  Crosshair
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    #  Pause blur/muffle filter
    # ------------------------------------------------------------------ #
    def set_paused_filter(self, enable: bool):
        """
        Simulate 'blurred' sound when paused by drastically reducing volume
        and applying a very low effective master — like hearing through a wall.
        """
        if self._paused_filter == enable:
            return
        self._paused_filter = enable
        self._apply_volumes()

    def _apply_volumes(self):
        filter_mult = 0.12 if self._paused_filter else 1.0
        for event, snd in self._sounds.items():
            snd.set_volume(self._master * self._vol.get(event, 1.0) * filter_mult)
        if self._bgm:
            bgm_vol = self._master * 0.6 * filter_mult
            self._bgm_channel.set_volume(bgm_vol)

    # ------------------------------------------------------------------ #
    #  Sound playback
    # ------------------------------------------------------------------ #
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

    def play_bgm(self):
        if self._bgm and not self._bgm_channel.get_busy():
            self._bgm_channel.play(self._bgm, loops=-1)

    def stop_bgm(self):
        self._bgm_channel.stop()

    # ------------------------------------------------------------------ #
    #  Volume
    # ------------------------------------------------------------------ #
    def set_volume(self, master: float):
        master = max(0.0, min(1.0, master))
        self._master = master
        self._apply_volumes()
