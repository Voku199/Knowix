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

    fetch("/hangman/guess", {
        method: "POST",
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({letter})
    })
        .then(res => res.json())
        .then(data => {
            // Update button style
            if (data.is_correct) {
                button.classList.add('correct');
            } else {
                button.classList.add('incorrect');
            }

            // Update game state
            document.getElementById("maskedWord").innerText = data.masked_word.split("").join(" ");
            document.getElementById("guessedLetters").innerText = data.guessed_letters.join(", ");
            document.getElementById("remainingAttempts").innerText = data.remaining_attempts;
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


// Zbytek kódu zůstává stejný

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
                    fetch("/hangman/reset", {method: "POST"})
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
    })
})


