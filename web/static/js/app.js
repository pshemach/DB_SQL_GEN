(() => {
  const STORAGE_KEY = "evision_ui_state";
  const CHART_TYPE_LABELS = {
    bar: "Bar",
    horizontal_bar: "Horizontal Bar",
    line: "Line",
    pie: "Pie",
    scatter: "Scatter",
  };
  const PREFERRED_X_TERMS = [
    "name", "rep", "customer", "outlet", "product",
    "route", "brand", "category", "type", "date",
  ];
  const NULL_VALUES = new Set(["None", "none", "NULL", "null", "NaN", "nan", "", " "]);

  const state = {
    token: null,
    user: null,
    sessionId: null,
    messages: [],
    lastResult: null,
    queryCount: 0,
    hasStarted: false,
    definitions: {},
    kbEditorMode: null,
    selectedKpi: null,
    chartRows: [],
    pivotRows: [],
  };

  const el = (id) => document.getElementById(id);

  function toast(message, type = "info") {
    const box = document.createElement("div");
    box.className = `toast ${type}`;
    box.textContent = message;
    el("toasts").appendChild(box);
    setTimeout(() => box.remove(), 3200);
  }

  function apiError(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail)) {
      return payload.detail.map((item) => item.msg || item).join(" ");
    }
    return payload.error || payload.message || fallback;
  }

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }
    if (state.token) headers.Authorization = `Bearer ${state.token}`;

    const response = await fetch(path, { ...options, headers });
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (!response.ok) {
      throw new Error(apiError(payload, `Request failed (${response.status})`));
    }
    return payload;
  }

  function saveLocal() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      token: state.token,
      user: state.user,
      sessionId: state.sessionId,
      messages: state.messages,
      lastResult: state.lastResult,
      queryCount: state.queryCount,
      hasStarted: state.hasStarted,
    }));
  }

  function loadLocal() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (!raw) return;
      Object.assign(state, raw);
      if (state.hasStarted == null) state.hasStarted = Boolean(state.messages?.length);
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
  }

  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderMarkdown(text) {
    const raw = window.marked ? marked.parse(String(text || "")) : `<p>${escapeHtml(text)}</p>`;
    return window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
  }

  function setLoginMethod(method) {
    document.querySelectorAll("[data-login-method]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.loginMethod === method);
    });
    el("phone-login").classList.toggle("hidden", method !== "phone");
    el("system-login").classList.toggle("hidden", method !== "system");
  }

  function renderAuth() {
    const loggedIn = Boolean(state.user);
    el("login-form").classList.toggle("hidden", loggedIn);
    el("logged-in").classList.toggle("hidden", !loggedIn);
    el("session-panel").classList.toggle("hidden", !loggedIn);
    el("login-gate").classList.toggle("hidden", loggedIn);
    el("workspace").classList.toggle("hidden", !loggedIn);
    el("chat-form").classList.toggle("hidden", !loggedIn);
    el("kb-panel").classList.toggle("hidden", !(loggedIn && state.user?.can_edit_kb));

    if (!loggedIn) {
      el("kb-editor").classList.add("hidden");
      return;
    }

    el("user-name").textContent = state.user.display_name || state.user.user_id || "User";
    el("user-role").textContent = state.user.user_role || "unknown";
    el("login-method").textContent = state.user.login_method || "";
    el("rep-codes").textContent = (state.user.allowed_rep_codes || []).join(", ") || "None";
    el("session-id").value = state.sessionId || "";
  }

  function fillSelect(select, options, selected) {
    const values = options.map(String);
    const current = new Set(Array.isArray(selected) ? selected.map(String) : selected != null ? [String(selected)] : []);
    select.innerHTML = values.map((value) => (
      `<option value="${escapeHtml(value)}" ${current.has(value) ? "selected" : ""}>${escapeHtml(value)}</option>`
    )).join("");
  }

  function renderKbSelect() {
    const keys = Object.keys(state.definitions || {});
    const selected = state.selectedKpi && keys.includes(state.selectedKpi) ? state.selectedKpi : keys[0] || "";
    state.selectedKpi = selected || null;
    fillSelect(el("kb-select"), keys, selected);
    const current = state.definitions[selected] || {};
    el("kb-keywords").textContent = (current.keywords || []).join(", ") || "No KPI definitions found.";
    el("kb-definition").textContent = current.definition || "";
  }

  function renderMessages() {
    const root = el("messages");
    root.innerHTML = "";
    state.messages.forEach((message) => {
      const wrap = document.createElement("div");
      wrap.className = `message ${message.role}`;
      if (message.role === "user") {
        wrap.innerHTML = `<div>${escapeHtml(message.content)}</div>`;
      } else {
        const canFeedback = Boolean(message.message_id) && ["answer", "clarification"].includes(message.type);
        wrap.innerHTML = `
          <div class="message-top">
            <div class="content">${renderMarkdown(message.content)}</div>
            ${canFeedback ? `
              <div class="feedback">
                <button type="button" class="btn icon" data-feedback="like" data-id="${escapeHtml(message.message_id)}">👍</button>
                <button type="button" class="btn icon" data-feedback="dislike" data-id="${escapeHtml(message.message_id)}">👎</button>
              </div>` : ""}
          </div>
        `;
        (message.metadata?.charts || []).forEach((chart, index) => {
          if (chart.title) {
            const title = document.createElement("h4");
            title.textContent = chart.title;
            wrap.appendChild(title);
          }
          const chartEl = document.createElement("div");
          chartEl.className = "chart";
          chartEl.dataset.chartIndex = String(index);
          wrap.appendChild(chartEl);
          requestAnimationFrame(() => renderPlotly(chartEl, chart.chart_json));
        });
      }
      root.appendChild(wrap);
    });
    root.scrollTop = root.scrollHeight;
  }

  function renderPlotly(target, chartJson) {
    if (!window.Plotly || !chartJson) return;
    try {
      const spec = typeof chartJson === "string" ? JSON.parse(chartJson) : chartJson;
      const layout = Object.assign({
        autosize: true,
        height: 460,
        margin: { t: 48, r: 24, b: 72, l: 64 },
      }, spec.layout || {});
      Plotly.react(target, spec.data || [], layout, { responsive: true, displaylogo: false });
    } catch (error) {
      target.textContent = `Failed to render chart: ${error.message}`;
    }
  }

  function tableHtml(rows) {
    if (!rows.length) return `<p class="muted">No tabular result available.</p>`;
    const cols = Object.keys(rows[0]);
    return `
      <table>
        <thead><tr>${cols.map((col) => `<th>${escapeHtml(col)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((row) => `<tr>${cols.map((col) => `<td>${escapeHtml(row[col])}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
    `;
  }

  function csvEscape(value) {
    const text = value == null ? "" : String(value);
    if (/[",\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
    return text;
  }

  function toCsv(rows) {
    if (!rows.length) return "";
    const cols = Object.keys(rows[0]);
    return [cols.join(","), ...rows.map((row) => cols.map((col) => csvEscape(row[col])).join(","))].join("\n");
  }

  function downloadText(filename, text, type = "text/plain") {
    const blob = new Blob([text], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  function asRows(value) {
    return Array.isArray(value)
      ? value.filter((row) => row && typeof row === "object" && !Array.isArray(row))
      : [];
  }

  function parseNumber(value) {
    if (value == null) return null;
    const cleaned = String(value).replace(/,/g, "").replace(/%/g, "").trim();
    if (NULL_VALUES.has(cleaned)) return null;
    const num = Number(cleaned);
    return Number.isFinite(num) ? num : null;
  }

  function coerceRows(rows, threshold = 0.7) {
    if (!rows.length) return [];
    const cols = Object.keys(rows[0]);
    const numeric = {};
    cols.forEach((col) => {
      const converted = rows.map((row) => parseNumber(row[col]));
      const hits = converted.filter((value) => value != null).length;
      numeric[col] = hits >= Math.max(1, rows.length * threshold);
    });
    return rows.map((row) => {
      const next = { ...row };
      cols.forEach((col) => {
        if (numeric[col]) {
          const parsed = parseNumber(row[col]);
          next[col] = parsed;
        }
      });
      return next;
    });
  }

  function prepareChartRows(rows) {
    if (!rows.length) return [];
    const cols = Object.keys(rows[0]);
    return rows.map((row) => {
      const next = { ...row };
      cols.forEach((col) => {
        const raw = row[col];
        if (NULL_VALUES.has(String(raw ?? ""))) next[col] = null;
        const parsed = parseNumber(raw);
        if (parsed != null) next[col] = parsed;
      });
      return next;
    });
  }

  function columnTypes(rows) {
    if (!rows.length) return { numeric: [], nonNumeric: [], all: [] };
    const all = Object.keys(rows[0]);
    const numeric = all.filter((col) => rows.some((row) => typeof row[col] === "number" && !Number.isNaN(row[col])));
    return { numeric, nonNumeric: all.filter((col) => !numeric.includes(col)), all };
  }

  function uniqueValues(rows, col) {
    return [...new Set(rows.map((row) => row[col]).filter((value) => value != null && !NULL_VALUES.has(String(value))))];
  }

  function aggregate(values, fn) {
    const nums = values.filter((value) => typeof value === "number" && !Number.isNaN(value));
    if (fn === "count") return values.length;
    if (!nums.length) return 0;
    if (fn === "sum") return nums.reduce((a, b) => a + b, 0);
    if (fn === "mean") return nums.reduce((a, b) => a + b, 0) / nums.length;
    if (fn === "min") return Math.min(...nums);
    if (fn === "max") return Math.max(...nums);
    return 0;
  }

  function pivotTable(rows, indexCols, columnCols, valueCol, aggFunc) {
    const groups = new Map();
    rows.forEach((row) => {
      const indexKey = indexCols.map((col) => row[col]);
      const colKey = columnCols.length ? columnCols.map((col) => row[col]).join(" | ") : valueCol;
      const mapKey = JSON.stringify(indexKey);
      if (!groups.has(mapKey)) groups.set(mapKey, { index: indexKey, values: {} });
      const bucket = groups.get(mapKey);
      if (!bucket.values[colKey]) bucket.values[colKey] = [];
      bucket.values[colKey].push(row[valueCol]);
    });

    const colNames = [...new Set([...groups.values()].flatMap((group) => Object.keys(group.values)))];
    const result = [];
    const totals = Object.fromEntries(colNames.map((name) => [name, []]));

    groups.forEach((group) => {
      const row = {};
      indexCols.forEach((col, i) => { row[col] = group.index[i]; });
      let rowTotal = [];
      colNames.forEach((name) => {
        const values = group.values[name] || [];
        row[name] = aggregate(values, aggFunc);
        totals[name].push(...values);
        rowTotal.push(...values);
      });
      row.Total = aggregate(rowTotal, aggFunc);
      result.push(row);
    });

    const totalRow = { [indexCols[0]]: "Total" };
    indexCols.slice(1).forEach((col) => { totalRow[col] = ""; });
    let grand = [];
    colNames.forEach((name) => {
      totalRow[name] = aggregate(totals[name], aggFunc);
      grand.push(...totals[name]);
    });
    totalRow.Total = aggregate(grand, aggFunc);
    result.push(totalRow);
    return result;
  }

  function selectedValues(select) {
    return [...select.selectedOptions].map((option) => option.value);
  }

  function renderPivot() {
    const rows = coerceRows(asRows(state.lastResult?.query_result));
    const types = columnTypes(rows);
    const indexCols = selectedValues(el("pivot-rows"));
    const columnCols = selectedValues(el("pivot-cols"));
    const valueCol = el("pivot-value").value;
    const aggFunc = el("pivot-agg").value;
    if (!indexCols.length || !valueCol) {
      el("pivot-table").innerHTML = `<p class="muted">Please select at least one row field.</p>`;
      state.pivotRows = [];
      return;
    }
    try {
      state.pivotRows = pivotTable(rows, indexCols, columnCols, valueCol, aggFunc);
      el("pivot-table").innerHTML = tableHtml(state.pivotRows);
    } catch (error) {
      el("pivot-table").innerHTML = `<p class="muted">Failed to create pivot table: ${escapeHtml(error.message)}</p>`;
    }
  }

  function setupPivot() {
    const rows = coerceRows(asRows(state.lastResult?.query_result));
    const types = columnTypes(rows);
    fillSelect(el("pivot-rows"), types.all, types.all[0] ? [types.all[0]] : []);
    fillSelect(el("pivot-cols"), types.all.filter((col) => col !== types.all[0]));
    fillSelect(el("pivot-value"), types.numeric, types.numeric[0]);
    renderPivot();
  }

  function defaultX(nonNumeric, all) {
    for (const term of PREFERRED_X_TERMS) {
      const match = nonNumeric.find((col) => col.toLowerCase().includes(term));
      if (match) return match;
    }
    return nonNumeric[0] || all[0];
  }

  function buildChartFigure(type, rows, xCol, yCol) {
    const x = rows.map((row) => row[xCol]);
    const y = rows.map((row) => row[yCol]);
    const title = `${yCol} by ${xCol}`;
    if (type === "Horizontal Bar") {
      return {
        data: [{ type: "bar", orientation: "h", x: y, y: x, text: y, textposition: "outside" }],
        layout: { title, height: 460 },
      };
    }
    if (type === "Line") {
      return { data: [{ type: "scatter", mode: "lines+markers", x, y }], layout: { title, height: 460 } };
    }
    if (type === "Pie") {
      return { data: [{ type: "pie", labels: x, values: y }], layout: { title: `${yCol} share by ${xCol}`, height: 460 } };
    }
    if (type === "Scatter") {
      return { data: [{ type: "scatter", mode: "markers", x, y, marker: { size: y.map((v) => Math.max(8, Number(v) || 8)) } }], layout: { title, height: 460 } };
    }
    return {
      data: [{ type: "bar", x, y, text: y, textposition: "outside" }],
      layout: { title, height: 460, xaxis: { tickangle: -45 } },
    };
  }

  function renderGraph() {
    const source = prepareChartRows(asRows(state.lastResult?.query_result));
    let rows = source;
    const filterCol = el("graph-filter-col").value;
    if (filterCol && filterCol !== "None") {
      const selected = new Set(selectedValues(el("graph-filter-values")));
      rows = rows.filter((row) => selected.has(String(row[filterCol])));
    }

    const types = columnTypes(rows);
    const xCol = el("graph-x").value;
    const yCol = el("graph-y").value;
    if (!xCol || !yCol) {
      el("graph-chart").innerHTML = `<p class="muted">No numeric column found for chart.</p>`;
      return;
    }

    rows = rows.filter((row) => row[xCol] != null && row[yCol] != null);
    if (!rows.length) {
      el("graph-chart").innerHTML = `<p class="muted">No rows available for selected chart columns.</p>`;
      return;
    }

    rows = [...rows].sort((a, b) => Number(b[yCol] || 0) - Number(a[yCol] || 0));
    const maxN = Math.min(100, rows.length);
    el("graph-topn").max = String(maxN);
    if (Number(el("graph-topn").value) > maxN) el("graph-topn").value = String(maxN);
    el("graph-topn-value").textContent = el("graph-topn").value;
    const topN = rows.length === 1 ? 1 : Number(el("graph-topn").value);
    const chartRows = rows.slice(0, topN);
    if (el("graph-type").value === "Horizontal Bar") {
      chartRows.reverse();
    }

    let chartType = el("graph-type").value;
    if (chartType === "Auto") chartType = chartRows.length > 15 ? "Horizontal Bar" : "Bar";
    renderPlotly(el("graph-chart"), buildChartFigure(chartType, chartRows, xCol, yCol));
    el("graph-data").innerHTML = tableHtml(chartRows);
    el("graph-meta").textContent = JSON.stringify({
      numeric_columns: types.numeric,
      non_numeric_columns: types.nonNumeric,
      selected_x: xCol,
      selected_y: yCol,
      rows_after_null_filter: chartRows.length,
    }, null, 2);
    state.chartRows = chartRows;
  }

  function setupGraph() {
    const rows = prepareChartRows(asRows(state.lastResult?.query_result));
    const types = columnTypes(rows);
    const filterCols = types.nonNumeric.filter((col) => {
      const count = uniqueValues(rows, col).length;
      return count > 1 && count <= 20;
    });
    fillSelect(el("graph-filter-col"), ["None", ...filterCols], "None");
    fillSelect(el("graph-x"), types.all, defaultX(types.nonNumeric, types.all));
    fillSelect(el("graph-y"), types.numeric, types.numeric[0]);
    const requested = CHART_TYPE_LABELS[state.lastResult?.requested_chart_type] || "Auto";
    el("graph-type").value = [...el("graph-type").options].some((opt) => opt.value === requested) ? requested : "Auto";
    el("graph-topn").value = String(Math.min(20, rows.length || 1));
    updateFilterValues();
    renderGraph();
  }

  function updateFilterValues() {
    const rows = prepareChartRows(asRows(state.lastResult?.query_result));
    const col = el("graph-filter-col").value;
    const wrap = el("graph-filter-values-wrap");
    if (!col || col === "None") {
      wrap.classList.add("hidden");
      return;
    }
    wrap.classList.remove("hidden");
    const values = uniqueValues(rows, col).map(String).sort();
    fillSelect(el("graph-filter-values"), values, values);
  }

  function renderResults() {
    const result = state.lastResult;
    const rows = coerceRows(asRows(result?.query_result));
    const hasOutput = rows.length || result?.sql_query || result?.plan;
    el("results-panel").classList.toggle("hidden", !result || !hasOutput);
    if (!result || !hasOutput) return;

    el("table-title").textContent = result.table_title || "Extracted Table";
    if (result.waiting_for_user) {
      el("result-table").innerHTML = `<p class="muted">${escapeHtml(result.question_to_user || "")}</p>`;
    } else if (result.error) {
      el("result-table").innerHTML = `<p class="muted">${escapeHtml(result.error)}</p>`;
    } else {
      el("result-table").innerHTML = tableHtml(rows);
      setupPivot();
    }

    if (result.sql_query) {
      el("sql-code").textContent = result.sql_query;
    } else {
      el("sql-code").textContent = "No SQL generated yet.";
    }

    el("plan-text").textContent = result.plan || "No plan available.";
    setupGraph();
  }

  function addMessage(role, content, type, metadata, messageId) {
    state.messages.push({
      role,
      content,
      type,
      message_id: messageId || uuid(),
      metadata: metadata || {},
    });
  }

  async function submitQuestion(question) {
    addMessage("user", question, "question");
    renderMessages();
    saveLocal();

    const thinking = document.createElement("div");
    thinking.className = "message assistant thinking";
    thinking.textContent = "Thinking...";
    el("messages").appendChild(thinking);
    el("send-btn").disabled = true;
    el("chat-input").disabled = true;

    try {
      let result;
      if (!state.hasStarted) {
        result = await api("/conversations", {
          method: "POST",
          body: JSON.stringify({
            question,
            session_id: state.sessionId,
          }),
        });
        state.hasStarted = true;
      } else {
        result = await api(`/conversations/${encodeURIComponent(state.sessionId)}/follow-up`, {
          method: "POST",
          body: JSON.stringify({ question }),
        });
      }
      state.sessionId = result.session_id || state.sessionId;
      state.lastResult = result;
      state.queryCount += 1;
      const messageType = result.waiting_for_user ? "clarification" : (result.error ? "error" : "answer");
      addMessage(
        "assistant",
        result.answer_text || "Done.",
        messageType,
        result.charts?.length ? { charts: result.charts } : null,
        result.assistant_message_id,
      );
      renderMessages();
      renderResults();
      saveLocal();
    } catch (error) {
      addMessage("assistant", `Unexpected error: ${error.message}`, "error");
      renderMessages();
      toast(error.message, "error");
    } finally {
      thinking.remove();
      el("send-btn").disabled = false;
      el("chat-input").disabled = false;
      el("chat-input").focus();
    }
  }

  async function login(path, body) {
    const result = await api(path, { method: "POST", body: JSON.stringify(body) });
    state.token = result.token;
    state.user = result.user;
    state.sessionId = result.user.session_id;
    state.messages = [];
    state.lastResult = null;
    state.queryCount = 0;
    state.hasStarted = false;
    renderAuth();
    renderMessages();
    renderResults();
    if (state.user.can_edit_kb) await loadDefinitions();
    saveLocal();
    toast("Login successful.", "success");
  }

  async function loadDefinitions() {
    const result = await api("/knowledge/definitions");
    state.definitions = result.definitions || {};
    renderKbSelect();
  }

  function openKbEditor(mode) {
    state.kbEditorMode = mode;
    const isEdit = mode === "edit";
    const key = isEdit ? state.selectedKpi : "";
    const existing = isEdit ? (state.definitions[key] || {}) : {};
    el("kb-editor-title").textContent = isEdit ? "✏️ Edit KPI Definition" : "➕ Add KPI Definition";
    el("kb-editor-form").key.value = key || "";
    el("kb-editor-form").keywords.value = (existing.keywords || []).join("\n");
    el("kb-editor-form").definition.value = existing.definition || "";
    el("kb-editor").classList.remove("hidden");
    el("kb-editor").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function bindEvents() {
    document.querySelectorAll("[data-login-method]").forEach((btn) => {
      btn.addEventListener("click", () => setLoginMethod(btn.dataset.loginMethod));
    });

    el("phone-login").addEventListener("submit", async (event) => {
      event.preventDefault();
      const phone = event.target.phone_no.value.trim();
      if (!phone) return toast("Please enter phone number.", "error");
      try {
        await login("/auth/phone", { phone_no: phone });
      } catch (error) {
        toast(error.message, "error");
      }
    });

    el("system-login").addEventListener("submit", async (event) => {
      event.preventDefault();
      const username = event.target.username.value.trim();
      const password = event.target.password.value.trim();
      if (!username || !password) return toast("Please enter username and password.", "error");
      try {
        await login("/auth/system", { username, password });
      } catch (error) {
        toast(error.message, "error");
      }
    });

    el("logout-btn").addEventListener("click", async () => {
      try { await api("/auth/logout", { method: "POST" }); } catch { /* ignore */ }
      state.token = null;
      state.user = null;
      state.sessionId = null;
      state.messages = [];
      state.lastResult = null;
      state.queryCount = 0;
      state.hasStarted = false;
      localStorage.removeItem(STORAGE_KEY);
      renderAuth();
      renderMessages();
      renderResults();
    });

    el("new-chat-btn").addEventListener("click", async () => {
      try {
        const result = await api("/conversations", { method: "POST", body: JSON.stringify({}) });
        state.sessionId = result.session_id;
        state.messages = [];
        state.lastResult = null;
        state.queryCount = 0;
        state.hasStarted = false;
        renderAuth();
        renderMessages();
        renderResults();
        saveLocal();
      } catch (error) {
        toast(error.message, "error");
      }
    });

    el("kb-reload-btn").addEventListener("click", async () => {
      try {
        const result = await api("/knowledge/reload", { method: "POST" });
        state.definitions = result.definitions || {};
        renderKbSelect();
        toast("Knowledge base reloaded", "success");
      } catch (error) {
        toast(error.message, "error");
      }
    });

    el("kb-add-btn").addEventListener("click", () => openKbEditor("add"));
    el("kb-edit-btn").addEventListener("click", () => {
      if (!state.selectedKpi) return toast("Select a KPI definition first.", "error");
      openKbEditor("edit");
    });
    el("kb-cancel-btn").addEventListener("click", () => {
      state.kbEditorMode = null;
      el("kb-editor").classList.add("hidden");
    });
    el("kb-select").addEventListener("change", () => {
      state.selectedKpi = el("kb-select").value;
      renderKbSelect();
    });
    el("kb-delete-btn").addEventListener("click", async () => {
      if (!state.selectedKpi) return;
      try {
        const result = await api(`/knowledge/definitions/${encodeURIComponent(state.selectedKpi)}`, { method: "DELETE" });
        state.definitions = result.definitions || {};
        state.selectedKpi = null;
        renderKbSelect();
        toast(result.message, "success");
      } catch (error) {
        toast(error.message, "error");
      }
    });

    el("kb-editor-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const key = event.target.key.value.trim();
      const definition = event.target.definition.value.trim();
      const keywords = event.target.keywords.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
      if (!key) return toast("KPI key is required.", "error");
      if (!definition) return toast("Definition is required.", "error");
      if (!keywords.length) return toast("At least one keyword is required.", "error");
      try {
        const result = await api("/knowledge/definitions", {
          method: "POST",
          body: JSON.stringify({ key, keywords, definition }),
        });
        state.definitions = result.definitions || {};
        state.selectedKpi = result.key;
        state.kbEditorMode = null;
        el("kb-editor").classList.add("hidden");
        renderKbSelect();
        toast(result.message, "success");
      } catch (error) {
        toast(error.message, "error");
      }
    });

    el("chat-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const question = el("chat-input").value.trim();
      if (!question) return;
      el("chat-input").value = "";
      submitQuestion(question);
    });

    el("chat-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        el("chat-form").requestSubmit();
      }
    });

    el("messages").addEventListener("click", async (event) => {
      const btn = event.target.closest("[data-feedback]");
      if (!btn) return;
      const message = state.messages.find((item) => item.message_id === btn.dataset.id);
      if (!message) return;
      try {
        await api("/feedback", {
          method: "POST",
          body: JSON.stringify({
            session_id: state.sessionId,
            message_id: message.message_id,
            message_type: message.type,
            message_content: String(message.content || "").slice(0, 500),
            feedback_type: btn.dataset.feedback,
          }),
        });
        toast("Feedback saved.", btn.dataset.feedback === "like" ? "success" : "info");
      } catch (error) {
        toast(error.message, "error");
      }
    });

    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((btn) => btn.classList.toggle("active", btn === tab));
        ["table", "graph", "sql", "plan"].forEach((name) => {
          el(`tab-${name}`).classList.toggle("hidden", name !== tab.dataset.tab);
        });
        if (tab.dataset.tab === "graph") renderGraph();
      });
    });

    ["pivot-rows", "pivot-cols", "pivot-value", "pivot-agg"].forEach((id) => {
      el(id).addEventListener("change", renderPivot);
    });
    el("pivot-download").addEventListener("click", () => downloadText("pivot_result.csv", toCsv(state.pivotRows), "text/csv"));
    el("table-download").addEventListener("click", () => {
      downloadText("query_result.csv", toCsv(coerceRows(asRows(state.lastResult?.query_result))), "text/csv");
    });
    el("sql-download").addEventListener("click", () => {
      downloadText("query.sql", state.lastResult?.sql_query || "", "text/plain");
    });
    el("graph-filter-col").addEventListener("change", () => { updateFilterValues(); renderGraph(); });
    el("graph-filter-values").addEventListener("change", renderGraph);
    el("graph-x").addEventListener("change", renderGraph);
    el("graph-y").addEventListener("change", renderGraph);
    el("graph-type").addEventListener("change", renderGraph);
    el("graph-topn").addEventListener("input", renderGraph);
    el("sidebar-toggle").addEventListener("click", () => el("sidebar").classList.toggle("open"));
  }

  async function init() {
    bindEvents();
    loadLocal();
    renderAuth();
    renderMessages();
    renderResults();
    if (!state.token) return;
    try {
      const me = await api("/auth/me");
      state.user = me.user;
      state.sessionId = state.sessionId || me.user.session_id;
      renderAuth();
      if (state.user.can_edit_kb) await loadDefinitions();
      saveLocal();
    } catch {
      state.token = null;
      state.user = null;
      localStorage.removeItem(STORAGE_KEY);
      renderAuth();
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
