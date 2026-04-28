const CURRENCY = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const VIEW_WIDTH = 960;
const VIEW_HEIGHT = 320;
const PADDING_X = 48;
const PADDING_Y = 24;

function readJsonScript(element) {
  if (!(element instanceof HTMLScriptElement)) {
    return null;
  }
  try {
    return JSON.parse(element.textContent || "null");
  } catch {
    return null;
  }
}

function formatCurrency(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return CURRENCY.format(value);
}

function joinOrFallback(items) {
  return Array.isArray(items) && items.length ? items.join(", ") : "해당 없음";
}

function setupSelectionSummary(form) {
  const presetScript = form.querySelector("[data-preset-options-json]");
  const costScript = form.querySelector("[data-cost-options-json]");
  const presets = readJsonScript(presetScript) || [];
  const costs = readJsonScript(costScript) || [];
  const presetById = new Map(presets.map((option) => [option.id, option]));
  const costById = new Map(costs.map((option) => [option.id, option]));

  const presetSelect = form.querySelector("[data-preset-select]");
  const costSelect = form.querySelector("[data-cost-select]");
  const presetHelp = form.querySelector("[data-preset-help]");
  const costHelp = form.querySelector("[data-cost-help]");
  const rationale = form.querySelector("[data-selection-rationale]");
  const description = form.querySelector("[data-selection-description]");
  const execution = form.querySelector("[data-selection-execution]");
  const costSummary = form.querySelector("[data-selection-cost]");
  const rationaleDetail = form.querySelector("[data-selection-rationale-detail]");
  const higher = form.querySelector("[data-selection-higher]");
  const lower = form.querySelector("[data-selection-lower]");
  const lookback = form.querySelector("[data-selection-lookback]");
  const risk = form.querySelector("[data-selection-risk]");

  const sync = () => {
    const preset = presetById.get(presetSelect?.value || "");
    const cost = costById.get(costSelect?.value || "");
    if (presetHelp instanceof HTMLElement) {
      presetHelp.textContent = preset ? `${preset.description} · ${preset.lookback_label}` : "";
    }
    if (costHelp instanceof HTMLElement) {
      costHelp.textContent = cost ? `${cost.description} · ${cost.details}` : "";
    }
    if (rationale instanceof HTMLElement) {
      rationale.textContent = preset?.rationale || "";
    }
    if (description instanceof HTMLElement) {
      description.textContent = preset?.description || "";
    }
    if (execution instanceof HTMLElement) {
      execution.textContent = Array.isArray(preset?.execution_notes) ? preset.execution_notes.join(" / ") : "";
    }
    if (costSummary instanceof HTMLElement) {
      costSummary.textContent = cost ? `${cost.description} · ${cost.details}` : "";
    }
    if (rationaleDetail instanceof HTMLElement) {
      rationaleDetail.textContent = preset?.rationale || "";
    }
    if (higher instanceof HTMLElement) {
      higher.textContent = joinOrFallback(preset?.higher_is_better);
    }
    if (lower instanceof HTMLElement) {
      lower.textContent = joinOrFallback(preset?.lower_is_better);
    }
    if (lookback instanceof HTMLElement) {
      lookback.textContent = preset?.lookback_label || "";
    }
    if (risk instanceof HTMLElement) {
      risk.textContent = Array.isArray(preset?.risk_notes) && preset.risk_notes.length ? preset.risk_notes.join(" / ") : "해당 없음";
    }
  };

  presetSelect?.addEventListener("change", sync);
  costSelect?.addEventListener("change", sync);
  sync();
}

