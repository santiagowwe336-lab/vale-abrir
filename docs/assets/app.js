document.addEventListener("DOMContentLoaded", () => {
    const CARDS_PER_PACK = 6;
    const REVEAL_LIMIT = 60;
    const USD_BRL_RATE = 5;
    const views = Array.from(document.querySelectorAll("[data-view]"));
    const collectionGrid = document.querySelector("[data-collection-grid]");
    const searchInput = document.querySelector("[data-search]");
    const clearSearch = document.querySelector("[data-clear-search]");
    const alertBox = document.querySelector("[data-alert]");
    const state = {
        collections: [],
        collection: null,
        cards: [],
        quantity: 1,
        result: null,
        revealCards: [],
        highlights: false,
        revealIndex: -1,
        openingLocked: false,
        audioContext: null,
    };

    const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const safeImage = (value) => {
        try {
            const url = new URL(value);
            return url.protocol === "https:" ? url.href : "";
        } catch {
            return "";
        }
    };

    const showAlert = (message) => {
        alertBox.textContent = message;
        alertBox.hidden = false;
        window.scrollTo({ top: 0, behavior: "smooth" });
    };

    const clearAlert = () => {
        alertBox.hidden = true;
        alertBox.textContent = "";
    };

    const showView = (name) => {
        views.forEach((view) => {
            view.hidden = view.dataset.view !== name;
        });
        clearAlert();
        window.scrollTo({ top: 0, behavior: "smooth" });
    };

    const rarityLevel = (rarity) => {
        const normalized = String(rarity || "").toLowerCase();
        if (["special", "secret", "hyper", "shiny", "illustration"].some((term) => normalized.includes(term))) return 5;
        if (["ultra", "rainbow", "gold"].some((term) => normalized.includes(term))) return 4;
        if (normalized.includes("double rare") || normalized.includes("dupla rara")) return 3;
        if (["rare", "rara", "holo"].some((term) => normalized.includes(term))) return 2;
        if (normalized.includes("uncommon") || normalized.includes("incomum")) return 1;
        return 0;
    };

    const estimateValue = (rarity) => {
        const values = {
            common: 0.5,
            uncommon: 1,
            rare: 2.5,
            "rare holo": 6,
            "rare holo ex": 12,
            "double rare": 12,
            "rare ultra": 25,
            "ultra rare": 25,
            "illustration rare": 35,
            "special illustration rare": 90,
            "hyper rare": 120,
            "rare secret": 120,
        };
        return values[String(rarity || "").toLowerCase()] ?? 1;
    };

    const extractApiPrice = (card) => {
        const prices = card?.tcgplayer?.prices || {};
        for (const type of ["holofoil", "normal", "reverseHolofoil", "1stEditionHolofoil", "unlimitedHolofoil"]) {
            const price = prices[type] || {};
            const usd = price.market ?? price.mid ?? price.low;
            if (usd != null) return Number(usd) * USD_BRL_RATE;
        }
        return null;
    };

    const estimateChances = (cards) => {
        const counts = new Map();
        cards.forEach((card) => {
            const rarity = String(card.rarity || "Sem raridade").toLowerCase();
            counts.set(rarity, (counts.get(rarity) || 0) + 1);
        });
        const rarityRates = {
            rare: 45,
            "rare holo": 28,
            "rare holo ex": 12.5,
            "double rare": 12.5,
            "rare ultra": 6.5,
            "ultra rare": 6.5,
            "illustration rare": 7.5,
            "special illustration rare": 1.2,
            "hyper rare": 0.75,
            "rare secret": 1,
            "rare rainbow": 1,
            "rare shiny": 4,
            "shiny rare": 4,
        };
        return cards.map((card) => {
            const rarity = String(card.rarity || "Sem raridade").toLowerCase();
            const count = counts.get(rarity) || 1;
            if (rarity === "common" || rarity === "uncommon") {
                const slots = rarity === "common" ? 4 : 3;
                return (1 - ((count - 1) / count) ** slots) * 100;
            }
            return rarityRates[rarity] ? rarityRates[rarity] / count : 100 / Math.max(cards.length, 1);
        });
    };

    const normalizeRemoteCards = (cards) => {
        const chances = estimateChances(cards);
        return cards.map((card, index) => {
            const rarity = card.rarity || "Sem raridade";
            return {
                id: card.id,
                nome: card.name || "Carta sem nome",
                numero: card.number || "",
                raridade: rarity,
                imagem: card.images?.small || card.images?.large || "",
                valor: Number((extractApiPrice(card) ?? estimateValue(rarity)).toFixed(2)),
                chance: Number(chances[index].toFixed(4)),
            };
        });
    };

    const fetchCardsFromApi = async (collectionId) => {
        const cards = [];
        let page = 1;
        let total = 1;
        while (cards.length < total) {
            const params = new URLSearchParams({
                q: `set.id:${collectionId}`,
                page: String(page),
                pageSize: "250",
            });
            const response = await fetch(`https://api.pokemontcg.io/v2/cards?${params}`);
            if (!response.ok) throw new Error(`API respondeu ${response.status}`);
            const payload = await response.json();
            cards.push(...(payload.data || []));
            total = Number(payload.totalCount || cards.length);
            page += 1;
            if (!(payload.data || []).length) break;
        }
        return normalizeRemoteCards(cards);
    };

    const loadCards = async (collection) => {
        if (collection.arquivo) {
            const response = await fetch(`./data/${collection.arquivo}`);
            if (response.ok) {
                const payload = await response.json();
                if (payload.cartas?.length) return payload.cartas;
            }
        }

        try {
            const rawUrl = `https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master/cards/en/${encodeURIComponent(collection.id)}.json`;
            const response = await fetch(rawUrl);
            if (response.ok) return normalizeRemoteCards(await response.json());
        } catch {
            // A API oficial abaixo é o segundo fallback.
        }
        return fetchCardsFromApi(collection.id);
    };

    const collectionCard = (collection) => {
        const logo = safeImage(collection.logo);
        const symbol = safeImage(collection.simbolo);
        return `
            <article class="collection-card hall-collection-card">
                <div class="collection-media">
                    ${logo
                        ? `<img class="collection-logo" src="${escapeHtml(logo)}" alt="Logo de ${escapeHtml(collection.nome)}" loading="lazy">`
                        : '<span class="collection-fallback" aria-hidden="true"><i class="bi bi-stars"></i></span>'}
                    ${symbol ? `<img class="collection-symbol" src="${escapeHtml(symbol)}" alt="" loading="lazy">` : ""}
                </div>
                <div class="collection-card-body">
                    <div class="collection-meta"><span>${escapeHtml(collection.serie || "Pokémon")}</span><span>${escapeHtml(collection.lancamento || "")}</span></div>
                    <div class="collection-title">
                        <h2>${escapeHtml(collection.nome)}</h2>
                        <p>${Number(collection.total || 0)} cartas na coleção</p>
                    </div>
                    <button class="btn btn-primary collection-card-button" type="button" data-choose-collection="${escapeHtml(collection.id)}">
                        <i class="bi bi-play-fill" aria-hidden="true"></i><span>Escolher e simular</span>
                    </button>
                </div>
            </article>`;
    };

    const renderCollections = (query = "") => {
        const normalized = query.trim().toLocaleLowerCase("pt-BR");
        const filtered = state.collections.filter((collection) =>
            collection.nome.toLocaleLowerCase("pt-BR").includes(normalized));
        document.querySelector("[data-hall-title]").textContent = normalized ? "Resultados" : "Todas as coleções";
        document.querySelector("[data-collection-count]").textContent = `${filtered.length} ${filtered.length === 1 ? "encontrada" : "encontradas"}`;
        clearSearch.hidden = !normalized;
        collectionGrid.innerHTML = filtered.length
            ? filtered.map(collectionCard).join("")
            : '<div class="empty-state static-empty"><h2 class="h5">Nenhuma coleção encontrada</h2><p class="text-muted mb-0">Tente buscar por outro nome.</p></div>';
    };

    const chooseCollection = async (collectionId, button) => {
        const collection = state.collections.find((item) => item.id === collectionId);
        if (!collection) return;
        const original = button?.innerHTML;
        if (button) {
            button.disabled = true;
            button.innerHTML = '<span class="spinner-border spinner-border-sm"></span><span>Preparando…</span>';
        }
        try {
            const cards = await loadCards(collection);
            if (!cards.length) throw new Error("Nenhuma carta encontrada.");
            state.collection = collection;
            state.cards = cards;
            document.querySelector("[data-simulation-collection]").textContent = collection.nome;
            document.title = `Simular ${collection.nome} — Vale Abrir?`;
            showView("simulate");
        } catch (error) {
            showAlert(`Não foi possível carregar ${collection.nome}. Verifique sua conexão e tente novamente.`);
        } finally {
            if (button) {
                button.disabled = false;
                button.innerHTML = original;
            }
        }
    };

    const weightedDraws = (cards, amount) => {
        const weights = cards.map((card) => Math.max(Number(card.chance || 0), 0));
        let total = weights.reduce((sum, value) => sum + value, 0);
        if (total <= 0) {
            weights.fill(1);
            total = weights.length;
        }
        const cumulative = [];
        let running = 0;
        weights.forEach((weight) => {
            running += weight;
            cumulative.push(running);
        });

        const draws = [];
        for (let draw = 0; draw < amount; draw += 1) {
            const target = Math.random() * total;
            let low = 0;
            let high = cumulative.length - 1;
            while (low < high) {
                const middle = Math.floor((low + high) / 2);
                if (target < cumulative[middle]) high = middle;
                else low = middle + 1;
            }
            draws.push(cards[low]);
        }
        return draws;
    };

    const orderForReveal = (cards) => {
        const ordered = [];
        for (let start = 0; start < cards.length; start += CARDS_PER_PACK) {
            ordered.push(...cards.slice(start, start + CARDS_PER_PACK).sort((a, b) =>
                rarityLevel(a.raridade) - rarityLevel(b.raridade) || Number(a.valor) - Number(b.valor)));
        }
        return ordered;
    };

    const summarize = (cards) => {
        const grouped = new Map();
        cards.forEach((card) => {
            const current = grouped.get(card.id) || { ...card, quantidade: 0, valor_total: 0 };
            current.quantidade += 1;
            current.valor_total = Number((current.quantidade * Number(card.valor || 0)).toFixed(2));
            grouped.set(card.id, current);
        });
        return Array.from(grouped.values()).sort((a, b) =>
            Number(b.valor) - Number(a.valor) || Number(b.valor_total) - Number(a.valor_total));
    };

    const runSimulation = (quantity) => {
        const draws = weightedDraws(state.cards, quantity * CARDS_PER_PACK);
        const ordered = orderForReveal(draws);
        const summary = summarize(draws);
        state.quantity = quantity;
        state.result = {
            cards: summary,
            totalCards: draws.length,
            totalValue: Number(draws.reduce((sum, card) => sum + Number(card.valor || 0), 0).toFixed(2)),
        };
        state.highlights = ordered.length > REVEAL_LIMIT;
        state.revealCards = state.highlights
            ? ordered.slice().sort((a, b) => Number(b.valor) - Number(a.valor)).slice(0, CARDS_PER_PACK).sort((a, b) => Number(a.valor) - Number(b.valor))
            : ordered;
        startOpening();
    };

    const opening = {
        packScene: document.querySelector("[data-pack-scene]"),
        revealScene: document.querySelector("[data-reveal-scene]"),
        complete: document.querySelector("[data-opening-complete]"),
        area: document.querySelector("[data-reveal-area]"),
        counter: document.querySelector("[data-reveal-counter]"),
        status: document.querySelector("[data-opening-status]"),
        progress: document.querySelector("[data-opening-progress]"),
        packNumber: document.querySelector("[data-pack-number]"),
        next: document.querySelector("[data-reveal-next]"),
        confetti: document.querySelector("[data-confetti]"),
    };

    const ensureAudio = () => {
        if (!state.audioContext) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) state.audioContext = new AudioContext();
        }
        if (state.audioContext?.state === "suspended") state.audioContext.resume();
    };

    const tone = (frequency, duration = 0.08, delay = 0, volume = 0.03) => {
        if (!state.audioContext) return;
        const oscillator = state.audioContext.createOscillator();
        const gain = state.audioContext.createGain();
        const start = state.audioContext.currentTime + delay;
        oscillator.frequency.setValueAtTime(frequency, start);
        gain.gain.setValueAtTime(0.001, start);
        gain.gain.exponentialRampToValueAtTime(volume, start + 0.012);
        gain.gain.exponentialRampToValueAtTime(0.001, start + duration);
        oscillator.connect(gain);
        gain.connect(state.audioContext.destination);
        oscillator.start(start);
        oscillator.stop(start + duration + 0.02);
    };

    const celebrate = () => {
        const colors = ["#df5635", "#22543d", "#f2c349", "#5bd7ff", "#ff6098"];
        for (let index = 0; index < 42; index += 1) {
            const piece = document.createElement("span");
            piece.className = "confetti-piece";
            piece.style.left = `${Math.random() * 100}%`;
            piece.style.background = colors[index % colors.length];
            piece.style.setProperty("--delay", `${Math.random() * 280}ms`);
            piece.style.setProperty("--duration", `${1400 + Math.random() * 900}ms`);
            piece.style.setProperty("--drift", `${-90 + Math.random() * 180}px`);
            opening.confetti.appendChild(piece);
            window.setTimeout(() => piece.remove(), 2700);
        }
    };

    const isBigHit = (card, index) => {
        if (/(special|secret|hyper|shiny|illustration|ultra|rainbow|gold|double rare|dupla rara)/i.test(card.raridade || "")) return true;
        const start = state.highlights ? 0 : Math.floor(index / CARDS_PER_PACK) * CARDS_PER_PACK;
        const previous = state.revealCards.slice(start, index).map((item) => Number(item.valor || 0));
        const average = previous.length ? previous.reduce((sum, value) => sum + value, 0) / previous.length : 0;
        return Number(card.valor || 0) >= 10 && Number(card.valor || 0) >= average * 2.5;
    };

    const cardMarkup = (card, isFinal, hit) => {
        const image = safeImage(card.imagem);
        return `
            <article class="reveal-card is-active${isFinal ? " is-final" : ""}${hit ? " is-big-hit" : ""}" data-current-card>
                ${isFinal ? '<span class="final-card-label"><i class="bi bi-stars"></i>Última carta</span>' : ""}
                <div class="reveal-card-image">
                    ${image ? `<img src="${escapeHtml(image)}" alt="Imagem de ${escapeHtml(card.nome)}" draggable="false">` : '<span class="reveal-card-placeholder"><i class="bi bi-card-image"></i></span>'}
                    <span class="card-holo" aria-hidden="true"></span>
                </div>
                <div class="reveal-card-info">
                    <div><h2>${escapeHtml(card.nome)}</h2><p>${escapeHtml(card.raridade)}</p></div>
                    <div class="reveal-card-price"><span>Valor</span><strong>${brl.format(Number(card.valor || 0))}</strong></div>
                </div>
            </article>`;
    };

    const revealCard = (index) => {
        state.revealIndex = index;
        opening.packScene.hidden = true;
        opening.revealScene.hidden = false;
        opening.complete.hidden = true;
        const current = opening.area.querySelector("[data-current-card]");
        if (current) current.remove();

        const card = state.revealCards[index];
        const cardInPack = state.highlights ? index + 1 : (index % CARDS_PER_PACK) + 1;
        const packIndex = Math.floor(index / CARDS_PER_PACK) + 1;
        const isFinal = state.highlights ? index === state.revealCards.length - 1 : cardInPack === CARDS_PER_PACK;
        const hit = isFinal && isBigHit(card, index);
        opening.area.insertAdjacentHTML("beforeend", cardMarkup(card, isFinal, hit));
        opening.area.querySelector("[data-current-card]").addEventListener("click", advanceOpening);
        opening.counter.textContent = state.highlights
            ? `Destaque ${index + 1} de ${state.revealCards.length}`
            : `Pack ${packIndex} de ${state.quantity} · Carta ${cardInPack} de ${CARDS_PER_PACK}`;
        opening.status.textContent = hit ? "É HIT!" : isFinal ? "Última carta..." : "Revelando cartas";
        const last = index === state.revealCards.length - 1;
        opening.next.querySelector("span").textContent = last ? "Concluir abertura" : isFinal && !state.highlights ? "Próximo pack" : "Próxima carta";
        opening.progress.style.width = `${((index + 1) / state.revealCards.length) * 100}%`;
        if (hit) {
            tone(440, 0.16); tone(660, 0.18, 0.1); tone(880, 0.24, 0.2); celebrate();
        } else {
            tone(isFinal ? 520 : 300 + cardInPack * 24, isFinal ? 0.16 : 0.08);
        }
        if (navigator.vibrate) navigator.vibrate(hit ? [35, 35, 70] : isFinal ? 35 : 12);
    };

    const showNextPack = () => {
        const nextPack = Math.floor((state.revealIndex + 1) / CARDS_PER_PACK) + 1;
        opening.revealScene.hidden = true;
        opening.packScene.hidden = false;
        opening.packScene.classList.remove("is-opening");
        opening.packNumber.textContent = `Pack ${nextPack} de ${state.quantity}`;
        opening.status.textContent = `Pack ${nextPack} pronto`;
        state.openingLocked = false;
    };

    const finishOpening = () => {
        opening.revealScene.hidden = true;
        opening.packScene.hidden = true;
        opening.complete.hidden = false;
        opening.progress.style.width = "100%";
        opening.status.textContent = "Abertura concluída";
        tone(520, 0.14); tone(660, 0.16, 0.1);
    };

    function advanceOpening() {
        if (opening.revealScene.hidden || state.revealIndex < 0) return;
        const current = opening.area.querySelector("[data-current-card]");
        current?.classList.add("is-leaving");
        window.setTimeout(() => {
            if (state.revealIndex >= state.revealCards.length - 1) finishOpening();
            else if (!state.highlights && (state.revealIndex + 1) % CARDS_PER_PACK === 0) showNextPack();
            else revealCard(state.revealIndex + 1);
        }, 190);
    }

    const openPack = () => {
        if (state.openingLocked || opening.packScene.hidden) return;
        ensureAudio();
        state.openingLocked = true;
        opening.packScene.classList.add("is-opening");
        opening.status.textContent = state.highlights ? "Preparando destaques..." : "Rasgando o pack...";
        tone(180, 0.12); tone(270, 0.14, 0.08); tone(390, 0.16, 0.17);
        if (navigator.vibrate) navigator.vibrate([25, 30, 45]);
        window.setTimeout(() => {
            opening.packScene.classList.remove("is-opening");
            revealCard(state.revealIndex + 1);
            state.openingLocked = false;
        }, 680);
    };

    function startOpening() {
        state.revealIndex = -1;
        state.openingLocked = false;
        opening.packScene.hidden = false;
        opening.revealScene.hidden = true;
        opening.complete.hidden = true;
        opening.progress.style.width = "0";
        opening.packScene.classList.remove("is-opening");
        document.querySelector("[data-opening-kicker]").textContent = state.highlights ? "Destaques da abertura" : state.collection.nome;
        opening.status.textContent = state.highlights ? "Suas melhores cartas" : "Pronto para abrir";
        opening.packNumber.textContent = state.highlights ? `6 destaques de ${state.quantity} packs` : `Pack 1 de ${state.quantity}`;
        document.querySelector("[data-booster-name]").textContent = state.collection.nome;
        const logo = safeImage(state.collection.logo);
        const logoElement = document.querySelector("[data-booster-logo]");
        const brand = document.querySelector("[data-booster-brand]");
        logoElement.hidden = !logo;
        brand.hidden = Boolean(logo);
        if (logo) logoElement.src = logo;
        document.querySelector("[data-pack-heading]").textContent = state.highlights ? "Revelar destaques" : "Abra seu pack";
        document.querySelector("[data-pack-description]").textContent = state.highlights
            ? "Veja as seis cartas mais valiosas da simulação."
            : "Toque no pack para rasgar e começar a revelar.";
        showView("opening");
    }

    const resultCard = (card) => {
        const image = safeImage(card.imagem);
        return `
            <article class="pulled-card">
                <div class="pulled-card-image">
                    ${image ? `<img src="${escapeHtml(image)}" alt="Imagem de ${escapeHtml(card.nome)}" loading="lazy">` : "<span>Sem imagem</span>"}
                    <strong class="pulled-card-count">x${card.quantidade}</strong>
                </div>
                <div class="pulled-card-body">
                    <div><h3>${escapeHtml(card.nome)}</h3><p>${escapeHtml(card.raridade)}</p></div>
                    <div class="card-price-row"><span>${card.quantidade === 1 ? "Valor da carta" : "Valor unitário"}</span><strong>${brl.format(Number(card.valor || 0))}</strong></div>
                    ${card.quantidade > 1 ? `<div class="card-price-row card-price-total"><span>Valor das ${card.quantidade} cartas</span><strong>${brl.format(Number(card.valor_total || 0))}</strong></div>` : ""}
                </div>
            </article>`;
    };

    const showResult = () => {
        document.querySelector("[data-result-collection]").textContent = state.collection.nome;
        document.querySelector("[data-result-description]").textContent = `${state.result.totalCards} cartas em ${state.quantity} ${state.quantity === 1 ? "pack" : "packs"}.`;
        document.querySelector("[data-result-value]").textContent = brl.format(state.result.totalValue);
        document.querySelector("[data-result-types]").textContent = `${state.result.cards.length} ${state.result.cards.length === 1 ? "tipo" : "tipos"}`;
        document.querySelector("[data-result-grid]").innerHTML = state.result.cards.map(resultCard).join("");
        document.title = `Resultado de ${state.collection.nome} — Vale Abrir?`;
        showView("result");
    };

    const goHome = () => {
        document.title = "Vale Abrir? — Simulador TCG";
        showView("hall");
    };

    document.querySelectorAll("[data-go-home]").forEach((button) => button.addEventListener("click", goHome));
    document.querySelector("[data-search-form]").addEventListener("submit", (event) => {
        event.preventDefault();
        renderCollections(searchInput.value);
    });
    searchInput.addEventListener("input", () => renderCollections(searchInput.value));
    clearSearch.addEventListener("click", () => {
        searchInput.value = "";
        renderCollections();
        searchInput.focus();
    });
    collectionGrid.addEventListener("click", (event) => {
        const button = event.target.closest("[data-choose-collection]");
        if (button) chooseCollection(button.dataset.chooseCollection, button);
    });

    document.querySelectorAll('input[name="quantidade_packs"]').forEach((radio) => {
        radio.addEventListener("change", () => {
            document.querySelector("[data-custom-quantity]").hidden = radio.value !== "personalizada" || !radio.checked;
        });
    });
    document.querySelector("[data-simulation-form]").addEventListener("submit", (event) => {
        event.preventDefault();
        const selected = document.querySelector('input[name="quantidade_packs"]:checked')?.value || "1";
        const quantity = selected === "personalizada"
            ? Number(document.querySelector("#quantidadePersonalizada").value)
            : Number(selected);
        if (!Number.isInteger(quantity) || quantity < 1 || quantity > 10000) {
            showAlert("Escolha uma quantidade entre 1 e 10.000 packs.");
            return;
        }
        runSimulation(quantity);
    });

    document.querySelectorAll("[data-open-pack]").forEach((button) => button.addEventListener("click", openPack));
    opening.next.addEventListener("click", advanceOpening);
    document.querySelector("[data-skip-opening]").addEventListener("click", showResult);
    document.querySelector("[data-show-result]").addEventListener("click", showResult);
    document.querySelector("[data-simulate-again]").addEventListener("click", () => showView("simulate"));

    let touchStartX = 0;
    opening.area.addEventListener("touchstart", (event) => {
        touchStartX = event.changedTouches[0]?.clientX || 0;
    }, { passive: true });
    opening.area.addEventListener("touchend", (event) => {
        const end = event.changedTouches[0]?.clientX || 0;
        if (Math.abs(end - touchStartX) > 45) advanceOpening();
    }, { passive: true });
    document.addEventListener("keydown", (event) => {
        if (!["ArrowRight", " "].includes(event.key) || document.querySelector('[data-view="opening"]').hidden) return;
        if (["INPUT", "TEXTAREA", "BUTTON", "A"].includes(document.activeElement?.tagName)) return;
        event.preventDefault();
        if (!opening.packScene.hidden) openPack();
        else if (!opening.revealScene.hidden) advanceOpening();
    });

    fetch("./data/collections.json")
        .then((response) => {
            if (!response.ok) throw new Error(`Falha ${response.status}`);
            return response.json();
        })
        .then(async (payload) => {
            state.collections = payload.colecoes || [];
            document.querySelector("[data-total-collections]").textContent = state.collections.length;
            renderCollections();

            const params = new URLSearchParams(window.location.search);
            const collectionId = params.get("colecao");
            const packs = Number(params.get("packs"));
            if (collectionId && state.collections.some((item) => item.id === collectionId)) {
                await chooseCollection(collectionId);
                if (Number.isInteger(packs) && packs >= 1 && packs <= 10000) {
                    runSimulation(packs);
                }
            }
        })
        .catch(() => {
            collectionGrid.innerHTML = '<div class="empty-state static-empty"><h2 class="h5">Não foi possível carregar as coleções</h2><p class="text-muted mb-0">Abra o site por um servidor HTTP ou publique pelo GitHub Pages.</p></div>';
            showAlert("Os arquivos de dados não foram encontrados.");
        });
});
