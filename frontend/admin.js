(function () {
  "use strict";

  var API_BASE = window.MARCLE_API_BASE || "";
  var ADMIN_URL = API_BASE + "/api/admin/services";
  var AUDIT_URL = API_BASE + "/api/admin/audit";
  var NOTIFICATIONS_URL = API_BASE + "/api/admin/notifications";
  var NOTIFICATIONS_TEST_URL = API_BASE + "/api/admin/notifications/test";
  var STATUS_URL = API_BASE + "/api/status";
  var OVERVIEW_URL = API_BASE + "/api/overview";
  var HEALTH_POLL_INTERVAL = 60000;
  var AUDIT_POLL_INTERVAL = 45000;

  var tokenInput = document.getElementById("admin-token");
  var loadServicesBtn = document.getElementById("load-services-btn");
  var authStatusIndicator = document.getElementById("auth-status-indicator");
  var authConnectionDetail = document.getElementById("auth-connection-detail");
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
  var bulkSelectionMeta = document.getElementById("bulk-selection-meta");
  var bulkSelectAllBtn = document.getElementById("bulk-select-all-btn");
  var bulkEnableBtn = document.getElementById("bulk-enable-btn");
  var bulkDisableBtn = document.getElementById("bulk-disable-btn");
  var auditTableBody = document.getElementById("audit-table-body");
  var auditListMeta = document.getElementById("audit-list-meta");
  var auditRefreshBtn = document.getElementById("audit-refresh-btn");
  var auditActionFilter = document.getElementById("audit-action-filter");
  var auditSearchInput = document.getElementById("audit-search-input");

  var notificationsMeta = document.getElementById("notifications-meta");
  var notificationsLoadBtn = document.getElementById("notifications-load-btn");
  var notificationsEnabled = document.getElementById("notifications-enabled");
  var notificationsSaveBtn = document.getElementById("notifications-save-btn");
  var notificationsTestBtn = document.getElementById("notifications-test-btn");
  var notificationsMessage = document.getElementById("notifications-message");
  var notificationsListBody = document.getElementById("notifications-list-body");
  var notificationForm = document.getElementById("notification-form");
  var notificationFormHeading = document.getElementById("notification-form-heading");
  var notificationCancelEditBtn = document.getElementById("notification-cancel-edit-btn");
  var notificationAddBtn = document.getElementById("notification-add-btn");
  var notificationResetBtn = document.getElementById("notification-reset-btn");
  var notificationAuthEnvWrap = document.getElementById("notification-auth-env-wrap");
  var notificationAuthHeaderWrap = document.getElementById("notification-auth-header-wrap");

  var notificationFields = {
    id: document.getElementById("notification-id"),
    url: document.getElementById("notification-url"),
    event_incident: document.getElementById("notification-event-incident"),
    event_recovery: document.getElementById("notification-event-recovery"),
    event_flapping: document.getElementById("notification-event-flapping"),
    groups: document.getElementById("notification-groups"),
    service_ids: document.getElementById("notification-service-ids"),
    min_severity: document.getElementById("notification-min-severity"),
    cooldown_seconds: document.getElementById("notification-cooldown"),
    auth_scheme: document.getElementById("notification-auth-scheme"),
    auth_env: document.getElementById("notification-auth-env"),
    auth_header_name: document.getElementById("notification-auth-header")
  };

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

  if (!tokenInput || !loadServicesBtn || !authStatusIndicator || !serviceListBody ||
      !bulkSelectionMeta || !bulkSelectAllBtn || !bulkEnableBtn || !bulkDisableBtn ||
      !serviceForm || !saveServiceBtn ||
      !auditTableBody || !auditListMeta || !auditRefreshBtn || !auditActionFilter || !auditSearchInput ||
      !notificationsMeta || !notificationsLoadBtn || !notificationsEnabled || !notificationsSaveBtn ||
      !notificationsTestBtn || !notificationsMessage || !notificationsListBody || !notificationForm ||
      !notificationAddBtn || !notificationResetBtn || !notificationCancelEditBtn) {
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
  var lastAdminSuccessAt = null;
  var selectedServiceIds = {};
  var notificationsConfig = { enabled: false, endpoints: [] };
  var notificationEditId = null;
  var hasTriedSave = false;
  var touchedFields = {};
  var saveMessageTimer = null;
  var notificationsMessageTimer = null;
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
        lowered === "toggle" || lowered === "bulk" ||
        lowered === "notifications_update" || lowered === "notifications_test") {
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

  function hideNotificationsMessage() {
    if (!notificationsMessage) return;
    if (notificationsMessageTimer) {
      clearTimeout(notificationsMessageTimer);
      notificationsMessageTimer = null;
    }
    notificationsMessage.textContent = "";
    notificationsMessage.className = "admin-success is-hidden";
  }

  function showNotificationsMessage(message, isError) {
    if (!notificationsMessage) return;
    hideNotificationsMessage();
    notificationsMessage.textContent = message || "Done.";
    notificationsMessage.className = isError ? "admin-alert admin-alert-error" : "admin-success";
    notificationsMessageTimer = setTimeout(function () {
      notificationsMessage.className = isError ? "admin-alert admin-alert-error is-hidden" : "admin-success is-hidden";
    }, 4200);
  }

  function parseCommaList(value) {
    return String(value || "")
      .split(",")
      .map(function (item) { return item.trim(); })
      .filter(function (item) { return item.length > 0; });
  }

  function selectedValues(selectEl) {
    if (!selectEl) return [];
    return Array.prototype.slice.call(selectEl.options)
      .filter(function (opt) { return !!opt.selected; })
      .map(function (opt) { return opt.value; });
  }

  function setSelectedValues(selectEl, values) {
    if (!selectEl) return;
    var selected = {};
    (values || []).forEach(function (value) {
      selected[value] = true;
    });
    Array.prototype.forEach.call(selectEl.options, function (opt) {
      opt.selected = !!selected[opt.value];
    });
  }

  function setNotificationAuthVisibility(clearHiddenValues) {
    var scheme = (notificationFields.auth_scheme && notificationFields.auth_scheme.value) || "none";
    var showEnv = scheme !== "none";
    var showHeader = scheme === "header";

    if (notificationAuthEnvWrap) notificationAuthEnvWrap.classList.toggle("is-hidden", !showEnv);
    if (notificationAuthHeaderWrap) notificationAuthHeaderWrap.classList.toggle("is-hidden", !showHeader);

    if (clearHiddenValues) {
      if (!showEnv && notificationFields.auth_env) notificationFields.auth_env.value = "";
      if (!showHeader && notificationFields.auth_header_name) notificationFields.auth_header_name.value = "";
    }
  }

  function notificationFormValues() {
    var events = [];
    if (notificationFields.event_incident && notificationFields.event_incident.checked) events.push("incident");
    if (notificationFields.event_recovery && notificationFields.event_recovery.checked) events.push("recovery");
    if (notificationFields.event_flapping && notificationFields.event_flapping.checked) events.push("flapping");

    return {
      id: notificationFields.id.value.trim(),
      url: notificationFields.url.value.trim(),
      events: events,
      groups: selectedValues(notificationFields.groups),
      service_ids: parseCommaList(notificationFields.service_ids.value),
      min_severity: (notificationFields.min_severity.value || "any").trim(),
      cooldown_seconds: Math.max(0, parseInt(notificationFields.cooldown_seconds.value || "0", 10) || 0),
      auth_scheme: (notificationFields.auth_scheme.value || "none").trim(),
      auth_env: notificationFields.auth_env.value.trim(),
      auth_header_name: notificationFields.auth_header_name.value.trim()
    };
  }

  function notificationValidation(values) {
    if (!values.id) return "Notification ID is required.";
    if (/\s/.test(values.id)) return "Notification ID cannot contain spaces.";
    if (!values.url) return "Notification URL is required.";
    if (!isValidUrl(values.url)) return "Notification URL must use http:// or https://.";
    if (!values.events.length) return "Select at least one event type.";
    if (values.auth_scheme !== "none" && !values.auth_env) return "Auth env var is required for this auth scheme.";
    if (values.auth_scheme === "header" && !values.auth_header_name) return "Header name is required for header auth.";

    var existing = (notificationsConfig.endpoints || []).some(function (endpoint) {
      if (!endpoint || !endpoint.id) return false;
      if (notificationEditId && endpoint.id === notificationEditId) return false;
      return endpoint.id === values.id;
    });
    if (existing) return "A notification endpoint with this ID already exists.";
    if (notificationEditId && values.id !== notificationEditId) return "ID cannot be changed while editing.";
    return "";
  }

  function buildNotificationAuthRef(values) {
    if (!values.auth_scheme || values.auth_scheme === "none") return null;
    var authRef = {
      scheme: values.auth_scheme,
      env: values.auth_env
    };
    if (values.auth_scheme === "header") authRef.header_name = values.auth_header_name;
    return authRef;
  }

  function buildNotificationEndpointPayload(values) {
    return {
      id: values.id,
      url: values.url,
      events: values.events,
      filters: {
        groups: values.groups,
        service_ids: values.service_ids,
        min_severity: values.min_severity || "any",
        cooldown_seconds: values.cooldown_seconds
      },
      auth_ref: buildNotificationAuthRef(values)
    };
  }

  function renderNotificationsMeta() {
    if (!notificationsMeta) return;
    var endpoints = notificationsConfig && Array.isArray(notificationsConfig.endpoints)
      ? notificationsConfig.endpoints
      : [];
    notificationsMeta.textContent = endpoints.length + " endpoint" + (endpoints.length === 1 ? "" : "s") +
      (notificationsConfig.enabled ? " · enabled" : " · disabled");
  }

  function notificationAuthBadge(endpoint) {
    if (!endpoint || !endpoint.auth_ref || !endpoint.auth_ref.scheme || endpoint.auth_ref.scheme === "none") {
      return { label: "Auth: N/A", className: "admin-chip-muted" };
    }
    if (endpoint.credential_present === true) {
      return { label: "Auth: OK", className: "admin-chip-success" };
    }
    return { label: "Auth: Missing", className: "admin-chip-danger" };
  }

  function renderNotificationsList() {
    if (!notificationsListBody) return;
    var endpoints = notificationsConfig && Array.isArray(notificationsConfig.endpoints)
      ? notificationsConfig.endpoints
      : [];

    if (!isAuthenticated) {
      notificationsListBody.innerHTML = "<tr><td class='admin-empty' colspan='6'>Authenticate to load notification endpoints.</td></tr>";
      return;
    }

    if (!endpoints.length) {
      notificationsListBody.innerHTML = "<tr><td class='admin-empty' colspan='6'>No notification endpoints configured.</td></tr>";
      return;
    }

    var disabledAttr = (!hasToken() || isLoading) ? " disabled" : "";
    notificationsListBody.innerHTML = endpoints.map(function (endpoint) {
      var authBadge = notificationAuthBadge(endpoint);
      var events = Array.isArray(endpoint.events) ? endpoint.events.join(", ") : "incident";
      var filters = endpoint.filters || {};
      var groups = Array.isArray(filters.groups) && filters.groups.length ? filters.groups.join(",") : "all groups";
      var serviceIds = Array.isArray(filters.service_ids) && filters.service_ids.length ? filters.service_ids.join(",") : "any service";
      var minSeverity = filters.min_severity || "any";
      var cooldown = typeof filters.cooldown_seconds === "number" ? filters.cooldown_seconds : 0;

      return (
        "<tr data-notification-id='" + escapeHtml(endpoint.id) + "'>" +
          "<td><span class='admin-service-id'>" + escapeHtml(endpoint.id) + "</span></td>" +
          "<td><span class='admin-table-text admin-notification-url'>" + escapeHtml(endpoint.url || "") + "</span></td>" +
          "<td><div class='admin-notification-events'><span class='admin-chip admin-chip-muted'>" + escapeHtml(events) + "</span></div></td>" +
          "<td><div class='admin-notification-filters'>" +
            "<span class='admin-table-text'>groups: " + escapeHtml(groups) + "</span>" +
            "<span class='admin-table-text'>services: " + escapeHtml(serviceIds) + "</span>" +
            "<span class='admin-table-text'>min: " + escapeHtml(minSeverity) + " · cooldown: " + escapeHtml(String(cooldown)) + "s</span>" +
          "</div></td>" +
          "<td><span class='admin-chip " + authBadge.className + "'>" + escapeHtml(authBadge.label) + "</span></td>" +
          "<td class='admin-row-actions'>" +
            "<button type='button' class='admin-button admin-button-small' data-notification-action='edit'" + disabledAttr + ">Edit</button>" +
            "<button type='button' class='admin-button admin-button-small admin-button-danger-ghost' data-notification-action='delete'" + disabledAttr + ">Delete</button>" +
          "</td>" +
        "</tr>"
      );
    }).join("");
  }

  function resetNotificationForm() {
    if (!notificationForm) return;
    notificationForm.reset();
    notificationFields.event_incident.checked = true;
    notificationFields.event_recovery.checked = false;
    notificationFields.event_flapping.checked = false;
    notificationFields.min_severity.value = "any";
    notificationFields.cooldown_seconds.value = "0";
    notificationFields.auth_scheme.value = "none";
    notificationFields.auth_env.value = "";
    notificationFields.auth_header_name.value = "";
    setSelectedValues(notificationFields.groups, []);
    notificationFields.service_ids.value = "";
    setNotificationAuthVisibility(true);
  }

  function applyNotificationAddMode() {
    notificationEditId = null;
    notificationFormHeading.textContent = "Add Notification Endpoint";
    notificationAddBtn.textContent = "Add endpoint";
    notificationCancelEditBtn.classList.add("is-hidden");
    notificationFields.id.readOnly = false;
    resetNotificationForm();
  }

  function applyNotificationEditMode(endpointId) {
    var endpoint = (notificationsConfig.endpoints || []).find(function (item) {
      return item && item.id === endpointId;
    });
    if (!endpoint) {
      showError("Notification endpoint not found.");
      return;
    }
    notificationEditId = endpoint.id;
    notificationFormHeading.textContent = "Edit Notification Endpoint";
    notificationAddBtn.textContent = "Save endpoint";
    notificationCancelEditBtn.classList.remove("is-hidden");
    notificationFields.id.readOnly = true;

    notificationFields.id.value = endpoint.id || "";
    notificationFields.url.value = endpoint.url || "";
    var events = Array.isArray(endpoint.events) ? endpoint.events : [];
    notificationFields.event_incident.checked = events.indexOf("incident") !== -1;
    notificationFields.event_recovery.checked = events.indexOf("recovery") !== -1;
    notificationFields.event_flapping.checked = events.indexOf("flapping") !== -1;

    var filters = endpoint.filters || {};
    setSelectedValues(notificationFields.groups, filters.groups || []);
    notificationFields.service_ids.value = Array.isArray(filters.service_ids) ? filters.service_ids.join(", ") : "";
    notificationFields.min_severity.value = filters.min_severity || "any";
    notificationFields.cooldown_seconds.value = String(typeof filters.cooldown_seconds === "number" ? filters.cooldown_seconds : 0);

    var authRef = endpoint.auth_ref || null;
    notificationFields.auth_scheme.value = authRef && authRef.scheme ? authRef.scheme : "none";
    notificationFields.auth_env.value = authRef && authRef.env ? authRef.env : "";
    notificationFields.auth_header_name.value = authRef && authRef.header_name ? authRef.header_name : "";
    setNotificationAuthVisibility(false);
  }

  function currentNotificationsPayload() {
    return {
      enabled: !!(notificationsEnabled && notificationsEnabled.checked),
      endpoints: (notificationsConfig.endpoints || []).map(function (endpoint) {
        return {
          id: endpoint.id,
          url: endpoint.url,
          events: endpoint.events || [],
          filters: endpoint.filters || {
            groups: [],
            service_ids: [],
            min_severity: "any",
            cooldown_seconds: 0
          },
          auth_ref: endpoint.auth_ref || null
        };
      })
    };
  }

  async function loadNotificationsConfig() {
    var payload = await requestJson(NOTIFICATIONS_URL, { headers: adminHeaders() }, true);
    notificationsConfig = {
      enabled: !!(payload && payload.enabled),
      endpoints: payload && Array.isArray(payload.endpoints) ? payload.endpoints.slice() : []
    };
    if (notificationsEnabled) notificationsEnabled.checked = notificationsConfig.enabled;
    renderNotificationsMeta();
    renderNotificationsList();
    if (notificationEditId) {
      var stillExists = notificationsConfig.endpoints.some(function (endpoint) {
        return endpoint && endpoint.id === notificationEditId;
      });
      if (!stillExists) applyNotificationAddMode();
    }
  }

  async function saveNotificationsConfig() {
    var payload = currentNotificationsPayload();
    await requestJson(NOTIFICATIONS_URL, {
      method: "PUT",
      headers: adminHeaders(),
      body: JSON.stringify(payload)
    }, true);
  }

  async function sendTestNotification() {
    return await requestJson(NOTIFICATIONS_TEST_URL, {
      method: "POST",
      headers: adminHeaders()
    }, true);
  }

  function upsertNotificationEndpoint() {
    var values = notificationFormValues();
    var validationMessage = notificationValidation(values);
    if (validationMessage) {
      showNotificationsMessage(validationMessage, true);
      return false;
    }

    var payload = buildNotificationEndpointPayload(values);
    var endpoints = (notificationsConfig.endpoints || []).slice();
    if (notificationEditId) {
      endpoints = endpoints.map(function (endpoint) {
        return endpoint && endpoint.id === notificationEditId ? payload : endpoint;
      });
    } else {
      endpoints.push(payload);
    }
    notificationsConfig.endpoints = endpoints;
    renderNotificationsList();
    renderNotificationsMeta();
    applyNotificationAddMode();
    updateActionAvailability();
    return true;
  }

  function deleteNotificationEndpoint(endpointId) {
    var endpoints = notificationsConfig.endpoints || [];
    var endpoint = endpoints.find(function (item) { return item && item.id === endpointId; });
    if (!endpoint) return;
    var confirmed = window.confirm("Delete notification endpoint '" + endpoint.id + "'?");
    if (!confirmed) return;
    notificationsConfig.endpoints = endpoints.filter(function (item) {
      return !item || item.id !== endpointId;
    });
    if (notificationEditId === endpointId) applyNotificationAddMode();
    renderNotificationsList();
    renderNotificationsMeta();
    updateActionAvailability();
  }

  function selectedServiceIdList() {
    return Object.keys(selectedServiceIds);
  }

  function syncSelectedServices() {
    var nextSelected = {};
    currentServices.forEach(function (service) {
      if (service && service.id && selectedServiceIds[service.id]) {
        nextSelected[service.id] = true;
      }
    });
    selectedServiceIds = nextSelected;
  }

  function renderBulkSelectionMeta() {
    var selectedCount = selectedServiceIdList().length;
    var total = currentServices.length;

    if (!total) {
      bulkSelectionMeta.textContent = "No services loaded.";
      bulkSelectAllBtn.textContent = "Select all";
      return;
    }

    bulkSelectionMeta.textContent = selectedCount + " selected of " + total + ".";
    bulkSelectAllBtn.textContent = selectedCount > 0 && selectedCount === total
      ? "Clear selection"
      : "Select all";
  }

  function updateConnectionDetail() {
    if (!authConnectionDetail) return;

    if (isAuthenticated && lastAdminSuccessAt) {
      authConnectionDetail.textContent = "Connected to admin API. Last success " + formatRelativeTime(lastAdminSuccessAt) + ".";
      return;
    }

    if (hasToken()) {
      authConnectionDetail.textContent = "Token set. Run an admin action to verify API connectivity.";
      return;
    }

    authConnectionDetail.textContent = "No successful admin requests yet.";
  }

  function setAuthIndicator(authenticated) {
    isAuthenticated = !!authenticated;
    if (isAuthenticated) {
      lastAdminSuccessAt = new Date().toISOString();
      authStatusIndicator.textContent = "Connected";
      authStatusIndicator.className = "admin-chip admin-chip-success";
      updateConnectionDetail();
      renderAuditEntries();
      return;
    }
    authStatusIndicator.textContent = "Not connected";
    authStatusIndicator.className = "admin-chip admin-chip-muted";
    updateConnectionDetail();
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
    syncSelectedServices();

    if (!services || services.length === 0) {
      selectedServiceIds = {};
      serviceListBody.innerHTML = "<tr><td class='admin-empty' colspan='7'>No services configured.</td></tr>";
      renderServiceListMeta(0);
      renderBulkSelectionMeta();
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
      var isSelected = selectedServiceIds[service.id] === true;
      var selectedAttr = isSelected ? " checked" : "";

      return (
        "<tr data-service-id='" + escapeHtml(service.id) + "'>" +
          "<td class='admin-select-cell'><input type='checkbox' class='admin-row-select' data-service-select='1' data-service-id='" + escapeHtml(service.id) + "' aria-label='Select " + escapeHtml(accessibleName) + " for bulk actions'" + selectedAttr + disabledAttr + "></td>" +
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
    renderBulkSelectionMeta();
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
    var selectedCount = selectedServiceIdList().length;

    loadServicesBtn.disabled = !tokenReady || isLoading;
    auditRefreshBtn.disabled = !tokenReady || isLoading;
    Array.prototype.forEach.call(serviceForm.querySelectorAll("fieldset"), function (fieldset) {
      fieldset.disabled = !tokenReady || isLoading;
    });
    resetServiceFormBtn.disabled = !tokenReady || isLoading;
    cancelEditBtn.disabled = !tokenReady || isLoading;
    bulkSelectAllBtn.disabled = !tokenReady || isLoading || currentServices.length === 0;
    bulkEnableBtn.disabled = !tokenReady || isLoading || selectedCount === 0;
    bulkDisableBtn.disabled = !tokenReady || isLoading || selectedCount === 0;

    if (isDeleteModalOpen()) {
      deleteConfirmBtn.disabled = !tokenReady || isLoading;
      deleteCancelBtn.disabled = isLoading;
    }

    Array.prototype.forEach.call(serviceListBody.querySelectorAll("button[data-action]"), function (button) {
      button.disabled = !tokenReady || isLoading;
    });
    Array.prototype.forEach.call(serviceListBody.querySelectorAll("input[data-service-select='1']"), function (input) {
      input.disabled = !tokenReady || isLoading;
    });

    notificationsLoadBtn.disabled = !tokenReady || isLoading;
    notificationsEnabled.disabled = !tokenReady || isLoading;
    notificationsSaveBtn.disabled = !tokenReady || isLoading;
    notificationsTestBtn.disabled = !tokenReady || isLoading;
    notificationResetBtn.disabled = !tokenReady || isLoading;
    notificationCancelEditBtn.disabled = !tokenReady || isLoading;
    Array.prototype.forEach.call(notificationForm.querySelectorAll("fieldset"), function (fieldset) {
      fieldset.disabled = !tokenReady || isLoading;
    });
    notificationAddBtn.disabled = !tokenReady || isLoading;
    Array.prototype.forEach.call(notificationsListBody.querySelectorAll("button[data-notification-action]"), function (button) {
      button.disabled = !tokenReady || isLoading;
    });

    var values = collectFormValues();
    var errors = getValidationErrors(values);
    renderValidation(errors);
    saveServiceBtn.disabled = !tokenReady || isLoading || Object.keys(errors).length > 0;
    renderBulkSelectionMeta();
    updateConnectionDetail();
  }

  function setAllServiceSelections(shouldSelect) {
    selectedServiceIds = {};
    if (shouldSelect) {
      currentServices.forEach(function (service) {
        if (service && service.id) selectedServiceIds[service.id] = true;
      });
    }
    renderServices(currentServices);
  }

  async function applyBulkEnabled(enabled, triggerButton, busyLabel) {
    if (!hasToken()) return;
    var ids = selectedServiceIdList();
    if (!ids.length) return;

    showError("");
    hideSaveMessage();

    await runAction(triggerButton, busyLabel, async function () {
      await requestJson(ADMIN_URL + "/bulk", {
        method: "POST",
        headers: adminHeaders(),
        body: JSON.stringify({
          ids: ids,
          enabled: !!enabled
        })
      }, true);

      selectedServiceIds = {};
      await loadServicesAndStatus();
    });
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
      loadAuditLog(),
      loadNotificationsConfig()
    ]);

    if (sideLoads[1].status !== "fulfilled") {
      setAuditMeta("Failed to load audit entries.");
    }
    if (sideLoads[2].status !== "fulfilled") {
      renderNotificationsMeta();
      renderNotificationsList();
      showNotificationsMessage("Failed to load notifications config.", true);
    }
  }

  tokenInput.addEventListener("input", function () {
    setAuthIndicator(false);
    showError("");
    auditEntries = [];
    selectedServiceIds = {};
    if (currentServices.length > 0) renderServices(currentServices);
    renderAuditEntries();
    renderNotificationsList();
    hideNotificationsMessage();
    setAuditMeta("Authenticate to load.");
    notificationsMeta.textContent = "Authenticate to load.";
    updateActionAvailability();
  });

  notificationsLoadBtn.addEventListener("click", async function () {
    if (!hasToken()) return;
    hideNotificationsMessage();
    showError("");
    await runAction(notificationsLoadBtn, "Loading...", async function () {
      await loadNotificationsConfig();
    });
  });

  notificationsSaveBtn.addEventListener("click", async function () {
    if (!hasToken()) return;
    hideNotificationsMessage();
    showError("");
    await runAction(notificationsSaveBtn, "Saving...", async function () {
      await saveNotificationsConfig();
      await loadNotificationsConfig();
      showNotificationsMessage("Notifications config saved.", false);
    });
  });

  notificationsTestBtn.addEventListener("click", async function () {
    if (!hasToken()) return;
    hideNotificationsMessage();
    showError("");
    await runAction(notificationsTestBtn, "Sending...", async function () {
      var payload = await sendTestNotification();
      var dispatched = payload && typeof payload.dispatched === "number" ? payload.dispatched : 0;
      showNotificationsMessage("Test queued. dispatched=" + dispatched + ".", false);
    });
  });

  notificationFields.auth_scheme.addEventListener("change", function () {
    setNotificationAuthVisibility(true);
    updateActionAvailability();
  });

  notificationForm.addEventListener("submit", function (evt) {
    evt.preventDefault();
    if (!hasToken() || isLoading) return;
    hideNotificationsMessage();
    var ok = upsertNotificationEndpoint();
    if (ok) showNotificationsMessage("Endpoint staged. Save notifications to persist.", false);
  });

  notificationResetBtn.addEventListener("click", function () {
    hideNotificationsMessage();
    if (notificationEditId) {
      applyNotificationEditMode(notificationEditId);
      return;
    }
    applyNotificationAddMode();
  });

  notificationCancelEditBtn.addEventListener("click", function () {
    hideNotificationsMessage();
    applyNotificationAddMode();
  });

  notificationsListBody.addEventListener("click", function (evt) {
    var button = evt.target.closest("button[data-notification-action]");
    if (!button || !hasToken() || isLoading) return;
    var row = button.closest("tr[data-notification-id]");
    if (!row) return;
    var endpointId = row.getAttribute("data-notification-id");
    var action = button.getAttribute("data-notification-action");
    hideNotificationsMessage();
    if (action === "edit") {
      applyNotificationEditMode(endpointId);
      return;
    }
    if (action === "delete") {
      deleteNotificationEndpoint(endpointId);
      showNotificationsMessage("Endpoint removed from staged config. Save notifications to persist.", false);
    }
  });

  loadServicesBtn.addEventListener("click", async function () {
    if (!hasToken()) return;
    showError("");

    await runAction(loadServicesBtn, "Loading...", async function () {
      await loadServicesAndStatus();
    });
  });

  bulkSelectAllBtn.addEventListener("click", function () {
    if (!hasToken() || isLoading || currentServices.length === 0) return;

    var selectedCount = selectedServiceIdList().length;
    var shouldClear = selectedCount > 0 && selectedCount === currentServices.length;
    setAllServiceSelections(!shouldClear);
  });

  bulkEnableBtn.addEventListener("click", async function () {
    await applyBulkEnabled(true, bulkEnableBtn, "Enabling...");
  });

  bulkDisableBtn.addEventListener("click", async function () {
    await applyBulkEnabled(false, bulkDisableBtn, "Disabling...");
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

  serviceListBody.addEventListener("change", function (evt) {
    var checkbox = evt.target.closest("input[data-service-select='1']");
    if (!checkbox) return;

    var serviceId = checkbox.getAttribute("data-service-id");
    if (!serviceId || !Object.prototype.hasOwnProperty.call(servicesById, serviceId)) return;

    if (checkbox.checked) selectedServiceIds[serviceId] = true;
    else delete selectedServiceIds[serviceId];

    updateActionAvailability();
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
  applyNotificationAddMode();
  renderBulkSelectionMeta();
  renderNotificationsMeta();
  renderNotificationsList();
  updateConnectionDetail();
  updateActionAvailability();

  refreshHealthPreview();
  setInterval(updateConnectionDetail, 30000);
  setInterval(refreshHealthPreview, HEALTH_POLL_INTERVAL);
  setInterval(function () {
    if (!hasToken() || !isAuthenticated || isLoading) return;
    loadAuditLog().catch(function () {
      setAuditMeta("Failed to refresh audit entries.");
    });
  }, AUDIT_POLL_INTERVAL);
})();
