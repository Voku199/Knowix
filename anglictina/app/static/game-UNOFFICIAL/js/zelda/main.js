// === 1. Nahraj si tyto soubory do /anglictina/app/static/game/assets/ ===
// - tiles.png (viz níže)
// - player.png (viz níže)
// - simple-map.json (viz níže)

// === 2. Upravený main.js ===

const config = {
    type: Phaser.AUTO,
    width: 800,
    height: 600,
    parent: 'game-container',
    physics: {
        default: 'arcade',
        arcade: {
            gravity: {y: 0},
            debug: false
        }
    },
    scene: {
        preload,
        create,
        update
    }
};

const game = new Phaser.Game(config);

let player;
let cursors;
let map;
let groundLayer;
let wallsLayer;

function preload() {
    // Všechny assety načítáme lokálně!
    this.load.image('tiles', 'static/game/assets/tiles.png');
    this.load.tilemapTiledJSON('map', 'static/game/assets/simple-map.json');
    this.load.spritesheet('player', 'static/game/assets/player.png', {
        frameWidth: 32,
        frameHeight: 48
    });
}

function create() {
    map = this.make.tilemap({key: 'map'});
    const tileset = map.addTilesetImage('tiles', 'tiles');
    groundLayer = map.createLayer('Ground', tileset, 0, 0);
    wallsLayer = map.createLayer('Walls', tileset, 0, 0);

    wallsLayer.setCollisionByProperty({collides: true});

    player = this.physics.add.sprite(64, 64, 'player', 1);
    player.setCollideWorldBounds(true);

    this.physics.add.collider(player, wallsLayer);

    this.cameras.main.startFollow(player);

    cursors = this.input.keyboard.createCursorKeys();

    this.anims.create({
        key: 'left',
        frames: this.anims.generateFrameNumbers('player', {start: 0, end: 3}),
        frameRate: 10,
        repeat: -1
    });
    this.anims.create({
        key: 'turn',
        frames: [{key: 'player', frame: 4}],
        frameRate: 20
    });
    this.anims.create({
        key: 'right',
        frames: this.anims.generateFrameNumbers('player', {start: 5, end: 8}),
        frameRate: 10,
        repeat: -1
    });
}

function update() {
    player.body.setVelocity(0);

    if (cursors.left.isDown) {
        player.body.setVelocityX(-150);
        player.anims.play('left', true);
    } else if (cursors.right.isDown) {
        player.body.setVelocityX(150);
        player.anims.play('right', true);
    } else if (cursors.up.isDown) {
        player.body.setVelocityY(-150);
        player.anims.play('turn', true);
    } else if (cursors.down.isDown) {
        player.body.setVelocityY(150);
        player.anims.play('turn', true);
    } else {
        player.anims.play('turn');
    }
}

// === 3. Jak získat assety ===
// - tiles.png: Použij např. https://kenney.nl/assets/topdown-tilemap (stáhni tileset a pojmenuj tiles.png)
// - player.png: Použij např. https://labs.phaser.io/assets/sprites/dude.png (ulož jako player.png)
// - simple-map.json: Viz níže (vlož do static/game/assets/simple-map.json)


// === 6. Poznámky ===
// - Všechny cesty musí být relativní ke složce static!
// - Pokud budeš chtít větší mapu, uprav simple-map.json.
// - Pokud budeš chtít lepší tileset, stáhni z Kenney nebo použij vlastní.