const chatWindow = document.getElementById('chat-window');
const answerForm = document.getElementById('answer-form');
const answerInput = document.getElementById('answer');
const feedback = document.getElementById('feedback');
const submitBtn = document.getElementById('submit-btn');

function addMessage(className, text) {
    const div = document.createElement('div');
    div.className = className;
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
    const res = await fetch('/chat/start');
    const data = await res.json();
    await simulateAlexMessage(data.alex, data.cz_reply);
}

async function simulateAlexMessage(alexText, czText) {
    addTypingIndicator();
    await new Promise(resolve => setTimeout(resolve, 1000 + Math.random() * 1000)); // 1–2 sek delay
    removeTypingIndicator();

    addMessage('alex', alexText);
    addMessage('cz', czText);
}

async function sendAnswer(answer) {
    submitBtn.disabled = true;
    feedback.textContent = '';
    feedback.className = '';

    const res = await fetch('/chat/next', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({answer})
    });

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
        } else {
            await simulateAlexMessage(data.alex, data.cz_reply);
        }
    } else {
        feedback.textContent = 'Špatně, zkus to ještě jednou.';
        feedback.className = 'incorrect';
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
