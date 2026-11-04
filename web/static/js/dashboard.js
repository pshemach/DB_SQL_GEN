(() => {
  const CHART_TYPES = ["bar", "horizontal_bar", "line", "pie", "scatter"];
  const dash = {
    current: null,
    list: [],
    grid: null,
    charts: new Map(),
    composing: false,
    saveTimer: null,
  };

  if (window.GridStack) {
    window.GridStack.renderCB = (contentEl) => {
      if (contentEl) contentEl.replaceChildren();
    };
  }

  const el = (id) => document.getElementById(id);
  const app = () => window.EVisionApp || {};

  function escapeHtml(value) {
    if (app().escapeHtml) return app().escapeHtml(value);
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toast(message, type) {
    if (app().toast) return app().toast(message, type);
  }

  async function api(path, options) {
    if (!app().api) throw new Error("App is not ready.");
    return app().api(path, options);
  }

  function formatNumber(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return value == null ? "—" : String(value);
    if (Math.abs(num) >= 1000) return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return String(Number(num.toFixed(2)));
  }

  function tableHtml(rows) {
    if (!rows?.length) return `<p class="tile-empty">No rows.</p>`;
    const columns = Object.keys(rows[0]);
    const head = columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("");
    const body = rows.slice(0, 50).map((row) => (
      `<tr>${columns.map((col) => `<td>${escapeHtml(row[col])}</td>`).join("")}</tr>`
    )).join("");
    return `<div class="tile-table"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function setStatus(text) {
    const status = el("dashboard-status");
    if (!status) return;
    status.textContent = text || "";
    status.classList.toggle("hidden", !text);
  }

  function setBusy(busy) {
    dash.composing = busy;
    ["dashboard-generate-btn", "dashboard-add-btn", "dashboard-refresh-btn", "dashboard-save-btn"].forEach((id) => {
      if (el(id)) el(id).disabled = busy;
    });
  }

  function resizeCharts() {
    document.querySelectorAll("#dashboard-grid .tile-chart").forEach((node) => {
      window.EVisionCharts?.resize(node);
    });
  }

  function scheduleResize() {
    [0, 50, 150, 400].forEach((ms) => window.setTimeout(resizeCharts, ms));
  }

  function ensureGrid() {
    if (dash.grid) return dash.grid;
    if (!window.GridStack) {
      toast("GridStack failed to load. Refresh the page.", "error");
      return null;
    }
    window.GridStack.renderCB = (contentEl) => {
      if (contentEl) contentEl.replaceChildren();
    };
    dash.grid = window.GridStack.init({
      column: 12,
      cellHeight: 80,
      margin: 8,
      float: true,
      disableOneColumnMode: false,
    }, el("dashboard-grid"));
    dash.grid.on("change", () => {
      scheduleSave();
      scheduleResize();
    });
    dash.grid.on("resizestop", () => scheduleResize());
    window.addEventListener("resize", () => scheduleResize());
    return dash.grid;
  }

  function currentLayout() {
    if (!dash.grid) return dash.current?.layout || [];
    return dash.grid.save(false).map((item) => ({
      id: item.id,
      x: item.x,
      y: item.y,
      w: item.w,
      h: item.h,
    }));
  }

  function applyCurrent(record) {
    dash.current = record;
    el("dashboard-title").value = record?.title || "";
    el("dashboard-requirement").value = record?.requirement_text || el("dashboard-requirement").value;
    el("dashboard-select").value = record?.dashboard_id || "";
    el("dashboard-add-form").classList.toggle("hidden", !record?.dashboard_id);
    renderGrid(record?.widgets || [], record?.layout || []);
  }

  function renderList() {
    const select = el("dashboard-select");
    const currentId = dash.current?.dashboard_id || "";
    const options = [`<option value="">New dashboard</option>`].concat(
      dash.list.map((item) => (
        `<option value="${escapeHtml(item.dashboard_id)}" ${item.dashboard_id === currentId ? "selected" : ""}>${escapeHtml(item.title)}</option>`
      ))
    );
    select.innerHTML = options.join("");
    if (currentId) select.value = currentId;
  }

    function widgetById(widgetId) {
      return (dash.current?.widgets || []).find((item) => item.widget_id === widgetId);
    }

    function gridItemById(widgetId) {
      return (dash.grid?.getGridItems() || []).find((item) => {
        const nodeId = item.gridstackNode?.id || item.getAttribute("gs-id");
        return nodeId === widgetId || Boolean(item.querySelector(`[data-widget-id="${widgetId}"]`));
      });
    }

    function widgetSize(widget, pos) {
      return {
        w: pos.w || (widget.type === "kpi" ? 3 : widget.type === "table" ? 12 : 6),
        h: pos.h || (widget.type === "kpi" ? 3 : 5),
      };
    }

    function needsChart(widget) {
      const type = widget?.chart?.chart_type || widget?.type;
      return Boolean(
        widget
        && !widget.last_error
        && widget.status !== "pending"
        && type !== "kpi"
        && type !== "table"
        && (widget.last_rows || []).length
      );
    }

    function tileBodyReady(itemEl) {
      const body = itemEl?.querySelector("[data-body]");
      return Boolean(body && body.clientWidth >= 80 && body.clientHeight >= 80);
    }

    function queueChartDraw(itemEl, widget) {
      let frames = 0;
      const draw = () => {
        if (!itemEl?.isConnected) return;
        if (tileBodyReady(itemEl) || frames >= 30) {
          fillTile(itemEl, widget);
          return;
        }
        frames += 1;
        requestAnimationFrame(draw);
      };
      requestAnimationFrame(draw);
    }

    function mountTile(itemEl, widget) {
      const host = itemEl.querySelector(".grid-stack-item-content") || itemEl;
      host.replaceChildren();
      host.innerHTML = tileHtml(widget);
      if (needsChart(widget)) {
        const body = itemEl.querySelector("[data-body]");
        if (body) body.innerHTML = `<p class="tile-empty">Loading chart...</p>`;
        queueChartDraw(itemEl, widget);
        return;
      }
      fillTile(itemEl, widget);
    }

    function addTile(widget, pos) {
      const grid = ensureGrid();
      if (!grid) return null;
      const size = widgetSize(widget, pos || {});
      const spec = {
        id: widget.widget_id,
        w: size.w,
        h: size.h,
      };
      if (Number.isInteger(pos?.x) && Number.isInteger(pos?.y)) {
        spec.x = pos.x;
        spec.y = pos.y;
      }
      const itemEl = grid.addWidget(spec);
      if (!itemEl) return null;
      mountTile(itemEl, widget);
      return itemEl;
    }

  function tileHtml(widget) {
    const chartType = widget.chart?.chart_type || widget.chart_type || widget.type || "bar";
    const typeOptions = CHART_TYPES.map((type) => (
      `<option value="${type}" ${type === chartType ? "selected" : ""}>${type.replaceAll("_", " ")}</option>`
    )).join("");
    const showChartSelect = widget.type !== "kpi" && widget.type !== "table";
    return `
      <div class="dashboard-tile" data-widget-id="${escapeHtml(widget.widget_id)}">
        <header>
          <h3 title="${escapeHtml(widget.title || "Widget")}">${escapeHtml(widget.title || "Widget")}</h3>
          ${showChartSelect ? `<select data-chart-type>${typeOptions}</select>` : ""}
          <button type="button" class="btn icon-btn" data-action="sql" title="View SQL">SQL</button>
          <button type="button" class="btn icon-btn danger" data-action="remove" title="Remove">✕</button>
        </header>
        <div class="tile-body" data-body></div>
        <pre class="widget-sql hidden" data-sql>${escapeHtml(widget.sql_query || "No SQL yet.")}</pre>
      </div>
    `;
  }

  function fillTile(itemEl, widget) {
    if (!itemEl || !widget) return;
    let body = itemEl.querySelector("[data-body]");
    if (!body) {
      const host = itemEl.querySelector(".grid-stack-item-content") || itemEl;
      host.innerHTML = tileHtml(widget);
      body = itemEl.querySelector("[data-body]");
    }
    if (!body) return;
    const sql = itemEl.querySelector("[data-sql]");
    if (sql) sql.textContent = widget.sql_query || "No SQL yet.";
    const title = itemEl.querySelector("h3");
    if (title) title.textContent = widget.title || "Widget";

    if (widget.last_error) {
      body.innerHTML = `<p class="tile-error">${escapeHtml(widget.last_error)}</p>`;
      return;
    }
    if (widget.status === "pending") {
      body.innerHTML = `<p class="tile-empty">Building this widget...</p>`;
      return;
    }

    const type = widget.chart?.chart_type || widget.type;
    if (type === "kpi") {
      const value = widget.chart?.kpi_value;
      const label = widget.chart?.kpi_column || widget.title || "";
      body.innerHTML = `<div class="tile-kpi"><div class="kpi-value">${escapeHtml(formatNumber(value))}</div><div class="kpi-label">${escapeHtml(label)}</div></div>`;
      return;
    }
    if (type === "table" || !window.EVisionCharts) {
      body.innerHTML = tableHtml(widget.last_rows || []);
      return;
    }
    if (!(widget.last_rows || []).length) {
      body.innerHTML = `<p class="tile-empty">No rows for this widget.</p>`;
      return;
    }
    const oldChart = body.querySelector(".tile-chart");
    if (oldChart) window.EVisionCharts?.dispose(oldChart);
    body.innerHTML = `<div class="tile-chart"></div>`;
    const chartEl = body.querySelector(".tile-chart");
    const item = itemEl.closest(".grid-stack-item") || itemEl;
    if (!tileBodyReady(item) && needsChart(widget)) {
      queueChartDraw(item, widget);
      return;
    }
    const chart = window.EVisionCharts.render(chartEl, widget);
    if (chart) dash.charts.set(widget.widget_id, chart);
  }

  function renderGrid(widgets, layout) {
    const empty = el("dashboard-empty");
    empty.classList.toggle("hidden", Boolean(widgets?.length));
    const grid = ensureGrid();
    if (!grid) return;
    document.querySelectorAll("#dashboard-grid .tile-chart").forEach((node) => {
      window.EVisionCharts?.dispose(node);
    });
    dash.charts.clear();
    grid.removeAll();
    const positions = Object.fromEntries((layout || []).map((item) => [String(item.id), item]));
    (widgets || []).forEach((widget) => addTile(widget, positions[widget.widget_id] || {}));
  }

  function upsertWidget(widget) {
    if (!dash.current) dash.current = { widgets: [], layout: [] };
    const widgets = dash.current.widgets || [];
    const index = widgets.findIndex((item) => item.widget_id === widget.widget_id);
    if (index >= 0) widgets[index] = widget;
    else widgets.push(widget);
    dash.current.widgets = widgets;
    const item = gridItemById(widget.widget_id);
    if (item) {
      const body = item.querySelector("[data-body]");
      if (body) fillTile(item, widget);
      else mountTile(item, widget);
    } else {
      addTile(widget, {});
    }
  }

  async function loadList() {
    const result = await api("/dashboards");
    dash.list = result.dashboards || [];
    renderList();
  }

  async function loadDashboard(dashboardId) {
    if (!dashboardId) {
      resetBoard();
      return;
    }
    const record = await api(`/dashboards/${encodeURIComponent(dashboardId)}`);
    applyCurrent(record);
    renderList();
  }

  function resetBoard() {
    dash.current = null;
    el("dashboard-title").value = "";
    el("dashboard-requirement").value = "";
    el("dashboard-select").value = "";
    el("dashboard-add-form").classList.add("hidden");
    setStatus("");
    renderGrid([], []);
  }

  function scheduleSave() {
    if (dash.composing || !dash.current?.dashboard_id) return;
    clearTimeout(dash.saveTimer);
    dash.saveTimer = setTimeout(() => saveCurrent({ quiet: true }), 700);
  }

  async function saveCurrent({ quiet } = {}) {
    if (!dash.current?.dashboard_id) {
      if (!quiet) toast("Generate a dashboard before saving.", "error");
      return;
    }
    const layout = currentLayout();
    const title = el("dashboard-title").value.trim() || dash.current.title;
    const result = await api(`/dashboards/${encodeURIComponent(dash.current.dashboard_id)}`, {
      method: "PUT",
      body: JSON.stringify({
        title,
        layout,
        widgets: dash.current.widgets,
      }),
    });
    dash.current = result;
    dash.current.layout = layout;
    await loadList();
    if (!quiet) toast("Dashboard saved.", "success");
  }

  async function compose(requirement) {
    setBusy(true);
    setStatus("Planning widgets...");
    try {
      const headers = {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      };
      const token = app().getState?.()?.token;
      if (token) headers.Authorization = `Bearer ${token}`;
      const response = await fetch("/dashboards/compose", {
        method: "POST",
        headers,
        body: JSON.stringify({
          requirement,
          dashboard_id: dash.current?.dashboard_id || null,
        }),
      });
      if (!response.ok) {
        let payload = null;
        try { payload = await response.json(); } catch { payload = null; }
        throw new Error(payload?.detail || payload?.error || `Request failed (${response.status})`);
      }
      const readSse = app().readSse;
      if (!readSse) throw new Error("Streaming is not available.");
      for await (const event of readSse(response)) {
        if (event.type === "status") setStatus(event.text || "Working...");
        else if (event.type === "plan") {
          applyCurrent({
            dashboard_id: dash.current?.dashboard_id,
            title: event.title,
            requirement_text: requirement,
            widgets: event.widgets || [],
            layout: event.layout || [],
          });
          el("dashboard-title").value = event.title || "";
        } else if (event.type === "widget_ready") {
          upsertWidget(event.widget);
        } else if (event.type === "result") {
          applyCurrent(event.payload);
          await loadList();
        } else if (event.type === "error") {
          throw new Error(event.error || "Dashboard compose failed.");
        }
      }
      setStatus("");
      toast("Dashboard ready.", "success");
    } finally {
      setBusy(false);
    }
  }

  async function addWidget(requirement) {
    if (!dash.current?.dashboard_id) {
      toast("Generate a dashboard first.", "error");
      return;
    }
    setBusy(true);
    setStatus("Adding widget...");
    try {
      const result = await api(`/dashboards/${encodeURIComponent(dash.current.dashboard_id)}/widgets`, {
        method: "POST",
        body: JSON.stringify({ requirement }),
      });
      applyCurrent(result);
      await loadList();
      setStatus("");
      toast("Widget added.", "success");
    } finally {
      setBusy(false);
    }
  }

  async function refreshBoard() {
    if (!dash.current?.dashboard_id) {
      toast("Generate or open a dashboard first.", "error");
      return;
    }
    setBusy(true);
    setStatus("Refreshing widgets...");
    try {
      const result = await api(`/dashboards/${encodeURIComponent(dash.current.dashboard_id)}/refresh`, {
        method: "POST",
      });
      applyCurrent(result);
      setStatus("");
      toast("Dashboard refreshed.", "success");
    } finally {
      setBusy(false);
    }
  }

  async function deleteBoard() {
    if (!dash.current?.dashboard_id) {
      resetBoard();
      return;
    }
    if (!window.confirm("Delete this dashboard?")) return;
    await api(`/dashboards/${encodeURIComponent(dash.current.dashboard_id)}`, { method: "DELETE" });
    resetBoard();
    await loadList();
    toast("Dashboard deleted.", "success");
  }

  function bindEvents() {
    el("dashboard-compose-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const requirement = el("dashboard-requirement").value.trim();
      if (!requirement) return toast("Describe the dashboard you need.", "error");
      try {
        await compose(requirement);
      } catch (error) {
        setStatus("");
        toast(error.message, "error");
      }
    });

    el("dashboard-add-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const requirement = el("dashboard-add-input").value.trim();
      if (!requirement) return;
      try {
        await addWidget(requirement);
        el("dashboard-add-input").value = "";
      } catch (error) {
        setStatus("");
        toast(error.message, "error");
      }
    });

    el("dashboard-save-btn")?.addEventListener("click", async () => {
      try { await saveCurrent(); } catch (error) { toast(error.message, "error"); }
    });
    el("dashboard-refresh-btn")?.addEventListener("click", async () => {
      try { await refreshBoard(); } catch (error) { toast(error.message, "error"); }
    });
    el("dashboard-new-btn")?.addEventListener("click", () => resetBoard());
    el("dashboard-delete-btn")?.addEventListener("click", async () => {
      try { await deleteBoard(); } catch (error) { toast(error.message, "error"); }
    });
    el("dashboard-select")?.addEventListener("change", async (event) => {
      try { await loadDashboard(event.target.value); } catch (error) { toast(error.message, "error"); }
    });
    el("dashboard-title")?.addEventListener("change", () => scheduleSave());

    el("dashboard-grid")?.addEventListener("click", async (event) => {
      const tile = event.target.closest(".dashboard-tile");
      if (!tile) return;
      const widgetId = tile.dataset.widgetId;
      const action = event.target.closest("[data-action]")?.dataset.action;
      if (action === "sql") {
        tile.querySelector("[data-sql]")?.classList.toggle("hidden");
        return;
      }
      if (action === "remove") {
        dash.current.widgets = (dash.current.widgets || []).filter((item) => item.widget_id !== widgetId);
        const node = gridItemById(widgetId);
        if (node) dash.grid.removeWidget(node);
        el("dashboard-empty").classList.toggle("hidden", Boolean(dash.current.widgets.length));
        scheduleSave();
      }
    });

    el("dashboard-grid")?.addEventListener("change", (event) => {
      const select = event.target.closest("[data-chart-type]");
      if (!select) return;
      const tile = event.target.closest(".dashboard-tile");
      const widget = widgetById(tile?.dataset.widgetId);
      if (!widget) return;
      widget.chart_type = select.value;
      widget.chart = { ...(widget.chart || {}), chart_type: select.value };
      fillTile(tile, widget);
      scheduleSave();
    });
  }

  window.EVisionDashboard = {
    async show() {
      try {
        await loadList();
        if (!dash.grid) ensureGrid();
        scheduleResize();
      } catch (error) {
        toast(error.message, "error");
      }
    },
    reset: resetBoard,
  };

  document.addEventListener("DOMContentLoaded", bindEvents);
})();
