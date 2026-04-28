document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-backtest-form]");
  if (!form) {
    return;
  }

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
});
