const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const buttonsContainer = document.getElementById("letterButtons");
let gameActive = true;
let currentHintCz = ""; // <-- tady to chybělo

const HANGMAN_STAGES = [
    `
     +–––––+
     |     |
           |
           |
           |
           |
    ===========`,
    `
     +–––––+
     |     |
     O     |
           |
           |
           |
    ===========`,
    `
     +–––––+
     |     |
     O     |
     |     |
           |
           |
    ===========`,
    `
     +–––––+
     |     |
     O     |
    /|     |
           |
           |
    ===========`,
    `
     +–––––+
     |     |
     O     |
    /|\\    |
           |
           |
    ===========`,
    `
     +–––––+
     |     |
     O     |
    /|\\    |
    /      |
           |
    ===========`,
    `
     +–––––+
     |     |
     O     |
    /|\\    |
    / \\    |
           |
    ===========`
];

// --- STREAK TOAST FUNKCE ---
function showStreakToast(streak) {
    const toast = document.getElementById('streakToast');
    const text = document.getElementById('streakToastText');
    text.textContent = `🔥 Máš streak ${streak} dní v řadě!`;
    toast.classList.add('active');
    toast.style.display = 'flex';
    setTimeout(() => {
        toast.classList.remove('active');
        setTimeout(() => {
            toast.style.display = 'none';
        }, 400);
    }, 3500);
}

function createButtons() {
    buttonsContainer.innerHTML = "";
    alphabet.forEach(letter => {
        const btn = document.createElement("button");
        btn.innerText = letter;
        btn.className = "letter-btn";
        btn.addEventListener("click", () => guessLetter(letter));
        buttonsContainer.appendChild(btn);
    });
}

function drawHangman(remainingAttempts) {
    const drawing = document.getElementById("hangmanDrawing");
    drawing.textContent = HANGMAN_STAGES[6 - remainingAttempts];
}

function guessLetter(letter) {
    const button = [...buttonsContainer.children].find(b => b.textContent === letter);
    button.disabled = true;

    // Get CSRF token
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : null;
    
    if (!csrfToken) {
        console.error('CSRF token not found');
        return;
    }

    fetch("/hangman/guess", {
        method: "POST",
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({letter})
    })
        .then(res => res.json())
        .then(data => {
            // Calculate if the letter was correct (if remaining attempts didn't decrease)
            const currentAttempts = parseInt(document.getElementById("remainingAttempts").innerText);
            const isCorrect = data.remaining_attempts >= currentAttempts;
            
            // Update button style
            if (isCorrect) {
                button.classList.add('correct');
            } else {
                button.classList.add('incorrect');
            }

            // Update game state
            document.getElementById("maskedWord").innerText = data.masked_word || "";
            document.getElementById("guessedLetters").innerText = (data.guessed_letters || []).join(", ");
            document.getElementById("remainingAttempts").innerText = data.remaining_attempts || 0;
            drawHangman(data.remaining_attempts);

            const resultMessage = document.getElementById("resultMessage");
            if (data.status === "win") {
                resultMessage.innerHTML = `
                <div class="result-win">
                    🎉 Výborně! Uhodl jsi slovo: <strong>${data.original_word}</strong>
                    📘 Překlad: <strong>${data.translation}</strong>
                </div>
            `;
                document.getElementById("nextWordBtn").style.display = "block";
                disableButtons();
                gameActive = false;

                // --- ZOBRAZ STREAK TOAST ---
                if (data.streak_info && (data.streak_info.status === "started" || data.streak_info.status === "continued")) {
                    showStreakToast(data.streak_info.streak);
                }
            } else if (data.status === "lose") {
                resultMessage.innerHTML = `
                <div class="result-lose">
                    💀 Prohrál jsi! Správné slovo bylo: <strong>${data.original_word}</strong>
                    📘 Překlad: <strong>${data.translation}</strong>
                </div>
            `;
                document.getElementById("nextWordBtn").style.display = "block";
                disableButtons();
                gameActive = false;
            }
        });
}

function disableButtons() {
    const buttons = document.querySelectorAll(".letter-btn");
    buttons.forEach(btn => btn.disabled = true);
}

function startGame() {
    gameActive = true;
    fetch("/hangman/start")
        .then(res => res.json())
        .then(data => {
            if (data.status === "done") {
                // Vyčistíme aktuální zobrazení
                document.getElementById("maskedWord").innerText = "";
                document.getElementById("hint").innerText = "";
                document.getElementById("level").innerText = "";
                document.getElementById("guessedLetters").innerText = "";
                document.getElementById("remainingAttempts").innerText = "";
                document.getElementById("resultMessage").innerText = "Hotovo! Vyřešil jsi všechna slova 🎉";

                // Změníme tlačítko na "Začít znovu"
                const nextWordBtn = document.getElementById("nextWordBtn");
                nextWordBtn.innerText = "Začít znovu";
                nextWordBtn.style.display = "inline-block";
                nextWordBtn.onclick = () => {
                    // Get CSRF token
                    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
                    const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : null;
                    
                    if (!csrfToken) {
                        console.error('CSRF token not found');
                        return;
                    }

                    fetch("/hangman/reset", {
                        method: "POST",
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken
                        }
                    })
                        .then(() => startGame());
                };
                return;
            }

            // Když hra pokračuje normálně
            document.getElementById("maskedWord").innerText = "_ ".repeat(data.word_length);
            document.getElementById("hint").innerText = "Nápověda: " + data.hint;
            document.getElementById("level").innerText = "Úroveň: " + data.level;
            document.getElementById("guessedLetters").innerText = "";
            document.getElementById("remainingAttempts").innerText = "6";
            document.getElementById("resultMessage").innerText = "";
            document.getElementById("nextWordBtn").style.display = "none";

            currentHintCz = data.hint_cz;

            document.getElementById("hintCz").innerText = "";

            drawHangman(6);
            createButtons();
        });
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("nextWordBtn").addEventListener("click", startGame);
    startGame();

    document.getElementById("showHintCzBtn").addEventListener("click", () => {
        const hintDiv = document.getElementById("hintCz");
        hintDiv.innerHTML = `
            💡 Nápověda: ${currentHintCz}
        `;
    });

    // 💡 Klávesnice support
    document.addEventListener("keydown", (event) => {
        if (!gameActive) return;

        const letter = event.key.toUpperCase();
        if (alphabet.includes(letter)) {
            const button = [...buttonsContainer.children].find(b => b.textContent === letter);
            if (button && !button.disabled) {
                button.click();
            }
        }
    });
});