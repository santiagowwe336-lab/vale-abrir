document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            const message = form.getAttribute("data-confirm") || "Confirmar ação?";
            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });

    const customRadio = document.getElementById("qtdPersonalizada");
    const customField = document.getElementById("campoQuantidadePersonalizada");
    const quantityRadios = document.querySelectorAll('input[name="quantidade_packs"]');

    if (customRadio && customField && quantityRadios.length) {
        const toggleCustomField = () => {
            customField.classList.toggle("d-none", !customRadio.checked);
        };

        quantityRadios.forEach((radio) => {
            radio.addEventListener("change", toggleCustomField);
        });
        toggleCustomField();
    }

    document.querySelectorAll("[data-copy-target]").forEach((button) => {
        button.addEventListener("click", async () => {
            const selector = button.getAttribute("data-copy-target");
            const target = document.querySelector(selector);
            if (!target) {
                return;
            }

            const originalHTML = button.innerHTML;
            try {
                await navigator.clipboard.writeText(target.value || target.textContent || "");
                button.innerHTML = '<i class="bi bi-check2" aria-hidden="true"></i><span>Copiado</span>';
                window.setTimeout(() => {
                    button.innerHTML = originalHTML;
                }, 1400);
            } catch {
                target.select();
                document.execCommand("copy");
            }
        });
    });

    document.querySelectorAll("[data-image-preview]").forEach((input) => {
        const preview = document.querySelector(input.getAttribute("data-image-preview"));
        if (!preview) {
            return;
        }

        input.addEventListener("input", () => {
            const value = input.value.trim();
            preview.src = value;
            preview.classList.toggle("d-none", value.length === 0);
        });
    });

    const opening = document.querySelector("[data-pack-opening]");
    if (opening) {
        const packScene = opening.querySelector("[data-pack-scene]");
        const revealScene = opening.querySelector("[data-reveal-scene]");
        const completeScene = opening.querySelector("[data-opening-complete]");
        const cards = Array.from(opening.querySelectorAll("[data-reveal-card]"));
        const openButtons = opening.querySelectorAll("[data-open-pack]");
        const nextButton = opening.querySelector("[data-reveal-next]");
        const nextButtonText = nextButton?.querySelector("span");
        const counter = opening.querySelector("[data-reveal-counter]");
        const status = opening.querySelector("[data-opening-status]");
        const progress = opening.querySelector("[data-opening-progress]");
        const packNumber = opening.querySelector("[data-pack-number]");
        const confettiLayer = opening.querySelector("[data-confetti]");
        const cardsPerPack = Number(opening.dataset.cardsPerPack || 6);
        const highlights = opening.dataset.highlights === "true";
        const totalPacks = highlights ? 1 : Math.ceil(cards.length / cardsPerPack);
        let currentIndex = -1;
        let openingLocked = false;
        let audioContext;
        let touchStartX = 0;
        let swiped = false;

        const ensureAudio = () => {
            if (!audioContext) {
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                if (AudioContext) {
                    audioContext = new AudioContext();
                }
            }
            if (audioContext?.state === "suspended") {
                audioContext.resume();
            }
        };

        const tone = (frequency, duration = 0.08, delay = 0, volume = 0.035) => {
            if (!audioContext) {
                return;
            }
            const oscillator = audioContext.createOscillator();
            const gain = audioContext.createGain();
            const start = audioContext.currentTime + delay;
            oscillator.type = "sine";
            oscillator.frequency.setValueAtTime(frequency, start);
            gain.gain.setValueAtTime(0.001, start);
            gain.gain.exponentialRampToValueAtTime(volume, start + 0.012);
            gain.gain.exponentialRampToValueAtTime(0.001, start + duration);
            oscillator.connect(gain);
            gain.connect(audioContext.destination);
            oscillator.start(start);
            oscillator.stop(start + duration + 0.02);
        };

        const playOpenSound = () => {
            tone(180, 0.12, 0, 0.03);
            tone(270, 0.14, 0.08, 0.035);
            tone(390, 0.16, 0.17, 0.03);
        };

        const playCardSound = (isFinal, isHit) => {
            if (isHit) {
                tone(440, 0.16, 0, 0.04);
                tone(660, 0.18, 0.1, 0.04);
                tone(880, 0.24, 0.2, 0.04);
            } else if (isFinal) {
                tone(390, 0.12, 0, 0.03);
                tone(520, 0.18, 0.1, 0.03);
            } else {
                tone(300 + ((currentIndex % cardsPerPack) * 24), 0.08, 0, 0.022);
            }
        };

        const celebrate = () => {
            if (!confettiLayer) {
                return;
            }
            const colors = ["#df5635", "#22543d", "#f2c349", "#5bd7ff", "#ff6098"];
            for (let index = 0; index < 42; index += 1) {
                const piece = document.createElement("span");
                piece.className = "confetti-piece";
                piece.style.left = `${Math.random() * 100}%`;
                piece.style.background = colors[index % colors.length];
                piece.style.setProperty("--delay", `${Math.random() * 280}ms`);
                piece.style.setProperty("--duration", `${1400 + (Math.random() * 900)}ms`);
                piece.style.setProperty("--drift", `${-90 + (Math.random() * 180)}px`);
                confettiLayer.appendChild(piece);
                window.setTimeout(() => piece.remove(), 2700);
            }
        };

        const isBigHit = (card, index) => {
            const rarity = card.dataset.rarity || "";
            const rarePattern = /(special|secret|hyper|shiny|illustration|ultra|rainbow|gold|double rare|dupla rara)/i;
            if (rarePattern.test(rarity)) {
                return true;
            }

            const packStart = highlights ? 0 : Math.floor(index / cardsPerPack) * cardsPerPack;
            const previousValues = cards
                .slice(packStart, index)
                .map((item) => Number(item.dataset.value || 0));
            const average = previousValues.length
                ? previousValues.reduce((sum, value) => sum + value, 0) / previousValues.length
                : 0;
            const value = Number(card.dataset.value || 0);
            return value >= 10 && value >= average * 2.5;
        };

        const updateProgress = () => {
            const revealed = Math.max(currentIndex + 1, 0);
            progress.style.width = `${(revealed / cards.length) * 100}%`;
        };

        const revealCard = (index) => {
            currentIndex = index;
            packScene.hidden = true;
            revealScene.hidden = false;
            completeScene.hidden = true;

            cards.forEach((card) => {
                card.hidden = true;
                card.classList.remove("is-active", "is-leaving", "is-final", "is-big-hit");
                const label = card.querySelector("[data-final-label]");
                if (label) {
                    label.hidden = true;
                }
            });

            const card = cards[index];
            const cardInPack = highlights ? index + 1 : (index % cardsPerPack) + 1;
            const packIndex = Math.floor(index / cardsPerPack) + 1;
            const isFinal = highlights ? index === cards.length - 1 : cardInPack === cardsPerPack;
            const hit = isFinal && isBigHit(card, index);

            card.hidden = false;
            card.classList.add("is-active");
            card.classList.toggle("is-final", isFinal);
            card.classList.toggle("is-big-hit", hit);
            const finalLabel = card.querySelector("[data-final-label]");
            if (finalLabel) {
                finalLabel.hidden = !isFinal;
            }

            counter.textContent = highlights
                ? `Destaque ${index + 1} de ${cards.length}`
                : `Pack ${packIndex} de ${totalPacks} · Carta ${cardInPack} de ${cardsPerPack}`;
            status.textContent = hit
                ? "É HIT!"
                : isFinal
                    ? "Última carta..."
                    : "Revelando cartas";

            const isLastCard = index === cards.length - 1;
            const isPackEnd = !highlights && cardInPack === cardsPerPack;
            nextButtonText.textContent = isLastCard
                ? "Concluir abertura"
                : isPackEnd
                    ? "Próximo pack"
                    : "Próxima carta";

            updateProgress();
            playCardSound(isFinal, hit);
            if (navigator.vibrate) {
                navigator.vibrate(hit ? [35, 35, 70] : isFinal ? 35 : 12);
            }
            if (hit) {
                celebrate();
            }
        };

        const showNextPack = () => {
            const nextPack = Math.floor((currentIndex + 1) / cardsPerPack) + 1;
            revealScene.hidden = true;
            packScene.hidden = false;
            packScene.classList.remove("is-opening");
            packNumber.textContent = `Pack ${nextPack} de ${totalPacks}`;
            status.textContent = `Pack ${nextPack} pronto`;
            openingLocked = false;
        };

        const finishOpening = () => {
            revealScene.hidden = true;
            packScene.hidden = true;
            completeScene.hidden = false;
            progress.style.width = "100%";
            status.textContent = "Abertura concluída";
            tone(520, 0.14, 0, 0.03);
            tone(660, 0.16, 0.1, 0.03);
        };

        const advance = () => {
            if (revealScene.hidden || currentIndex < 0) {
                return;
            }
            const currentCard = cards[currentIndex];
            currentCard.classList.add("is-leaving");

            window.setTimeout(() => {
                if (currentIndex >= cards.length - 1) {
                    finishOpening();
                    return;
                }
                if (!highlights && (currentIndex + 1) % cardsPerPack === 0) {
                    showNextPack();
                    return;
                }
                revealCard(currentIndex + 1);
            }, 190);
        };

        const openPack = () => {
            if (openingLocked || packScene.hidden) {
                return;
            }
            ensureAudio();
            openingLocked = true;
            packScene.classList.add("is-opening");
            status.textContent = highlights ? "Preparando destaques..." : "Rasgando o pack...";
            playOpenSound();
            if (navigator.vibrate) {
                navigator.vibrate([25, 30, 45]);
            }
            window.setTimeout(() => {
                packScene.classList.remove("is-opening");
                revealCard(currentIndex + 1);
                openingLocked = false;
            }, 680);
        };

        openButtons.forEach((button) => button.addEventListener("click", openPack));
        nextButton?.addEventListener("click", advance);
        cards.forEach((card) => {
            card.addEventListener("click", () => {
                if (swiped) {
                    swiped = false;
                    return;
                }
                advance();
            });
        });

        revealScene?.addEventListener("touchstart", (event) => {
            touchStartX = event.changedTouches[0]?.clientX || 0;
        }, { passive: true });
        revealScene?.addEventListener("touchend", (event) => {
            const touchEndX = event.changedTouches[0]?.clientX || 0;
            if (Math.abs(touchEndX - touchStartX) > 45) {
                swiped = true;
                advance();
            }
        }, { passive: true });

        document.addEventListener("keydown", (event) => {
            if (!["ArrowRight", " ", "Enter"].includes(event.key)) {
                return;
            }
            if (["INPUT", "TEXTAREA", "BUTTON", "A"].includes(document.activeElement?.tagName)) {
                return;
            }
            event.preventDefault();
            if (!packScene.hidden) {
                openPack();
            } else if (!revealScene.hidden) {
                advance();
            }
        });
    }
});
