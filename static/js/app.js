// Stop row-tap from bubbling from inner controls (links, buttons, inputs)
document.addEventListener(
  "click",
  function (e) {
    const nestedControl = e.target.closest(".js-no-rowtap");
    const htmxControl = e.target.closest("[hx-get], [hx-post], [hx-put], [hx-patch], [hx-delete]");
    if (nestedControl && !htmxControl) e.stopPropagation();
  },
  true
);

  // Dark mode toggle. Defaults to the OS preference (no data-bs-theme
  // attribute at all) until the user explicitly picks one, then that
  // choice is remembered per-browser and applied before first paint by
  // the inline script in base.html.
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-theme-toggle]");
    if (!btn) return;

    const root = document.documentElement;
    const current = root.getAttribute("data-bs-theme");
    const systemPrefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const currentlyDark = current ? current === "dark" : systemPrefersDark;
    const next = currentlyDark ? "light" : "dark";

    root.setAttribute("data-bs-theme", next);
    try {
      localStorage.setItem("prepapp:theme", next);
    } catch (err) {
      // Private browsing / blocked storage: the toggle still works for this page view.
    }
  });

  // Django requires a CSRF token on HTMX POST requests such as task tap/claim.
  document.body.addEventListener("htmx:configRequest", function (event) {
    const csrfInput = document.querySelector("[name=csrfmiddlewaretoken]");
    if (csrfInput) {
      event.detail.headers["X-CSRFToken"] = csrfInput.value;
    }
  });
  
