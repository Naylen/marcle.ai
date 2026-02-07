(function () {
  "use strict";

  var API_BASE = window.MARCLE_API_BASE || "";
  var ADMIN_URL = API_BASE + "/api/admin/services";
  var tokenInput = document.getElementById("admin-token");
  var connectBtn = document.getElementById("connect-btn");
  var form = document.getElementById("service-form");
  var list = document.getElementById("service-list");
  var authScheme = document.getElementById("auth-scheme");
  var headerWrap = document.getElementById("header-name-wrap");
  var authEnv = document.getElementById("auth-env");
  var authHeaderName = document.getElementById("auth-header-name");

  function authHeaders() {
    return {
      "Authorization": "Bearer " + tokenInput.value.trim(),
      "Content-Type": "application/json"
    };
  }

  function toggleHeaderField() {
    headerWrap.style.display = authScheme.value === "header" ? "block" : "none";
  }

  function buildAuthRefFromForm() {
    var scheme = authScheme.value;
    if (scheme === "none") return null;
    var ref = {
      scheme: scheme,
      env: authEnv.value.trim()
    };
    if (scheme === "header") {
      ref.header_name = authHeaderName.value.trim();
    }
    return ref;
  }

  function renderServices(services) {
    if (!services || services.length === 0) {
      list.innerHTML = "<div class=\"admin-item\">No services configured.</div>";
      return;
    }
    list.innerHTML = services.map(function (svc) {
      var auth = svc.auth_ref ? (svc.auth_ref.scheme + " / " + (svc.auth_ref.env || "")) : "none";
      if (svc.auth_ref && svc.auth_ref.scheme === "header") {
        auth += " / " + (svc.auth_ref.header_name || "");
      }
      return (
        "<div class=\"admin-item\">" +
          "<code>" + escapeHtml(svc.id) + "</code>" +
          "<code>" + escapeHtml(svc.check_type) + "</code>" +
          "<code>" + escapeHtml(svc.group) + "</code>" +
          "<code>" + escapeHtml(auth) + "</code>" +
        "</div>"
      );
    }).join("");
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  async function loadServices() {
    var resp = await fetch(ADMIN_URL, { headers: authHeaders() });
    if (!resp.ok) {
      throw new Error("Failed to load services: HTTP " + resp.status);
    }
    var data = await resp.json();
    renderServices(data.services || []);
  }

  connectBtn.addEventListener("click", async function () {
    try {
      await loadServices();
    } catch (err) {
      list.innerHTML = "<div class=\"admin-item\">" + escapeHtml(err.message) + "</div>";
    }
  });

  authScheme.addEventListener("change", toggleHeaderField);
  toggleHeaderField();

  form.addEventListener("submit", async function (evt) {
    evt.preventDefault();
    var formData = new FormData(form);
    var service = {
      id: String(formData.get("id") || "").trim(),
      name: String(formData.get("name") || "").trim(),
      group: String(formData.get("group") || "").trim(),
      url: String(formData.get("url") || "").trim(),
      icon: String(formData.get("icon") || "").trim() || null,
      check_type: String(formData.get("check_type") || "").trim(),
      enabled: true,
      auth_ref: buildAuthRefFromForm()
    };

    try {
      var resp = await fetch(ADMIN_URL + "/" + encodeURIComponent(service.id), {
        method: "PUT",
        headers: authHeaders(),
        body: JSON.stringify(service)
      });
      if (!resp.ok) {
        throw new Error("Save failed: HTTP " + resp.status);
      }
      await loadServices();
    } catch (err) {
      list.innerHTML = "<div class=\"admin-item\">" + escapeHtml(err.message) + "</div>";
    }
  });
})();
