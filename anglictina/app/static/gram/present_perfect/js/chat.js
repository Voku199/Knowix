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

const chatWindow = document.getElementById('chat-window');
const answerForm = document.getElementById('answer-form');
const answerInput = document.getElementById('answer');
const feedback = document.getElementById('feedback');
const submitBtn = document.getElementById('submit-btn');
const endOfChatDiv = document.getElementById('end-of-chat');

// theme-toggle.js
const themeToggle = document.getElementById('theme-toggle');
if (themeToggle) {
    themeToggle.addEventListener('click', () => {
        fetch('/set_theme', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                theme: document.body.classList.contains('dark-mode') ? 'light' : 'dark'
            })
        }).then(() => {
            document.body.classList.toggle('dark-mode');
            localStorage.setItem('theme', document.body.classList.contains('dark-mode') ? 'dark' : 'light');
        });
    });
}

function addMessage(className, text) {
    if (!text) return;
    const div = document.createElement('div');
    div.className = `chat-bubble ${className}`;
    div.textContent = text;
    chatWindow.appendChild(div);
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function addTypingIndicator() {
    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator';
    typingDiv.id = 'typing';
    typingDiv.innerHTML = '<span></span><span></span><span></span>';
    chatWindow.appendChild(typingDiv);
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function removeTypingIndicator() {
    const typingDiv = document.getElementById('typing');
    if (typingDiv) {
        typingDiv.remove();
    }
}

async function startChat() {
    try {
        const res = await fetch('/chat/start');
        if (!res.ok) throw new Error('Chyba serveru: ' + res.status);
        const data = await res.json();
        await simulateAlexMessage(data.alex, data.cz_reply);
    } catch (err) {
        feedback.textContent = 'Chyba při načítání chatu. Zkuste to později.';
        feedback.className = 'incorrect';
        console.error(err);
    }
}

async function simulateAlexMessage(alexText, czText) {
    addTypingIndicator();
    await new Promise(resolve => setTimeout(resolve, 1000 + Math.random() * 1000)); // 1–2 sek delay
    removeTypingIndicator();

    addMessage('alex', alexText);
    addMessage('cz', czText);
}

// Funkce pro zobrazení tlačítka na konci chatu
function showEndOfChat(xp) {
    endOfChatDiv.innerHTML = `
        <div class="end-of-chat-message" style="margin-top:2rem; text-align:center;">
            <div style="font-size:2.2rem;">🎉</div>
            <div style="font-size:1.2rem; margin:0.5rem 0;">
                Lekce dokončena!<br>
                Získáváš <b>+${xp || 10} XP</b>!
            </div>
            <button id="new-chat-btn" class="popup-button confirm" style="margin-top:1rem;">Nový chat?</button>
        </div>
    `;
    document.getElementById('new-chat-btn').onclick = function () {
        window.location.href = "/sl_chat";
    };
}

async function sendAnswer(answer) {
    submitBtn.disabled = true;
    feedback.textContent = '';
    feedback.className = '';

    try {
        const res = await fetch('/chat/next', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({answer})
        });

        // Pokud server vrátí HTML místo JSON, vyhodíme chybu
        const contentType = res.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
            throw new Error('Server nevrátil JSON. Pravděpodobně došlo k chybě.');
        }

        const data = await res.json();

        if (data.correct) {
            if (data.almost) {
                feedback.textContent = `Skoro správně! 👍 Správně to mělo být: "${data.expected}"`;
                feedback.className = 'almost';
            } else {
                feedback.textContent = 'Správně! 🎉';
                feedback.className = 'correct';
            }

            if (data.done) {
                await simulateAlexMessage('Skvěle, lekce je u konce! 👏', '');
                answerForm.style.display = 'none';
                showEndOfChat(data.xp);

                // --- ZOBRAZ STREAK TOAST ---
                if (data.streak_info && (data.streak_info.status === "started" || data.streak_info.status === "continued")) {
                    showStreakToast(data.streak_info.streak);
                }
            } else {
                await simulateAlexMessage(data.alex, data.cz_reply);
            }
        } else if (data.done) {
            // Pokud backend vrátí pouze done:true bez correct (např. při magickém heslu)
            await simulateAlexMessage('Skvěle, lekce je u konce! 👏', '');
            answerForm.style.display = 'none';
            showEndOfChat(data.xp);

            // --- ZOBRAZ STREAK TOAST ---
            if (data.streak_info && (data.streak_info.status === "started" || data.streak_info.status === "continued")) {
                showStreakToast(data.streak_info.streak);
            }
        } else {
            feedback.textContent = 'Špatně, zkus to ještě jednou.';
            feedback.className = 'incorrect';
        }
    } catch (err) {
        feedback.textContent = 'Chyba komunikace se serverem. Zkuste to později.';
        feedback.className = 'incorrect';
        console.error(err);
    }

    submitBtn.disabled = false;
    answerInput.value = '';
    answerInput.focus();
}

answerForm.addEventListener('submit', e => {
    e.preventDefault();
    const answer = answerInput.value.trim();
    if (answer) {
        sendAnswer(answer);
    }
});

window.onload = () => {
    startChat();
    answerInput.focus();
};