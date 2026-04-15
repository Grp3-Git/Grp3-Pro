# enemy.py — Enemy module (M3)
# LAN architecture: HOST is authoritative for ALL enemy simulation.
#   - Host runs update() as normal, serialises enemy states each tick.
#   - Clients call apply_remote_state() to mirror what the host sends;
#     they never spawn or move enemies locally.
#   - Bullet hits on clients are reported to the host via "hit" events;
#     the host applies damage and broadcasts the result.

import pygame
import random
import math
import os
from constants import *


class Enemy(pygame.sprite.Sprite):
    def __init__(self, x, y, groups, eid: int = 0):
        super().__init__(groups)
        self.eid = eid          # unique id so clients can track the same enemy
        self._load_sprites()
        self.image  = self.frames["idle"]
        self.rect   = self.image.get_rect(center=(x, y))
        self.fx     = float(x)
        self.fy     = float(y)
        self.health = ENEMY_HEALTH
        self.alive  = True

        self._dying      = False
        self._dead_timer = 0.0

        self._anim_timer = 0.0
        self._anim_frame = 0

        self.contact_timer = 0.0

        self._last_hit_slot = 0
        self._kill_counted  = False

    # ------------------------------------------------------------------ #
    def _load_sprites(self):
        size = (48, 48)
        def load(name):
            path = os.path.join(SPRITES_DIR, name)
            try:
                img = pygame.image.load(path).convert_alpha()
                return pygame.transform.scale(img, size)
            except Exception:
                surf = pygame.Surface(size, pygame.SRCALPHA)
                surf.fill((220, 60, 60, 220))
                return surf

        self.frames = {
            "idle": load("Monster_idle.png"),
            "walk": [load("Monster_w-1.png"), load("Monster_w-2.png")],
            "dead": load("Monster_Dead.png"),
        }

    # ------------------------------------------------------------------ #
    def _rotate_toward(self, base_frame, tx, ty):
        dx = tx - self.fx
        dy = ty - self.fy
        angle_rad = math.atan2(-dy, dx)
        angle_deg = math.degrees(angle_rad) - 90
        rotated   = pygame.transform.rotate(base_frame, angle_deg)
        new_rect  = rotated.get_rect(center=(int(self.fx), int(self.fy)))
        return rotated, new_rect

    # ------------------------------------------------------------------ #
    def update(self, dt, player_pos):
        """Full simulation — only called on the HOST."""
        self.contact_timer = max(0.0, self.contact_timer - dt)
        px, py = player_pos

        if self._dying:
            self._dead_timer -= dt
            rotated, self.rect = self._rotate_toward(self.frames["dead"], px, py)
            self.image = rotated
            if self._dead_timer <= 0:
                self.alive = False
                self.kill()
            return

        dx = px - self.fx
        dy = py - self.fy
        dist = math.hypot(dx, dy)
        if dist > 0:
            self.fx += (dx / dist) * ENEMY_SPEED * dt
            self.fy += (dy / dist) * ENEMY_SPEED * dt

        self.rect.centerx = int(self.fx)
        self.rect.centery  = int(self.fy)

        self._anim_timer += dt
        if self._anim_timer >= WALK_ANIM_SPEED:
            self._anim_timer = 0.0
            self._anim_frame = 1 - self._anim_frame
        base_frame = self.frames["walk"][self._anim_frame]

        rotated, self.rect = self._rotate_toward(base_frame, px, py)
        self.image = rotated

    # ------------------------------------------------------------------ #
    def apply_remote_state(self, state: dict):
        """
        Mirror state from the host broadcast — only called on CLIENTS.
        state keys: x, y, dying, dead_timer, anim_frame
        """
        self.fx      = float(state.get("x", self.fx))
        self.fy      = float(state.get("y", self.fy))
        self._dying  = bool(state.get("dying", False))
        self._dead_timer = float(state.get("dead_timer", 0.0))
        self._anim_frame = int(state.get("anim_frame", 0))

        # Pick display frame
        if self._dying:
            # Face toward screen centre as a neutral direction for clients
            base = self.frames["dead"]
            rotated = pygame.transform.rotate(base, float(state.get("angle", 0)))
        else:
            base    = self.frames["walk"][self._anim_frame]
            rotated = pygame.transform.rotate(base, float(state.get("angle", 0)))

        self.rect = rotated.get_rect(center=(int(self.fx), int(self.fy)))
        self.image = rotated

        # Client-side: mark for removal when dying timer expired
        if self._dying and self._dead_timer <= 0:
            self.alive = False
            self.kill()

    # ------------------------------------------------------------------ #
    def serialise(self) -> dict:
        """Snapshot for network broadcast (host → clients)."""
        # Compute current facing angle for rendering on client
        angle = 0.0
        if self.image is not None:
            # Re-derive angle from rect size change is unreliable;
            # store last computed angle separately
            pass
        return {
            "eid":        self.eid,
            "x":          self.fx,
            "y":          self.fy,
            "dying":      self._dying,
            "dead_timer": self._dead_timer,
            "anim_frame": self._anim_frame,
            "angle":      getattr(self, "_last_angle", 0.0),
        }

    # ------------------------------------------------------------------ #
    def take_damage(self, amount=1, attacker_slot=0):
        if self._dying:
            return
        self._last_hit_slot = attacker_slot
        self.health -= amount
        if self.health <= 0:
            self._dying      = True
            self._dead_timer = DEATH_DURATION

    def can_damage_player(self):
        return self.contact_timer <= 0 and not self._dying

    def mark_contact(self):
        self.contact_timer = ENEMY_CONTACT_CD

    # Store angle for serialisation
    def _rotate_toward(self, base_frame, tx, ty):
        dx = tx - self.fx
        dy = ty - self.fy
        angle_rad = math.atan2(-dy, dx)
        angle_deg = math.degrees(angle_rad) - 90
        self._last_angle = angle_deg
        rotated  = pygame.transform.rotate(base_frame, angle_deg)
        new_rect = rotated.get_rect(center=(int(self.fx), int(self.fy)))
        return rotated, new_rect


