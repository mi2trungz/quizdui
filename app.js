const STORAGE_KEY = "quiz-flash-progress-v2";
const ALL_CHAPTERS = "__all__";

const state = {
  cards: [],
  cardsById: new Map(),
  chapterOptions: [],
  mode: "all",
  wrongScope: "chapter",
  selectedChapter: ALL_CHAPTERS,
  order: [],
  index: 0,
  shown: false,
  choiceResult: null,
  roundWrong: [],
  savedWrong: [],
  shuffle: false,
  pendingSession: null,
};

const els = {
  totalCards: document.querySelector("#totalCards"),
  wrongCount: document.querySelector("#wrongCount"),
  chapterSelect: document.querySelector("#chapterSelect"),
  allModeBtn: document.querySelector("#allModeBtn"),
  wrongModeBtn: document.querySelector("#wrongModeBtn"),
  resetBtn: document.querySelector("#resetBtn"),
  shuffleToggle: document.querySelector("#shuffleToggle"),
  scopeChapterBtn: document.querySelector("#scopeChapterBtn"),
  scopeGlobalBtn: document.querySelector("#scopeGlobalBtn"),
  sessionName: document.querySelector("#sessionName"),
  progressText: document.querySelector("#progressText"),
  progressFill: document.querySelector("#progressFill"),
  cardContext: document.querySelector("#cardContext"),
  cardTitle: document.querySelector("#cardTitle"),
  cardPosition: document.querySelector("#cardPosition"),
  cardBody: document.querySelector("#cardBody"),
  showBtn: document.querySelector("#showBtn"),
  correctBtn: document.querySelector("#correctBtn"),
  wrongBtn: document.querySelector("#wrongBtn"),
  nextBtn: document.querySelector("#nextBtn"),
  nextWrongBtn: document.querySelector("#nextWrongBtn"),
  message: document.querySelector("#message"),
};

function parseChapter(context) {
  const source = (context || "").trim();
  if (!source) return { key: "Khac", label: "Khac" };
  const slashSplit = source.split("/").map((part) => part.trim()).filter(Boolean);
  for (const part of slashSplit.slice().reverse()) {
    if (/^TCQT_C\d+$/i.test(part)) return { key: part.toUpperCase(), label: part.toUpperCase() };
    if (/^chapter\b/i.test(part)) return { key: part, label: part };
    if (/^chương\b/i.test(part)) return { key: part, label: part };
  }
  return { key: slashSplit[slashSplit.length - 1] || source, label: slashSplit[slashSplit.length - 1] || source };
}

function prepareCards(cards) {
  const chapterCounter = new Map();
  const mapped = cards.map((card) => {
    const chapter = parseChapter(card.context);
    chapterCounter.set(chapter.key, (chapterCounter.get(chapter.key) || 0) + 1);
    return { ...card, chapterKey: chapter.key, chapterLabel: chapter.label };
  });

  state.chapterOptions = [{ key: ALL_CHAPTERS, label: "Tất cả chương", count: mapped.length }]
    .concat(
      [...chapterCounter.entries()]
        .sort((a, b) => a[0].localeCompare(b[0], "vi", { numeric: true }))
        .map(([key, count]) => ({ key, label: key, count })),
    );

  state.cardsById = new Map(mapped.map((card) => [card.id, card]));
  return mapped;
}

function cardById(id) {
  return state.cardsById.get(id);
}

function currentCard() {
  return cardById(state.order[state.index]);
}

function isCardInSelectedChapter(card) {
  return state.selectedChapter === ALL_CHAPTERS || card.chapterKey === state.selectedChapter;
}

function loadProgress() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    state.savedWrong = Array.isArray(saved.savedWrong) ? saved.savedWrong : [];
    state.shuffle = Boolean(saved.shuffle);
    state.selectedChapter = typeof saved.selectedChapter === "string" ? saved.selectedChapter : ALL_CHAPTERS;
    state.wrongScope = saved.wrongScope === "global" ? "global" : "chapter";
    state.pendingSession = saved.session && Array.isArray(saved.session.order) ? saved.session : null;
  } catch {
    state.savedWrong = [];
    state.shuffle = false;
    state.selectedChapter = ALL_CHAPTERS;
    state.wrongScope = "chapter";
    state.pendingSession = null;
  }
}

