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
  const qs = (root, selector) => root.querySelector(selector);

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
    const payload = {
      token: state.token,
      user: state.user,
      sessionId: state.sessionId,
      messages: state.messages,
      lastResult: state.lastResult,
      queryCount: state.queryCount,
      hasStarted: state.hasStarted,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch {
      try {
        const slim = {
          ...payload,
          lastResult: compactResult(state.lastResult),
          messages: state.messages.map((message) => ({
            ...message,
            metadata: {
              ...(message.metadata || {}),
              charts: [],
              result: compactResult(message.metadata?.result),
            },
          })),
        };
        localStorage.setItem(STORAGE_KEY, JSON.stringify(slim));
      } catch {
        /* keep in-memory history even if storage is full */
      }
    }
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

  function wrapMarkdownTables(html) {
    const holder = document.createElement("div");
    holder.innerHTML = html;
    holder.querySelectorAll("table").forEach((table) => {
      if (table.parentElement?.classList.contains("table-wrap")) return;
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      table.replaceWith(wrap);
      wrap.appendChild(table);
    });
    return holder.innerHTML;
  }

  function renderMarkdown(text) {
    const raw = window.marked ? marked.parse(String(text || "")) : `<p>${escapeHtml(text)}</p>`;
    const safe = window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
    return wrapMarkdownTables(safe);
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

  function buildMessageEl(message) {
    const wrap = document.createElement("div");
    wrap.className = `message ${message.role}`;
    if (message.role === "user") {
      wrap.innerHTML = `<div>${escapeHtml(message.content)}</div>`;
      return wrap;
    }

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
    mountResults(wrap, message.metadata?.result);
    (message.metadata?.charts || []).forEach((chart, index) => {
      if (chart.title) {
        const title = document.createElement("h4");
        title.className = "chart-title";
        title.textContent = chart.title;
        wrap.appendChild(title);
      }
      const chartEl = document.createElement("div");
      chartEl.className = "chart";
      chartEl.dataset.chartIndex = String(index);
      wrap.appendChild(chartEl);
      requestAnimationFrame(() => renderPlotly(chartEl, chart.chart_json, { hideTitle: true }));
    });
    return wrap;
  }

  function renderMessages() {
    const root = el("messages");
    root.innerHTML = "";
    state.messages.forEach((message) => {
      root.appendChild(buildMessageEl(message));
    });
  }

  function appendMessageEl(message) {
    const root = el("messages");
    root.appendChild(buildMessageEl(message));
    const scroller = document.querySelector(".main-scroll");
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }

  function renderPlotly(target, chartJson, options = {}) {
    if (!window.Plotly || !chartJson) return;
    try {
      const spec = typeof chartJson === "string" ? JSON.parse(chartJson) : chartJson;
      const traces = (spec.data || []).map((trace) => ({ ...trace }));
      const isPie = traces.some((trace) => trace.type === "pie");
      traces.forEach((trace) => {
        if (trace.type === "pie") {
          trace.textinfo = "percent";
          trace.textposition = "inside";
          trace.insidetextorientation = "horizontal";
          trace.automargin = true;
          trace.hole = trace.hole || 0;
          trace.domain = { x: [0.15, 0.85], y: [0.28, 1] };
        }
      });

      const baseLayout = spec.layout || {};
      const layout = {
        ...baseLayout,
        autosize: true,
        height: isPie ? 640 : Math.max(baseLayout.height || 0, 480),
        title: options.hideTitle ? null : baseLayout.title,
        margin: isPie
          ? { t: 8, r: 16, b: 180, l: 16, pad: 4 }
          : Object.assign({ t: 48, r: 32, b: 72, l: 64 }, baseLayout.margin || {}),
        legend: isPie
          ? {
              orientation: "h",
              y: -0.08,
              x: 0.5,
              xanchor: "center",
              yanchor: "top",
              font: { size: 11 },
              itemwidth: 80,
              tracegroupgap: 6,
              bgcolor: "rgba(255,255,255,0.92)",
            }
          : baseLayout.legend,
        showlegend: true,
      };

      target.style.height = `${layout.height}px`;
      Plotly.react(target, traces, layout, { responsive: true, displaylogo: false });
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

  function compactResult(result) {
    if (!result) return null;
    return {
      query_result: result.query_result,
      sql_query: result.sql_query,
      plan: result.plan,
      table_title: result.table_title,
      waiting_for_user: result.waiting_for_user,
      question_to_user: result.question_to_user,
      error: result.error,
      requested_chart_type: result.requested_chart_type,
      charts: result.charts || [],
    };
  }

  function hasResultOutput(result) {
    if (!result) return false;
    return asRows(result.query_result).length > 0 || Boolean(result.sql_query) || Boolean(result.plan);
  }

  function renderPivot(panel) {
    const result = panel._result;
    const rows = coerceRows(asRows(result?.query_result));
    const indexCols = selectedValues(qs(panel, ".pivot-rows"));
    const columnCols = selectedValues(qs(panel, ".pivot-cols"));
    const valueCol = qs(panel, ".pivot-value").value;
    const aggFunc = qs(panel, ".pivot-agg").value;
    const pivotEl = qs(panel, ".pivot-table");
    if (!indexCols.length || !valueCol) {
      pivotEl.innerHTML = `<p class="muted">Please select at least one row field.</p>`;
      panel._pivotRows = [];
      return;
    }
    try {
      panel._pivotRows = pivotTable(rows, indexCols, columnCols, valueCol, aggFunc);
      pivotEl.innerHTML = tableHtml(panel._pivotRows);
    } catch (error) {
      pivotEl.innerHTML = `<p class="muted">Failed to create pivot table: ${escapeHtml(error.message)}</p>`;
    }
  }

  function setupPivot(panel, result) {
    const rows = coerceRows(asRows(result?.query_result));
    const types = columnTypes(rows);
    fillSelect(qs(panel, ".pivot-rows"), types.all, types.all[0] ? [types.all[0]] : []);
    fillSelect(qs(panel, ".pivot-cols"), types.all.filter((col) => col !== types.all[0]));
    fillSelect(qs(panel, ".pivot-value"), types.numeric, types.numeric[0]);
    renderPivot(panel);
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

  function renderGraph(panel) {
    const result = panel._result;
    const source = prepareChartRows(asRows(result?.query_result));
    let rows = source;
    const filterCol = qs(panel, ".graph-filter-col").value;
    if (filterCol && filterCol !== "None") {
      const selected = new Set(selectedValues(qs(panel, ".graph-filter-values")));
      rows = rows.filter((row) => selected.has(String(row[filterCol])));
    }

    const types = columnTypes(rows);
    const xCol = qs(panel, ".graph-x").value;
    const yCol = qs(panel, ".graph-y").value;
    const chartEl = qs(panel, ".graph-chart");
    if (!xCol || !yCol) {
      chartEl.innerHTML = `<p class="muted">No numeric column found for chart.</p>`;
      return;
    }

    rows = rows.filter((row) => row[xCol] != null && row[yCol] != null);
    if (!rows.length) {
      chartEl.innerHTML = `<p class="muted">No rows available for selected chart columns.</p>`;
      return;
    }

    rows = [...rows].sort((a, b) => Number(b[yCol] || 0) - Number(a[yCol] || 0));
    const topn = qs(panel, ".graph-topn");
    const maxN = Math.min(100, rows.length);
    topn.max = String(maxN);
    if (Number(topn.value) > maxN) topn.value = String(maxN);
    qs(panel, ".graph-topn-value").textContent = topn.value;
    const topN = rows.length === 1 ? 1 : Number(topn.value);
    const chartRows = rows.slice(0, topN);
    const chartTypeSelect = qs(panel, ".graph-type").value;
    if (chartTypeSelect === "Horizontal Bar") {
      chartRows.reverse();
    }

    let chartType = chartTypeSelect;
    if (chartType === "Auto") chartType = chartRows.length > 15 ? "Horizontal Bar" : "Bar";
    renderPlotly(chartEl, buildChartFigure(chartType, chartRows, xCol, yCol));
    qs(panel, ".graph-data").innerHTML = tableHtml(chartRows);
    qs(panel, ".graph-meta").textContent = JSON.stringify({
      numeric_columns: types.numeric,
      non_numeric_columns: types.nonNumeric,
      selected_x: xCol,
      selected_y: yCol,
      rows_after_null_filter: chartRows.length,
    }, null, 2);
  }

  function setupGraph(panel, result) {
    const rows = prepareChartRows(asRows(result?.query_result));
    const types = columnTypes(rows);
    const filterCols = types.nonNumeric.filter((col) => {
      const count = uniqueValues(rows, col).length;
      return count > 1 && count <= 20;
    });
    fillSelect(qs(panel, ".graph-filter-col"), ["None", ...filterCols], "None");
    fillSelect(qs(panel, ".graph-x"), types.all, defaultX(types.nonNumeric, types.all));
    fillSelect(qs(panel, ".graph-y"), types.numeric, types.numeric[0]);
    const requested = CHART_TYPE_LABELS[result?.requested_chart_type] || "Auto";
    const typeSelect = qs(panel, ".graph-type");
    typeSelect.value = [...typeSelect.options].some((opt) => opt.value === requested) ? requested : "Auto";
    qs(panel, ".graph-topn").value = String(Math.min(20, rows.length || 1));
    updateFilterValues(panel);
    renderGraph(panel);
  }

  function updateFilterValues(panel) {
    const result = panel._result;
    const rows = prepareChartRows(asRows(result?.query_result));
    const col = qs(panel, ".graph-filter-col").value;
    const wrap = qs(panel, ".graph-filter-values-wrap");
    if (!col || col === "None") {
      wrap.classList.add("hidden");
      return;
    }
    wrap.classList.remove("hidden");
    const values = uniqueValues(rows, col).map(String).sort();
    fillSelect(qs(panel, ".graph-filter-values"), values, values);
  }

  function fillResultsPanel(panel, result) {
    panel._result = result;
    const rows = coerceRows(asRows(result?.query_result));
    qs(panel, ".table-title").textContent = result.table_title || "Extracted Table";
    const tableEl = qs(panel, ".result-table");
    if (result.waiting_for_user) {
      tableEl.innerHTML = `<p class="muted">${escapeHtml(result.question_to_user || "")}</p>`;
    } else if (result.error) {
      tableEl.innerHTML = `<p class="muted">${escapeHtml(result.error)}</p>`;
    } else {
      tableEl.innerHTML = tableHtml(rows);
      try { setupPivot(panel, result); } catch { /* table still visible */ }
    }
    qs(panel, ".sql-code").textContent = result.sql_query || "No SQL generated yet.";
    qs(panel, ".plan-text").textContent = result.plan || "No plan available.";
    panel._graphReady = false;
  }

  function mountResults(wrap, result) {
    if (!hasResultOutput(result)) return;
    const template = el("results-template");
    if (!template) return;
    const panel = template.content.firstElementChild.cloneNode(true);
    wrap.appendChild(panel);
    try {
      fillResultsPanel(panel, result);
    } catch {
      qs(panel, ".result-table").innerHTML = tableHtml(coerceRows(asRows(result.query_result)));
    }
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
    appendMessageEl(state.messages[state.messages.length - 1]);
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
        {
          charts: result.charts || [],
          result: compactResult(result),
        },
        result.assistant_message_id,
      );
      thinking.remove();
      appendMessageEl(state.messages[state.messages.length - 1]);
      saveLocal();
    } catch (error) {
      thinking.remove();
      addMessage("assistant", `Unexpected error: ${error.message}`, "error");
      appendMessageEl(state.messages[state.messages.length - 1]);
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
      const panel = event.target.closest(".results-panel");
      if (panel) {
        const tab = event.target.closest(".tab");
        if (tab) {
          panel.querySelectorAll(".tab").forEach((btn) => btn.classList.toggle("active", btn === tab));
          panel.querySelectorAll(".tab-panel").forEach((item) => {
            item.classList.toggle("hidden", item.dataset.panel !== tab.dataset.tab);
          });
          if (tab.dataset.tab === "graph") {
            if (!panel._graphReady) {
              try { setupGraph(panel, panel._result); } catch { /* ignore */ }
              panel._graphReady = true;
            } else {
              renderGraph(panel);
            }
          }
          return;
        }
        if (event.target.closest(".table-download")) {
          downloadText("query_result.csv", toCsv(coerceRows(asRows(panel._result?.query_result))), "text/csv");
          return;
        }
        if (event.target.closest(".sql-download")) {
          downloadText("query.sql", panel._result?.sql_query || "", "text/plain");
          return;
        }
        if (event.target.closest(".pivot-download")) {
          downloadText("pivot_result.csv", toCsv(panel._pivotRows || []), "text/csv");
          return;
        }
      }

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

    el("messages").addEventListener("change", (event) => {
      const panel = event.target.closest(".results-panel");
      if (!panel) return;
      if (event.target.matches(".pivot-rows, .pivot-cols, .pivot-value, .pivot-agg")) {
        renderPivot(panel);
      }
      if (event.target.matches(".graph-filter-col")) {
        updateFilterValues(panel);
        renderGraph(panel);
      }
      if (event.target.matches(".graph-filter-values, .graph-x, .graph-y, .graph-type")) {
        renderGraph(panel);
      }
    });

    el("messages").addEventListener("input", (event) => {
      const panel = event.target.closest(".results-panel");
      if (panel && event.target.matches(".graph-topn")) renderGraph(panel);
    });

    el("sidebar-toggle").addEventListener("click", () => el("sidebar").classList.toggle("open"));
  }

  async function init() {
    bindEvents();
    loadLocal();
    renderAuth();
    renderMessages();
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