# ======================================================================
class EnemyManager:
    """
    HOST mode  : runs full simulation, serialises state each tick.
    CLIENT mode: receives serialised state, mirrors sprites only.
    """

    def __init__(self, all_group):
        self.all_group   = all_group
        self.enemies     = pygame.sprite.Group()
        self.kill_counts = [0] * LAN_MAX_PLAYERS
        self._wave_timer  = 0.0
        self._max_enemies = ENEMY_BASE_COUNT
        self._next_eid    = 0          # monotonic enemy id counter

    @property
    def kill_count(self):
        return sum(self.kill_counts)

    def reset(self):
        self.enemies.empty()
        self.kill_counts  = [0] * LAN_MAX_PLAYERS
        self._wave_timer  = 0.0
        self._max_enemies = ENEMY_BASE_COUNT
        self._next_eid    = 0

    # ── HOST-only simulation ───────────────────────────────────────────
    def update(self, dt, player_pos, bullet_group, player,
               sound_manager=None, local_slot=0):
        """Full physics + collision — called only on the HOST."""
        self._wave_timer  += dt
        self._max_enemies  = ENEMY_BASE_COUNT + int(self._wave_timer // ENEMY_INTERVAL)

        while len(self.enemies) < self._max_enemies:
            self._spawn_one()

        for enemy in list(self.enemies):
            enemy.update(dt, player_pos)

            hits = pygame.sprite.spritecollide(enemy, bullet_group, True)
            if hits:
                enemy.take_damage(BULLET_DAMAGE * len(hits), attacker_slot=local_slot)
                if sound_manager:
                    sound_manager.play("monster_hurt")

            if enemy._dying and not enemy._kill_counted:
                enemy._kill_counted = True
                slot = enemy._last_hit_slot
                if 0 <= slot < LAN_MAX_PLAYERS:
                    self.kill_counts[slot] += 1
                if sound_manager:
                    sound_manager.play("monster_death")

            if (not enemy._dying
                    and enemy.rect.colliderect(player.rect)
                    and enemy.can_damage_player()):
                enemy.mark_contact()
                player.take_damage(ENEMY_DAMAGE)
                if sound_manager:
                    sound_manager.play("player_hurt")

    def serialise_enemies(self) -> list:
        """Return list of enemy state dicts for broadcasting."""
        return [e.serialise() for e in self.enemies]

    def apply_hit_from_client(self, eid: int, attacker_slot: int,
                               sound_manager=None):
        """
        Host receives a bullet-hit event from a client.
        Finds enemy by eid and applies damage.
        """
        for enemy in self.enemies:
            if enemy.eid == eid:
                enemy.take_damage(BULLET_DAMAGE, attacker_slot=attacker_slot)
                if sound_manager:
                    sound_manager.play("monster_hurt")
                return

    # ── CLIENT-only mirror ─────────────────────────────────────────────
    def apply_remote_enemies(self, enemy_states: list, dt: float):
        """
        Clients call this instead of update().
        Reconciles the local sprite pool with the host's authoritative list.
        """
        seen_eids = set()

        # Build lookup
        by_eid = {e.eid: e for e in self.enemies}

        for state in enemy_states:
            eid = state["eid"]
            seen_eids.add(eid)
            if eid in by_eid:
                by_eid[eid].apply_remote_state(state)
            else:
                # New enemy — create sprite
                e = Enemy(state["x"], state["y"],
                          (self.enemies, self.all_group), eid=eid)
                e.apply_remote_state(state)

        # Remove enemies not in the host's list any more
        for eid, enemy in list(by_eid.items()):
            if eid not in seen_eids:
                enemy.kill()

    # ── CLIENT: process kill-count updates ────────────────────────────
    def apply_remote_kill_counts(self, counts: list):
        for i, kc in enumerate(counts):
            if i < LAN_MAX_PLAYERS:
                self.kill_counts[i] = kc

    # ── Shared helper ─────────────────────────────────────────────────
    def add_remote_kill(self, slot: int):
        if 0 <= slot < LAN_MAX_PLAYERS:
            self.kill_counts[slot] += 1

    def _spawn_one(self):
        edge = random.randint(0, 3)
        m = SPAWN_MARGIN
        if edge == 0:
            x, y = random.randint(0, SCREEN_W), -m
        elif edge == 1:
            x, y = random.randint(0, SCREEN_W), SCREEN_H + m
        elif edge == 2:
            x, y = -m, random.randint(0, SCREEN_H)
        else:
            x, y = SCREEN_W + m, random.randint(0, SCREEN_H)
        eid = self._next_eid
        self._next_eid += 1
        Enemy(x, y, (self.enemies, self.all_group), eid=eid)

    @property
    def current_max(self):
        return self._max_enemies
