# player.py — Player module (M2)
# Multi-player aware: each player slot loads its own sprites (_2, _3, _4 suffix)
# Handles: movement (WASD + ZQSD), rotation toward cursor, shooting, lives, iframes

import pygame
import math
import os
from constants import *


class Bullet(pygame.sprite.Sprite):
    def __init__(self, x, y, dx, dy, groups):
        super().__init__(groups)
        size = 8
        self.image = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(self.image, (255, 210, 40), (size // 2, size // 2), size // 2)
        pygame.draw.circle(self.image, (255, 245, 180), (size // 2, size // 2), size // 4)
        self.rect   = self.image.get_rect(center=(x, y))
        self.vx     = dx * BULLET_SPEED
        self.vy     = dy * BULLET_SPEED
        self.damage = BULLET_DAMAGE
        self.fx     = float(x)
        self.fy     = float(y)

    def update(self, dt, *args, **kwargs):
        self.fx += self.vx * dt
        self.fy += self.vy * dt
        self.rect.centerx = int(self.fx)
        self.rect.centery  = int(self.fy)
        if (self.rect.right < 0 or self.rect.left > SCREEN_W or
                self.rect.bottom < 0 or self.rect.top > SCREEN_H):
            self.kill()


class RemotePlayer(pygame.sprite.Sprite):
    """
    A ghost sprite representing another player (received via LAN).
    Does NOT handle input or shooting — just mirrors the remote state.
    """
    def __init__(self, slot: int, groups):
        super().__init__(groups)
        self.slot = slot
        self._load_sprites(slot)
        self.image = self.frames["idle"]
        self.fx = float(SCREEN_W // 2)
        self.fy = float(SCREEN_H // 2)
        self.rect = self.image.get_rect(center=(int(self.fx), int(self.fy)))
        self._angle = 0.0
        self._anim_frame = 0
        self._anim_timer = 0.0
        self.is_dead = False
        self.username = f"P{slot+1}"

    def _load_sprites(self, slot):
        suffix = PLAYER_SPRITE_SUFFIX.get(slot, f"_{slot+1}")
        size = (48, 48)
        color = PLAYER_COLORS[slot % len(PLAYER_COLORS)]

        def load(name):
            path = os.path.join(SPRITES_DIR, name)
            try:
                img = pygame.image.load(path).convert_alpha()
                return pygame.transform.scale(img, size)
            except Exception:
                surf = pygame.Surface(size, pygame.SRCALPHA)
                surf.fill((*color, 220))
                return surf

        self.frames = {
            "idle": load(f"Player_idle{suffix}.png"),
            "walk": [load(f"Player_w-1{suffix}.png"), load(f"Player_w-2{suffix}.png")],
            "dead": load(f"Player_Dead{suffix}.png"),
        }

    def apply_state(self, state: dict, dt: float):
        """Update from a network state dict."""
        self.fx = float(state.get("x", self.fx))
        self.fy = float(state.get("y", self.fy))
        self._angle = float(state.get("angle", self._angle))
        self.is_dead = bool(state.get("is_dead", False))
        moving = bool(state.get("moving", False))

        if self.is_dead:
            base = self.frames["dead"]
        elif moving:
            self._anim_timer += dt
            if self._anim_timer >= WALK_ANIM_SPEED:
                self._anim_timer = 0.0
                self._anim_frame = 1 - self._anim_frame
            base = self.frames["walk"][self._anim_frame]
        else:
            self._anim_frame = 0
            base = self.frames["idle"]

        rotated = pygame.transform.rotate(base, self._angle)
        self.rect = rotated.get_rect(center=(int(self.fx), int(self.fy)))
        self.image = rotated


class Player(pygame.sprite.Sprite):
    """
    Local player. Handles input, physics, animation, shooting, lives.

    Public interface:
        player.update(dt, keys, mouse_pos)
        player.try_shoot(mouse_pos, bullet_group, all_group) -> bool
        player.take_damage(amount)
        player.reset(x, y)
        player.get_net_state() -> dict   (for broadcasting over LAN)
        player.lives    (int)
        player.is_dead  (bool)
        player.rect     (pygame.Rect)
    """

    def __init__(self, x, y, groups, slot=0):
        super().__init__(groups)
        self.slot = slot
        self._load_sprites(slot)
        self.image = self.frames["idle"]
        self.rect  = self.image.get_rect(center=(x, y))

        self.fx = float(x)
        self.fy = float(y)

        self.lives       = PLAYER_LIVES
        self.is_dead     = False
        self._dead_timer = 0.0
        self._shoot_cd   = 0.0
        self._iframe     = 0.0
        self._dying      = False

        self._anim_timer = 0.0
        self._anim_frame = 0
        self._angle      = 0.0
        self._moving     = False

    def _load_sprites(self, slot):
        suffix = PLAYER_SPRITE_SUFFIX.get(slot, f"_{slot+1}")
        size   = (48, 48)
        color  = PLAYER_COLORS[slot % len(PLAYER_COLORS)]

        def load(name):
            path = os.path.join(SPRITES_DIR, name)
            try:
                img = pygame.image.load(path).convert_alpha()
                return pygame.transform.scale(img, size)
            except Exception:
                surf = pygame.Surface(size, pygame.SRCALPHA)
                surf.fill((*color, 220))
                return surf

        self.frames = {
            "idle": load(f"Player_idle{suffix}.png"),
            "walk": [load(f"Player_w-1{suffix}.png"), load(f"Player_w-2{suffix}.png")],
            "dead": load(f"Player_Dead{suffix}.png"),
        }

    def _rotate(self, base_frame, mouse_pos):
        cx, cy = self.rect.center
        mx, my = mouse_pos
        dx = mx - cx
        dy = my - cy
        angle_rad = math.atan2(-dy, dx)
        angle_deg = math.degrees(angle_rad) - 90
        self._angle = angle_deg
        rotated = pygame.transform.rotate(base_frame, angle_deg)
        new_rect = rotated.get_rect(center=(int(self.fx), int(self.fy)))
        return rotated, new_rect

    def update(self, dt, keys, mouse_pos):
        if self._dying:
            self._dead_timer -= dt
            if self._dead_timer <= 0:
                self._dying  = False
                self.is_dead = True
            rotated, self.rect = self._rotate(self.frames["dead"], mouse_pos)
            self.image = rotated
            return

        self._shoot_cd = max(0.0, self._shoot_cd - dt)
        self._iframe   = max(0.0, self._iframe   - dt)

        vx, vy = 0.0, 0.0
        if keys[pygame.K_LEFT]  or keys[pygame.K_a] or keys[pygame.K_q]: vx -= 1
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:                      vx += 1
        if keys[pygame.K_UP]    or keys[pygame.K_w] or keys[pygame.K_z]: vy -= 1
        if keys[pygame.K_DOWN]  or keys[pygame.K_s]:                      vy += 1

        if vx != 0 and vy != 0:
            vx *= 0.7071
            vy *= 0.7071

        self.fx += vx * PLAYER_SPEED * dt
        self.fy += vy * PLAYER_SPEED * dt

        half_w = self.rect.width  // 2
        half_h = self.rect.height // 2
        self.fx = max(half_w, min(SCREEN_W - half_w, self.fx))
        self.fy = max(half_h, min(SCREEN_H - half_h, self.fy))

        self._moving = (vx != 0 or vy != 0)

        if self._moving:
            self._anim_timer += dt
            if self._anim_timer >= WALK_ANIM_SPEED:
                self._anim_timer = 0.0
                self._anim_frame = 1 - self._anim_frame
            base_frame = self.frames["walk"][self._anim_frame]
        else:
            self._anim_frame = 0
            base_frame = self.frames["idle"]

        rotated, self.rect = self._rotate(base_frame, mouse_pos)

        if self._iframe > 0 and int(self._iframe * 10) % 2 == 1:
            self.image = pygame.Surface(rotated.get_size(), pygame.SRCALPHA)
        else:
            self.image = rotated

    def try_shoot(self, mouse_pos, bullet_group, all_group):
        if self._shoot_cd > 0 or self._dying:
            return False
        self._shoot_cd = PLAYER_SHOOT_CD
        mx, my = mouse_pos
        cx, cy = int(self.fx), int(self.fy)
        dx = mx - cx
        dy = my - cy
        dist = math.hypot(dx, dy)
        if dist == 0:
            return False
        Bullet(cx, cy, dx / dist, dy / dist, (bullet_group, all_group))
        return True

    def take_damage(self, amount=1):
        if self._iframe > 0 or self._dying:
            return
        self._iframe = PLAYER_IFRAMES
        self.lives -= amount
        if self.lives <= 0:
            self.lives       = 0
            self._dying      = True
            self._dead_timer = DEATH_DURATION

    def reset(self, x=None, y=None):
        self.lives     = PLAYER_LIVES
        self.is_dead   = False
        self._dying    = False
        self._iframe   = 0.0
        self._shoot_cd = 0.0
        self._angle    = 0.0
        self._moving   = False
        cx = x if x is not None else SCREEN_W // 2
        cy = y if y is not None else SCREEN_H // 2
        self.fx = float(cx)
        self.fy = float(cy)
        self.image = self.frames["idle"]
        self.rect  = self.image.get_rect(center=(cx, cy))

    def get_net_state(self) -> dict:
        """Snapshot for broadcasting to other LAN clients."""
        return {
            "x":       self.fx,
            "y":       self.fy,
            "angle":   self._angle,
            "moving":  self._moving,
            "is_dead": self.is_dead or self._dying,
        }