// Confirm modal controller (works for both builder-form actions and direct POST actions)
document.addEventListener("DOMContentLoaded", function () {
  const modalEl = document.getElementById("confirmModal");
  if (!modalEl) return;

  modalEl.addEventListener("show.bs.modal", function (event) {
    const trigger = event.relatedTarget;
    if (!trigger) return;

    const title = trigger.getAttribute("data-confirm-title") || "Confirm";
    const body = trigger.getAttribute("data-confirm-body") || "Are you sure?";
    const submitText = trigger.getAttribute("data-confirm-submit") || "Confirm";

    const postUrl = trigger.getAttribute("data-confirm-post");
    const formId = trigger.getAttribute("data-confirm-form");
    const actionValue = trigger.getAttribute("data-confirm-action");

    document.getElementById("confirmModalTitle").textContent = title;
    document.getElementById("confirmModalBody").textContent = body;
    document.getElementById("confirmModalSubmit").textContent = submitText;

    const modalForm = document.getElementById("confirmModalForm");

    if (postUrl) {
      modalForm.setAttribute("action", postUrl);
      modalForm.onsubmit = null;
      return;
    }

    if (formId && actionValue) {
      modalForm.setAttribute("action", "#");
      modalForm.onsubmit = function (e) {
        e.preventDefault();
        const form = document.getElementById(formId);
        const hidden = document.getElementById("builder-action");
        if (hidden) hidden.value = actionValue;
        form.submit();
      };
    }
  });
});

  // List/Cards view toggle for the task groups on the Builder and Sheet.
  // Preference is per-device (localStorage), defaulting to list.
  (function () {
    const STORAGE_KEY = "prepapp:taskView";

    function applyView(view) {
      document.querySelectorAll("[data-task-view-container]").forEach(function (el) {
        if (view === "cards") {
          el.setAttribute("data-view", "cards");
        } else {
          el.removeAttribute("data-view");
        }
      });
      document.querySelectorAll("[data-view-btn]").forEach(function (btn) {
        const pressed = btn.getAttribute("data-view-btn") === view;
        btn.setAttribute("aria-pressed", pressed ? "true" : "false");
        btn.classList.toggle("btn-secondary", pressed);
        btn.classList.toggle("btn-outline-secondary", !pressed);
      });
    }

    document.addEventListener("DOMContentLoaded", function () {
      let saved = "list";
      try {
        saved = localStorage.getItem(STORAGE_KEY) || "list";
      } catch (e) {
        // Private browsing / blocked storage: fall back to the default view.
      }
      applyView(saved);
    });

    document.addEventListener("click", function (e) {
      const btn = e.target.closest("[data-view-btn]");
      if (!btn) return;
      const view = btn.getAttribute("data-view-btn");
      applyView(view);
      try {
        localStorage.setItem(STORAGE_KEY, view);
      } catch (e) {
        // Ignore storage failures — the toggle still works for this view.
      }
    });
  })();

  // Recipe ingredient scaling: a quick multiplier next to the recipe title.
  // Purely a display transform (nothing is saved) — it only rescales the
  // leading quantity of each ingredient line (the app's own convention,
  // e.g. "300 g butter"), never a number anywhere else in the line, so a
  // stray digit inside an ingredient name (free text can contain anything)
  // is never mistaken for a quantity. Lines with no leading number (e.g.
  // "Salt to taste") are left untouched.
  (function () {
    const LEADING_RANGE = /^(\s*)(\d+(?:\.\d+)?)(\s*-\s*)(\d+(?:\.\d+)?)(.*)$/;
    const LEADING_QUANTITY = /^(\s*)(\d+\s*\/\s*\d+|\d+(?:\.\d+)?)(.*)$/;

    function formatScaled(value) {
      return String(Math.round(value * 100) / 100);
    }

    function scaleQuantity(quantity, multiplier) {
      if (quantity.indexOf("/") !== -1) {
        const parts = quantity.split("/");
        const numerator = parseFloat(parts[0]);
        const denominator = parseFloat(parts[1]);
        if (!denominator) return null;
        return (numerator / denominator) * multiplier;
      }
      return parseFloat(quantity) * multiplier;
    }

    function scaleLine(text, multiplier) {
      // At 1x, always show the exact original text — skip parsing entirely
      // so a fraction like "1/2" never gets rewritten into "0.5" on revert.
      if (multiplier === 1) return text;

      // "2-3 cloves garlic" style ranges: scale both ends, keep the dash.
      const rangeMatch = text.match(LEADING_RANGE);
      if (rangeMatch) {
        const [, leading, lo, sep, hi, rest] = rangeMatch;
        const loValue = scaleQuantity(lo, multiplier);
        const hiValue = scaleQuantity(hi, multiplier);
        if (loValue !== null && hiValue !== null && isFinite(loValue) && isFinite(hiValue)) {
          return leading + formatScaled(loValue) + sep + formatScaled(hiValue) + rest;
        }
      }

      const match = text.match(LEADING_QUANTITY);
      if (!match) return text;
      const [, leading, quantity, rest] = match;

      const value = scaleQuantity(quantity, multiplier);
      if (value === null || !isFinite(value)) return text;

      return leading + formatScaled(value) + rest;
    }

    document.addEventListener("change", function (e) {
      const select = e.target.closest("#recipe-scale");
      if (!select) return;

      const multiplier = parseFloat(select.value) || 1;
      document.querySelectorAll("[data-base-text]").forEach(function (el) {
        el.textContent = scaleLine(el.dataset.baseText, multiplier);
      });

      const note = document.getElementById("recipe-scale-note");
      if (note) {
        note.textContent = multiplier === 1 ? "" : `(scaled ×${multiplier})`;
      }
    });
  })();

  // Dynamic formset "+" button: clones a hidden <template> row (Django's
  // {{ formset.empty_form }}, using its __prefix__ placeholder) and bumps
  // TOTAL_FORMS. Works for any formset via data-formset-* attributes.
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-formset-add]");
    if (!btn) return;

    const container = document.getElementById(btn.getAttribute("data-formset-add"));
    const template = document.getElementById(btn.getAttribute("data-formset-template"));
    const prefix = btn.getAttribute("data-formset-prefix");
    const totalForms = document.getElementById(`id_${prefix}-TOTAL_FORMS`);
    if (!container || !template || !totalForms) return;

    const formIndex = parseInt(totalForms.value, 10);
    const html = template.innerHTML.replace(/__prefix__/g, formIndex);
    const wrapper = document.createElement("div");
    wrapper.innerHTML = html.trim();
    container.appendChild(wrapper.firstElementChild);
    totalForms.value = formIndex + 1;
  });
