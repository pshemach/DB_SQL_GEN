const API_BASE = "http://localhost:8588";

// =============================
// STORAGE
// =============================

function getSessionId() {
  let sessionId = localStorage.getItem("session_id");

  if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem("session_id", sessionId);
  }

  return sessionId;
}

function setSessionId(sessionId) {
  localStorage.setItem("session_id", sessionId);
}

function getUser() {
  const raw = localStorage.getItem("user");
  return raw ? JSON.parse(raw) : null;
}

function setUser(user) {
  localStorage.setItem("user", JSON.stringify(user));
}

function clearUser() {
  localStorage.removeItem("user");
}

function getMessagesKey() {
  return `chat_messages_${getSessionId()}`;
}

function getStoredMessages() {
  const raw = localStorage.getItem(getMessagesKey());
  return raw ? JSON.parse(raw) : [];
}

function saveStoredMessages(messages) {
  localStorage.setItem(getMessagesKey(), JSON.stringify(messages));
}

function clearStoredMessages() {
  localStorage.removeItem(getMessagesKey());
}

function getFeedbackKey(messageId) {
  return `feedback_${getSessionId()}_${messageId}`;
}

function setFeedbackSaved(messageId, feedbackType) {
  localStorage.setItem(getFeedbackKey(messageId), feedbackType);
}

function getFeedbackSaved(messageId) {
  return localStorage.getItem(getFeedbackKey(messageId));
}

// =============================
// API
// =============================

