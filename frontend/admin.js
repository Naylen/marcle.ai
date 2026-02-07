(function () {
  "use strict";

  var API_BASE = window.MARCLE_API_BASE || "";
  var ADMIN_URL = API_BASE + "/api/admin/services";
  var TOKEN_STORAGE_KEY = "marcle_admin_token";

  var tokenInput = document.getElementById("admin-token");
  var saveTokenBtn = document.getElementById("save-token-btn");
  var connectBtn = document.getElementById("connect-btn");
  var createForm = document.getElementById("create-form");
  var list = document.getElementById("service-list");
  var errorBox = document.getElementById("admin-error");

  var servicesById = {};

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  function showError(message) {
    if (!message) {
      errorBox.style.display = "none";
      errorBox.textContent = "";
      return;
    }
    errorBox.style.display = "block";
    errorBox.textContent = message;
  }

  function authHeaders() {
    return {
      "Authorization": "Bearer " + tokenInput.value.trim(),
      "Content-Type": "application/json"
    };
  }

  function persistToken() {
    localStorage.setItem(TOKEN_STORAGE_KEY, tokenInput.value.trim());
  }

  function loadStoredToken() {
    var stored = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
    tokenInput.value = stored;
  }

  async function request(url, options) {
    var resp = await fetch(url, options || {});
    if (!resp.ok) {
      var detail = "HTTP " + resp.status;
      try {
        var payload = await resp.json();
        if (payload && payload.detail) {
          detail = payload.detail + " (HTTP " + resp.status + ")";
        }
      } catch (_err) {
        // Ignore JSON parse failure; use status fallback
      }
      throw new Error(detail);
    }
    if (resp.status === 204) return null;
    return await resp.json();
  }

  function getRowValue(row, selector) {
    var el = row.querySelector(selector);
    return el ? el.value.trim() : "";
  }

  function collectServiceFromRow(row, existing) {
    return {
      id: existing.id,
      name: getRowValue(row, "[data-field='name']"),
      group: getRowValue(row, "[data-field='group']"),
      url: getRowValue(row, "[data-field='url']"),
      icon: getRowValue(row, "[data-field='icon']") || null,
      description: getRowValue(row, "[data-field='description']") || null,
      check_type: getRowValue(row, "[data-field='check_type']"),
      enabled: existing.enabled,
      auth_ref: existing.auth_ref || null
    };
  }

  function serviceRowMarkup(svc) {
    var checked = svc.enabled ? "checked" : "";
    var authLabel = "none";
    if (svc.auth_ref && svc.auth_ref.scheme) {
      authLabel = svc.auth_ref.scheme + " / " + (svc.auth_ref.env || "");
      if (svc.auth_ref.scheme === "header") {
        authLabel += " / " + (svc.auth_ref.header_name || "");
      }
    }

    return (
      "<div class='admin-item' data-service-id='" + escapeHtml(svc.id) + "'>" +
        "<div class='admin-inline'><strong>" + escapeHtml(svc.id) + "</strong> · auth_ref: " + escapeHtml(authLabel) + "</div>" +
        "<div class='admin-grid'>" +
          "<div><label class='admin-label'>Name</label><input class='admin-input' data-field='name' value='" + escapeHtml(svc.name) + "'></div>" +
          "<div><label class='admin-label'>Group</label>" +
            "<select class='admin-select' data-field='group'>" +
              "<option value='core'" + (svc.group === "core" ? " selected" : "") + ">core</option>" +
              "<option value='media'" + (svc.group === "media" ? " selected" : "") + ">media</option>" +
              "<option value='automation'" + (svc.group === "automation" ? " selected" : "") + ">automation</option>" +
            "</select>" +
          "</div>" +
          "<div><label class='admin-label'>Check type</label><input class='admin-input' data-field='check_type' value='" + escapeHtml(svc.check_type) + "'></div>" +
          "<div><label class='admin-label'>URL</label><input class='admin-input' data-field='url' value='" + escapeHtml(svc.url) + "'></div>" +
          "<div><label class='admin-label'>Icon</label><input class='admin-input' data-field='icon' value='" + escapeHtml(svc.icon || "") + "'></div>" +
          "<div><label class='admin-label'>Description</label><input class='admin-input' data-field='description' value='" + escapeHtml(svc.description || "") + "'></div>" +
        "</div>" +
        "<div class='admin-actions'>" +
          "<button class='admin-button' type='button' data-action='save'>Save</button>" +
          "<button class='admin-button' type='button' data-action='toggle'>" + (svc.enabled ? "Disable" : "Enable") + "</button>" +
          "<button class='admin-button' type='button' data-action='delete'>Delete</button>" +
        "</div>" +
        "<div class='admin-inline'>enabled: <input type='checkbox' disabled " + checked + "></div>" +
      "</div>"
    );
  }

  function renderServices(services) {
    servicesById = {};
    if (!services || services.length === 0) {
      list.innerHTML = "<div class='admin-item'>No services configured.</div>";
      return;
    }

    services.forEach(function (svc) {
      servicesById[svc.id] = svc;
    });
    list.innerHTML = services.map(serviceRowMarkup).join("");
  }

  async function loadServices() {
    showError("");
    var data = await request(ADMIN_URL, { headers: authHeaders() });
    renderServices(data.services || []);
  }

  function buildServiceFromCreateForm() {
    var formData = new FormData(createForm);
    return {
      id: String(formData.get("id") || "").trim(),
      name: String(formData.get("name") || "").trim(),
      group: String(formData.get("group") || "").trim(),
      url: String(formData.get("url") || "").trim(),
      icon: String(formData.get("icon") || "").trim() || null,
      description: String(formData.get("description") || "").trim() || null,
      check_type: String(formData.get("check_type") || "").trim(),
      enabled: true
    };
  }

  connectBtn.addEventListener("click", async function () {
    try {
      await loadServices();
    } catch (err) {
      showError(err.message);
    }
  });

  saveTokenBtn.addEventListener("click", function () {
    persistToken();
    showError("");
  });

  tokenInput.addEventListener("change", persistToken);

  createForm.addEventListener("submit", async function (evt) {
    evt.preventDefault();
    var service = buildServiceFromCreateForm();
    try {
      await request(ADMIN_URL, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(service)
      });
      createForm.reset();
      await loadServices();
    } catch (err) {
      showError(err.message);
    }
  });

  list.addEventListener("click", async function (evt) {
    var button = evt.target.closest("button[data-action]");
    if (!button) return;

    var row = evt.target.closest("[data-service-id]");
    if (!row) return;

    var serviceId = row.getAttribute("data-service-id");
    var action = button.getAttribute("data-action");
    var existing = servicesById[serviceId];
    if (!existing) {
      showError("Service not found in UI state.");
      return;
    }

    try {
      if (action === "save") {
        var updated = collectServiceFromRow(row, existing);
        await request(ADMIN_URL + "/" + encodeURIComponent(serviceId), {
          method: "PUT",
          headers: authHeaders(),
          body: JSON.stringify(updated)
        });
      } else if (action === "toggle") {
        await request(ADMIN_URL + "/" + encodeURIComponent(serviceId) + "/toggle", {
          method: "POST",
          headers: authHeaders()
        });
      } else if (action === "delete") {
        await request(ADMIN_URL + "/" + encodeURIComponent(serviceId), {
          method: "DELETE",
          headers: authHeaders()
        });
      }

      await loadServices();
    } catch (err) {
      showError(err.message);
    }
  });

  loadStoredToken();
})();
