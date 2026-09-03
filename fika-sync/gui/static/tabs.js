/**
 * Fika Sync — tab navigation.
 *
 * Deliberately isolated script: it only handles which panel is shown
 * and the active tab's visual state. It doesn't touch data
 * fetch/render — that's still app.js's responsibility, which doesn't
 * need to know anything about this (it uses the same IDs as always,
 * whether they're visible or not).
 *
 * Remembers the last open tab in sessionStorage (not
 * localStorage: it's lost when the browser tab is closed, it doesn't
 * persist "forever" like app data does).
 */
(function () {
  const STORAGE_KEY = "fika-sync:active-tab";
  const tabButtons = Array.from(document.querySelectorAll(".tab[data-tab-target]"));
  const panels = Array.from(document.querySelectorAll(".tab-panel[data-tab]"));

  function activate(tabId, { focus = false } = {}) {
    const validId = panels.some((p) => p.dataset.tab === tabId) ? tabId : panels[0]?.dataset.tab;
    if (!validId) return;

    panels.forEach((panel) => {
      const isActive = panel.dataset.tab === validId;
      panel.hidden = !isActive;
    });

    tabButtons.forEach((btn) => {
      const isActive = btn.dataset.tabTarget === validId;
      btn.classList.toggle("tab--active", isActive);
      btn.setAttribute("aria-selected", isActive ? "true" : "false");
      btn.tabIndex = isActive ? 0 : -1;
      if (isActive && focus) btn.focus();
    });

    try {
      sessionStorage.setItem(STORAGE_KEY, validId);
    } catch {
      // sessionStorage can fail in strict private mode; not critical.
    }

    if (window.location.hash !== `#${validId}`) {
      history.replaceState(null, "", `#${validId}`);
    }
  }

  tabButtons.forEach((btn, index) => {
    btn.addEventListener("click", () => activate(btn.dataset.tabTarget));

    // Left/right arrow navigation between tabs, like any accessible
    // tablist (WAI-ARIA Authoring Practices).
    btn.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      event.preventDefault();
      const delta = event.key === "ArrowRight" ? 1 : -1;
      const nextIndex = (index + delta + tabButtons.length) % tabButtons.length;
      activate(tabButtons[nextIndex].dataset.tabTarget, { focus: true });
    });
  });

  const fromHash = window.location.hash.replace("#", "");
  let initial = fromHash;
  if (!initial) {
    try {
      initial = sessionStorage.getItem(STORAGE_KEY);
    } catch {
      initial = null;
    }
  }
  activate(initial || panels[0]?.dataset.tab);
})();