function setupChart(card) {
  const frame = card.querySelector("[data-chart-frame]");
  const layer = card.querySelector("[data-chart-layer]");
  const guide = card.querySelector("[data-chart-guide]");
  const scrubber = card.querySelector("[data-chart-scrubber]");
  const dateNode = card.querySelector("[data-readout-date]");
  const netNode = card.querySelector("[data-readout-net]");
  const spyNode = card.querySelector("[data-readout-spy]");
  const grossNode = card.querySelector("[data-readout-gross]");
  const pointsScript = frame?.querySelector("[data-chart-points-json]");
  const points = readJsonScript(pointsScript);
  const netMarker = card.querySelector('[data-marker="net"]');
  const spyMarker = card.querySelector('[data-marker="spy"]');
  const grossMarker = card.querySelector('[data-marker="gross"]');

  if (!(frame instanceof HTMLElement) || !(layer instanceof HTMLElement) || !Array.isArray(points) || !points.length) {
    return;
  }

  const values = points.flatMap((point) => [point.gross_equity, point.net_equity, point.benchmark_equity].filter((value) => typeof value === "number"));
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const usableWidth = VIEW_WIDTH - PADDING_X * 2;
  const usableHeight = VIEW_HEIGHT - PADDING_Y * 2;
  let activeIndex = points.length - 1;

  function pointToPixel(index, value) {
    const rect = frame.getBoundingClientRect();
    const xView = PADDING_X + (usableWidth * index) / Math.max(points.length - 1, 1);
    const yRatio = maxValue === minValue ? 0.5 : (value - minValue) / (maxValue - minValue);
    const yView = VIEW_HEIGHT - PADDING_Y - usableHeight * yRatio;
    return {
      x: (xView / VIEW_WIDTH) * rect.width,
      y: (yView / VIEW_HEIGHT) * rect.height,
    };
  }

  function setMarker(marker, point) {
    if (!(marker instanceof HTMLElement)) {
      return;
    }
    if (!point) {
      marker.hidden = true;
      return;
    }
    marker.hidden = false;
    marker.style.left = `${point.x}px`;
    marker.style.top = `${point.y}px`;
  }

  function renderIndex(index) {
    activeIndex = Math.max(0, Math.min(points.length - 1, index));
    const point = points[activeIndex];
    const rect = frame.getBoundingClientRect();
    const netPixel = pointToPixel(activeIndex, point.net_equity);
    const grossPixel = pointToPixel(activeIndex, point.gross_equity);
    const spyPixel = typeof point.benchmark_equity === "number" ? pointToPixel(activeIndex, point.benchmark_equity) : null;

    if (guide instanceof HTMLElement) {
      guide.hidden = false;
      guide.style.left = `${netPixel.x}px`;
      guide.style.height = `${rect.height}px`;
    }
    if (dateNode instanceof HTMLElement) {
      dateNode.textContent = point.date;
    }
    if (netNode instanceof HTMLElement) {
      netNode.textContent = formatCurrency(point.net_equity);
    }
    if (grossNode instanceof HTMLElement) {
      grossNode.textContent = formatCurrency(point.gross_equity);
    }
    if (spyNode instanceof HTMLElement) {
      spyNode.textContent = typeof point.benchmark_equity === "number" ? formatCurrency(point.benchmark_equity) : "전략 첫 체결 전";
    }
    if (scrubber instanceof HTMLInputElement) {
      const spySummary = typeof point.benchmark_equity === "number" ? `SPY ${formatCurrency(point.benchmark_equity)}` : "SPY 비교선 없음";
      scrubber.setAttribute(
        "aria-valuetext",
        `${point.date}, Net ${formatCurrency(point.net_equity)}, ${spySummary}, Gross ${formatCurrency(point.gross_equity)}`,
      );
    }

    setMarker(netMarker, netPixel);
    setMarker(grossMarker, grossPixel);
    setMarker(spyMarker, spyPixel);

    if (scrubber instanceof HTMLInputElement) {
      scrubber.value = String(activeIndex);
    }
  }

  function indexFromClientX(clientX) {
    const rect = frame.getBoundingClientRect();
    const relative = Math.max(0, Math.min(rect.width, clientX - rect.left));
    return Math.round((relative / Math.max(rect.width, 1)) * Math.max(points.length - 1, 0));
  }

  layer.addEventListener("mousemove", (event) => {
    renderIndex(indexFromClientX(event.clientX));
  });
  layer.addEventListener("mouseenter", (event) => {
    renderIndex(indexFromClientX(event.clientX));
  });
  layer.addEventListener("touchstart", (event) => {
    const touch = event.touches[0];
    if (touch) {
      renderIndex(indexFromClientX(touch.clientX));
    }
  }, { passive: true });
  layer.addEventListener("touchmove", (event) => {
    const touch = event.touches[0];
    if (touch) {
      renderIndex(indexFromClientX(touch.clientX));
    }
  }, { passive: true });

  scrubber?.addEventListener("input", () => {
    renderIndex(Number(scrubber.value));
  });
  window.addEventListener("resize", () => {
    renderIndex(activeIndex);
  });

  renderIndex(activeIndex);
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-backtest-form]");
  if (form instanceof HTMLFormElement) {
    setupSelectionSummary(form);

    const button = form.querySelector("[data-submit-button]");
    const loadingNote = form.querySelector("[data-loading-note]");
    form.addEventListener("submit", () => {
      if (button instanceof HTMLButtonElement) {
        button.disabled = true;
        button.textContent = "계산 중...";
      }
      if (loadingNote instanceof HTMLElement) {
        loadingNote.hidden = false;
      }
    });
  }

  document.querySelectorAll("[data-chart-card]").forEach((card) => {
    if (card instanceof HTMLElement) {
      setupChart(card);
    }
  });
});
