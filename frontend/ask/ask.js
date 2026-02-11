/* ============================================================
   ask.marcle.ai — Frontend Logic
   Handles auth state, question submission, history rendering.
   ============================================================ */

(function () {
  "use strict";

  const API_BASE = (window.MARCLE_API_BASE || "") + "/api/ask";

  // --- DOM refs ---
  const loginView = document.getElementById("login-view");
  const appView = document.getElementById("app-view");
  const loadingView = document.getElementById("loading-view");
  const loginBtn = document.getElementById("btn-login");
  const logoutBtn = document.getElementById("btn-logout");
  const navUserSection = document.getElementById("nav-user-section");
  const userAvatar = document.getElementById("user-avatar");
  const userName = document.getElementById("user-name");
  const navPoints = document.getElementById("nav-points");
  const pointsDisplay = document.getElementById("points-display");
  const questionTextarea = document.getElementById("question-text");
  const charCount = document.getElementById("char-count");
  const submitBtn = document.getElementById("btn-submit");
  const statusMsg = document.getElementById("status-msg");
  const questionList = document.getElementById("question-list");
  const costDisplay = document.getElementById("cost-display");

  let currentUser = null;
  const activeQuestionStreams = new Map();
  let fallbackPollTimer = null;

  function getCookie(name) {
    const cookieName = `${name}=`;
    const chunks = document.cookie ? document.cookie.split(";") : [];
    for (const rawChunk of chunks) {
      const chunk = rawChunk.trim();
      if (chunk.startsWith(cookieName)) {
        return decodeURIComponent(chunk.substring(cookieName.length));
      }
    }
    return "";
  }

  function isMutatingMethod(method) {
    const normalized = String(method || "GET").toUpperCase();
    return !["GET", "HEAD", "OPTIONS", "TRACE"].includes(normalized);
  }

  // --- API Helpers ---
  async function apiFetch(path, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const csrfToken = isMutatingMethod(method) ? getCookie("ask_csrf") : "";
    const requestHeaders = {
      ...(options.headers || {}),
    };
    if (isMutatingMethod(method) && csrfToken) {
      requestHeaders["X-CSRF-Token"] = csrfToken;
    }

    const resp = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...requestHeaders,
      },
    });
    return resp;
  }

  // --- Auth ---
  async function checkAuth() {
    try {
      const resp = await apiFetch("/me");
      if (resp.ok) {
        currentUser = await resp.json();
        showApp();
        loadQuestions();
      } else {
        showLogin();
      }
    } catch {
      showLogin();
    }
  }

  function showLogin() {
    loadingView.style.display = "none";
    loginView.style.display = "block";
    appView.style.display = "none";
    if (navUserSection) {
      navUserSection.style.display = "none";
    }
    questionTextarea.disabled = true;
  }

  function showApp() {
    loadingView.style.display = "none";
    loginView.style.display = "none";
    appView.style.display = "block";
    if (navUserSection) {
      navUserSection.style.display = "flex";
    }
    questionTextarea.disabled = false;
    renderUser();
  }

  function renderUser() {
    if (!currentUser) return;
    userAvatar.src = currentUser.picture_url || "";
    userAvatar.alt = currentUser.name;
    userName.textContent = currentUser.name;
    updatePoints(currentUser.points);
  }

  function updatePoints(pts) {
    pointsDisplay.textContent = pts;
    navPoints.title = `${pts} Marcle Points`;
    // Disable submit if insufficient
    const hasEnough = pts >= getCost();
    submitBtn.disabled = !hasEnough || questionTextarea.value.trim().length < 10;
    if (!hasEnough) {
      submitBtn.title = "Insufficient points";
    } else {
      submitBtn.title = "";
    }
  }

  function getCost() {
    return parseInt(costDisplay.textContent, 10) || 1;
  }

  // --- Login / Logout ---
  loginBtn.addEventListener("click", () => {
    window.location.href = `${API_BASE}/auth/login`;
  });

  logoutBtn.addEventListener("click", async () => {
    try {
      await apiFetch("/auth/logout", { method: "POST" });
    } catch {
      // Ignore
    }
    for (const stream of activeQuestionStreams.values()) {
      stream.close();
    }
    activeQuestionStreams.clear();
    if (fallbackPollTimer) {
      clearInterval(fallbackPollTimer);
      fallbackPollTimer = null;
    }
    currentUser = null;
    showLogin();
  });

  // --- Question Submission ---
  questionTextarea.addEventListener("input", () => {
    const len = questionTextarea.value.length;
    charCount.textContent = `${len} / 5000`;
    if (currentUser) {
      submitBtn.disabled =
        len < 10 || len > 5000 || currentUser.points < getCost();
    }
  });

  submitBtn.addEventListener("click", async () => {
    const text = questionTextarea.value.trim();
    if (text.length < 10) return;

    submitBtn.disabled = true;
    submitBtn.innerHTML =
      '<span class="loading-spinner"></span> Submitting...';
    hideStatus();

    try {
      const resp = await apiFetch("/questions", {
        method: "POST",
        body: JSON.stringify({ question_text: text }),
      });

      if (resp.ok) {
        const data = await resp.json();
        currentUser.points = data.remaining_points;
        updatePoints(data.remaining_points);
        questionTextarea.value = "";
        charCount.textContent = "0 / 5000";

        showStatus(
          "success",
          `Question submitted! (ID: #${data.question_id}) ${
            data.discord_notified
              ? "Marc has been notified."
              : "Discord notification pending."
          }`
        );
        openQuestionStream(data.question_id);
        loadQuestions();
      } else {
        const err = await resp.json().catch(() => ({}));
        showStatus(
          "error",
          err.detail || `Failed to submit (${resp.status})`
        );
      }
    } catch (e) {
      showStatus("error", "Network error. Please try again.");
    }

    submitBtn.disabled = false;
    submitBtn.innerHTML = "Submit Question";
    if (currentUser) {
      submitBtn.disabled = currentUser.points < getCost();
    }
  });

  // --- Status Messages ---
  function showStatus(type, msg) {
    statusMsg.className = `status-msg visible ${type}`;
    statusMsg.textContent = msg;
  }

  function hideStatus() {
    statusMsg.className = "status-msg";
    statusMsg.textContent = "";
  }

  // --- Questions History ---
  async function loadQuestions() {
    try {
      const resp = await apiFetch("/questions?limit=20");
      if (!resp.ok) return;
      const questions = await resp.json();
      renderQuestions(questions);
      syncQuestionStreams(questions);
    } catch {
      // Silently fail
    }
  }

  function openQuestionStream(questionId) {
    if (!questionId || activeQuestionStreams.has(questionId)) return;

    const es = new EventSource(`${API_BASE}/questions/${questionId}/events`);

    es.addEventListener("snapshot", (evt) => {
      try {
        const payload = JSON.parse(evt.data);
        if (payload && payload.answer_text) {
          showStatus("success", `Answer received for question #${questionId}.`);
          loadQuestions();
          closeQuestionStream(questionId);
          return;
        }
        loadQuestions();
      } catch {
        // ignore bad event payload
      }
    });

    es.addEventListener("status", (evt) => {
      try {
        const payload = JSON.parse(evt.data);
        if (payload && payload.status) {
          showStatus("success", `Question #${questionId} is ${payload.status}.`);
        }
      } catch {
        // ignore
      }
    });

    es.addEventListener("answer", (evt) => {
      try {
        JSON.parse(evt.data);
      } catch {
        // ignore parse errors and still refresh
      }
      showStatus("success", `Answer received for question #${questionId}.`);
      loadQuestions();
      closeQuestionStream(questionId);
    });

    es.onerror = () => {
      closeQuestionStream(questionId);
      enablePollingFallback();
    };

    activeQuestionStreams.set(questionId, es);
  }

  function closeQuestionStream(questionId) {
    const es = activeQuestionStreams.get(questionId);
    if (!es) return;
    es.close();
    activeQuestionStreams.delete(questionId);
  }

  function syncQuestionStreams(questions) {
    const pendingIds = new Set(
      (questions || [])
        .filter((q) => q.status === "pending")
        .map((q) => q.id)
    );

    for (const qid of pendingIds) {
      openQuestionStream(qid);
    }

    for (const existingId of Array.from(activeQuestionStreams.keys())) {
      if (!pendingIds.has(existingId)) {
        closeQuestionStream(existingId);
      }
    }
  }

  function enablePollingFallback() {
    if (fallbackPollTimer) return;
    fallbackPollTimer = setInterval(() => {
      loadQuestions();
    }, 5000);
  }

  function renderQuestions(questions) {
    if (!questions || questions.length === 0) {
      questionList.innerHTML =
        '<li class="empty-state">No questions yet. Ask your first one above!</li>';
      return;
    }

    questionList.innerHTML = questions
      .map(
        (q) => `
      <li class="question-item">
        <div class="question-header">
          <span class="question-status ${q.status}">${q.status}</span>
          <span class="question-date">${formatDate(q.created_at)}</span>
        </div>
        <div class="question-text">${escapeHtml(q.question_text)}</div>
        ${
          q.answer_text
            ? `<div class="answer-block">
                <div class="answer-label">Answer</div>
                ${escapeHtml(q.answer_text)}
              </div>`
            : ""
        }
      </li>
    `
      )
      .join("");
  }

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // --- Init ---
  checkAuth();
})();
