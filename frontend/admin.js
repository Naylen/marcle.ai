(function () {
  "use strict";

  var API_BASE = window.MARCLE_API_BASE || "";
  var ADMIN_URL = API_BASE + "/api/admin/services";
  var AUDIT_URL = API_BASE + "/api/admin/audit";
  var STATUS_URL = API_BASE + "/api/status";
  var OVERVIEW_URL = API_BASE + "/api/overview";
  var HEALTH_POLL_INTERVAL = 60000;
  var AUDIT_POLL_INTERVAL = 45000;

  var tokenInput = document.getElementById("admin-token");
  var loadServicesBtn = document.getElementById("load-services-btn");
  var authStatusIndicator = document.getElementById("auth-status-indicator");
  var errorBox = document.getElementById("admin-error");

  var healthOverall = document.getElementById("admin-health-overall");
  var healthCountHealthy = document.getElementById("admin-health-count-healthy");
  var healthCountDegraded = document.getElementById("admin-health-count-degraded");
  var healthCountDown = document.getElementById("admin-health-count-down");
  var healthCountUnknown = document.getElementById("admin-health-count-unknown");
  var healthCacheAge = document.getElementById("admin-health-cache-age");
  var healthUpdatedAt = document.getElementById("admin-health-updated-at");
  var healthNote = document.getElementById("admin-health-note");

  var serviceListBody = document.getElementById("service-list-body");
  var serviceListMeta = document.getElementById("service-list-meta");
  var auditTableBody = document.getElementById("audit-table-body");
  var auditListMeta = document.getElementById("audit-list-meta");
  var auditRefreshBtn = document.getElementById("audit-refresh-btn");
  var auditActionFilter = document.getElementById("audit-action-filter");
  var auditSearchInput = document.getElementById("audit-search-input");

  var serviceForm = document.getElementById("service-form");
  var serviceFormHeading = document.getElementById("service-form-heading");
  var serviceFormModeNote = document.getElementById("service-form-mode-note");
  var saveServiceBtn = document.getElementById("save-service-btn");
  var resetServiceFormBtn = document.getElementById("reset-service-form-btn");
  var cancelEditBtn = document.getElementById("cancel-edit-btn");
  var serviceSaveMessage = document.getElementById("service-save-message");
  var serviceIdNote = document.getElementById("service-id-note");
  var serviceAuthEnvWrap = document.getElementById("service-auth-env-wrap");
  var serviceAuthHeaderWrap = document.getElementById("service-auth-header-wrap");

  var deleteModalBackdrop = document.getElementById("delete-modal-backdrop");
  var deleteModal = document.getElementById("delete-modal");
  var deleteModalMessage = document.getElementById("delete-modal-message");
  var deleteCancelBtn = document.getElementById("delete-cancel-btn");
  var deleteConfirmBtn = document.getElementById("delete-confirm-btn");

  var formFields = {
    id: document.getElementById("service-id"),
    name: document.getElementById("service-name"),
    group: document.getElementById("service-group"),
    icon: document.getElementById("service-icon"),
    description: document.getElementById("service-description"),
    url: document.getElementById("service-url"),
    check_type: document.getElementById("service-check-type"),
    auth_scheme: document.getElementById("service-auth-scheme"),
    auth_env: document.getElementById("service-auth-env"),
    auth_header_name: document.getElementById("service-auth-header-name")
  };

  var fieldErrorNodes = {
    id: document.getElementById("service-id-error"),
    name: document.getElementById("service-name-error"),
    group: document.getElementById("service-group-error"),
    url: document.getElementById("service-url-error"),
    check_type: document.getElementById("service-check-type-error"),
    auth_env: document.getElementById("service-auth-env-error"),
    auth_header_name: document.getElementById("service-auth-header-name-error")
  };

  if (!tokenInput || !loadServicesBtn || !serviceListBody || !serviceForm || !saveServiceBtn ||
      !auditTableBody || !auditListMeta || !auditRefreshBtn || !auditActionFilter || !auditSearchInput) {
    return;
  }

  var STATUS_CLASSES = {
    healthy: true,
    degraded: true,
    down: true,
    unknown: true
  };

  var servicesById = {};
  var currentServices = [];
  var healthById = {};
  var auditEntries = [];
  var latestStatusPayload = null;
  var latestOverviewPayload = null;
  var editServiceId = null;
  var pendingDeleteServiceId = null;
  var isLoading = false;
  var isAuthenticated = false;
  var hasTriedSave = false;
  var touchedFields = {};
  var saveMessageTimer = null;
  var modalLastFocused = null;

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function hasToken() {
    return tokenInput.value.trim().length > 0;
  }

  function normalizeStatus(statusValue) {
    if (!statusValue || typeof statusValue !== "string") return "unknown";
    var lowered = statusValue.toLowerCase();
    return STATUS_CLASSES[lowered] ? lowered : "unknown";
  }

  function titleCase(value) {
    if (!value) return "Unknown";
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function parseIso(value) {
    if (!value || typeof value !== "string") return null;
    var parsed = new Date(value);
    if (isNaN(parsed.getTime())) return null;
    return parsed;
  }

  function secondsSinceIso(value) {
    var parsed = parseIso(value);
    if (!parsed) return null;
    return Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 1000));
  }

  function humanizeDuration(totalSeconds) {
    var seconds = Math.max(0, Math.floor(totalSeconds || 0));
    if (seconds < 60) return seconds + "s";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h";
    return Math.floor(seconds / 86400) + "d";
  }

  function formatRelativeTime(isoTimestamp) {
    var ageSeconds = secondsSinceIso(isoTimestamp);
    if (ageSeconds == null) return "--";
    return humanizeDuration(ageSeconds) + " ago";
  }

  function formatAuditTimestamp(isoTimestamp) {
    var parsed = parseIso(isoTimestamp);
    if (!parsed) return "--";
    return parsed.toLocaleString();
  }

  function normalizeAuditAction(value) {
    if (!value || typeof value !== "string") return "";
    var lowered = value.toLowerCase();
    if (lowered === "create" || lowered === "update" || lowered === "delete" ||
        lowered === "toggle" || lowered === "bulk") {
      return lowered;
    }
    return "";
  }

  function truncateValue(value, maxLen) {
    if (!value || typeof value !== "string") return "";
    if (value.length <= maxLen) return value;
    return value.slice(0, maxLen - 3) + "...";
  }

  function showError(message) {
    if (!message) {
      errorBox.textContent = "";
      errorBox.className = "admin-alert is-hidden";
      return;
    }
    errorBox.textContent = message;
    errorBox.className = "admin-alert admin-alert-error";
  }

  function hideSaveMessage() {
    if (saveMessageTimer) {
      clearTimeout(saveMessageTimer);
      saveMessageTimer = null;
    }
    serviceSaveMessage.textContent = "Service saved.";
    serviceSaveMessage.classList.add("is-hidden");
  }

  function showSaveMessage(message) {
    hideSaveMessage();
    serviceSaveMessage.textContent = message || "Service saved.";
    serviceSaveMessage.classList.remove("is-hidden");
    saveMessageTimer = setTimeout(function () {
      serviceSaveMessage.classList.add("is-hidden");
    }, 3500);
  }

  function setAuthIndicator(authenticated) {
    isAuthenticated = !!authenticated;
    if (isAuthenticated) {
      authStatusIndicator.textContent = "Authenticated";
      authStatusIndicator.className = "admin-chip admin-chip-success";
      renderAuditEntries();
      return;
    }
    authStatusIndicator.textContent = "Not authenticated";
    authStatusIndicator.className = "admin-chip admin-chip-muted";
    renderAuditEntries();
  }

  function setHealthNote(message, isWarning) {
    if (!healthNote) return;
    healthNote.textContent = message;
    healthNote.className = isWarning ? "admin-health-note is-warning" : "admin-health-note";
  }

  function adminHeaders() {
    return {
      "Authorization": "Bearer " + tokenInput.value.trim(),
      "Content-Type": "application/json"
    };
  }

  async function buildApiErrorMessage(response, isAdminCall) {
    var detail = "";
    try {
      var payload = await response.json();
      if (payload && typeof payload.detail === "string" && payload.detail.trim()) {
        detail = payload.detail.trim();
      }
    } catch (_err) {
      // Ignore JSON parse failures.
    }

    if (response.status === 401 || response.status === 403) {
      if (isAdminCall) {
        setAuthIndicator(false);
      }
      return "Authentication failed. Check your admin token.";
    }

    if (!detail) {
      if (response.status === 404) detail = "Requested service was not found.";
      else if (response.status === 409) detail = "A service with this ID already exists.";
      else if (response.status === 400) detail = "Request validation failed. Review the form fields.";
      else if (response.status >= 500) detail = "Server error while processing the request.";
      else detail = "Request failed.";
    }

    return detail + " (HTTP " + response.status + ")";
  }

  async function requestJson(url, options, isAdminCall) {
    var response = await fetch(url, options || {});
    if (!response.ok) {
      var errorMessage = await buildApiErrorMessage(response, isAdminCall);
      throw new Error(errorMessage);
    }

    if (isAdminCall) setAuthIndicator(true);
    if (response.status === 204) return null;

    var contentType = response.headers.get("content-type") || "";
    if (contentType.indexOf("application/json") === -1) return null;

    return await response.json();
  }

  function collectFormValues() {
    return {
      id: formFields.id.value.trim(),
      name: formFields.name.value.trim(),
      group: formFields.group.value.trim(),
      icon: formFields.icon.value.trim(),
      description: formFields.description.value.trim(),
      url: formFields.url.value.trim(),
      check_type: formFields.check_type.value.trim(),
      auth_scheme: formFields.auth_scheme.value.trim() || "none",
      auth_env: formFields.auth_env.value.trim(),
      auth_header_name: formFields.auth_header_name.value.trim()
    };
  }

  function isValidUrl(value) {
    try {
      var parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch (_err) {
      return false;
    }
  }

  function getValidationErrors(values) {
    var errors = {};

    if (!values.id) errors.id = "ID is required.";
    else if (/\s/.test(values.id)) errors.id = "ID cannot contain spaces.";

    if (!values.name) errors.name = "Name is required.";
    if (!values.group) errors.group = "Group is required.";

    if (!values.url) errors.url = "URL is required.";
    else if (!isValidUrl(values.url)) errors.url = "Enter a valid URL with http:// or https://.";

    if (!values.check_type) errors.check_type = "Check type is required.";

    if (!editServiceId && values.id && Object.prototype.hasOwnProperty.call(servicesById, values.id)) {
      errors.id = "A service with this ID already exists.";
    }

    if (editServiceId && values.id !== editServiceId) {
      errors.id = "ID cannot be changed while editing.";
    }

    if (values.auth_scheme !== "none" && !values.auth_env) {
      errors.auth_env = "Auth env var name is required for this auth scheme.";
    }

    if (values.auth_scheme === "header" && !values.auth_header_name) {
      errors.auth_header_name = "Header name is required for header auth.";
    }

    return errors;
  }

  function setFieldError(fieldName, message) {
    var errorNode = fieldErrorNodes[fieldName];
    var field = formFields[fieldName];
    if (!errorNode || !field) return;

    var shouldShow = !!message && (hasTriedSave || touchedFields[fieldName]);
    if (fieldName === "auth_env" && serviceAuthEnvWrap.classList.contains("is-hidden")) shouldShow = false;
    if (fieldName === "auth_header_name" && serviceAuthHeaderWrap.classList.contains("is-hidden")) shouldShow = false;

    errorNode.textContent = shouldShow ? message : "";
    field.setAttribute("aria-invalid", shouldShow ? "true" : "false");
  }

  function renderValidation(errors) {
    Object.keys(fieldErrorNodes).forEach(function (fieldName) {
      setFieldError(fieldName, errors[fieldName] || "");
    });
  }

  function clearValidation() {
    hasTriedSave = false;
    touchedFields = {};
    Object.keys(fieldErrorNodes).forEach(function (fieldName) {
      var node = fieldErrorNodes[fieldName];
      if (node) node.textContent = "";
      if (formFields[fieldName]) formFields[fieldName].setAttribute("aria-invalid", "false");
    });
  }

  function setAuthFieldVisibility(clearHiddenValues) {
    var scheme = formFields.auth_scheme.value || "none";
    var showEnv = scheme !== "none";
    var showHeader = scheme === "header";

    serviceAuthEnvWrap.classList.toggle("is-hidden", !showEnv);
    serviceAuthHeaderWrap.classList.toggle("is-hidden", !showHeader);

    if (clearHiddenValues) {
      if (!showEnv) formFields.auth_env.value = "";
      if (!showHeader) formFields.auth_header_name.value = "";
    }
  }

  function buildAuthRef(values) {
    if (!values.auth_scheme || values.auth_scheme === "none") return null;

    var authRef = {
      scheme: values.auth_scheme,
      env: values.auth_env
    };

    if (values.auth_scheme === "header") authRef.header_name = values.auth_header_name;
    return authRef;
  }

  function buildServicePayload(values, existingService) {
    return {
      id: values.id,
      name: values.name,
      group: values.group,
      url: values.url,
      icon: values.icon || null,
      description: values.description || null,
      check_type: values.check_type,
      enabled: existingService ? !!existingService.enabled : true,
      auth_ref: buildAuthRef(values)
    };
  }

  function authBadgeForService(service) {
    if (!service.auth_ref || !service.auth_ref.scheme || service.auth_ref.scheme === "none") {
      return { label: "Auth: N/A", className: "admin-chip-muted" };
    }
    if (service.credential_present === true) {
      return { label: "Auth: OK", className: "admin-chip-success" };
    }
    return { label: "Auth: Missing", className: "admin-chip-danger" };
  }

  function toHealthIndex(payload) {
    var index = {};
    if (!payload || !Array.isArray(payload.services)) return index;

    payload.services.forEach(function (service) {
      if (!service || !service.id) return;
      index[service.id] = {
        status: normalizeStatus(service.status),
        latency_ms: typeof service.latency_ms === "number" ? service.latency_ms : null,
        last_checked: typeof service.last_checked === "string" ? service.last_checked : null
      };
    });

    return index;
  }

  function buildCountsFromStatusPayload(payload) {
    var counts = {
      healthy: 0,
      degraded: 0,
      down: 0,
      unknown: 0
    };

    if (!payload || !Array.isArray(payload.services)) return counts;

    payload.services.forEach(function (service) {
      var status = normalizeStatus(service && service.status);
      if (Object.prototype.hasOwnProperty.call(counts, status)) counts[status] += 1;
    });

    return counts;
  }

  function renderHealthWidget() {
    var overallStatus = normalizeStatus(
      latestOverviewPayload && latestOverviewPayload.overall_status
        ? latestOverviewPayload.overall_status
        : latestStatusPayload && latestStatusPayload.overall_status
    );

    if (healthOverall) {
      healthOverall.className = "admin-status-badge " + overallStatus;
      healthOverall.textContent = titleCase(overallStatus);
    }

    var counts = latestOverviewPayload && latestOverviewPayload.counts
      ? latestOverviewPayload.counts
      : buildCountsFromStatusPayload(latestStatusPayload);

    if (healthCountHealthy) healthCountHealthy.textContent = "H " + (counts.healthy || 0);
    if (healthCountDegraded) healthCountDegraded.textContent = "Dg " + (counts.degraded || 0);
    if (healthCountDown) healthCountDown.textContent = "Dn " + (counts.down || 0);
    if (healthCountUnknown) healthCountUnknown.textContent = "U " + (counts.unknown || 0);

    if (healthCacheAge) {
      if (latestOverviewPayload && typeof latestOverviewPayload.cache_age_seconds === "number") {
        healthCacheAge.textContent = humanizeDuration(latestOverviewPayload.cache_age_seconds);
      } else {
        healthCacheAge.textContent = "--";
      }
    }

    if (healthUpdatedAt) {
      var updatedSource = latestOverviewPayload && latestOverviewPayload.last_refresh_at
        ? latestOverviewPayload.last_refresh_at
        : latestStatusPayload && latestStatusPayload.generated_at
          ? latestStatusPayload.generated_at
          : "";
      healthUpdatedAt.textContent = formatRelativeTime(updatedSource);
    }
  }

  function healthPreviewForService(service) {
    if (!service || service.enabled === false) {
      return {
        statusClass: "disabled",
        statusLabel: "Disabled",
        meta: "Service disabled"
      };
    }

    var health = healthById[service.id];
    if (!health) {
      return {
        statusClass: "unknown",
        statusLabel: "Unknown",
        meta: "No public status"
      };
    }

    var normalizedStatus = normalizeStatus(health.status);
    var latency = health.latency_ms != null ? health.latency_ms + "ms" : "--";
    var checked = health.last_checked ? formatRelativeTime(health.last_checked) : "--";

    return {
      statusClass: normalizedStatus,
      statusLabel: titleCase(normalizedStatus),
      latency: latency,
      checked: checked
    };
  }

  function renderServiceListMeta(count) {
    serviceListMeta.textContent = count + " services loaded.";
  }

  function setAuditMeta(message) {
    auditListMeta.textContent = message;
  }

  function getAuditFilteredEntries() {
    var actionFilter = (auditActionFilter.value || "").trim().toLowerCase();
    var search = (auditSearchInput.value || "").trim().toLowerCase();

    return auditEntries.filter(function (entry) {
      var action = normalizeAuditAction(entry && entry.action);
      if (actionFilter && action !== actionFilter) return false;

      if (!search) return true;
      var serviceId = entry && typeof entry.service_id === "string" ? entry.service_id.toLowerCase() : "";
      var ids = Array.isArray(entry && entry.ids) ? entry.ids.join(" ").toLowerCase() : "";
      return serviceId.indexOf(search) !== -1 || ids.indexOf(search) !== -1;
    });
  }

  function auditDetailsForEntry(entry) {
    var action = normalizeAuditAction(entry && entry.action);
    if (action === "bulk") {
      var ids = Array.isArray(entry && entry.ids) ? entry.ids : [];
      var enabled = typeof entry.enabled === "boolean" ? String(entry.enabled) : "--";
      return "enabled=" + enabled + " ids=[" + ids.join(", ") + "]";
    }
    if (action === "toggle") {
      return typeof entry.enabled === "boolean" ? "enabled=" + String(entry.enabled) : "--";
    }
    return "--";
  }

  function auditSourceForEntry(entry) {
    var ip = entry && typeof entry.ip === "string" ? entry.ip : "--";
    var userAgent = entry && typeof entry.user_agent === "string" ? entry.user_agent : "--";
    return {
      ip: truncateValue(ip, 128),
      userAgent: truncateValue(userAgent, 160)
    };
  }

  function renderAuditEntries() {
    if (!isAuthenticated) {
      auditTableBody.innerHTML = "<tr><td class='admin-empty' colspan='5'>Authenticate to load audit entries.</td></tr>";
      setAuditMeta("Authenticate to load.");
      return;
    }

    if (!auditEntries.length) {
      auditTableBody.innerHTML = "<tr><td class='admin-empty' colspan='5'>No audit entries found.</td></tr>";
      setAuditMeta("0 entries.");
      return;
    }

    var filtered = getAuditFilteredEntries();
    if (!filtered.length) {
      auditTableBody.innerHTML = "<tr><td class='admin-empty' colspan='5'>No rows match current filters.</td></tr>";
      setAuditMeta("0 entries shown of " + auditEntries.length + ".");
      return;
    }

    auditTableBody.innerHTML = filtered.map(function (entry, index) {
      var action = normalizeAuditAction(entry && entry.action) || "unknown";
      var target = entry && typeof entry.service_id === "string" ? entry.service_id : "bulk";
      var details = auditDetailsForEntry(entry);
      var source = auditSourceForEntry(entry);

      return (
        "<tr data-audit-index='" + index + "'>" +
          "<td><span class='admin-table-text'>" + escapeHtml(formatAuditTimestamp(entry && entry.ts)) + "</span></td>" +
          "<td><span class='admin-status-badge unknown'>" + escapeHtml(action) + "</span></td>" +
          "<td><span class='admin-audit-target'>" + escapeHtml(target) + "</span></td>" +
          "<td><div class='admin-audit-detail-wrap'>" +
            "<span class='admin-audit-detail'>" + escapeHtml(details) + "</span>" +
            "<button type='button' class='admin-button admin-button-quiet admin-copy-json' data-action='copy-json' aria-label='Copy audit row JSON'>Copy JSON</button>" +
          "</div></td>" +
          "<td><div class='admin-audit-source'>" +
            "<span class='admin-table-text'>" + escapeHtml(source.ip) + "</span>" +
            "<span class='admin-table-text'>" + escapeHtml(source.userAgent) + "</span>" +
          "</div></td>" +
        "</tr>"
      );
    }).join("");
    setAuditMeta(filtered.length + " entries shown of " + auditEntries.length + ".");
  }

  async function copyAuditRowJson(entry) {
    var serialized = JSON.stringify(entry);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(serialized);
      return;
    }

    var textArea = document.createElement("textarea");
    textArea.value = serialized;
    document.body.appendChild(textArea);
    textArea.select();
    document.execCommand("copy");
    document.body.removeChild(textArea);
  }

  function actionDisabledAttr() {
    return (!hasToken() || isLoading) ? " disabled" : "";
  }

  function renderServices(services) {
    currentServices = Array.isArray(services) ? services.slice() : [];
    servicesById = {};

    if (!services || services.length === 0) {
      serviceListBody.innerHTML = "<tr><td class='admin-empty' colspan='6'>No services configured.</td></tr>";
      renderServiceListMeta(0);
      updateActionAvailability();
      return;
    }

    services.forEach(function (service) {
      servicesById[service.id] = service;
    });

    var disabledAttr = actionDisabledAttr();
    serviceListBody.innerHTML = services.map(function (service) {
      var healthPreview = healthPreviewForService(service);
      var authBadge = authBadgeForService(service);
      var toggleLabel = service.enabled ? "Enabled" : "Disabled";
      var enabledState = service.enabled ? "enabled" : "disabled";
      var accessibleName = service.name || service.id;

      return (
        "<tr data-service-id='" + escapeHtml(service.id) + "'>" +
          "<td>" +
            "<span class='admin-service-name'>" + escapeHtml(accessibleName) + "</span>" +
            "<span class='admin-service-id'>" + escapeHtml(service.id) + "</span>" +
          "</td>" +
          "<td><span class='admin-chip admin-chip-muted'>" + escapeHtml(service.group || "core") + "</span></td>" +
          "<td><div class='admin-health-preview'>" +
            "<span class='admin-status-badge " + escapeHtml(healthPreview.statusClass) + "'>" + escapeHtml(healthPreview.statusLabel) + "</span>" +
            "<div class='admin-health-meta-stack'>" +
              "<span class='admin-health-latency'>" + escapeHtml(healthPreview.latency) + "</span>" +
              "<span class='admin-health-checked'>" + escapeHtml(healthPreview.checked) + "</span>" +
            "</div>" +
          "</div></td>" +
          "<td><button type='button' class='admin-toggle-button " + (service.enabled ? "is-enabled" : "is-disabled") + "' data-action='toggle' aria-label='Toggle enabled for " + escapeHtml(accessibleName) + " (currently " + enabledState + ")'" + disabledAttr + ">" + escapeHtml(toggleLabel) + "</button></td>" +
          "<td><span class='admin-chip " + authBadge.className + "'>" + escapeHtml(authBadge.label) + "</span></td>" +
          "<td class='admin-row-actions'>" +
            "<button type='button' class='admin-button admin-button-small' data-action='edit' aria-label='Edit " + escapeHtml(accessibleName) + "'" + disabledAttr + ">Edit</button>" +
            "<button type='button' class='admin-button admin-button-small admin-button-danger-ghost' data-action='delete' aria-label='Delete " + escapeHtml(accessibleName) + "'" + disabledAttr + ">Delete</button>" +
          "</td>" +
        "</tr>"
      );
    }).join("");

    renderServiceListMeta(services.length);
    updateActionAvailability();
  }

  function setLoadingState(loading) {
    isLoading = !!loading;
    updateActionAvailability();
  }

  async function runAction(button, busyText, action) {
    if (isLoading) return null;

    var originalText = "";
    if (button) {
      originalText = button.textContent;
      if (busyText) button.textContent = busyText;
    }

    setLoadingState(true);

    try {
      return await action();
    } catch (err) {
      showError(err && err.message ? err.message : "Unexpected error.");
      return null;
    } finally {
      if (button) button.textContent = originalText;
      setLoadingState(false);
    }
  }

  function isDeleteModalOpen() {
    return !deleteModalBackdrop.classList.contains("is-hidden");
  }

  function openDeleteModal(serviceId) {
    var service = servicesById[serviceId];
    if (!service) {
      showError("Service not found in current UI state.");
      return;
    }

    pendingDeleteServiceId = serviceId;
    var displayName = service.name || service.id;
    deleteModalMessage.textContent = "Delete service '" + displayName + "'? This removes it immediately.";

    modalLastFocused = document.activeElement;
    deleteModalBackdrop.hidden = false;
    deleteModalBackdrop.classList.remove("is-hidden");
    document.body.classList.add("admin-modal-open");
    deleteCancelBtn.focus();
    updateActionAvailability();
  }

  function closeDeleteModal() {
    pendingDeleteServiceId = null;
    deleteModalBackdrop.classList.add("is-hidden");
    deleteModalBackdrop.hidden = true;
    document.body.classList.remove("admin-modal-open");

    if (
      modalLastFocused &&
      typeof modalLastFocused.focus === "function" &&
      document.contains(modalLastFocused)
    ) {
      modalLastFocused.focus();
    }

    modalLastFocused = null;
    updateActionAvailability();
  }

  function getFocusableElements(container) {
    if (!container) return [];
    var selectors = [
      "a[href]",
      "button:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])"
    ].join(",");

    return Array.prototype.slice.call(container.querySelectorAll(selectors)).filter(function (el) {
      return el.offsetParent !== null;
    });
  }

  function trapModalFocus(evt) {
    if (evt.key !== "Tab" || !isDeleteModalOpen()) return;

    var focusable = getFocusableElements(deleteModal);
    if (!focusable.length) return;

    var first = focusable[0];
    var last = focusable[focusable.length - 1];

    if (evt.shiftKey && document.activeElement === first) {
      evt.preventDefault();
      last.focus();
      return;
    }
    if (!evt.shiftKey && document.activeElement === last) {
      evt.preventDefault();
      first.focus();
    }
  }

  function applyAddMode(resetFormFields) {
    editServiceId = null;
    serviceFormHeading.textContent = "Add Service";
    serviceFormModeNote.textContent = "Create a new service entry.";
    saveServiceBtn.textContent = "Add service";
    cancelEditBtn.classList.add("is-hidden");
    formFields.id.readOnly = false;
    serviceIdNote.classList.add("is-hidden");

    if (resetFormFields) {
      serviceForm.reset();
      formFields.group.value = "core";
      formFields.auth_scheme.value = "none";
      formFields.auth_env.value = "";
      formFields.auth_header_name.value = "";
    }

    clearValidation();
    setAuthFieldVisibility(true);
    updateActionAvailability();
  }

  function applyEditMode(serviceId) {
    var service = servicesById[serviceId];
    if (!service) {
      showError("Service not found in current UI state.");
      return;
    }

    editServiceId = serviceId;
    serviceFormHeading.textContent = "Edit Service";
    serviceFormModeNote.textContent = "Editing '" + (service.name || service.id) + "'. Press Esc to cancel.";
    saveServiceBtn.textContent = "Save changes";
    cancelEditBtn.classList.remove("is-hidden");
    formFields.id.readOnly = true;
    serviceIdNote.classList.remove("is-hidden");

    formFields.id.value = service.id || "";
    formFields.name.value = service.name || "";
    formFields.group.value = service.group || "core";
    formFields.icon.value = service.icon || "";
    formFields.description.value = service.description || "";
    formFields.url.value = service.url || "";
    formFields.check_type.value = service.check_type || "";

    var authRef = service.auth_ref || null;
    formFields.auth_scheme.value = authRef && authRef.scheme ? authRef.scheme : "none";
    formFields.auth_env.value = authRef && authRef.env ? authRef.env : "";
    formFields.auth_header_name.value = authRef && authRef.header_name ? authRef.header_name : "";

    clearValidation();
    setAuthFieldVisibility(false);
    updateActionAvailability();
    formFields.name.focus();
  }

  function updateActionAvailability() {
    var tokenReady = hasToken();

    loadServicesBtn.disabled = !tokenReady || isLoading;
    auditRefreshBtn.disabled = !tokenReady || isLoading;
    Array.prototype.forEach.call(serviceForm.querySelectorAll("fieldset"), function (fieldset) {
      fieldset.disabled = !tokenReady || isLoading;
    });
    resetServiceFormBtn.disabled = !tokenReady || isLoading;
    cancelEditBtn.disabled = !tokenReady || isLoading;

    if (isDeleteModalOpen()) {
      deleteConfirmBtn.disabled = !tokenReady || isLoading;
      deleteCancelBtn.disabled = isLoading;
    }

    Array.prototype.forEach.call(serviceListBody.querySelectorAll("button[data-action]"), function (button) {
      button.disabled = !tokenReady || isLoading;
    });

    var values = collectFormValues();
    var errors = getValidationErrors(values);
    renderValidation(errors);
    saveServiceBtn.disabled = !tokenReady || isLoading || Object.keys(errors).length > 0;
  }

  async function refreshHealthPreview() {
    var results = await Promise.allSettled([
      requestJson(STATUS_URL, {}, false),
      requestJson(OVERVIEW_URL, {}, false)
    ]);

    var statusOk = results[0].status === "fulfilled";
    var overviewOk = results[1].status === "fulfilled";

    if (statusOk) {
      latestStatusPayload = results[0].value;
      healthById = toHealthIndex(latestStatusPayload);
    } else if (!latestStatusPayload) {
      healthById = {};
    }

    if (overviewOk) latestOverviewPayload = results[1].value;

    renderHealthWidget();
    if (currentServices.length > 0) renderServices(currentServices);

    if (statusOk && overviewOk) {
      setHealthNote("Public health preview updates every 60s.", false);
      return;
    }
    if (statusOk || overviewOk) {
      setHealthNote("Public health preview is partially available.", true);
      return;
    }
    setHealthNote("Public health preview unavailable.", true);
  }

  async function loadAuditLog() {
    var payload = await requestJson(AUDIT_URL + "?limit=200", { headers: adminHeaders() }, true);
    auditEntries = Array.isArray(payload) ? payload : [];
    renderAuditEntries();
  }

  async function loadServicesAndStatus() {
    var payload = await requestJson(ADMIN_URL, { headers: adminHeaders() }, true);
    var services = payload && Array.isArray(payload.services) ? payload.services : [];
    renderServices(services);

    if (editServiceId && !Object.prototype.hasOwnProperty.call(servicesById, editServiceId)) {
      applyAddMode(true);
    }

    var sideLoads = await Promise.allSettled([
      refreshHealthPreview(),
      loadAuditLog()
    ]);

    if (sideLoads[1].status !== "fulfilled") {
      setAuditMeta("Failed to load audit entries.");
    }
  }

  tokenInput.addEventListener("input", function () {
    setAuthIndicator(false);
    showError("");
    auditEntries = [];
    renderAuditEntries();
    setAuditMeta("Authenticate to load.");
    updateActionAvailability();
  });

  loadServicesBtn.addEventListener("click", async function () {
    if (!hasToken()) return;
    showError("");

    await runAction(loadServicesBtn, "Loading...", async function () {
      await loadServicesAndStatus();
    });
  });

  serviceForm.addEventListener("submit", async function (evt) {
    evt.preventDefault();
    if (!hasToken()) return;

    showError("");
    hideSaveMessage();
    hasTriedSave = true;

    var values = collectFormValues();
    var errors = getValidationErrors(values);
    renderValidation(errors);
    if (Object.keys(errors).length > 0) {
      updateActionAvailability();
      return;
    }

    var serviceIdForRequest = editServiceId;
    var existingService = serviceIdForRequest ? servicesById[serviceIdForRequest] : null;
    var payload = buildServicePayload(values, existingService);
    var method = serviceIdForRequest ? "PUT" : "POST";
    var endpoint = serviceIdForRequest
      ? ADMIN_URL + "/" + encodeURIComponent(serviceIdForRequest)
      : ADMIN_URL;

    await runAction(saveServiceBtn, serviceIdForRequest ? "Saving..." : "Adding...", async function () {
      await requestJson(endpoint, {
        method: method,
        headers: adminHeaders(),
        body: JSON.stringify(payload)
      }, true);

      applyAddMode(true);
      showSaveMessage("Service saved.");
      await loadServicesAndStatus();
    });
  });

  resetServiceFormBtn.addEventListener("click", function () {
    showError("");
    hideSaveMessage();
    if (editServiceId && Object.prototype.hasOwnProperty.call(servicesById, editServiceId)) {
      applyEditMode(editServiceId);
      return;
    }
    applyAddMode(true);
  });

  cancelEditBtn.addEventListener("click", function () {
    showError("");
    hideSaveMessage();
    applyAddMode(true);
  });

  formFields.auth_scheme.addEventListener("change", function () {
    touchedFields.auth_scheme = true;
    setAuthFieldVisibility(true);
    updateActionAvailability();
  });

  Object.keys(formFields).forEach(function (fieldName) {
    var field = formFields[fieldName];
    if (!field) return;

    field.addEventListener("input", function () {
      touchedFields[fieldName] = true;
      updateActionAvailability();
    });
    field.addEventListener("change", function () {
      touchedFields[fieldName] = true;
      updateActionAvailability();
    });
    field.addEventListener("blur", function () {
      touchedFields[fieldName] = true;
      updateActionAvailability();
    });
  });

  serviceListBody.addEventListener("click", async function (evt) {
    var button = evt.target.closest("button[data-action]");
    if (!button) return;

    var row = button.closest("tr[data-service-id]");
    if (!row) return;

    var serviceId = row.getAttribute("data-service-id");
    var action = button.getAttribute("data-action");
    var service = servicesById[serviceId];
    if (!service) {
      showError("Service not found in current UI state.");
      return;
    }
    if (!hasToken() || isLoading) return;

    showError("");
    hideSaveMessage();

    if (action === "edit") {
      applyEditMode(serviceId);
      return;
    }

    if (action === "toggle") {
      await runAction(button, service.enabled ? "Disabling..." : "Enabling...", async function () {
        await requestJson(ADMIN_URL + "/" + encodeURIComponent(serviceId) + "/toggle", {
          method: "POST",
          headers: adminHeaders()
        }, true);
        await loadServicesAndStatus();
      });
      return;
    }

    if (action === "delete") openDeleteModal(serviceId);
  });

  auditRefreshBtn.addEventListener("click", async function () {
    if (!hasToken()) return;
    showError("");

    await runAction(auditRefreshBtn, "Refreshing...", async function () {
      await loadAuditLog();
    });
  });

  auditActionFilter.addEventListener("change", function () {
    renderAuditEntries();
  });

  auditSearchInput.addEventListener("input", function () {
    renderAuditEntries();
  });

  auditTableBody.addEventListener("click", async function (evt) {
    var button = evt.target.closest("button[data-action='copy-json']");
    if (!button) return;

    var row = button.closest("tr[data-audit-index]");
    if (!row) return;

    var filtered = getAuditFilteredEntries();
    var index = Number(row.getAttribute("data-audit-index"));
    if (!isFinite(index) || index < 0 || index >= filtered.length) return;

    try {
      await copyAuditRowJson(filtered[index]);
      setAuditMeta("Copied row JSON.");
    } catch (_err) {
      setAuditMeta("Unable to copy row JSON.");
    }
  });

  deleteCancelBtn.addEventListener("click", function () {
    if (isLoading) return;
    closeDeleteModal();
  });

  deleteConfirmBtn.addEventListener("click", async function () {
    if (!pendingDeleteServiceId || !hasToken()) return;
    var deletingServiceId = pendingDeleteServiceId;

    await runAction(deleteConfirmBtn, "Deleting...", async function () {
      await requestJson(ADMIN_URL + "/" + encodeURIComponent(deletingServiceId), {
        method: "DELETE",
        headers: adminHeaders()
      }, true);

      closeDeleteModal();
      if (editServiceId === deletingServiceId) applyAddMode(true);
      await loadServicesAndStatus();
    });
  });

  deleteModalBackdrop.addEventListener("click", function (evt) {
    if (evt.target !== deleteModalBackdrop || isLoading) return;
    closeDeleteModal();
  });

  deleteModal.addEventListener("keydown", trapModalFocus);

  document.addEventListener("keydown", function (evt) {
    if (evt.key !== "Escape") return;

    if (isDeleteModalOpen()) {
      evt.preventDefault();
      if (!isLoading) closeDeleteModal();
      return;
    }

    if (editServiceId) {
      evt.preventDefault();
      applyAddMode(true);
    }
  });

  setAuthIndicator(false);
  applyAddMode(true);
  updateActionAvailability();

  refreshHealthPreview();
  setInterval(refreshHealthPreview, HEALTH_POLL_INTERVAL);
  setInterval(function () {
    if (!hasToken() || !isAuthenticated || isLoading) return;
    loadAuditLog().catch(function () {
      setAuditMeta("Failed to refresh audit entries.");
    });
  }, AUDIT_POLL_INTERVAL);
})();