async function postJson(url, data) {
  const response = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

async function getJson(url) {
  const response = await fetch(`${API_BASE}${url}`);

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

async function deleteJson(url) {
  const response = await fetch(`${API_BASE}${url}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

// =============================
// LOGIN
// =============================

function showLoginMode(mode) {
  document
    .getElementById("phoneLogin")
    .classList.toggle("hidden", mode !== "phone");
  document
    .getElementById("systemLogin")
    .classList.toggle("hidden", mode !== "system");

  document
    .getElementById("phoneModeBtn")
    .classList.toggle("active", mode === "phone");
  document
    .getElementById("systemModeBtn")
    .classList.toggle("active", mode === "system");
}

async function loginPhone() {
  const phoneNo = document.getElementById("phoneNo").value.trim();
  const loginMessage = document.getElementById("loginMessage");

  loginMessage.textContent = "";

  if (!phoneNo) {
    loginMessage.textContent = "Please enter phone number.";
    return;
  }

  try {
    const result = await postJson("/auth/phone", {
      phone_no: phoneNo,
    });

    if (!result.success) {
      loginMessage.textContent = result.error || "Login failed.";
      return;
    }

    result.user_id = String(result.user_id);

    setUser(result);

    // If backend returns session_id, use it. Otherwise keep browser session.
    if (result.session_id) {
      setSessionId(result.session_id);
    } else {
      getSessionId();
    }

    updateUi();
  } catch (e) {
    loginMessage.textContent = e.message;
  }
}

async function loginSystem() {
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value.trim();
  const loginMessage = document.getElementById("loginMessage");

  loginMessage.textContent = "";

  if (!username || !password) {
    loginMessage.textContent = "Please enter username and password.";
    return;
  }

  try {
    const result = await postJson("/auth/system", {
      username,
      password,
    });

    if (!result.success) {
      loginMessage.textContent = result.error || "Login failed.";
      return;
    }

    result.user_id = String(result.user_id);

    setUser(result);

    if (result.session_id) {
      setSessionId(result.session_id);
    } else {
      getSessionId();
    }

    updateUi();
  } catch (e) {
    loginMessage.textContent = e.message;
  }
}

function logout() {
  clearUser();
  localStorage.removeItem("session_id");
  location.reload();
}

function newChat() {
  clearStoredMessages();

  const newId = crypto.randomUUID();
  setSessionId(newId);

  document.getElementById("messages").innerHTML = "";
  document.getElementById("resultBox").classList.add("hidden");

  updateUi();
}

// =============================
// UI STATE
// =============================

function updateUi() {
  const user = getUser();
  const sessionId = getSessionId();

  document.getElementById("sessionText").textContent = `Session: ${sessionId}`;

  if (!user) {
    document.getElementById("loginBox").classList.remove("hidden");
    document.getElementById("userBox").classList.add("hidden");
    document.getElementById("feedbackStatsBox").classList.add("hidden");
    document.getElementById("kbBox").classList.add("hidden");
    document.getElementById("messages").innerHTML = "";
    return;
  }

  document.getElementById("loginBox").classList.add("hidden");
  document.getElementById("userBox").classList.remove("hidden");
  document.getElementById("feedbackStatsBox").classList.remove("hidden");

  document.getElementById("userName").textContent =
    user.display_name || user.user_id;

  document.getElementById("userRole").textContent =
    `Role: ${user.user_role || "unknown"}`;

  document.getElementById("loginMethod").textContent =
    `Login: ${user.login_method || "unknown"}`;

  const role = (user.user_role || "").toLowerCase();

  if (role === "rep") {
    document.getElementById("kbBox").classList.add("hidden");
  } else {
    document.getElementById("kbBox").classList.remove("hidden");
    loadKb();
  }

  renderStoredMessages();
  loadFeedbackStats();
}

// =============================
// MESSAGES + FEEDBACK
// =============================

function addMessage(
  role,
  content,
  messageId = null,
  messageType = "message",
  persist = true,
) {
  const message = {
    role,
    content,
    message_id: messageId,
    message_type: messageType,
  };

  if (persist) {
    const messages = getStoredMessages();
    messages.push(message);
    saveStoredMessages(messages);
  }

  renderSingleMessage(message);
}

function renderStoredMessages() {
  const container = document.getElementById("messages");
  container.innerHTML = "";

  const messages = getStoredMessages();

  messages.forEach((message) => {
    renderSingleMessage(message);
  });
}

function renderSingleMessage(message) {
  const role = message.role;
  const content = message.content;
  const messageId = message.message_id;
  const messageType = message.message_type || "message";

  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;

  if (
    role === "assistant" &&
    messageId &&
    ["answer", "clarification"].includes(messageType)
  ) {
    const feedback = buildFeedbackButtons(messageId, messageType, content);
    bubble.appendChild(feedback);
  }

  wrapper.appendChild(bubble);

  const container = document.getElementById("messages");
  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;
}

function buildFeedbackButtons(messageId, messageType, content) {
  const feedback = document.createElement("div");
  feedback.className = "feedback";

  const likeBtn = document.createElement("button");
  likeBtn.type = "button";
  likeBtn.textContent = "👍 Like";

  const dislikeBtn = document.createElement("button");
  dislikeBtn.type = "button";
  dislikeBtn.textContent = "👎 Dislike";

  const existingFeedback = getFeedbackSaved(messageId);

  if (existingFeedback === "like") {
    likeBtn.textContent = "👍 Saved";
    likeBtn.classList.add("saved");
    likeBtn.disabled = true;
    dislikeBtn.disabled = true;
  } else if (existingFeedback === "dislike") {
    dislikeBtn.textContent = "👎 Saved";
    dislikeBtn.classList.add("saved");
    likeBtn.disabled = true;
    dislikeBtn.disabled = true;
  }

  likeBtn.onclick = () =>
    saveFeedback(messageId, messageType, content, "like", likeBtn, dislikeBtn);

  dislikeBtn.onclick = () =>
    saveFeedback(
      messageId,
      messageType,
      content,
      "dislike",
      likeBtn,
      dislikeBtn,
    );

  feedback.appendChild(likeBtn);
  feedback.appendChild(dislikeBtn);

  return feedback;
}

async function saveFeedback(
  messageId,
  messageType,
  content,
  feedbackType,
  likeBtn,
  dislikeBtn,
) {
  const user = getUser();

  if (!user) {
    alert("Please login first.");
    return;
  }

  likeBtn.disabled = true;
  dislikeBtn.disabled = true;

  try {
    await postJson("/feedback", {
      session_id: getSessionId(),
      user_id: String(user.user_id),
      message_id: messageId,
      message_type: messageType,
      message_content: content.substring(0, 500),
      feedback_type: feedbackType,
    });

    setFeedbackSaved(messageId, feedbackType);

    if (feedbackType === "like") {
      likeBtn.textContent = "👍 Saved";
      likeBtn.classList.add("saved");
    } else {
      dislikeBtn.textContent = "👎 Saved";
      dislikeBtn.classList.add("saved");
    }

    loadFeedbackStats();
  } catch (e) {
    alert(`Feedback save failed: ${e.message}`);
    likeBtn.disabled = false;
    dislikeBtn.disabled = false;
  }
}

async function loadFeedbackStats() {
  try {
    const stats = await getJson(`/feedback/stats/${getSessionId()}`);

    document.getElementById("likes").textContent = stats.likes || 0;
    document.getElementById("dislikes").textContent = stats.dislikes || 0;
    document.getElementById("satisfaction").textContent =
      `${Math.round(stats.satisfaction || 0)}%`;
  } catch (e) {
    console.warn("Feedback stats failed", e);
  }
}

// =============================
// CHAT
// =============================

function formatResponse(result) {
  if (result.waiting_for_user) {
    return result.question_to_user || "Please provide more details.";
  }

  if (result.error) {
    return result.error;
  }

  if (result.final_answer) {
    return result.final_answer;
  }

  if (result.result_summary) {
    return result.result_summary;
  }

  if (result.query_result) {
    return "Query executed successfully.";
  }

  return "Done.";
}

async function sendQuestion() {
  const input = document.getElementById("questionInput");
  const question = input.value.trim();
  const user = getUser();

  if (!question) {
    return;
  }

  if (!user) {
    alert("Please login first.");
    return;
  }

  input.value = "";

  addMessage("user", question, null, "question", true);
  addMessage("assistant", "Thinking...", null, "system", false);

  try {
    const result = await postJson("/query", {
      question,
      session_id: getSessionId(),

      // Keep these for your current API.
      // Later you can remove them if backend reads auth from session.
      user_id: String(user.user_id),
      user_role: user.user_role,
      allowed_rep_codes: user.allowed_rep_codes || [],
    });

    removeThinking();

    const text = formatResponse(result);
    const messageType = result.waiting_for_user ? "clarification" : "answer";

    addMessage(
      "assistant",
      text,
      result.assistant_message_id || null,
      messageType,
      true,
    );

    renderResult(result);
    loadFeedbackStats();
  } catch (e) {
    removeThinking();
    addMessage("assistant", `Error: ${e.message}`, null, "error", true);
  }
}

function removeThinking() {
  const messages = document.querySelectorAll("#messages .message.assistant");
  const last = messages[messages.length - 1];

  if (last && last.textContent.includes("Thinking...")) {
    last.remove();
  }
}

// =============================
// RESULT RENDERING
// =============================

function renderResult(result) {
  const rows = result.query_result || [];
  const hasTable = Array.isArray(rows) && rows.length > 0;
  const hasSql = !!result.sql_query;
  const hasPlan = !!result.plan;
  const hasChart =
    Array.isArray(result.visualizations) &&
    result.visualizations.some((v) => v.chart_image_base64);

  if (!hasTable && !hasSql && !hasPlan && !hasChart) {
    document.getElementById("resultBox").classList.add("hidden");
    return;
  }

  document.getElementById("resultBox").classList.remove("hidden");

  document.getElementById("tableTab").innerHTML = hasTable
    ? buildTable(rows)
    : "<p>No table result.</p>";

  renderChartTab(result.visualizations || []);

  document.getElementById("sqlTab").textContent = result.sql_query || "No SQL.";
  document.getElementById("planTab").textContent = Array.isArray(
    result.plan_steps,
  )
    ? result.plan_steps.join("\n")
    : result.plan || "No plan.";

  showTab("table");
}

function buildTable(rows) {
  if (!rows.length) {
    return "<p>No data available.</p>";
  }

  const columns = Object.keys(rows[0]);

  let html = `<div class="table-wrap"><table><thead><tr>`;

  columns.forEach((col) => {
    html += `<th>${escapeHtml(col)}</th>`;
  });

  html += `</tr></thead><tbody>`;

  rows.forEach((row) => {
    html += `<tr>`;

    columns.forEach((col) => {
      html += `<td>${escapeHtml(row[col])}</td>`;
    });

    html += `</tr>`;
  });

  html += `</tbody></table></div>`;

  return html;
}

function renderChartTab(visualizations) {
  const chartTab = document.getElementById("chartTab");
  chartTab.innerHTML = "";

  if (!visualizations || visualizations.length === 0) {
    chartTab.innerHTML = "<p>No chart available.</p>";
    return;
  }

  visualizations.forEach((viz, index) => {
    const block = document.createElement("div");
    block.className = "chart-block";

    const title = document.createElement("h3");
    title.textContent = viz.title || `Chart ${index + 1}`;
    block.appendChild(title);

    if (viz.chart_image_base64) {
      const img = document.createElement("img");
      img.className = "chart-img";
      img.src = `data:image/png;base64,${viz.chart_image_base64}`;
      img.alt = viz.title || "Chart";
      block.appendChild(img);
    } else {
      const p = document.createElement("p");
      p.textContent = "Chart image was not generated.";
      block.appendChild(p);
    }

    chartTab.appendChild(block);
  });
}

function showTab(name) {
  const tabs = ["table", "chart", "sql", "plan"];

  tabs.forEach((tab) => {
    document.getElementById(`${tab}Tab`).classList.add("hidden");
    document.getElementById(`${tab}TabBtn`).classList.remove("active");
  });

  document.getElementById(`${name}Tab`).classList.remove("hidden");
  document.getElementById(`${name}TabBtn`).classList.add("active");
}

function escapeHtml(value) {
  if (value === null || value === undefined) {
    return "";
  }

  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// =============================
// KNOWLEDGE BASE
// =============================

let kbDefinitions = {};

async function loadKb() {
  const user = getUser();

  if (!user) {
    return;
  }

  const role = (user.user_role || "").toLowerCase();

  if (role === "rep") {
    document.getElementById("kbBox").classList.add("hidden");
    return;
  }

  try {
    kbDefinitions = await getJson("/kb");

    const select = document.getElementById("kbSelect");
    select.innerHTML = "";

    const keys = Object.keys(kbDefinitions);

    if (keys.length === 0) {
      select.innerHTML = `<option value="">No definitions</option>`;
      document.getElementById("kbView").textContent =
        "No KPI definitions found.";
      return;
    }

    keys.forEach((key) => {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = key;
      select.appendChild(option);
    });

    loadSelectedKb();
  } catch (e) {
    console.warn("KB load failed", e);
  }
}

function loadSelectedKb() {
  const key = document.getElementById("kbSelect").value;
  const def = kbDefinitions[key];

  if (!def) {
    document.getElementById("kbView").textContent = "";
    return;
  }

  const keywords = def.keywords || [];
  const definition = def.definition || "";

  document.getElementById("kbView").textContent =
    `Keywords:\n${keywords.join(", ")}\n\nDefinition:\n${definition}`;
}

function showKbForm() {
  const key = document.getElementById("kbSelect").value;
  const def = kbDefinitions[key] || {};

  document.getElementById("kbKey").value = key || "";
  document.getElementById("kbKeywords").value = (def.keywords || []).join("\n");
  document.getElementById("kbDefinition").value = def.definition || "";

  document.getElementById("kbForm").classList.remove("hidden");
}

function cancelKb() {
  document.getElementById("kbForm").classList.add("hidden");
}

async function saveKb() {
  const key = document.getElementById("kbKey").value.trim();
  const keywordsText = document.getElementById("kbKeywords").value.trim();
  const definition = document.getElementById("kbDefinition").value.trim();

  if (!key) {
    alert("KPI key is required.");
    return;
  }

  if (!definition) {
    alert("Definition is required.");
    return;
  }

  const keywords = keywordsText
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

  if (keywords.length === 0) {
    alert("At least one keyword is required.");
    return;
  }

  try {
    await postJson("/kb", {
      key,
      keywords,
      definition,
    });

    document.getElementById("kbForm").classList.add("hidden");

    await postJson("/kb/reload", {});
    await loadKb();

    alert("KPI definition saved.");
  } catch (e) {
    alert(`KB save failed: ${e.message}`);
  }
}

async function deleteKb() {
  const key = document.getElementById("kbKey").value.trim();

  if (!key) {
    alert("Select a KPI definition first.");
    return;
  }

  if (!confirm(`Delete KPI definition: ${key}?`)) {
    return;
  }

  try {
    await deleteJson(`/kb/${encodeURIComponent(key)}`);
    document.getElementById("kbForm").classList.add("hidden");
    await postJson("/kb/reload", {});
    await loadKb();

    alert("KPI definition deleted.");
  } catch (e) {
    alert(`KB delete failed: ${e.message}`);
  }
}

// =============================
// INIT
// =============================

document.addEventListener("DOMContentLoaded", () => {
  updateUi();

  const questionInput = document.getElementById("questionInput");

  questionInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      sendQuestion();
    }
  });
});