function saveProgress() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      savedWrong: state.savedWrong,
      shuffle: state.shuffle,
      selectedChapter: state.selectedChapter,
      wrongScope: state.wrongScope,
      session: {
        mode: state.mode,
        order: state.order,
        index: state.index,
        shown: state.shown,
        choiceResult: state.choiceResult,
        roundWrong: state.roundWrong,
        selectedChapter: state.selectedChapter,
        wrongScope: state.wrongScope,
      },
    }),
  );
}

function shuffled(items) {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function baseIdsForAllMode() {
  return state.cards.filter((card) => isCardInSelectedChapter(card)).map((card) => card.id);
}

function baseIdsForWrongMode() {
  const wrongIds = state.savedWrong.filter((id) => cardById(id));
  if (state.wrongScope === "global") return wrongIds;
  return wrongIds.filter((id) => {
    const card = cardById(id);
    return card ? isCardInSelectedChapter(card) : false;
  });
}

function startSession(mode) {
  state.mode = mode;
  const base = mode === "wrong" ? baseIdsForWrongMode() : baseIdsForAllMode();
  state.order = state.shuffle ? shuffled(base) : [...base];
  state.index = 0;
  state.shown = false;
  state.choiceResult = null;
  state.roundWrong = [];
  saveProgress();
  render();
}

function setButtonsForCard(hasCard) {
  const card = hasCard ? currentCard() : null;
  const isChoice = card?.type === "choice";
  const answeredChoice = isChoice && state.choiceResult?.cardId === card.id;
  els.showBtn.classList.toggle("hidden", !hasCard || isChoice || state.shown);
  els.correctBtn.classList.toggle("hidden", !hasCard || isChoice || !state.shown);
  els.wrongBtn.classList.toggle("hidden", !hasCard || isChoice || !state.shown);
  els.nextBtn.classList.toggle("hidden", !answeredChoice);
  els.nextWrongBtn.classList.add("hidden");
}

function renderEmpty() {
  const noWrong = state.mode === "wrong";
  els.sessionName.textContent = noWrong ? "Làm lại câu sai" : "Tất cả câu";
  els.progressText.textContent = "0 / 0";
  els.progressFill.style.width = "0%";
  els.cardContext.textContent = "";
  els.cardPosition.textContent = "";
  els.cardTitle.textContent = noWrong ? "Chưa có câu sai để làm lại" : "Không có dữ liệu câu hỏi";
  els.cardBody.innerHTML = noWrong
    ? "<p>Bạn chưa đánh dấu sai câu nào trong phạm vi đang chọn.</p>"
    : "<p>Không có card cho bộ lọc hiện tại. Thử đổi chương hoặc tắt xáo trộn.</p>";
  setButtonsForCard(false);
  els.message.textContent = "";
}

function renderComplete() {
  const wrongCount = state.roundWrong.length;
  const merged = new Set(state.savedWrong);
  if (state.mode === "wrong") {
    const roundSet = new Set(state.order);
    for (const id of state.savedWrong) {
      if (roundSet.has(id)) merged.delete(id);
    }
  }
  for (const id of state.roundWrong) merged.add(id);
  state.savedWrong = [...merged];
  saveProgress();

  els.progressText.textContent = `${state.order.length} / ${state.order.length}`;
  els.progressFill.style.width = "100%";
  els.cardContext.textContent = "";
  els.cardPosition.textContent = "";
  els.cardTitle.textContent = wrongCount ? `Còn ${wrongCount} câu sai` : "Xong vòng này";
  els.cardBody.innerHTML = wrongCount
    ? "<p>Bấm Làm lại câu sai để học tiếp nhóm vừa đánh dấu sai.</p>"
    : "<p>Không còn câu sai trong vòng hiện tại.</p>";

  els.showBtn.classList.add("hidden");
  els.correctBtn.classList.add("hidden");
  els.wrongBtn.classList.add("hidden");
  els.nextBtn.classList.add("hidden");
  els.nextWrongBtn.classList.toggle("hidden", wrongCount === 0);
  els.message.textContent = wrongCount
    ? "Danh sách câu sai đã được cập nhật."
    : "Đã hoàn thành vòng này.";
  updateStats();
}

function activeSessionLabel() {
  const chapterLabel = state.selectedChapter === ALL_CHAPTERS ? "Tất cả chương" : state.selectedChapter;
  return state.mode === "wrong" ? `Làm lại câu sai - ${chapterLabel}` : `Luyện theo bộ lọc - ${chapterLabel}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderChoiceCard(card) {
  const result = state.choiceResult?.cardId === card.id ? state.choiceResult : null;
  const question = card.frontHtml || escapeHtml(card.question || card.text || "").replace(/\n/g, "<br>");
  const options = Array.isArray(card.options) ? card.options : [];
  const optionHtml = options
    .map((option, index) => {
      const key = String.fromCharCode(65 + index);
      const classes = ["choice-option"];
      if (result && index === card.answerIndex) classes.push("is-correct");
      if (result && index === result.selectedIndex && index !== card.answerIndex) classes.push("is-wrong");
      return `<button class="${classes.join(" ")}" type="button" data-choice-index="${index}" ${result ? "disabled" : ""}>
        <span class="choice-key">${key}</span>
        <span class="choice-text">${escapeHtml(option)}</span>
      </button>`;
    })
    .join("");

  els.cardBody.innerHTML = `<div class="choice-question">${question}</div><div class="choice-options">${optionHtml}</div>`;
  if (!result) {
    els.message.textContent = "Chọn một đáp án để kiểm tra ngay.";
  } else if (result.isWrong) {
    const answerKey = String(card.answerKey || "").toUpperCase();
    els.message.textContent = `Sai rồi. Đáp án đúng là ${answerKey}.`;
  } else {
    els.message.textContent = "Đúng rồi. Bấm Tiếp để sang câu sau.";
  }
}

function render() {
  updateStats();
  els.shuffleToggle.checked = state.shuffle;
  els.allModeBtn.classList.toggle("primary", state.mode === "all");
  els.wrongModeBtn.classList.toggle("primary", state.mode === "wrong");
  els.scopeChapterBtn.classList.toggle("primary", state.wrongScope === "chapter");
  els.scopeGlobalBtn.classList.toggle("primary", state.wrongScope === "global");

  if (state.order.length === 0) {
    renderEmpty();
    return;
  }

  if (state.index >= state.order.length) {
    renderComplete();
    return;
  }

  const card = currentCard();
  const position = state.index + 1;
  els.sessionName.textContent = activeSessionLabel();
  els.progressText.textContent = `${position} / ${state.order.length}`;
  els.progressFill.style.width = `${((position - 1) / state.order.length) * 100}%`;
  els.cardContext.textContent = card.context || card.chapterLabel;
  els.cardTitle.textContent = card.title;
  els.cardPosition.textContent = `#${card.index}`;
  if (card.type === "choice") {
    renderChoiceCard(card);
  } else {
    els.cardBody.innerHTML = state.shown ? card.originalHtml : card.frontHtml;
    els.message.textContent = state.shown ? "Đã show đáp án gốc. Tự đánh giá đúng/sai để sang câu tiếp." : "";
  }
  setButtonsForCard(true);
}

function updateStats() {
  const inChapter = state.cards.filter((card) => isCardInSelectedChapter(card)).length;
  els.totalCards.textContent = `${inChapter} câu`;
  const wrongFiltered = state.savedWrong.filter((id) => {
    const card = cardById(id);
    if (!card) return false;
    return state.selectedChapter === ALL_CHAPTERS ? true : card.chapterKey === state.selectedChapter;
  });
  els.wrongCount.textContent = `${wrongFiltered.length} câu sai`;
}

function markCurrent(isWrong) {
  const card = currentCard();
  if (isWrong && card && !state.roundWrong.includes(card.id)) {
    state.roundWrong.push(card.id);
  }
  state.index += 1;
  state.shown = false;
  state.choiceResult = null;
  saveProgress();
  render();
}

function selectChoice(index) {
  const card = currentCard();
  if (!card || card.type !== "choice" || state.choiceResult?.cardId === card.id) return;
  const selectedIndex = Number(index);
  if (!Number.isInteger(selectedIndex)) return;

  const isWrong = selectedIndex !== card.answerIndex;
  state.choiceResult = { cardId: card.id, selectedIndex, isWrong };
  if (isWrong && !state.roundWrong.includes(card.id)) {
    state.roundWrong.push(card.id);
  }
  saveProgress();
  render();
}

function nextCard() {
  state.index += 1;
  state.shown = false;
  state.choiceResult = null;
  saveProgress();
  render();
}

function restoreSessionIfPossible() {
  const session = state.pendingSession;
  if (!session) return false;
  const selectedChapter = typeof session.selectedChapter === "string" ? session.selectedChapter : state.selectedChapter;
  const wrongScope = session.wrongScope === "global" ? "global" : "chapter";

  const validOrder = session.order.filter((id) => {
    const card = cardById(id);
    if (!card) return false;
    return selectedChapter === ALL_CHAPTERS ? true : card.chapterKey === selectedChapter || wrongScope === "global";
  });
  if (validOrder.length === 0) return false;

  state.selectedChapter = selectedChapter;
  state.wrongScope = wrongScope;
  state.mode = session.mode === "wrong" ? "wrong" : "all";
  state.order = validOrder;
  state.index = Math.min(Math.max(Number(session.index) || 0, 0), validOrder.length);
  state.shown = Boolean(session.shown);
  state.choiceResult = session.choiceResult && session.choiceResult.cardId === validOrder[state.index]
    ? session.choiceResult
    : null;
  state.roundWrong = Array.isArray(session.roundWrong)
    ? session.roundWrong.filter((id) => cardById(id))
    : [];
  return true;
}

function renderChapterOptions() {
  els.chapterSelect.innerHTML = "";
  for (const option of state.chapterOptions) {
    const node = document.createElement("option");
    node.value = option.key;
    node.textContent = `${option.label} (${option.count})`;
    if (option.key === state.selectedChapter) node.selected = true;
    els.chapterSelect.appendChild(node);
  }
}

async function init() {
  loadProgress();
  els.shuffleToggle.checked = state.shuffle;

  try {
    let payload = window.QUIZ_DATA;
    if (!payload) {
      const response = await fetch("data/cards.json");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      payload = await response.json();
    }
    state.cards = prepareCards(payload.cards || []);
  } catch (error) {
    els.cardTitle.textContent = "Không tải được dữ liệu";
    els.cardBody.innerHTML = `<p>${error.message}</p>`;
    updateStats();
    return;
  }

  if (!state.chapterOptions.some((item) => item.key === state.selectedChapter)) {
    state.selectedChapter = ALL_CHAPTERS;
  }
  renderChapterOptions();

  els.showBtn.addEventListener("click", () => {
    state.shown = true;
    saveProgress();
    render();
  });
  els.correctBtn.addEventListener("click", () => markCurrent(false));
  els.wrongBtn.addEventListener("click", () => markCurrent(true));
  els.nextBtn.addEventListener("click", nextCard);
  els.cardBody.addEventListener("click", (event) => {
    const option = event.target.closest("[data-choice-index]");
    if (!option) return;
    selectChoice(Number(option.dataset.choiceIndex));
  });
  els.allModeBtn.addEventListener("click", () => startSession("all"));
  els.wrongModeBtn.addEventListener("click", () => startSession("wrong"));
  els.nextWrongBtn.addEventListener("click", () => startSession("wrong"));
  els.chapterSelect.addEventListener("change", () => {
    state.selectedChapter = els.chapterSelect.value;
    saveProgress();
    startSession(state.mode);
  });
  els.scopeChapterBtn.addEventListener("click", () => {
    state.wrongScope = "chapter";
    saveProgress();
    startSession(state.mode);
  });
  els.scopeGlobalBtn.addEventListener("click", () => {
    state.wrongScope = "global";
    saveProgress();
    startSession(state.mode);
  });
  els.shuffleToggle.addEventListener("change", () => {
    state.shuffle = els.shuffleToggle.checked;
    saveProgress();
    startSession(state.mode);
  });
  els.resetBtn.addEventListener("click", () => {
    state.savedWrong = [];
    state.roundWrong = [];
    saveProgress();
    startSession("all");
  });

  if (restoreSessionIfPossible()) {
    renderChapterOptions();
    render();
  } else {
    startSession("all");
  }
}

init();
