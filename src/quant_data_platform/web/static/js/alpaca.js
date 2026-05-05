/* ==========================================================================
   Alpaca Trading — 모달 및 페이지 전용 JS
   ========================================================================== */

// ---------------------------------------------------------------------------
// 모달 열기 / 닫기
// ---------------------------------------------------------------------------

function openOrderModal() {
  const modal = document.getElementById("alpaca-order-modal");
  modal.hidden = false;
  document.body.style.overflow = "hidden";
  // 최초 오픈 시 행이 없으면 기본 3개 추가
  const tbody = document.getElementById("order-rows-body");
  if (tbody && tbody.rows.length === 0) {
    addOrderRow();
    addOrderRow();
    addOrderRow();
  }
}

function closeOrderModal() {
  const modal = document.getElementById("alpaca-order-modal");
  modal.hidden = true;
  document.body.style.overflow = "";
}

// ESC 키로 닫기
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeOrderModal();
});

// 오버레이 클릭으로 닫기
document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "alpaca-order-modal") closeOrderModal();
});

// ---------------------------------------------------------------------------
// 주문 행 관리
// ---------------------------------------------------------------------------

let _rowId = 0;

function addOrderRow(symbol = "", side = null, amount = null) {
  const tbody = document.getElementById("order-rows-body");
  if (!tbody) return;
  const id = ++_rowId;

  const defaultSide = side ?? document.getElementById("order-default-side")?.value ?? "buy";
  const defaultAmount = amount ?? document.getElementById("order-default-amount")?.value ?? "";

  const tr = document.createElement("tr");
  tr.id = `order-row-${id}`;
  tr.innerHTML = `
    <td>
      <input
        type="text"
        class="form-input form-input--sm order-symbol"
        placeholder="AAPL"
        value="${escHtml(symbol.toUpperCase())}"
        style="text-transform:uppercase"
      >
    </td>
    <td>
      <select class="form-select form-select--sm order-side">
        <option value="buy"  ${defaultSide === "buy"  ? "selected" : ""}>매수</option>
        <option value="sell" ${defaultSide === "sell" ? "selected" : ""}>매도</option>
      </select>
    </td>
    <td>
      <input
        type="number"
        class="form-input form-input--sm order-amount"
        min="0"
        step="any"
        placeholder="1000"
        value="${escHtml(defaultAmount)}"
      >
    </td>
    <td>
      <button class="btn btn--ghost btn--xs" type="button" onclick="removeOrderRow(${id})">✕</button>
    </td>
  `;
  tbody.appendChild(tr);
}

function removeOrderRow(id) {
  const row = document.getElementById(`order-row-${id}`);
  if (row) row.remove();
}

function clearOrderRows() {
  const tbody = document.getElementById("order-rows-body");
  if (tbody) tbody.innerHTML = "";
}

function applyDefaultsToAllRows() {
  const side = document.getElementById("order-default-side")?.value;
  const amount = document.getElementById("order-default-amount")?.value;
  const tbody = document.getElementById("order-rows-body");
  if (!tbody) return;
  for (const row of tbody.rows) {
    if (side) {
      const sel = row.querySelector(".order-side");
      if (sel) sel.value = side;
    }
    if (amount) {
      const inp = row.querySelector(".order-amount");
      if (inp && !inp.value) inp.value = amount;
    }
  }
}

function updateOrderTypeHeaders() {
  const type = document.getElementById("order-default-type")?.value;
  const header = document.getElementById("order-amount-header");
  if (header) {
    header.textContent = type === "qty" ? "수량 (주)" : "금액 ($)";
  }
}

// ---------------------------------------------------------------------------
// 종목 붙여넣기
// ---------------------------------------------------------------------------

function pasteSymbols() {
  const raw = document.getElementById("order-paste-symbols")?.value ?? "";
  const symbols = raw
    .split(/[\n,]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  symbols.forEach((sym) => addOrderRow(sym));
  const ta = document.getElementById("order-paste-symbols");
  if (ta) ta.value = "";
}

// ---------------------------------------------------------------------------
// 주문 수집 및 제출
// ---------------------------------------------------------------------------

function collectOrders() {
  const tbody = document.getElementById("order-rows-body");
  if (!tbody) return [];
  const orderType = document.getElementById("order-default-type")?.value ?? "notional";

  const orders = [];
  for (const row of tbody.rows) {
    const symbol = row.querySelector(".order-symbol")?.value?.trim().toUpperCase();
    const side = row.querySelector(".order-side")?.value ?? "buy";
    const amountRaw = row.querySelector(".order-amount")?.value?.trim();
    const amount = parseFloat(amountRaw);

    if (!symbol || !amountRaw || isNaN(amount) || amount <= 0) continue;

    const entry = { symbol, side, order_type: orderType };
    if (orderType === "qty") {
      entry.qty = String(amount);
    } else {
      entry.notional = String(amount);
    }
    orders.push(entry);
  }
  return orders;
}

async function submitOrders() {
  const orders = collectOrders();
  if (orders.length === 0) {
    alert("유효한 주문 항목이 없습니다. Symbol과 금액/수량을 확인해 주세요.");
    return;
  }

  const btn = document.getElementById("order-submit-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "처리 중…";
  }

  try {
    const resp = await fetch("/alpaca/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(orders),
    });
    const data = await resp.json();
    renderOrderResults(data);
  } catch (err) {
    alert(`주문 요청 실패: ${err}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "주문 실행";
    }
  }
}

// ---------------------------------------------------------------------------
// 결과 렌더링
// ---------------------------------------------------------------------------

function renderOrderResults(data) {
  const area = document.getElementById("order-result-area");
  const summary = document.getElementById("order-result-summary");
  const tbody = document.getElementById("order-result-body");
  if (!area || !summary || !tbody) return;

  area.hidden = false;

  if (data.error && !data.results?.length) {
    summary.innerHTML = `<p class="status-state--error">${escHtml(data.error)}</p>`;
    tbody.innerHTML = "";
    return;
  }

  const s = data.summary ?? {};
  const successClass = s.errors === 0 ? "status-filled" : "status-rejected";
  summary.innerHTML = `
    <span class="status-badge ${successClass}">
      총 ${s.total ?? 0}건 — 접수 ${s.submitted ?? 0}건 / 오류 ${s.errors ?? 0}건
    </span>
  `;

  tbody.innerHTML = "";
  for (const r of data.results ?? []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escHtml(r.symbol)}</strong></td>
      <td><span class="side-pill side-pill--${escHtml(r.side)}">${r.side === "buy" ? "매수" : "매도"}</span></td>
      <td>${escHtml(r.qty !== "-" ? r.qty : r.notional)}</td>
      <td class="mono text-sm">${escHtml(r.order_id)}</td>
      <td><span class="status-badge ${escHtml(r.status_class)}">${escHtml(r.status)}</span></td>
      <td class="text-sm text-error">${escHtml(r.error || "")}</td>
    `;
    tbody.appendChild(tr);
  }
}

// ---------------------------------------------------------------------------
// 유틸
// ---------------------------------------------------------------------------

function escHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
