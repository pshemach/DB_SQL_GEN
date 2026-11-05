(() => {
  const COLORS = ["#0f766e", "#0d9488", "#14b8a6", "#f59e0b", "#b91c1c", "#334155"];
  const MAX_POINTS = 30;
  const observers = new WeakMap();
  const pending = new WeakMap();

  function rowsOf(widget) {
    return Array.isArray(widget?.last_rows) ? widget.last_rows.slice(0, MAX_POINTS) : [];
  }

  function chartOf(widget) {
    return widget?.chart || {};
  }

  function values(rows, column) {
    return rows.map((row) => {
      const value = row?.[column];
      if (value == null || value === "") return null;
      const num = Number(value);
      return Number.isFinite(num) ? num : value;
    });
  }

  function labels(rows, column) {
    return rows.map((row) => {
      const value = row?.[column];
      return value == null ? "" : String(value);
    });
  }

  function hasSize(target) {
    return Boolean(target && target.clientWidth >= 80 && target.clientHeight >= 80);
  }

  function baseOption(title) {
    return {
      color: COLORS,
      animationDuration: 280,
      tooltip: { trigger: "axis" },
      grid: { left: 16, right: 16, top: 28, bottom: 8, containLabel: true },
      title: title ? { text: title, show: false } : undefined,
    };
  }

  function optionFromWidget(widget) {
    const rows = rowsOf(widget);
    const chart = chartOf(widget);
    const type = chart.chart_type || widget.chart_type || widget.type;
    if (!rows.length || type === "kpi" || type === "table" || type === "none") return null;

    const xCol = chart.x_column;
    const yCol = chart.y_column;
    const option = baseOption(widget.title);
    const xLabels = xCol ? labels(rows, xCol) : rows.map((_, index) => String(index + 1));
    const yValues = yCol ? values(rows, yCol) : [];

    if (type === "pie") {
      option.tooltip = { trigger: "item" };
      option.series = [{
        type: "pie",
        radius: ["28%", "62%"],
        data: rows.map((row, index) => ({
          name: xLabels[index] || `Row ${index + 1}`,
          value: Number(yValues[index]) || 0,
        })),
      }];
      return option;
    }

    if (type === "scatter") {
      option.xAxis = { type: "value", name: xCol || "" };
      option.yAxis = { type: "value", name: yCol || "" };
      option.series = [{
        type: "scatter",
        data: rows.map((row) => [Number(row[xCol]) || 0, Number(row[yCol]) || 0]),
      }];
      return option;
    }

    if (type === "horizontal_bar") {
      option.tooltip = { trigger: "axis", axisPointer: { type: "shadow" } };
      option.xAxis = { type: "value", name: yCol || "" };
      option.yAxis = { type: "category", data: xLabels, inverse: true };
      option.series = [{ type: "bar", data: yValues, name: yCol || widget.title }];
      return option;
    }

    option.xAxis = { type: "category", data: xLabels, axisLabel: { rotate: xLabels.length > 8 ? 30 : 0 } };
    option.yAxis = { type: "value", name: yCol || "" };
    option.series = [{
      type: type === "line" ? "line" : "bar",
      data: yValues,
      name: yCol || widget.title,
      smooth: type === "line",
    }];
    return option;
  }

  function watch(target) {
    if (!window.ResizeObserver || observers.has(target)) return;
    const observer = new ResizeObserver(() => {
      if (!hasSize(target)) return;
      const widget = target._widget;
      const chart = window.echarts?.getInstanceByDom(target);
      const next = { w: target.clientWidth, h: target.clientHeight };
      const prev = target._chartSize || { w: 0, h: 0 };
      const jumped = Math.abs(next.w - prev.w) > 40 || Math.abs(next.h - prev.h) > 40;
      target._chartSize = next;
      if (!chart && widget) {
        paint(target, widget);
        return;
      }
      if (chart && jumped && widget) {
        chart.dispose();
        paint(target, widget);
        return;
      }
      chart?.resize({ width: next.w, height: next.h });
    });
    observer.observe(target);
    observers.set(target, observer);
  }

  function paint(target, widget) {
    if (!window.echarts || !target) return null;
    const option = optionFromWidget(widget);
    let chart = window.echarts.getInstanceByDom(target);
    if (!chart) {
      chart = window.echarts.init(target, null, {
        width: target.clientWidth,
        height: target.clientHeight,
      });
    }
    if (!option) {
      chart.clear();
      return chart;
    }
    chart.setOption(option, true);
    chart.resize({
      width: target.clientWidth,
      height: target.clientHeight,
    });
    return chart;
  }

  function render(target, widget) {
    if (!window.echarts || !target) return null;
    target._widget = widget;
    watch(target);
    if (!hasSize(target)) {
      if (!pending.has(target)) {
        pending.set(target, true);
        window.setTimeout(() => {
          pending.delete(target);
          if (target.isConnected) render(target, target._widget || widget);
        }, 80);
      }
      return window.echarts.getInstanceByDom(target);
    }
    return paint(target, widget);
  }

  function resize(target) {
    if (!window.echarts || !target) return;
    if (!hasSize(target)) return;
    const chart = window.echarts.getInstanceByDom(target);
    if (chart) {
      chart.resize({
        width: target.clientWidth,
        height: target.clientHeight,
      });
      return;
    }
    if (target._widget) paint(target, target._widget);
  }

  function dispose(target) {
    if (!target || !window.echarts) return;
    observers.get(target)?.disconnect();
    observers.delete(target);
    pending.delete(target);
    window.echarts.getInstanceByDom(target)?.dispose();
  }

  window.EVisionCharts = { optionFromWidget, render, resize, dispose };
})();
