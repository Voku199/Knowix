class ShadowingApp {
    constructor() {
        this.userLevel = window.userEnglishLevel;
        this.currentLevel = this.userLevel;
        this.currentSentence = '';
        this.recognition = null;
        this.synthesis = window.speechSynthesis;
        this.isRecording = false;

        this.initElements();
        this.initSpeechRecognition();
        this.bindEvents();
    }

    initElements() {
        this.elements = {
            sentenceDisplay: document.getElementById('sentenceDisplay'),
            newSentenceBtn: document.getElementById('newSentenceBtn'),
            playBtn: document.getElementById('playBtn'),
            recordBtn: document.getElementById('recordBtn'),
            stopBtn: document.getElementById('stopBtn'),
            recordingIndicator: document.getElementById('recordingIndicator'),
            loading: document.getElementById('loading'),
            resultArea: document.getElementById('resultArea'),
            accuracyBar: document.getElementById('accuracyBar'),
            accuracyText: document.getElementById('accuracyText'),
            resultTitle: document.getElementById('resultTitle'),
            comparison: document.getElementById('comparison'),
            originalText: document.getElementById('originalText'),
            spokenText: document.getElementById('spokenText'),
            feedback: document.getElementById('feedback')
        };
    }

    initSpeechRecognition() {
        if ('webkitSpeechRecognition' in window) {
            this.recognition = new webkitSpeechRecognition();
        } else if ('SpeechRecognition' in window) {
            this.recognition = new SpeechRecognition();
        } else {
            alert('Váš prohlížeč nepodporuje rozpoznávání řeči. Zkuste Google Chrome.');
            return;
        }

        this.recognition.continuous = false;
        this.recognition.interimResults = false;
        this.recognition.lang = 'en-US';

        this.recognition.onstart = () => {
            this.elements.recordingIndicator.classList.add('active');
            this.elements.recordBtn.style.display = 'none';
            this.elements.stopBtn.style.display = 'inline-flex';
            this.isRecording = true;
        };

        this.recognition.onresult = (event) => {
            const userSpeech = event.results[0][0].transcript;
            this.processResult(userSpeech);
        };

        this.recognition.onerror = (event) => {
            console.error('Chyba rozpoznávání:', event.error);
            this.stopRecording();
            alert('Chyba při rozpoznávání řeči. Zkuste to znovu.');
        };

        this.recognition.onend = () => {
            this.stopRecording();
        };
    }

    bindEvents() {
        this.elements.newSentenceBtn.addEventListener('click', () => this.getNewSentence());
        this.elements.playBtn.addEventListener('click', () => this.playSentence());
        this.elements.recordBtn.addEventListener('click', () => this.startRecording());
        this.elements.stopBtn.addEventListener('click', () => this.recognition.stop());
    }

    async getNewSentence() {
        try {
            const response = await fetch(`/shadow/get_sentence?level=${this.currentLevel}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.currentSentence = data.sentence;
            this.elements.sentenceDisplay.textContent = data.sentence;
            this.elements.playBtn.disabled = false;
            this.elements.recordBtn.disabled = false;
            this.hideResult();

        } catch (error) {
            console.error('Chyba při načítání věty:', error);
            alert('Nepodařilo se načíst větu. Zkuste to znovu.');
        }
    }

    playSentence() {
        if (!this.currentSentence) return;

        // Zastavit všechny předchozí syntézy
        this.synthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(this.currentSentence);
        utterance.lang = 'en-US';
        utterance.rate = 0.8; // Pomalejší řeč pro lepší pochopení
        utterance.pitch = 1;

        this.synthesis.speak(utterance);
    }

    startRecording() {
        if (!this.recognition || this.isRecording) return;

        this.hideResult();
        this.recognition.start();
    }

    stopRecording() {
        this.elements.recordingIndicator.classList.remove('active');
        this.elements.recordBtn.style.display = 'inline-flex';
        this.elements.stopBtn.style.display = 'none';
        this.isRecording = false;
    }

    async processResult(userSpeech) {
        this.elements.loading.classList.add('show');

        try {
            // Výpočet přesnosti pomocí jednoduchého algoritmu
            const accuracy = this.calculateAccuracy(this.currentSentence, userSpeech);

            // Uložení výsledku
            await this.saveResult(userSpeech, accuracy);

            // Zobrazení výsledku
            this.showResult(userSpeech, accuracy);

        } catch (error) {
            console.error('Chyba při zpracování výsledku:', error);
        } finally {
            this.elements.loading.classList.remove('show');
        }
    }

    calculateAccuracy(original, spoken) {
        // Jednoduchý algoritmus pro porovnání podobnosti
        const originalWords = original.toLowerCase().replace(/[^\w\s]/g, '').split(/\s+/);
        const spokenWords = spoken.toLowerCase().replace(/[^\w\s]/g, '').split(/\s+/);

        let matches = 0;
        const maxLength = Math.max(originalWords.length, spokenWords.length);

        for (let i = 0; i < Math.min(originalWords.length, spokenWords.length); i++) {
            if (originalWords[i] === spokenWords[i]) {
                matches++;
            } else if (this.areSimilar(originalWords[i], spokenWords[i])) {
                matches += 0.7; // Částečná shoda
            }
        }

        return Math.round((matches / maxLength) * 100);
    }

    areSimilar(word1, word2) {
        // Jednoduché porovnání podobnosti slov
        if (Math.abs(word1.length - word2.length) > 2) return false;

        let differences = 0;
        const maxLength = Math.max(word1.length, word2.length);

        for (let i = 0; i < maxLength; i++) {
            if (word1[i] !== word2[i]) differences++;
        }

        return differences <= Math.ceil(maxLength * 0.3);
    }

    async saveResult(userSpeech, accuracy) {
        try {
            const response = await fetch('/shadow/save_result', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    sentence: this.currentSentence,
                    user_speech: userSpeech,
                    accuracy: accuracy,
                    level: this.currentLevel
                })
            });

            const data = await response.json();

            if (data.xp_gained) {
                this.showXPGain(data.xp_gained);
            }

        } catch (error) {
            console.error('Chyba při ukládání výsledku:', error);
        }
    }

    showResult(userSpeech, accuracy) {
        this.elements.resultArea.classList.add('show');

        // Nastavení barvy a třídy podle přesnosti
        let resultClass, title, feedback;

        if (accuracy >= 85) {
            resultClass = 'result-excellent';
            title = '🎉 Výborně!';
            feedback = 'Vaše výslovnost je skvělá! Pokračujte v dobré práci.';
        } else if (accuracy >= 70) {
            resultClass = 'result-good';
            title = '👍 Dobře!';
            feedback = 'Dobrá práce! Zkuste si větu přečíst ještě jednou a zaměřte se na přesnost.';
        } else {
            resultClass = 'result-poor';
            title = '💪 Zkuste znovu!';
            feedback = 'Nebojte se, procvičování pomáhá! Poslouchejte pozorně a zkuste to znovu.';
        }

        this.elements.resultArea.className = `result-area show ${resultClass}`;
        this.elements.resultTitle.textContent = title;
        this.elements.accuracyBar.style.width = `${accuracy}%`;
        this.elements.accuracyText.textContent = `Přesnost: ${accuracy}%`;
        this.elements.feedback.textContent = feedback;

        // Zobrazení porovnání
        this.elements.comparison.style.display = 'grid';
        this.elements.originalText.textContent = this.currentSentence;
        this.elements.spokenText.textContent = userSpeech;
    }

    showXPGain(xp) {
        // Jednoduchá notifikace o získaných XP
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #28a745;
            color: white;
            padding: 15px 20px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            z-index: 1000;
            font-weight: bold;
        `;
        notification.textContent = `+${xp} XP!`;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.remove();
        }, 3000);
    }

    hideResult() {
        this.elements.resultArea.classList.remove('show');
    }
}

// Inicializace aplikace po načtení stránky
document.addEventListener('DOMContentLoaded', () => {
    new ShadowingApp();
});
