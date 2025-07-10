import pygame
import os
import pytmx
from pytmx.util_pygame import load_pygame

# Konstanty
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 600
FPS = 60
PLAYER_WIDTH = 30
PLAYER_HEIGHT = 30
PLAYER_SPAWN_OFFSET_Y = 120  # záporné nahoru, kladné dolů

# Inicializace Pygame
pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Map Loader with Debug Character")
clock = pygame.time.Clock()


# Načtení mapy
# Vrací škálovanou mapu na celou obrazovku a spawnpoint (x, y) pokud existuje

def load_map(filename):
    try:
        if not os.path.exists(filename):
            print(f"Map file not found: {filename}")
            return None, None
        tmx_data = load_pygame(filename)
        map_width = tmx_data.width * tmx_data.tilewidth
        map_height = tmx_data.height * tmx_data.tileheight
        map_surface = pygame.Surface((map_width, map_height))
        for layer in tmx_data.visible_layers:
            if isinstance(layer, pytmx.TiledTileLayer):
                for x, y, gid in layer:
                    tile = tmx_data.get_tile_image_by_gid(gid)
                    if tile:
                        map_surface.blit(tile, (x * tmx_data.tilewidth, y * tmx_data.tileheight))
        print(f"Map loaded: {os.path.basename(filename)}")
        # Najdi spawnpoint
        spawn_x, spawn_y = None, None
        for obj in tmx_data.objects:
            if obj.name == "spawn":
                spawn_x, spawn_y = obj.x, obj.y
                break
        # Škálování na celou obrazovku
        scaled_map = pygame.transform.scale(map_surface, (SCREEN_WIDTH, SCREEN_HEIGHT))
        # Přepočítej spawnpoint na škálované souřadnice
        if spawn_x is not None and spawn_y is not None:
            scale_x = SCREEN_WIDTH / map_width
            scale_y = SCREEN_HEIGHT / map_height
            spawn_x = int(spawn_x * scale_x)
            spawn_y = int(spawn_y * scale_y)
            spawnpoint = (spawn_x, spawn_y)
        else:
            spawnpoint = None
        return scaled_map, spawnpoint
    except Exception as e:
        print(f"Error loading map: {e}")
        return None, None


# Načtení mapy (změňte cestu podle vašeho prostředí)
map_surface, spawnpoint = load_map("chill.tmx")
map_rect = map_surface.get_rect() if map_surface else pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)


# Debug panáček
class DebugPlayer:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.width = PLAYER_WIDTH
        self.height = PLAYER_HEIGHT
        self.speed = 5
        self.jumping = False
        self.jump_count = 10
        self.velocity_y = 0
        self.gravity = 0.5

    def move(self, keys):
        # Pohyb do stran
        if keys[pygame.K_LEFT]:
            self.x -= self.speed
        if keys[pygame.K_RIGHT]:
            self.x += self.speed

        # Skok
        if keys[pygame.K_SPACE] and not self.jumping:
            self.velocity_y = -12
            self.jumping = True

        # Aplikace gravitace
        self.velocity_y += self.gravity
        self.y += self.velocity_y

        # Detekce "země" (spodní část obrazovky)
        if self.y > SCREEN_HEIGHT - self.height:
            self.y = SCREEN_HEIGHT - self.height
            self.velocity_y = 0
            self.jumping = False

    def draw(self, surface):
        # Tělo panáčka (červený obdélník)
        pygame.draw.rect(surface, (255, 0, 0), (self.x, self.y, self.width, self.height))

        # Oči (pro orientaci)
        pygame.draw.circle(surface, (0, 0, 255), (self.x + 8, self.y + 15), 5)
        pygame.draw.circle(surface, (0, 0, 255), (self.x + self.width - 8, self.y + 15), 5)

        # Ruce (pro ukázku pohybu)
        pygame.draw.line(surface, (200, 0, 0),
                         (self.x, self.y + 20),
                         (self.x - 15, self.y + 40), 3)
        pygame.draw.line(surface, (200, 0, 0),
                         (self.x + self.width, self.y + 20),
                         (self.x + self.width + 15, self.y + 40), 3)


# Vytvoření panáčka na spawnpointu, nebo na středu pokud není
if spawnpoint:
    player = DebugPlayer(spawnpoint[0], spawnpoint[1] + PLAYER_SPAWN_OFFSET_Y)
else:
    player = DebugPlayer(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)

# Pozice kamery
camera_x, camera_y = 0, 0

# Hlavní smyčka
running = True
while running:
    # Zpracování událostí
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False

    # Pohyb panáčka
    keys = pygame.key.get_pressed()
    player.move(keys)

    # Pohyb kamery za panáčkem
    camera_x = player.x - SCREEN_WIDTH // 2
    camera_y = player.y - SCREEN_HEIGHT // 2

    # Omezení kamery na velikost mapy
    if map_surface:
        camera_x = max(0, min(camera_x, map_surface.get_width() - SCREEN_WIDTH))
        camera_y = max(0, min(camera_y, map_surface.get_height() - SCREEN_HEIGHT))

    # Vykreslení
    # screen.fill((50, 50, 80))  # Pozadí

    # Vykreslení mapy (pokud existuje)
    if map_surface:
        screen.blit(map_surface, (0, 0))

    # Vykreslení panáčka (relativně ke kameře)
    player.draw(screen)

    # Debug informace
    font = pygame.font.SysFont(None, 24)
    info = [
        f"Position: {player.x:.0f}, {player.y:.0f}",
        f"Camera: {camera_x:.0f}, {camera_y:.0f}",
        f"Map: {'Loaded' if map_surface else 'Not found'}",
        f"Controls: Arrows, Space to jump"
    ]

    for i, text in enumerate(info):
        text_surface = font.render(text, True, (255, 255, 0))
        screen.blit(text_surface, (10, 10 + i * 30))

    # Mřížka pro lepší orientaci
    for x in range(0, SCREEN_WIDTH, 50):
        pygame.draw.line(screen, (100, 100, 150), (x, 0), (x, SCREEN_HEIGHT), 1)
    for y in range(0, SCREEN_HEIGHT, 50):
        pygame.draw.line(screen, (100, 100, 150), (0, y), (SCREEN_WIDTH, y), 1)

    # Střed obrazovky
    pygame.draw.circle(screen, (255, 255, 0), (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2), 5)

    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
