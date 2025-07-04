import pygame
import os
import sys

# Initialize Pygame
pygame.init()

# Set up the display
screen_width = 800
screen_height = 600
screen = pygame.display.set_mode((screen_width, screen_height))
pygame.display.set_caption("Falling Image")
clock = pygame.time.Clock()

# Colors
WHITE = (255, 255, 255)
RED = (255, 0, 0)

class FallingImage(pygame.sprite.Sprite):
    def __init__(self, x, y, image_path=None):
        super().__init__()
        
        # Load image or create a placeholder
        if image_path and os.path.exists(image_path):
            self.image = pygame.image.load(image_path).convert_alpha()
            # Scale the image if needed
            self.image = pygame.transform.scale(self.image, (50, 50))
        else:
            # Create a simple colored rectangle as fallback
            self.image = pygame.Surface((50, 50), pygame.SRCALPHA)
            pygame.draw.rect(self.image, (255, 0, 0), (0, 0, 50, 50))
        
        # Set up rectangle for position
        self.rect = self.image.get_rect()
        self.rect.topleft = (x, y)
        
        # Movement
        self.velocity_y = 0
        self.gravity = 0.5
        self.ground_level = screen_height - 100  # 100px from bottom
    
    def update(self):
        # Apply gravity
        self.velocity_y += self.gravity
        
        # Update position
        self.rect.y += self.velocity_y
        
        # Stop at ground
        if self.rect.bottom > self.ground_level:
            self.rect.bottom = self.ground_level
            self.velocity_y = 0

# Create a sprite group
all_sprites = pygame.sprite.Group()

# Try to load an image from the Samurai/Idle folder
base_path = os.path.dirname(os.path.abspath(__file__))
image_path = os.path.join(base_path, 'Samurai', 'Idle', 'Idle_1.png')

# Create the falling image
falling_img = FallingImage(screen_width // 2 - 25, 50, image_path)  # 25 is half the width for centering
all_sprites.add(falling_img)

# Game loop
running = True
while running:
    # Process events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
    
    # Update
    all_sprites.update()
    
    # Draw
    screen.fill(WHITE)
    
    # Draw ground line
    pygame.draw.line(screen, RED, (0, screen_height - 100), (screen_width, screen_height - 100), 2)
    
    # Draw all sprites
    all_sprites.draw(screen)
    
    # Draw a red dot at the bottom center of the image
    pygame.draw.circle(screen, RED, (falling_img.rect.centerx, falling_img.rect.bottom), 3)
    
    # Update the display
    pygame.display.flip()
    
    # Cap the frame rate
    clock.tick(60)

pygame.quit()
sys.exit()
