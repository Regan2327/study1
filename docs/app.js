const sampleCourses = {
  biology: {
    name: "Biology 101",
    lectures: ["Cell Biology", "Genetics"],
    cards: [
      {
        lecture: "Cell Biology",
        front: "What is the basic unit of life?",
        back: "The cell is the smallest structural and functional unit of a living organism.",
        stability: 1,
        difficulty: 0.5,
      },
      {
        lecture: "Cell Biology",
        front: "What is the role of the cell membrane?",
        back: "It forms a selective boundary that regulates what enters and leaves the cell.",
        stability: 1.4,
        difficulty: 0.45,
      },
      {
        lecture: "Genetics",
        front: "What does DNA encode?",
        back: "DNA stores hereditary instructions used in the growth, development, and function of organisms.",
        stability: 0.8,
        difficulty: 0.65,
      },
      {
        lecture: "Genetics",
        front: "What is a gene?",
        back: "A gene is a segment of DNA that contributes to a functional product, such as a protein or RNA.",
        stability: 2,
        difficulty: 0.4,
      },
    ],
  },
  neuroscience: {
    name: "Neuroscience",
    lectures: ["Neurons", "Learning & Memory"],
    cards: [
      {
        lecture: "Neurons",
        front: "What is the primary role of a neuron?",
        back: "A neuron receives, processes, and transmits information using electrical and chemical signals.",
        stability: 1,
        difficulty: 0.5,
      },
      {
        lecture: "Learning & Memory",
        front: "What is synaptic plasticity?",
        back: "Synaptic plasticity is the ability of connections between neurons to strengthen or weaken over time.",
        stability: 1.3,
        difficulty: 0.55,
      },
    ],
  },
};

const elements = {
  course: document.querySelector("#course-select"),
  lecture: document.querySelector("#lecture-select"),
  importButton: document.querySelector("#import-button"),
  fileInput: document.querySelector("#file-input"),
  loadSample: document.querySelector("#load-sample"),
  reset: document.querySelector("#reset-demo"),
  empty: document.querySelector("#empty-state"),
  flashcard: document.querySelector("#flashcard"),
  cardFront: document.querySelector("#card-front"),
  cardBack: document.querySelector("#card-back"),
  answer: document.querySelector("#answer"),
  lectureLabel: document.querySelector("#lecture-label"),
  progress: document.querySelector("#progress-label"),
  count: document.querySelector("#card-count"),
  reviewControls: document.querySelector("#review-controls"),
  showAnswer: document.querySelector("#show-answer"),
  gradeButtons: document.querySelector("#grade-buttons"),
  forgot: document.querySelector("#forgot"),
  recalled: document.querySelector("#recalled"),
  chart: document.querySelector("#chart-line"),
  stability: document.querySelector("#stability-label"),
  export: document.querySelector("#export-button"),
  log: document.querySelector("#activity-log"),
  toast: document.querySelector("#toast"),
};

const state = {
  cards: [],
  index: 0,
  toastTimer: null,
};

function currentCard() {
  return state.cards[state.index] ?? null;
}

function log(message, label = "NOW") {
  const row = document.createElement("p");
  const time = document.createElement("time");
  const text = document.createElement("span");
  time.textContent = label;
  text.textContent = message;
  row.append(time, text);
  elements.log.prepend(row);
  while (elements.log.children.length > 6) {
    elements.log.lastElementChild.remove();
  }
}

function toast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => {
    elements.toast.classList.remove("visible");
  }, 2600);
}

function visibleCards() {
  const lecture = elements.lecture.value;
  return state.cards.filter((card) => lecture === "all" || card.lecture === lecture);
}

function render() {
  const cards = visibleCards();
  const card = cards[state.index] ?? null;
  const hasCards = Boolean(card);

  elements.empty.hidden = hasCards;
  elements.flashcard.hidden = !hasCards;
  elements.reviewControls.hidden = !hasCards;
  elements.count.textContent = `${cards.length} ${cards.length === 1 ? "card" : "cards"}`;

  if (!card) {
    drawRetention(1);
    return;
  }

  elements.cardFront.textContent = card.front;
  elements.cardBack.textContent = card.back;
  elements.lectureLabel.textContent = card.lecture;
  elements.progress.textContent = `Card ${state.index + 1} of ${cards.length}`;
  elements.answer.hidden = true;
  elements.showAnswer.hidden = false;
  elements.gradeButtons.hidden = true;
  drawRetention(card.stability);
}

