(function () {
  "use strict";

  var API_BASE = window.MARCLE_API_BASE || "";
  var ADMIN_URL = API_BASE + "/api/admin/services";

  var tokenInput = document.getElementById("admin-token");
  var connectBtn = document.getElementById("connect-btn");
  var createForm = document.getElementById("create-form");
  var createAuthScheme = document.getElementById("create-auth-scheme");
  var createAuthEnv = document.getElementById("create-auth-env");
  var createAuthHeaderWrap = document.getElementById("create-auth-header-wrap");
  var createAuthHeaderName = document.getElementById("create-auth-header-name");
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

  function toggleCreateHeaderField() {
    createAuthHeaderWrap.style.display = createAuthScheme.value === "header" ? "block" : "none";
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

  function parseAuthRefFields(scheme, env, headerName) {
    if (!scheme || scheme === "none") return null;

    var ref = {
      scheme: scheme,
      env: env || ""
    };

    if (scheme === "header") {
      ref.header_name = headerName || "";
    }
    return ref;
  }

  function getAuthRefFromRow(row) {
    var scheme = getRowValue(row, "[data-auth-field='scheme']");
    var env = getRowValue(row, "[data-auth-field='env']");
    var headerName = getRowValue(row, "[data-auth-field='header_name']");
    return parseAuthRefFields(scheme, env, headerName);
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
      auth_ref: getAuthRefFromRow(row)
    };
  }

  function credentialSummary(authRef) {
    if (!authRef || !authRef.scheme || authRef.scheme === "none") return "auth_ref: none";
    if (authRef.scheme === "header") {
      return "auth_ref: " + authRef.scheme + " / " + (authRef.env || "") + " / " + (authRef.header_name || "");
    }
    return "auth_ref: " + authRef.scheme + " / " + (authRef.env || "");
  }

  function serviceRowMarkup(svc) {
    var checked = svc.enabled ? "checked" : "";
    var authRef = svc.auth_ref || {};
    var authScheme = authRef.scheme || "none";
    var showHeader = authScheme === "header" ? "block" : "none";

    return (
      "<div class='admin-item' data-service-id='" + escapeHtml(svc.id) + "'>" +
        "<div class='admin-inline'><strong>" + escapeHtml(svc.id) + "</strong> · " + escapeHtml(credentialSummary(svc.auth_ref)) + "</div>" +
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
        "<div class='admin-grid'>" +
          "<div><label class='admin-label'>Auth scheme</label>" +
            "<select class='admin-select' data-auth-field='scheme'>" +
              "<option value='none'" + (authScheme === "none" ? " selected" : "") + ">none</option>" +
              "<option value='bearer'" + (authScheme === "bearer" ? " selected" : "") + ">bearer</option>" +
              "<option value='basic'" + (authScheme === "basic" ? " selected" : "") + ">basic</option>" +
              "<option value='header'" + (authScheme === "header" ? " selected" : "") + ">header</option>" +
            "</select>" +
          "</div>" +
          "<div><label class='admin-label'>Auth env var name</label><input class='admin-input' data-auth-field='env' value='" + escapeHtml(authRef.env || "") + "'></div>" +
          "<div data-auth-header-wrap='1' style='display:" + showHeader + ";'><label class='admin-label'>Header name</label><input class='admin-input' data-auth-field='header_name' value='" + escapeHtml(authRef.header_name || "") + "'></div>" +
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
      enabled: true,
      auth_ref: parseAuthRefFields(
        createAuthScheme.value,
        createAuthEnv.value.trim(),
        createAuthHeaderName.value.trim()
      )
    };
  }

  connectBtn.addEventListener("click", async function () {
    try {
      await loadServices();
    } catch (err) {
      showError(err.message);
    }
  });

  createAuthScheme.addEventListener("change", toggleCreateHeaderField);
  toggleCreateHeaderField();

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
      createAuthScheme.value = "none";
      toggleCreateHeaderField();
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

  list.addEventListener("change", function (evt) {
    var schemeSelect = evt.target.closest("[data-auth-field='scheme']");
    if (!schemeSelect) return;
    var row = schemeSelect.closest("[data-service-id]");
    if (!row) return;
    var wrap = row.querySelector("[data-auth-header-wrap='1']");
    if (!wrap) return;
    wrap.style.display = schemeSelect.value === "header" ? "block" : "none";
  });
})();
