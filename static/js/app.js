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