function drawRetention(stability) {
  const left = 58;
  const top = 28;
  const width = 442;
  const height = 240;
  const points = [];
  for (let i = 0; i <= 80; i += 1) {
    const elapsed = (i / 80) * 3;
    const retention = Math.exp(-elapsed / Math.max(stability, 0.1));
    const x = left + (elapsed / 3) * width;
    const y = top + (1 - retention) * height;
    points.push(`${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`);
  }
  elements.chart.setAttribute("d", points.join(" "));
  elements.stability.textContent = `${stability.toFixed(1)}d stability`;
}

function updateLectures() {
  const course = sampleCourses[elements.course.value];
  const currentValue = elements.lecture.value;
  elements.lecture.replaceChildren(new Option("All materials", "all"));
  for (const lecture of course.lectures) {
    elements.lecture.add(new Option(lecture, lecture));
  }
  elements.lecture.value = course.lectures.includes(currentValue) ? currentValue : "all";
}

function loadSampleDeck() {
  const course = sampleCourses[elements.course.value];
  state.cards = course.cards.map((card) => ({ ...card }));
  state.index = 0;
  updateLectures();
  render();
  log(`Loaded ${state.cards.length} sample cards for ${course.name}.`);
  toast("Sample deck loaded");
}

function grade(recalled) {
  const card = currentCard();
  if (!card) return;

  if (recalled) {
    card.stability = Math.min(3650, card.stability * 1.6);
    card.difficulty = Math.max(0, card.difficulty - 0.05);
    log(`Recalled “${card.front}” · stability increased.`, "REVIEW");
  } else {
    card.stability = Math.max(0.1, card.stability * 0.3);
    card.difficulty = Math.min(1, card.difficulty + 0.1);
    log(`Forgot “${card.front}” · it will return sooner.`, "REVIEW");
  }

  const cards = visibleCards();
  if (cards.length > 1) state.index = (state.index + 1) % cards.length;
  render();
}

async function importText(file) {
  if (!file) return;
  if (file.size > 1_000_000) {
    toast("For this demo, text files must be smaller than 1 MB");
    return;
  }

  const content = await file.text();
  const firstLine = content.split(/\r?\n/).map((line) => line.trim()).find(Boolean);
  if (!firstLine) {
    toast("The selected file has no readable text");
    return;
  }

  const course = sampleCourses[elements.course.value];
  const lecture = file.name.replace(/\.[^.]+$/, "") || "Imported material";
  if (!course.lectures.includes(lecture)) course.lectures.push(lecture);
  state.cards.push({
    lecture,
    front: `What is a key idea from ${file.name}?`,
    back: firstLine.slice(0, 1200),
    stability: 1,
    difficulty: 0.5,
  });
  elements.lecture.add(new Option(lecture, lecture));
  elements.lecture.value = lecture;
  state.index = state.cards.filter((card) => card.lecture === lecture).length - 1;
  render();
  log(`Read ${file.name} locally and added one example review card.`, "IMPORT");
  toast("Text added locally — no upload made");
  elements.fileInput.value = "";
}

function exportDeck() {
  const rows = [["front", "back"], ...state.cards.map((card) => [card.front, card.back])];
  const csv = rows.map((row) => row.map((field) => `"${String(field).replaceAll('"', '""')}"`).join(",")).join("\r\n");
  const link = document.createElement("a");
  const downloadUrl = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  link.href = downloadUrl;
  link.download = "synaptiq-demo-deck.csv";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
  log(`Exported ${state.cards.length} cards as CSV.`, "EXPORT");
  toast("CSV deck downloaded");
}

elements.course.addEventListener("change", () => {
  state.cards = [];
  state.index = 0;
  updateLectures();
  render();
  log(`Switched course to ${sampleCourses[elements.course.value].name}.`);
});

elements.lecture.addEventListener("change", () => {
  state.index = 0;
  render();
});

elements.importButton.addEventListener("click", () => elements.fileInput.click());
elements.fileInput.addEventListener("change", (event) => {
  importText(event.target.files[0]).catch(() => toast("Could not read that file"));
});
elements.loadSample.addEventListener("click", loadSampleDeck);
elements.reset.addEventListener("click", () => {
  state.cards = [];
  state.index = 0;
  elements.course.value = "biology";
  updateLectures();
  render();
  log("Demo reset. Load a sample deck to start again.", "RESET");
  toast("Demo reset");
});
elements.showAnswer.addEventListener("click", () => {
  elements.answer.hidden = false;
  elements.showAnswer.hidden = true;
  elements.gradeButtons.hidden = false;
});
elements.forgot.addEventListener("click", () => grade(false));
elements.recalled.addEventListener("click", () => grade(true));
elements.export.addEventListener("click", exportDeck);

updateLectures();
render();
