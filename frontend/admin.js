(function () {
  "use strict";

  // --- constants + DOM refs -------------------------------------------------
  var API_BASE = window.MARCLE_API_BASE || "";
  var ENDPOINTS = {
    services: API_BASE + "/api/admin/services",
    servicesBulk: API_BASE + "/api/admin/services/bulk",
    audit: API_BASE + "/api/admin/audit?limit=200",
    notifications: API_BASE + "/api/admin/notifications",
    notificationsTest: API_BASE + "/api/admin/notifications/test",
    status: API_BASE + "/api/status",
    overview: API_BASE + "/api/overview"
  };

  var HEALTH_POLL_INTERVAL = 60000;
  var AUDIT_POLL_INTERVAL = 45000;
  var SEARCH_DEBOUNCE_MS = 150;

  var dom = {
    tokenInput: document.getElementById("admin-token"),
    connectBtn: document.getElementById("load-services-btn"),
    authStatusIndicator: document.getElementById("auth-status-indicator"),
    authConnectionDetail: document.getElementById("auth-connection-detail"),
    errorBox: document.getElementById("admin-error"),

    healthOverall: document.getElementById("admin-health-overall"),
    healthCountHealthy: document.getElementById("admin-health-count-healthy"),
    healthCountDegraded: document.getElementById("admin-health-count-degraded"),
    healthCountDown: document.getElementById("admin-health-count-down"),
    healthCountUnknown: document.getElementById("admin-health-count-unknown"),
    healthCacheAge: document.getElementById("admin-health-cache-age"),
    healthUpdatedAt: document.getElementById("admin-health-updated-at"),
    healthNote: document.getElementById("admin-health-note"),

    serviceListBody: document.getElementById("service-list-body"),
    serviceListMeta: document.getElementById("service-list-meta"),
    searchInput: document.getElementById("services-search-input"),
    groupFilter: document.getElementById("services-group-filter"),
    unhealthyOnlyToggle: document.getElementById("services-unhealthy-only"),
    sortSelect: document.getElementById("services-sort-select"),
    clearFiltersBtn: document.getElementById("clear-services-filters-btn"),
    secretsHealthFilterBtn: document.getElementById("secrets-health-filter-btn"),
    secretsHealthSummary: document.getElementById("secrets-health-summary"),
    newServiceBtn: document.getElementById("new-service-btn"),

    bulkSelectionMeta: document.getElementById("bulk-selection-meta"),
    bulkSelectAllBtn: document.getElementById("bulk-select-all-btn"),
    bulkEnableBtn: document.getElementById("bulk-enable-btn"),
    bulkDisableBtn: document.getElementById("bulk-disable-btn"),

    serviceFormHeading: document.getElementById("service-form-heading"),
    serviceFormModeNote: document.getElementById("service-form-mode-note"),
    serviceSaveMessage: document.getElementById("service-save-message"),
    serviceForm: document.getElementById("service-form"),
    saveServiceBtn: document.getElementById("save-service-btn"),
    resetServiceFormBtn: document.getElementById("reset-service-form-btn"),
    cancelEditBtn: document.getElementById("cancel-edit-btn"),
    serviceDeleteBtn: document.getElementById("service-delete-btn"),
    serviceRunCheckBtn: document.getElementById("service-run-check-btn"),
    serviceIdNote: document.getElementById("service-id-note"),
    serviceDangerZone: document.querySelector(".admin-danger-zone"),

    serviceAuthEnvWrap: document.getElementById("service-auth-env-wrap"),
    serviceAuthHeaderWrap: document.getElementById("service-auth-header-wrap"),
    serviceAuthParamWrap: document.getElementById("service-auth-param-wrap"),

    tabs: Array.prototype.slice.call(document.querySelectorAll("[data-admin-tab]")),
    tabPanels: {
      service: document.getElementById("admin-panel-service"),
      notifications: document.getElementById("admin-panel-notifications"),
      audit: document.getElementById("admin-panel-audit")
    },

    notificationsMeta: document.getElementById("notifications-meta"),
    notificationsLoadBtn: document.getElementById("notifications-load-btn"),
    notificationsEnabled: document.getElementById("notifications-enabled"),
    notificationsSaveBtn: document.getElementById("notifications-save-btn"),
    notificationsTestBtn: document.getElementById("notifications-test-btn"),
    notificationsMessage: document.getElementById("notifications-message"),
    notificationsListBody: document.getElementById("notifications-list-body"),
    notificationForm: document.getElementById("notification-form"),
    notificationFormHeading: document.getElementById("notification-form-heading"),
    notificationCancelEditBtn: document.getElementById("notification-cancel-edit-btn"),
    notificationAddBtn: document.getElementById("notification-add-btn"),
    notificationResetBtn: document.getElementById("notification-reset-btn"),
    notificationAuthEnvWrap: document.getElementById("notification-auth-env-wrap"),
    notificationAuthHeaderWrap: document.getElementById("notification-auth-header-wrap"),

    auditTableBody: document.getElementById("audit-table-body"),
    auditListMeta: document.getElementById("audit-list-meta"),
    auditRefreshBtn: document.getElementById("audit-refresh-btn"),
    auditActionFilter: document.getElementById("audit-action-filter"),
    auditSearchInput: document.getElementById("audit-search-input"),

    modalBackdrop: document.getElementById("confirm-modal-backdrop"),
    modal: document.getElementById("confirm-modal"),
    modalTitle: document.getElementById("confirm-modal-title"),
    modalMessage: document.getElementById("confirm-modal-message"),
    modalRequireWrap: document.getElementById("confirm-modal-require-wrap"),
    modalRequireLabel: document.getElementById("confirm-modal-require-label"),
    modalRequireInput: document.getElementById("confirm-modal-require-input"),
    modalCancelBtn: document.getElementById("confirm-modal-cancel-btn"),
    modalConfirmBtn: document.getElementById("confirm-modal-confirm-btn")
  };

  var serviceFields = {
    id: document.getElementById("service-id"),
    name: document.getElementById("service-name"),
    group: document.getElementById("service-group"),
    icon: document.getElementById("service-icon"),
    description: document.getElementById("service-description"),
    url: document.getElementById("service-url"),
    check_type: document.getElementById("service-check-type"),
    auth_scheme: document.getElementById("service-auth-scheme"),
    auth_env: document.getElementById("service-auth-env"),
    auth_header_name: document.getElementById("service-auth-header-name"),
    auth_param_name: document.getElementById("service-auth-param-name")
  };

  var serviceFieldErrors = {
    id: document.getElementById("service-id-error"),
    name: document.getElementById("service-name-error"),
    group: document.getElementById("service-group-error"),
    url: document.getElementById("service-url-error"),
    check_type: document.getElementById("service-check-type-error"),
    auth_env: document.getElementById("service-auth-env-error"),
    auth_header_name: document.getElementById("service-auth-header-name-error"),
    auth_param_name: document.getElementById("service-auth-param-name-error")
  };

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

  var requiredElements = [
    dom.tokenInput,
    dom.connectBtn,
    dom.authStatusIndicator,
    dom.serviceListBody,
    dom.serviceForm,
    dom.notificationsListBody,
    dom.auditTableBody,
    dom.modalBackdrop,
    dom.modalConfirmBtn,
    dom.modalRequireInput
  ];
  if (requiredElements.some(function (node) { return !node; })) {
    return;
  }

  // --- state ---------------------------------------------------------------
  var state = {
    auth: {
      token: "",
      connected: false,
      lastSuccessAt: null,
      capabilities: {
        runCheck: true
      }
    },
    data: {
      services: [],
      servicesById: {},
      healthById: {},
      overview: null,
      auditEntries: [],
      notificationsConfig: {
        enabled: false,
        endpoints: []
      }
    },
    selection: {
      selectedServiceId: null,
      bulkSelectedIds: {}
    },
    filters: {
      search: "",
      group: "all",
      onlyUnhealthy: false,
      sortBy: "health",
      missingSecretsOnly: false
    },
    ui: {
      activeTab: "service",
      groupCollapsed: {},
      loading: {
        services: false,
        saveService: false,
        notifications: false,
        audit: false,
        bulk: false,
        modalAction: false,
        runCheck: false
      },
      serviceEditorMode: "empty", // empty | add | edit
      notificationEditId: null,
      hasTriedServiceSave: false,
      touchedServiceFields: {},
      searchDebounceTimer: null
    },
    modal: {
      open: false,
      kind: null,
      title: "",
      message: "",
      requiredText: "",
      targetId: null,
      onConfirm: null,
      confirmLabel: "Confirm",
      lastFocused: null
    }
  };

  // --- helpers -------------------------------------------------------------
  var HEALTH_RANK = {
    down: 0,
    degraded: 1,
    unknown: 2,
    healthy: 3,
    disabled: 4
  };

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
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

  function normalizeStatus(statusValue) {
    if (!statusValue || typeof statusValue !== "string") return "unknown";
    var lowered = statusValue.trim().toLowerCase();
    if (lowered === "healthy" || lowered === "degraded" || lowered === "down" || lowered === "unknown") {
      return lowered;
    }
    return "unknown";
  }

  function titleCase(value) {
    if (!value) return "Unknown";
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function truncateValue(value, maxLen) {
    if (!value || typeof value !== "string") return "";
    if (value.length <= maxLen) return value;
    return value.slice(0, maxLen - 3) + "...";
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
      .filter(function (option) { return !!option.selected; })
      .map(function (option) { return option.value; });
  }

  function setSelectedValues(selectEl, values) {
    if (!selectEl) return;
    var selected = {};
    (values || []).forEach(function (value) {
      selected[value] = true;
    });
    Array.prototype.forEach.call(selectEl.options, function (option) {
      option.selected = !!selected[option.value];
    });
  }

  function hasToken() {
    return state.auth.token.trim().length > 0;
  }

  function anyLoading() {
    var loading = state.ui.loading;
    return !!(
      loading.services ||
      loading.saveService ||
      loading.notifications ||
      loading.audit ||
      loading.bulk ||
      loading.modalAction ||
      loading.runCheck
    );
  }

  function setLoading(key, value) {
    state.ui.loading[key] = !!value;
    renderActionState();
  }

  function debounceSearch(callback) {
    if (state.ui.searchDebounceTimer) {
      clearTimeout(state.ui.searchDebounceTimer);
    }
    state.ui.searchDebounceTimer = setTimeout(function () {
      state.ui.searchDebounceTimer = null;
      callback();
    }, SEARCH_DEBOUNCE_MS);
  }

  function setError(message) {
    if (!message) {
      dom.errorBox.textContent = "";
      dom.errorBox.className = "admin-alert is-hidden";
      return;
    }
    dom.errorBox.textContent = message;
    dom.errorBox.className = "admin-alert admin-alert-error";
  }

  var serviceMessageTimer = null;
  function showServiceMessage(message, isError) {
    if (serviceMessageTimer) {
      clearTimeout(serviceMessageTimer);
      serviceMessageTimer = null;
    }
    dom.serviceSaveMessage.textContent = message || "Done.";
    dom.serviceSaveMessage.className = isError
      ? "admin-alert admin-alert-error"
      : "admin-success";
    serviceMessageTimer = setTimeout(function () {
      dom.serviceSaveMessage.className = isError
        ? "admin-alert admin-alert-error is-hidden"
        : "admin-success is-hidden";
    }, 4200);
  }

  function hideServiceMessage() {
    if (serviceMessageTimer) {
      clearTimeout(serviceMessageTimer);
      serviceMessageTimer = null;
    }
    dom.serviceSaveMessage.textContent = "";
    dom.serviceSaveMessage.className = "admin-success is-hidden";
  }

  var notificationsMessageTimer = null;
  function showNotificationsMessage(message, isError) {
    if (notificationsMessageTimer) {
      clearTimeout(notificationsMessageTimer);
      notificationsMessageTimer = null;
    }
    dom.notificationsMessage.textContent = message || "Done.";
    dom.notificationsMessage.className = isError
      ? "admin-alert admin-alert-error"
      : "admin-success";
    notificationsMessageTimer = setTimeout(function () {
      dom.notificationsMessage.className = isError
        ? "admin-alert admin-alert-error is-hidden"
        : "admin-success is-hidden";
    }, 4200);
  }

  function hideNotificationsMessage() {
    if (notificationsMessageTimer) {
      clearTimeout(notificationsMessageTimer);
      notificationsMessageTimer = null;
    }
    dom.notificationsMessage.textContent = "";
    dom.notificationsMessage.className = "admin-success is-hidden";
  }

  function markConnected() {
    state.auth.connected = true;
    state.auth.lastSuccessAt = new Date().toISOString();
    renderHeader();
  }

  function setDisconnected() {
    state.auth.connected = false;
    renderHeader();
  }

  // --- API helper (adminFetch with bearer token) ---------------------------
  function buildAdminHeaders(extraHeaders) {
    var headers = {
      Authorization: "Bearer " + state.auth.token,
      "Content-Type": "application/json"
    };
    return Object.assign(headers, extraHeaders || {});
  }

  async function extractErrorDetail(response) {
    try {
      var payload = await response.json();
      if (!payload || typeof payload !== "object") return "";
      if (typeof payload.detail === "string") return payload.detail;
      return "";
    } catch (_err) {
      return "";
    }
  }

  function formatAdminError(statusCode, detail, contextLabel) {
    var context = contextLabel ? contextLabel + ": " : "";
    if (statusCode === 401 || statusCode === 403) {
      return context + "Invalid admin token. Update token and reconnect.";
    }
    if (statusCode === 503) {
      return context + "Admin API is disabled on server.";
    }
    if (statusCode === 404) {
      return context + "Requested resource was not found.";
    }
    if (statusCode === 409) {
      return context + "Conflict: a resource with this id already exists.";
    }
    if (statusCode === 400) {
      return context + (detail || "Request validation failed.") + " (HTTP 400)";
    }
    if (detail) {
      return context + detail + " (HTTP " + statusCode + ")";
    }
    return context + "Request failed (HTTP " + statusCode + ").";
  }

  async function adminFetch(path, options, config) {
    var opts = options || {};
    var cfg = config || {};
    var contextLabel = cfg.context || "";
    var expectJson = cfg.expectJson !== false;

    var response = await fetch(path, {
      method: opts.method || "GET",
      headers: buildAdminHeaders(opts.headers),
      body: opts.body,
      credentials: "same-origin"
    });

    if (!response.ok) {
      var detail = await extractErrorDetail(response);
      var message = formatAdminError(response.status, detail, contextLabel);
      if (response.status === 401 || response.status === 403) {
        setDisconnected();
      }
      var error = new Error(message);
      error.status = response.status;
      error.detail = detail;
      throw error;
    }

    markConnected();

    if (!expectJson || response.status === 204) {
      return null;
    }

    var contentType = response.headers.get("content-type") || "";
    if (contentType.indexOf("application/json") === -1) {
      return null;
    }

    return await response.json();
  }

  async function publicFetch(path) {
    var response = await fetch(path, { credentials: "same-origin" });
    if (!response.ok) {
      var err = new Error("Public status request failed (HTTP " + response.status + ").");
      err.status = response.status;
      throw err;
    }
    var contentType = response.headers.get("content-type") || "";
    if (contentType.indexOf("application/json") === -1) {
      return null;
    }
    return await response.json();
  }

  // --- selectors / derivations ---------------------------------------------
  function isServiceMissingSecret(service) {
    if (!service || !service.auth_ref || !service.auth_ref.scheme || service.auth_ref.scheme === "none") {
      return false;
    }
    return service.credential_present === false;
  }

  function healthPreviewForService(service) {
    if (!service || service.enabled === false) {
      return {
        statusClass: "disabled",
        statusLabel: "Disabled",
        latency: "--",
        checked: "--"
      };
    }

    var health = state.data.healthById[service.id];
    if (!health) {
      return {
        statusClass: "unknown",
        statusLabel: "Unknown",
        latency: "--",
        checked: "--"
      };
    }

    var statusClass = normalizeStatus(health.status);
    return {
      statusClass: statusClass,
      statusLabel: titleCase(statusClass),
      latency: health.latency_ms != null ? String(health.latency_ms) + "ms" : "--",
      checked: health.last_checked ? formatRelativeTime(health.last_checked) : "--"
    };
  }

  function serviceHealthSortValue(service) {
    var preview = healthPreviewForService(service);
    return HEALTH_RANK[preview.statusClass] != null ? HEALTH_RANK[preview.statusClass] : 99;
  }

  function serviceLatencySortValue(service) {
    var health = state.data.healthById[service.id];
    if (!health || typeof health.latency_ms !== "number") return -1;
    return health.latency_ms;
  }

  function getServiceGroups() {
    var unique = {};
    state.data.services.forEach(function (service) {
      if (service && service.group) unique[service.group] = true;
    });
    return Object.keys(unique).sort();
  }

  function getFilteredAndSortedServices() {
    var search = state.filters.search.trim().toLowerCase();

    var filtered = state.data.services.filter(function (service) {
      if (!service) return false;
      if (state.filters.group !== "all" && service.group !== state.filters.group) {
        return false;
      }

      if (state.filters.missingSecretsOnly && !isServiceMissingSecret(service)) {
        return false;
      }

      if (state.filters.onlyUnhealthy) {
        var preview = healthPreviewForService(service);
        var unhealthy = preview.statusClass === "degraded" || preview.statusClass === "down" || preview.statusClass === "unknown";
        if (!unhealthy) return false;
      }

      if (!search) return true;
      var haystack = [service.name || "", service.id || "", service.group || ""].join(" ").toLowerCase();
      return haystack.indexOf(search) !== -1;
    });

    filtered.sort(function (left, right) {
      if (state.filters.sortBy === "name") {
        var leftName = String(left.name || left.id || "").toLowerCase();
        var rightName = String(right.name || right.id || "").toLowerCase();
        return leftName.localeCompare(rightName);
      }

      if (state.filters.sortBy === "latency") {
        var leftLatency = serviceLatencySortValue(left);
        var rightLatency = serviceLatencySortValue(right);
        if (leftLatency !== rightLatency) return rightLatency - leftLatency;
        var leftLatencyName = String(left.name || left.id || "").toLowerCase();
        var rightLatencyName = String(right.name || right.id || "").toLowerCase();
        return leftLatencyName.localeCompare(rightLatencyName);
      }

      var healthOrderDiff = serviceHealthSortValue(left) - serviceHealthSortValue(right);
      if (healthOrderDiff !== 0) return healthOrderDiff;
      var leftHealthName = String(left.name || left.id || "").toLowerCase();
      var rightHealthName = String(right.name || right.id || "").toLowerCase();
      return leftHealthName.localeCompare(rightHealthName);
    });

    return filtered;
  }

  function groupServices(services) {
    var grouped = {};
    services.forEach(function (service) {
      var group = service.group || "other";
      if (!grouped[group]) grouped[group] = [];
      grouped[group].push(service);
    });
    return grouped;
  }

  function syncBulkSelectionToServices() {
    var next = {};
    state.data.services.forEach(function (service) {
      if (service && service.id && state.selection.bulkSelectedIds[service.id]) {
        next[service.id] = true;
      }
    });
    state.selection.bulkSelectedIds = next;
  }

  function setServiceEditorMode(mode, serviceId) {
    var resolvedMode = mode;
    if (resolvedMode === "edit") {
      if (!serviceId || !state.data.servicesById[serviceId]) {
        resolvedMode = "empty";
      }
    }

    state.ui.serviceEditorMode = resolvedMode;

    if (resolvedMode === "edit") {
      state.selection.selectedServiceId = serviceId;
    } else if (resolvedMode === "add") {
      state.selection.selectedServiceId = null;
    }

    clearServiceValidation();
    hideServiceMessage();
    renderServices();
    renderServiceEditor();
    renderActionState();
  }

  // --- renderers ------------------------------------------------------------
  function renderHeader() {
    var overview = state.data.overview || null;
    var overallStatus = normalizeStatus(
      overview && overview.overall_status
        ? overview.overall_status
        : "unknown"
    );

    dom.healthOverall.className = "admin-status-badge " + overallStatus;
    dom.healthOverall.textContent = titleCase(overallStatus);

    var counts = overview && overview.counts ? overview.counts : {
      healthy: 0,
      degraded: 0,
      down: 0,
      unknown: 0
    };

    dom.healthCountHealthy.textContent = "H " + (counts.healthy || 0);
    dom.healthCountDegraded.textContent = "Dg " + (counts.degraded || 0);
    dom.healthCountDown.textContent = "Dn " + (counts.down || 0);
    dom.healthCountUnknown.textContent = "U " + (counts.unknown || 0);

    dom.healthCacheAge.textContent =
      overview && typeof overview.cache_age_seconds === "number"
        ? humanizeDuration(overview.cache_age_seconds)
        : "--";

    var updatedAt = overview && overview.last_refresh_at
      ? overview.last_refresh_at
      : null;
    dom.healthUpdatedAt.textContent = updatedAt ? formatRelativeTime(updatedAt) : "--";

    if (state.auth.connected) {
      dom.authStatusIndicator.textContent = "Connected";
      dom.authStatusIndicator.className = "admin-chip admin-chip-success";
      dom.authConnectionDetail.textContent = "Connected to admin API. Last success " + formatRelativeTime(state.auth.lastSuccessAt) + ".";
    } else if (hasToken()) {
      dom.authStatusIndicator.textContent = "Token present";
      dom.authStatusIndicator.className = "admin-chip admin-chip-warning";
      dom.authConnectionDetail.textContent = "Token present but not verified. Click Connect.";
    } else {
      dom.authStatusIndicator.textContent = "Not connected";
      dom.authStatusIndicator.className = "admin-chip admin-chip-muted";
      dom.authConnectionDetail.textContent = "No successful admin requests yet.";
    }
  }

  function renderGroupFilterOptions() {
    var groups = getServiceGroups();
    var existingValue = state.filters.group;
    dom.groupFilter.innerHTML = "<option value='all'>All groups</option>" + groups.map(function (group) {
      return "<option value='" + escapeHtml(group) + "'>" + escapeHtml(group) + "</option>";
    }).join("");

    if (existingValue !== "all" && groups.indexOf(existingValue) === -1) {
      state.filters.group = "all";
    }
    dom.groupFilter.value = state.filters.group;
  }

  function renderSecretsSummary() {
    var missingCount = state.data.services.filter(isServiceMissingSecret).length;
    dom.secretsHealthSummary.textContent = "Missing secrets: " + missingCount;
    dom.secretsHealthFilterBtn.textContent = state.filters.missingSecretsOnly
      ? "Show all services"
      : "Filter missing secrets";
  }

  function authBadgeForService(service) {
    if (!service.auth_ref || !service.auth_ref.scheme || service.auth_ref.scheme === "none") {
      return { className: "admin-chip-muted", label: "Auth: N/A" };
    }
    if (service.credential_present === true) {
      return { className: "admin-chip-success", label: "Auth: OK" };
    }
    return { className: "admin-chip-danger", label: "Auth: Missing" };
  }

  function renderServices() {
    renderGroupFilterOptions();
    renderSecretsSummary();

    var services = getFilteredAndSortedServices();
    var grouped = groupServices(services);
    var groups = Object.keys(grouped).sort();

    dom.serviceListMeta.textContent = state.data.services.length
      ? services.length + " services shown of " + state.data.services.length + "."
      : "No services loaded.";

    if (!services.length) {
      var emptyMessage = hasToken()
        ? "No services match current filters."
        : "Connect to load services.";
      dom.serviceListBody.innerHTML = "<tr><td class='admin-empty' colspan='8'>" + escapeHtml(emptyMessage) + "</td></tr>";
      renderBulkMeta(services);
      renderActionState();
      return;
    }

    var disabledAttr = (!hasToken() || anyLoading()) ? " disabled" : "";
    var rows = [];

    groups.forEach(function (groupName) {
      var collapsed = !!state.ui.groupCollapsed[groupName];
      rows.push(
        "<tr class='admin-group-row' data-group='" + escapeHtml(groupName) + "'>" +
          "<td colspan='8'>" +
            "<button type='button' class='admin-group-toggle' data-group-toggle='" + escapeHtml(groupName) + "'" + disabledAttr + ">" +
              "<span class='admin-group-caret" + (collapsed ? " is-collapsed" : "") + "'>v</span>" +
              "<span class='admin-group-title'>" + escapeHtml(groupName) + "</span>" +
              "<span class='admin-group-count'>" + grouped[groupName].length + "</span>" +
            "</button>" +
          "</td>" +
        "</tr>"
      );

      if (collapsed) {
        return;
      }

      grouped[groupName].forEach(function (service) {
        var preview = healthPreviewForService(service);
        var authBadge = authBadgeForService(service);
        var isSelected = state.selection.selectedServiceId === service.id;
        var isChecked = !!state.selection.bulkSelectedIds[service.id];

        rows.push(
          "<tr class='admin-service-row" + (isSelected ? " is-selected" : "") + "' data-service-id='" + escapeHtml(service.id) + "'>" +
            "<td class='admin-select-cell'>" +
              "<input type='checkbox' class='admin-row-select' data-service-select='" + escapeHtml(service.id) + "'" + (isChecked ? " checked" : "") + disabledAttr + ">" +
            "</td>" +
            "<td>" +
              "<span class='admin-service-name'>" + escapeHtml(service.name || service.id) + "</span>" +
              "<span class='admin-service-id'>" + escapeHtml(service.id) + "</span>" +
            "</td>" +
            "<td><span class='admin-chip admin-chip-muted'>" + escapeHtml(service.group || "core") + "</span></td>" +
            "<td><span class='admin-status-badge " + escapeHtml(preview.statusClass) + "'>" + escapeHtml(preview.statusLabel) + "</span></td>" +
            "<td><div class='admin-health-meta-stack'>" +
              "<span class='admin-health-latency'>" + escapeHtml(preview.latency) + "</span>" +
              "<span class='admin-health-checked'>" + escapeHtml(preview.checked) + "</span>" +
            "</div></td>" +
            "<td>" +
              "<button type='button' class='admin-toggle-button " + (service.enabled ? "is-enabled" : "is-disabled") + "' data-service-action='toggle' data-service-id='" + escapeHtml(service.id) + "'" + disabledAttr + ">" +
                (service.enabled ? "Enabled" : "Disabled") +
              "</button>" +
            "</td>" +
            "<td><span class='admin-chip " + authBadge.className + "'>" + escapeHtml(authBadge.label) + "</span></td>" +
            "<td class='admin-row-actions'>" +
              "<button type='button' class='admin-button admin-button-small' data-service-action='edit' data-service-id='" + escapeHtml(service.id) + "'" + disabledAttr + ">Edit</button>" +
              "<button type='button' class='admin-button admin-button-small admin-button-danger-ghost' data-service-action='delete' data-service-id='" + escapeHtml(service.id) + "'" + disabledAttr + ">Delete</button>" +
            "</td>" +
          "</tr>"
        );
      });
    });

    dom.serviceListBody.innerHTML = rows.join("");
    renderBulkMeta(services);
    renderActionState();
  }

  function renderBulkMeta(visibleServices) {
    var visibleIds = (visibleServices || []).map(function (service) { return service.id; });
    var selectedVisibleCount = visibleIds.filter(function (id) {
      return !!state.selection.bulkSelectedIds[id];
    }).length;

    if (!visibleIds.length) {
      dom.bulkSelectionMeta.textContent = "No services selected.";
      dom.bulkSelectAllBtn.textContent = "Select all";
      return;
    }

    dom.bulkSelectionMeta.textContent = selectedVisibleCount + " selected of " + visibleIds.length + " shown.";
    dom.bulkSelectAllBtn.textContent = (selectedVisibleCount > 0 && selectedVisibleCount === visibleIds.length)
      ? "Clear selection"
      : "Select all";
  }

  function renderTabs() {
    dom.tabs.forEach(function (tabButton) {
      var tabName = tabButton.getAttribute("data-admin-tab");
      var active = tabName === state.ui.activeTab;
      tabButton.classList.toggle("is-active", active);
      tabButton.setAttribute("aria-selected", active ? "true" : "false");
    });

    Object.keys(dom.tabPanels).forEach(function (tabName) {
      var panel = dom.tabPanels[tabName];
      if (!panel) return;
      panel.classList.toggle("is-active", tabName === state.ui.activeTab);
    });
  }

  function setServiceAuthVisibility(clearHiddenValues) {
    var scheme = serviceFields.auth_scheme.value || "none";
    var showEnv = scheme !== "none";
    var showHeader = scheme === "header";
    var showParam = scheme === "query_param";

    dom.serviceAuthEnvWrap.classList.toggle("is-hidden", !showEnv);
    dom.serviceAuthHeaderWrap.classList.toggle("is-hidden", !showHeader);
    dom.serviceAuthParamWrap.classList.toggle("is-hidden", !showParam);

    if (clearHiddenValues) {
      if (!showEnv) serviceFields.auth_env.value = "";
      if (!showHeader) serviceFields.auth_header_name.value = "";
      if (!showParam) serviceFields.auth_param_name.value = "";
    }
  }

  function maybeDefaultAuthForCheckType(checkTypeValue) {
    var checkType = String(checkTypeValue || "").trim().toLowerCase();
    var scheme = String(serviceFields.auth_scheme.value || "").trim().toLowerCase();

    if (checkType === "tautulli" && (scheme === "" || scheme === "none")) {
      serviceFields.auth_scheme.value = "query_param";
      if (!serviceFields.auth_env.value.trim()) {
        serviceFields.auth_env.value = "TAUTULLI_API_KEY";
      }
      if (!serviceFields.auth_param_name.value.trim()) {
        serviceFields.auth_param_name.value = "apikey";
      }
      setServiceAuthVisibility(false);
    }
  }

  function collectServiceFormValues() {
    return {
      id: serviceFields.id.value.trim(),
      name: serviceFields.name.value.trim(),
      group: serviceFields.group.value.trim(),
      icon: serviceFields.icon.value.trim(),
      description: serviceFields.description.value.trim(),
      url: serviceFields.url.value.trim(),
      check_type: serviceFields.check_type.value.trim(),
      auth_scheme: (serviceFields.auth_scheme.value || "none").trim(),
      auth_env: serviceFields.auth_env.value.trim(),
      auth_header_name: serviceFields.auth_header_name.value.trim(),
      auth_param_name: serviceFields.auth_param_name.value.trim()
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

  function validateServiceForm(values) {
    var errors = {};

    if (!values.id) errors.id = "ID is required.";
    else if (/\s/.test(values.id)) errors.id = "ID cannot contain spaces.";

    if (!values.name) errors.name = "Name is required.";
    if (!values.group) errors.group = "Group is required.";

    if (!values.url) errors.url = "URL is required.";
    else if (!isValidUrl(values.url)) errors.url = "URL must use http:// or https://.";

    if (!values.check_type) errors.check_type = "Check type is required.";

    if (state.ui.serviceEditorMode === "add" && values.id && state.data.servicesById[values.id]) {
      errors.id = "A service with this ID already exists.";
    }

    if (state.ui.serviceEditorMode === "edit" && values.id !== state.selection.selectedServiceId) {
      errors.id = "ID cannot be changed while editing.";
    }

    if (values.auth_scheme !== "none" && !values.auth_env) {
      errors.auth_env = "Auth env var is required for this auth scheme.";
    }

    if (values.auth_scheme === "header" && !values.auth_header_name) {
      errors.auth_header_name = "Header name is required for header auth.";
    }

    if (values.auth_scheme === "query_param" && !values.auth_param_name) {
      errors.auth_param_name = "Query param name is required for query param auth.";
    }

    return errors;
  }

  function setServiceFieldError(fieldName, message) {
    var node = serviceFieldErrors[fieldName];
    var input = serviceFields[fieldName];
    if (!node || !input) return;

    var shouldShow = !!message && (state.ui.hasTriedServiceSave || !!state.ui.touchedServiceFields[fieldName]);
    if (fieldName === "auth_env" && dom.serviceAuthEnvWrap.classList.contains("is-hidden")) shouldShow = false;
    if (fieldName === "auth_header_name" && dom.serviceAuthHeaderWrap.classList.contains("is-hidden")) shouldShow = false;
    if (fieldName === "auth_param_name" && dom.serviceAuthParamWrap.classList.contains("is-hidden")) shouldShow = false;

    node.textContent = shouldShow ? message : "";
    input.setAttribute("aria-invalid", shouldShow ? "true" : "false");
  }

  function renderServiceValidation(errors) {
    Object.keys(serviceFieldErrors).forEach(function (fieldName) {
      setServiceFieldError(fieldName, errors[fieldName] || "");
    });
  }

  function clearServiceValidation() {
    state.ui.hasTriedServiceSave = false;
    state.ui.touchedServiceFields = {};
    Object.keys(serviceFieldErrors).forEach(function (fieldName) {
      var node = serviceFieldErrors[fieldName];
      if (node) node.textContent = "";
      if (serviceFields[fieldName]) {
        serviceFields[fieldName].setAttribute("aria-invalid", "false");
      }
    });
  }

  function buildServiceAuthRef(values) {
    if (!values.auth_scheme || values.auth_scheme === "none") {
      return null;
    }
    var authRef = {
      scheme: values.auth_scheme,
      env: values.auth_env
    };
    if (values.auth_scheme === "header") authRef.header_name = values.auth_header_name;
    if (values.auth_scheme === "query_param") authRef.param_name = values.auth_param_name;
    return authRef;
  }

  function buildServicePayload(values, existingService) {
    var payload = {
      id: values.id,
      name: values.name,
      group: values.group,
      url: values.url,
      check_type: values.check_type,
      enabled: existingService ? !!existingService.enabled : true,
      icon: values.icon || null,
      description: values.description || null,
      auth_ref: buildServiceAuthRef(values)
    };

    // Preserve advanced service fields that are not currently editable in the UI.
    if (existingService && Object.prototype.hasOwnProperty.call(existingService, "path")) {
      payload.path = existingService.path;
    }
    if (existingService && Object.prototype.hasOwnProperty.call(existingService, "verify_ssl")) {
      payload.verify_ssl = !!existingService.verify_ssl;
    }
    if (existingService && Object.prototype.hasOwnProperty.call(existingService, "healthy_status_codes")) {
      payload.healthy_status_codes = Array.isArray(existingService.healthy_status_codes)
        ? existingService.healthy_status_codes.slice()
        : existingService.healthy_status_codes;
    }

    return payload;
  }

  function fillServiceFormFromService(service) {
    serviceFields.id.value = service.id || "";
    serviceFields.name.value = service.name || "";
    serviceFields.group.value = service.group || "core";
    serviceFields.icon.value = service.icon || "";
    serviceFields.description.value = service.description || "";
    serviceFields.url.value = service.url || "";
    serviceFields.check_type.value = service.check_type || "";

    var authRef = service.auth_ref || null;
    serviceFields.auth_scheme.value = authRef && authRef.scheme ? authRef.scheme : "none";
    serviceFields.auth_env.value = authRef && authRef.env ? authRef.env : "";
    serviceFields.auth_header_name.value = authRef && authRef.header_name ? authRef.header_name : "";
    serviceFields.auth_param_name.value = authRef && authRef.param_name ? authRef.param_name : "";

    maybeDefaultAuthForCheckType(serviceFields.check_type.value);
    setServiceAuthVisibility(false);
  }

  function resetServiceFormForAdd() {
    dom.serviceForm.reset();
    serviceFields.group.value = "core";
    serviceFields.auth_scheme.value = "none";
    serviceFields.auth_env.value = "";
    serviceFields.auth_header_name.value = "";
    serviceFields.auth_param_name.value = "";
    setServiceAuthVisibility(true);
  }

  function renderServiceEditor() {
    var mode = state.ui.serviceEditorMode;
    var service = state.selection.selectedServiceId
      ? state.data.servicesById[state.selection.selectedServiceId]
      : null;

    if (mode === "edit" && !service) {
      mode = "empty";
      state.ui.serviceEditorMode = "empty";
      state.selection.selectedServiceId = null;
    }

    if (mode === "empty") {
      dom.serviceFormHeading.textContent = "Service Editor";
      dom.serviceFormModeNote.textContent = "Select a service from the table or click New service to create one.";
      dom.cancelEditBtn.classList.add("is-hidden");
      dom.serviceIdNote.classList.add("is-hidden");
      dom.saveServiceBtn.textContent = "Add service";
      dom.serviceRunCheckBtn.classList.add("is-hidden");
      dom.serviceForm.classList.add("is-hidden");
      dom.serviceDangerZone.classList.add("is-hidden");
      clearServiceValidation();
      renderActionState();
      return;
    }

    dom.serviceForm.classList.remove("is-hidden");

    if (mode === "add") {
      dom.serviceFormHeading.textContent = "Add Service";
      dom.serviceFormModeNote.textContent = "Create a new service entry.";
      dom.saveServiceBtn.textContent = "Add service";
      dom.cancelEditBtn.classList.add("is-hidden");
      dom.serviceIdNote.classList.add("is-hidden");
      dom.serviceDangerZone.classList.add("is-hidden");
      dom.serviceRunCheckBtn.classList.add("is-hidden");
      serviceFields.id.readOnly = false;
      resetServiceFormForAdd();
      clearServiceValidation();
      renderActionState();
      return;
    }

    dom.serviceFormHeading.textContent = "Edit Service";
    dom.serviceFormModeNote.textContent = "Editing '" + (service.name || service.id) + "'.";
    dom.saveServiceBtn.textContent = "Save changes";
    dom.cancelEditBtn.classList.remove("is-hidden");
    dom.serviceIdNote.classList.remove("is-hidden");
    dom.serviceDangerZone.classList.remove("is-hidden");
    serviceFields.id.readOnly = true;
    fillServiceFormFromService(service);
    clearServiceValidation();

    var canRunCheck = state.auth.capabilities.runCheck;
    dom.serviceRunCheckBtn.classList.toggle("is-hidden", !canRunCheck);
    renderActionState();
  }

  function renderNotificationAuthVisibility(clearHiddenValues) {
    var scheme = notificationFields.auth_scheme.value || "none";
    var showEnv = scheme !== "none";
    var showHeader = scheme === "header";
    dom.notificationAuthEnvWrap.classList.toggle("is-hidden", !showEnv);
    dom.notificationAuthHeaderWrap.classList.toggle("is-hidden", !showHeader);

    if (clearHiddenValues) {
      if (!showEnv) notificationFields.auth_env.value = "";
      if (!showHeader) notificationFields.auth_header_name.value = "";
    }
  }

  function collectNotificationFormValues() {
    var events = [];
    if (notificationFields.event_incident.checked) events.push("incident");
    if (notificationFields.event_recovery.checked) events.push("recovery");
    if (notificationFields.event_flapping.checked) events.push("flapping");

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

  function validateNotificationForm(values) {
    if (!values.id) return "Notification ID is required.";
    if (/\s/.test(values.id)) return "Notification ID cannot contain spaces.";
    if (!values.url) return "Notification URL is required.";
    if (!isValidUrl(values.url)) return "Notification URL must use http:// or https://.";
    if (!values.events.length) return "Select at least one event type.";
    if (values.auth_scheme !== "none" && !values.auth_env) return "Auth env var is required for this auth scheme.";
    if (values.auth_scheme === "header" && !values.auth_header_name) return "Header name is required for header auth.";

    var duplicate = state.data.notificationsConfig.endpoints.some(function (endpoint) {
      if (!endpoint || !endpoint.id) return false;
      if (state.ui.notificationEditId && endpoint.id === state.ui.notificationEditId) return false;
      return endpoint.id === values.id;
    });
    if (duplicate) return "A notification endpoint with this ID already exists.";

    if (state.ui.notificationEditId && values.id !== state.ui.notificationEditId) {
      return "ID cannot be changed while editing.";
    }

    return "";
  }

  function buildNotificationAuthRef(values) {
    if (!values.auth_scheme || values.auth_scheme === "none") return null;
    var authRef = {
      scheme: values.auth_scheme,
      env: values.auth_env
    };
    if (values.auth_scheme === "header") {
      authRef.header_name = values.auth_header_name;
    }
    return authRef;
  }

  function buildNotificationPayload(values) {
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

  function resetNotificationForm() {
    dom.notificationForm.reset();
    notificationFields.event_incident.checked = true;
    notificationFields.event_recovery.checked = false;
    notificationFields.event_flapping.checked = false;
    notificationFields.min_severity.value = "any";
    notificationFields.cooldown_seconds.value = "0";
    notificationFields.auth_scheme.value = "none";
    notificationFields.auth_env.value = "";
    notificationFields.auth_header_name.value = "";
    notificationFields.service_ids.value = "";
    setSelectedValues(notificationFields.groups, []);
    renderNotificationAuthVisibility(true);
  }

  function applyNotificationAddMode() {
    state.ui.notificationEditId = null;
    dom.notificationFormHeading.textContent = "Add Notification Endpoint";
    dom.notificationAddBtn.textContent = "Add endpoint";
    dom.notificationCancelEditBtn.classList.add("is-hidden");
    notificationFields.id.readOnly = false;
    resetNotificationForm();
    renderActionState();
  }

  function applyNotificationEditMode(endpointId) {
    var endpoint = state.data.notificationsConfig.endpoints.find(function (item) {
      return item && item.id === endpointId;
    });
    if (!endpoint) {
      setError("Notification endpoint not found.");
      return;
    }

    state.ui.notificationEditId = endpoint.id;
    dom.notificationFormHeading.textContent = "Edit Notification Endpoint";
    dom.notificationAddBtn.textContent = "Save endpoint";
    dom.notificationCancelEditBtn.classList.remove("is-hidden");
    notificationFields.id.readOnly = true;

    notificationFields.id.value = endpoint.id || "";
    notificationFields.url.value = endpoint.url || "";

    var events = Array.isArray(endpoint.events) ? endpoint.events : [];
    notificationFields.event_incident.checked = events.indexOf("incident") !== -1;
    notificationFields.event_recovery.checked = events.indexOf("recovery") !== -1;
    notificationFields.event_flapping.checked = events.indexOf("flapping") !== -1;

    var filters = endpoint.filters || {};
    setSelectedValues(notificationFields.groups, filters.groups || []);
    notificationFields.service_ids.value = Array.isArray(filters.service_ids)
      ? filters.service_ids.join(", ")
      : "";
    notificationFields.min_severity.value = filters.min_severity || "any";
    notificationFields.cooldown_seconds.value = String(typeof filters.cooldown_seconds === "number" ? filters.cooldown_seconds : 0);

    var authRef = endpoint.auth_ref || null;
    notificationFields.auth_scheme.value = authRef && authRef.scheme ? authRef.scheme : "none";
    notificationFields.auth_env.value = authRef && authRef.env ? authRef.env : "";
    notificationFields.auth_header_name.value = authRef && authRef.header_name ? authRef.header_name : "";

    renderNotificationAuthVisibility(false);
    renderActionState();
  }

  function currentNotificationsConfigPayload() {
    return {
      enabled: !!dom.notificationsEnabled.checked,
      endpoints: (state.data.notificationsConfig.endpoints || []).map(function (endpoint) {
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

  function renderNotificationsMeta() {
    var endpoints = state.data.notificationsConfig.endpoints || [];
    dom.notificationsMeta.textContent = endpoints.length + " endpoint" + (endpoints.length === 1 ? "" : "s") +
      (state.data.notificationsConfig.enabled ? " | enabled" : " | disabled");
  }

  function notificationAuthBadge(endpoint) {
    if (!endpoint || !endpoint.auth_ref || !endpoint.auth_ref.scheme || endpoint.auth_ref.scheme === "none") {
      return { className: "admin-chip-muted", label: "Auth: N/A" };
    }
    if (endpoint.credential_present === true) {
      return { className: "admin-chip-success", label: "Auth: OK" };
    }
    return { className: "admin-chip-danger", label: "Auth: Missing" };
  }

  function renderNotificationsList() {
    if (!state.auth.connected) {
      dom.notificationsListBody.innerHTML = "<tr><td class='admin-empty' colspan='6'>Authenticate to load notification endpoints.</td></tr>";
      return;
    }

    var endpoints = state.data.notificationsConfig.endpoints || [];
    if (!endpoints.length) {
      dom.notificationsListBody.innerHTML = "<tr><td class='admin-empty' colspan='6'>No notification endpoints configured.</td></tr>";
      return;
    }

    var disabledAttr = (!hasToken() || anyLoading()) ? " disabled" : "";

    dom.notificationsListBody.innerHTML = endpoints.map(function (endpoint) {
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
            "<span class='admin-table-text'>min: " + escapeHtml(minSeverity) + " | cooldown: " + escapeHtml(String(cooldown)) + "s</span>" +
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

  function normalizeAuditAction(value) {
    if (!value || typeof value !== "string") return "";
    var lowered = value.toLowerCase();
    if (
      lowered === "create" ||
      lowered === "update" ||
      lowered === "delete" ||
      lowered === "toggle" ||
      lowered === "bulk" ||
      lowered === "notifications_update" ||
      lowered === "notifications_test"
    ) {
      return lowered;
    }
    return "";
  }

  function getFilteredAuditEntries() {
    var actionFilter = (dom.auditActionFilter.value || "").trim().toLowerCase();
    var search = (dom.auditSearchInput.value || "").trim().toLowerCase();

    return state.data.auditEntries.filter(function (entry) {
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

  function renderAudit() {
    if (!state.auth.connected) {
      dom.auditTableBody.innerHTML = "<tr><td class='admin-empty' colspan='5'>Authenticate to load audit entries.</td></tr>";
      dom.auditListMeta.textContent = "Authenticate to load.";
      return;
    }

    if (!state.data.auditEntries.length) {
      dom.auditTableBody.innerHTML = "<tr><td class='admin-empty' colspan='5'>No audit entries found.</td></tr>";
      dom.auditListMeta.textContent = "0 entries.";
      return;
    }

    var filtered = getFilteredAuditEntries();
    if (!filtered.length) {
      dom.auditTableBody.innerHTML = "<tr><td class='admin-empty' colspan='5'>No rows match current filters.</td></tr>";
      dom.auditListMeta.textContent = "0 entries shown of " + state.data.auditEntries.length + ".";
      return;
    }

    dom.auditTableBody.innerHTML = filtered.map(function (entry, index) {
      var action = normalizeAuditAction(entry && entry.action) || "unknown";
      var target = entry && typeof entry.service_id === "string" ? entry.service_id : "bulk";
      var details = auditDetailsForEntry(entry);
      var ip = entry && typeof entry.ip === "string" ? entry.ip : "--";
      var userAgent = entry && typeof entry.user_agent === "string" ? entry.user_agent : "--";

      return (
        "<tr data-audit-index='" + index + "'>" +
          "<td><span class='admin-table-text'>" + escapeHtml(formatAuditTimestamp(entry && entry.ts)) + "</span></td>" +
          "<td><span class='admin-status-badge unknown'>" + escapeHtml(action) + "</span></td>" +
          "<td><span class='admin-audit-target'>" + escapeHtml(target) + "</span></td>" +
          "<td><div class='admin-audit-detail-wrap'>" +
            "<span class='admin-audit-detail'>" + escapeHtml(details) + "</span>" +
            "<button type='button' class='admin-button admin-button-quiet admin-copy-json' data-audit-copy='1'>Copy JSON</button>" +
          "</div></td>" +
          "<td><div class='admin-audit-source'>" +
            "<span class='admin-table-text'>" + escapeHtml(truncateValue(ip, 96)) + "</span>" +
            "<span class='admin-table-text'>" + escapeHtml(truncateValue(userAgent, 140)) + "</span>" +
          "</div></td>" +
        "</tr>"
      );
    }).join("");

    dom.auditListMeta.textContent = filtered.length + " entries shown of " + state.data.auditEntries.length + ".";
  }

  function renderModal() {
    if (!state.modal.open) {
      dom.modalBackdrop.classList.add("is-hidden");
      dom.modalBackdrop.hidden = true;
      document.body.classList.remove("admin-modal-open");
      dom.modalRequireInput.value = "";
      return;
    }

    dom.modalTitle.textContent = state.modal.title || "Confirm action";
    dom.modalMessage.textContent = state.modal.message || "";
    dom.modalConfirmBtn.textContent = state.modal.confirmLabel || "Confirm";

    var requireText = state.modal.requiredText || "";
    var needsTypedConfirm = requireText.length > 0;
    dom.modalRequireWrap.classList.toggle("is-hidden", !needsTypedConfirm);
    dom.modalRequireLabel.textContent = needsTypedConfirm
      ? "Type '" + requireText + "' to confirm"
      : "Type to confirm";

    dom.modalBackdrop.hidden = false;
    dom.modalBackdrop.classList.remove("is-hidden");
    document.body.classList.add("admin-modal-open");

    updateModalConfirmState();
  }

  function updateModalConfirmState() {
    var requireText = state.modal.requiredText || "";
    var inputValue = (dom.modalRequireInput.value || "").trim();
    var matched = !requireText || inputValue === requireText;
    dom.modalConfirmBtn.disabled = !matched || state.ui.loading.modalAction;
    dom.modalCancelBtn.disabled = state.ui.loading.modalAction;
    dom.modalRequireInput.disabled = state.ui.loading.modalAction;
  }

  function openConfirmModal(config) {
    state.modal.open = true;
    state.modal.kind = config.kind || "confirm";
    state.modal.title = config.title || "Confirm action";
    state.modal.message = config.message || "";
    state.modal.requiredText = config.requiredText || "";
    state.modal.targetId = config.targetId || null;
    state.modal.onConfirm = config.onConfirm || null;
    state.modal.confirmLabel = config.confirmLabel || "Confirm";
    state.modal.lastFocused = document.activeElement;

    dom.modalRequireInput.value = "";
    renderModal();

    if (state.modal.requiredText) {
      dom.modalRequireInput.focus();
    } else {
      dom.modalConfirmBtn.focus();
    }
  }

  function closeConfirmModal() {
    state.modal.open = false;
    state.modal.kind = null;
    state.modal.title = "";
    state.modal.message = "";
    state.modal.requiredText = "";
    state.modal.targetId = null;
    state.modal.onConfirm = null;
    state.modal.confirmLabel = "Confirm";
    state.ui.loading.modalAction = false;

    renderModal();
    renderActionState();

    if (state.modal.lastFocused && typeof state.modal.lastFocused.focus === "function" && document.contains(state.modal.lastFocused)) {
      state.modal.lastFocused.focus();
    }
    state.modal.lastFocused = null;
  }

  function renderActionState() {
    var tokenReady = hasToken();
    var busy = anyLoading();

    dom.connectBtn.disabled = !tokenReady || state.ui.loading.services;
    dom.newServiceBtn.disabled = !tokenReady || busy;

    dom.searchInput.disabled = !tokenReady || busy;
    dom.groupFilter.disabled = !tokenReady || busy;
    dom.unhealthyOnlyToggle.disabled = !tokenReady || busy;
    dom.sortSelect.disabled = !tokenReady || busy;
    dom.clearFiltersBtn.disabled = !tokenReady || busy;
    dom.secretsHealthFilterBtn.disabled = !tokenReady || busy;

    var visibleServices = getFilteredAndSortedServices();
    var visibleIds = visibleServices.map(function (service) { return service.id; });
    var selectedVisibleCount = visibleIds.filter(function (id) {
      return !!state.selection.bulkSelectedIds[id];
    }).length;

    dom.bulkSelectAllBtn.disabled = !tokenReady || busy || !visibleIds.length;
    dom.bulkEnableBtn.disabled = !tokenReady || busy || selectedVisibleCount === 0;
    dom.bulkDisableBtn.disabled = !tokenReady || busy || selectedVisibleCount === 0;

    var serviceMode = state.ui.serviceEditorMode;
    var serviceValues = collectServiceFormValues();
    var serviceErrors = validateServiceForm(serviceValues);
    renderServiceValidation(serviceErrors);

    var serviceFormEnabled = tokenReady && !busy && serviceMode !== "empty";
    Array.prototype.forEach.call(dom.serviceForm.querySelectorAll("fieldset"), function (fieldset) {
      fieldset.disabled = !serviceFormEnabled;
    });

    dom.saveServiceBtn.disabled = !serviceFormEnabled || Object.keys(serviceErrors).length > 0;
    dom.resetServiceFormBtn.disabled = !serviceFormEnabled;
    dom.cancelEditBtn.disabled = !tokenReady || busy;

    var canDeleteSelected = tokenReady && !busy && serviceMode === "edit" && !!state.selection.selectedServiceId;
    dom.serviceDeleteBtn.disabled = !canDeleteSelected;

    var canRunCheck = tokenReady && !busy && serviceMode === "edit" && !!state.selection.selectedServiceId && state.auth.capabilities.runCheck;
    dom.serviceRunCheckBtn.disabled = !canRunCheck;

    var notificationsEnabled = tokenReady && !busy;
    dom.notificationsLoadBtn.disabled = !notificationsEnabled;
    dom.notificationsEnabled.disabled = !notificationsEnabled;
    dom.notificationsSaveBtn.disabled = !notificationsEnabled;
    dom.notificationsTestBtn.disabled = !notificationsEnabled;
    dom.notificationAddBtn.disabled = !notificationsEnabled;
    dom.notificationResetBtn.disabled = !notificationsEnabled;
    dom.notificationCancelEditBtn.disabled = !notificationsEnabled;
    Array.prototype.forEach.call(dom.notificationForm.querySelectorAll("fieldset"), function (fieldset) {
      fieldset.disabled = !notificationsEnabled;
    });

    dom.auditRefreshBtn.disabled = !tokenReady || busy;

    if (state.modal.open) {
      updateModalConfirmState();
    }

    renderHeader();
  }

  // --- data loaders ---------------------------------------------------------
  async function refreshPublicHealthPreview() {
    var statusResult = null;
    var overviewResult = null;

    try {
      statusResult = await publicFetch(ENDPOINTS.status);
    } catch (_err) {
      statusResult = null;
    }

    try {
      overviewResult = await publicFetch(ENDPOINTS.overview);
    } catch (_err) {
      overviewResult = null;
    }

    if (statusResult && Array.isArray(statusResult.services)) {
      var healthMap = {};
      statusResult.services.forEach(function (service) {
        if (!service || !service.id) return;
        healthMap[service.id] = {
          status: normalizeStatus(service.status),
          latency_ms: typeof service.latency_ms === "number" ? service.latency_ms : null,
          last_checked: typeof service.last_checked === "string" ? service.last_checked : null
        };
      });
      state.data.healthById = healthMap;
    }

    if (overviewResult && typeof overviewResult === "object") {
      state.data.overview = overviewResult;
    }

    if (statusResult && overviewResult) {
      dom.healthNote.textContent = "Public health preview updates every 60s.";
      dom.healthNote.className = "admin-health-note";
    } else if (statusResult || overviewResult) {
      dom.healthNote.textContent = "Public health preview is partially available.";
      dom.healthNote.className = "admin-health-note is-warning";
    } else {
      dom.healthNote.textContent = "Public health preview unavailable.";
      dom.healthNote.className = "admin-health-note is-warning";
    }

    renderHeader();
    renderServices();
  }

  async function loadServices() {
    var payload = await adminFetch(ENDPOINTS.services, {}, { context: "Load services" });
    var services = payload && Array.isArray(payload.services) ? payload.services.slice() : [];

    var map = {};
    services.forEach(function (service) {
      if (service && service.id) map[service.id] = service;
      if (service && service.group && state.ui.groupCollapsed[service.group] == null) {
        state.ui.groupCollapsed[service.group] = false;
      }
    });

    state.data.services = services;
    state.data.servicesById = map;

    syncBulkSelectionToServices();

    if (state.ui.serviceEditorMode === "edit") {
      if (!state.selection.selectedServiceId || !state.data.servicesById[state.selection.selectedServiceId]) {
        state.ui.serviceEditorMode = "empty";
        state.selection.selectedServiceId = null;
      }
    }

    renderServices();
    renderServiceEditor();
  }

  async function loadAudit() {
    var payload = await adminFetch(ENDPOINTS.audit, {}, { context: "Load audit" });
    state.data.auditEntries = Array.isArray(payload) ? payload : [];
    renderAudit();
  }

  async function loadNotifications() {
    var payload = await adminFetch(ENDPOINTS.notifications, {}, { context: "Load notifications" });
    state.data.notificationsConfig = {
      enabled: !!(payload && payload.enabled),
      endpoints: payload && Array.isArray(payload.endpoints) ? payload.endpoints.slice() : []
    };

    dom.notificationsEnabled.checked = state.data.notificationsConfig.enabled;

    if (state.ui.notificationEditId) {
      var exists = state.data.notificationsConfig.endpoints.some(function (endpoint) {
        return endpoint && endpoint.id === state.ui.notificationEditId;
      });
      if (!exists) applyNotificationAddMode();
    }

    renderNotificationsMeta();
    renderNotificationsList();
  }

  async function loadAllAdminData() {
    setError("");
    hideServiceMessage();
    hideNotificationsMessage();

    setLoading("services", true);
    try {
      await loadServices();
      var secondaryLoads = await Promise.allSettled([
        refreshPublicHealthPreview(),
        loadAudit(),
        loadNotifications()
      ]);

      var firstFailure = secondaryLoads.find(function (result) {
        return result.status === "rejected";
      });
      if (firstFailure && firstFailure.reason) {
        var failureMessage = firstFailure.reason && firstFailure.reason.message
          ? firstFailure.reason.message
          : "Some admin sections failed to load.";
        setError("Connected, but some sections could not be loaded. " + failureMessage);
      }
    } finally {
      setLoading("services", false);
    }

    renderAudit();
    renderNotificationsMeta();
    renderNotificationsList();
    renderServices();
    renderServiceEditor();
    renderActionState();
  }

  // --- event handlers -------------------------------------------------------
  function onTokenInputChanged() {
    state.auth.token = dom.tokenInput.value.trim();
    if (state.auth.connected) {
      setDisconnected();
    } else {
      renderHeader();
    }
    renderActionState();
  }

  async function onConnectClicked() {
    if (!hasToken() || state.ui.loading.services) return;
    try {
      await loadAllAdminData();
    } catch (error) {
      setError(error && error.message ? error.message : "Failed to load admin data.");
    }
  }

  function onSearchInputChanged() {
    state.filters.search = dom.searchInput.value || "";
    debounceSearch(function () {
      renderServices();
      renderActionState();
    });
  }

  function onGroupFilterChanged() {
    state.filters.group = dom.groupFilter.value || "all";
    renderServices();
  }

  function onSortChanged() {
    state.filters.sortBy = dom.sortSelect.value || "health";
    renderServices();
  }

  function onUnhealthyToggleChanged() {
    state.filters.onlyUnhealthy = !!dom.unhealthyOnlyToggle.checked;
    renderServices();
  }

  function onClearFiltersClicked() {
    state.filters.search = "";
    state.filters.group = "all";
    state.filters.onlyUnhealthy = false;
    state.filters.sortBy = "health";
    state.filters.missingSecretsOnly = false;

    dom.searchInput.value = "";
    dom.groupFilter.value = "all";
    dom.unhealthyOnlyToggle.checked = false;
    dom.sortSelect.value = "health";

    renderServices();
    renderActionState();
  }

  function onSecretsFilterClicked() {
    state.filters.missingSecretsOnly = !state.filters.missingSecretsOnly;
    renderServices();
  }

  function onNewServiceClicked() {
    state.ui.activeTab = "service";
    renderTabs();
    setServiceEditorMode("add", null);
  }

  function onServiceGroupToggle(groupName) {
    state.ui.groupCollapsed[groupName] = !state.ui.groupCollapsed[groupName];
    renderServices();
  }

  function onServiceRowSelected(serviceId) {
    if (!serviceId || !state.data.servicesById[serviceId]) return;
    state.ui.activeTab = "service";
    renderTabs();
    setServiceEditorMode("edit", serviceId);
  }

  async function onServiceToggleClicked(serviceId) {
    if (!serviceId || !hasToken() || anyLoading()) return;
    setError("");
    setLoading("bulk", true);
    try {
      await adminFetch(
        ENDPOINTS.services + "/" + encodeURIComponent(serviceId) + "/toggle",
        { method: "POST" },
        { context: "Toggle service" }
      );
      await loadServices();
      await refreshPublicHealthPreview();
      await loadAudit();
    } catch (error) {
      setError(error && error.message ? error.message : "Failed toggling service.");
    } finally {
      setLoading("bulk", false);
    }
  }

  function onServiceDeleteClicked(serviceId) {
    if (!serviceId || !state.data.servicesById[serviceId]) return;

    var service = state.data.servicesById[serviceId];
    openConfirmModal({
      kind: "delete-service",
      title: "Delete service",
      message: "Delete service '" + (service.name || service.id) + "'? This removes it immediately.",
      requiredText: service.id,
      targetId: service.id,
      confirmLabel: "Delete",
      onConfirm: async function () {
        setLoading("modalAction", true);
        updateModalConfirmState();
        try {
          await adminFetch(
            ENDPOINTS.services + "/" + encodeURIComponent(service.id),
            { method: "DELETE" },
            { context: "Delete service" }
          );
          closeConfirmModal();
          await loadServices();
          await refreshPublicHealthPreview();
          await loadAudit();
          if (state.selection.selectedServiceId === service.id) {
            setServiceEditorMode("empty", null);
          }
          showServiceMessage("Service deleted.", false);
        } catch (error) {
          setLoading("modalAction", false);
          setError(error && error.message ? error.message : "Failed deleting service.");
          updateModalConfirmState();
        }
      }
    });
  }

  function onServiceBulkSelectionChanged(serviceId, checked) {
    if (!serviceId) return;
    if (checked) state.selection.bulkSelectedIds[serviceId] = true;
    else delete state.selection.bulkSelectedIds[serviceId];
    renderServices();
  }

  function onBulkSelectAllClicked() {
    var visible = getFilteredAndSortedServices();
    var visibleIds = visible.map(function (service) { return service.id; });
    var selectedVisibleCount = visibleIds.filter(function (id) {
      return !!state.selection.bulkSelectedIds[id];
    }).length;
    var shouldClear = selectedVisibleCount > 0 && selectedVisibleCount === visibleIds.length;

    if (shouldClear) {
      visibleIds.forEach(function (id) { delete state.selection.bulkSelectedIds[id]; });
    } else {
      visibleIds.forEach(function (id) { state.selection.bulkSelectedIds[id] = true; });
    }

    renderServices();
  }

  async function applyBulkEnabled(enabled) {
    var visible = getFilteredAndSortedServices();
    var visibleIds = visible.map(function (service) { return service.id; });
    var selectedVisibleIds = visibleIds.filter(function (id) {
      return !!state.selection.bulkSelectedIds[id];
    });

    if (!selectedVisibleIds.length || !hasToken()) return;

    setError("");
    setLoading("bulk", true);
    try {
      await adminFetch(
        ENDPOINTS.servicesBulk,
        {
          method: "POST",
          body: JSON.stringify({
            ids: selectedVisibleIds,
            enabled: !!enabled
          })
        },
        { context: enabled ? "Bulk enable" : "Bulk disable" }
      );

      state.selection.bulkSelectedIds = {};
      await loadServices();
      await refreshPublicHealthPreview();
      await loadAudit();
    } catch (error) {
      setError(error && error.message ? error.message : "Failed applying bulk action.");
    } finally {
      setLoading("bulk", false);
    }
  }

  function onBulkDisableClicked() {
    openConfirmModal({
      kind: "bulk-disable",
      title: "Confirm bulk disable",
      message: "Disable selected visible services? Type DISABLE to confirm.",
      requiredText: "DISABLE",
      confirmLabel: "Disable selected",
      onConfirm: async function () {
        setLoading("modalAction", true);
        updateModalConfirmState();
        try {
          closeConfirmModal();
          await applyBulkEnabled(false);
        } catch (_err) {
          setLoading("modalAction", false);
          updateModalConfirmState();
        }
      }
    });
  }

  async function onBulkEnableClicked() {
    await applyBulkEnabled(true);
  }

  async function onServiceFormSubmit(event) {
    event.preventDefault();
    if (!hasToken()) return;

    setError("");
    hideServiceMessage();

    state.ui.hasTriedServiceSave = true;

    var values = collectServiceFormValues();
    var errors = validateServiceForm(values);
    renderServiceValidation(errors);
    if (Object.keys(errors).length > 0) {
      renderActionState();
      return;
    }

    var existing = state.ui.serviceEditorMode === "edit"
      ? state.data.servicesById[state.selection.selectedServiceId]
      : null;

    var path = state.ui.serviceEditorMode === "edit"
      ? ENDPOINTS.services + "/" + encodeURIComponent(state.selection.selectedServiceId)
      : ENDPOINTS.services;

    var method = state.ui.serviceEditorMode === "edit" ? "PUT" : "POST";

    setLoading("saveService", true);
    try {
      await adminFetch(
        path,
        {
          method: method,
          body: JSON.stringify(buildServicePayload(values, existing))
        },
        { context: state.ui.serviceEditorMode === "edit" ? "Save service" : "Add service" }
      );

      await loadServices();
      await refreshPublicHealthPreview();
      await loadAudit();

      if (state.ui.serviceEditorMode === "add") {
        setServiceEditorMode("edit", values.id);
      } else {
        setServiceEditorMode("edit", values.id);
      }
      showServiceMessage("Service saved.", false);
    } catch (error) {
      setError(error && error.message ? error.message : "Failed saving service.");
    } finally {
      setLoading("saveService", false);
    }
  }

  function onServiceFormReset() {
    hideServiceMessage();
    setError("");

    if (state.ui.serviceEditorMode === "edit" && state.selection.selectedServiceId) {
      var service = state.data.servicesById[state.selection.selectedServiceId];
      if (service) {
        fillServiceFormFromService(service);
        clearServiceValidation();
      }
      return;
    }

    if (state.ui.serviceEditorMode === "add") {
      resetServiceFormForAdd();
      clearServiceValidation();
    }
  }

  function onServiceCancelEdit() {
    hideServiceMessage();
    setError("");

    if (state.selection.selectedServiceId && state.data.servicesById[state.selection.selectedServiceId]) {
      setServiceEditorMode("edit", state.selection.selectedServiceId);
      return;
    }
    setServiceEditorMode("empty", null);
  }

  function onServiceDangerDeleteClicked() {
    if (state.ui.serviceEditorMode !== "edit" || !state.selection.selectedServiceId) return;
    onServiceDeleteClicked(state.selection.selectedServiceId);
  }

  async function onRunCheckClicked() {
    if (!state.selection.selectedServiceId || !hasToken() || !state.auth.capabilities.runCheck) return;

    setError("");
    setLoading("runCheck", true);
    try {
      var payload = await adminFetch(
        ENDPOINTS.services + "/" + encodeURIComponent(state.selection.selectedServiceId) + "/check",
        { method: "POST" },
        { context: "Run check" }
      );

      if (payload && payload.id) {
        state.data.healthById[payload.id] = {
          status: normalizeStatus(payload.status),
          latency_ms: typeof payload.latency_ms === "number" ? payload.latency_ms : null,
          last_checked: payload.last_checked || new Date().toISOString()
        };
        renderServices();
        showServiceMessage("Check completed for " + payload.id + ".", false);
      }
    } catch (error) {
      if (error && error.status === 404) {
        state.auth.capabilities.runCheck = false;
        dom.serviceRunCheckBtn.classList.add("is-hidden");
        showServiceMessage("Run check endpoint is not available in this backend.", true);
      } else {
        setError(error && error.message ? error.message : "Failed running check.");
      }
    } finally {
      setLoading("runCheck", false);
    }
  }

  function onServiceFieldTouched(fieldName) {
    state.ui.touchedServiceFields[fieldName] = true;
    renderActionState();
  }

  async function onNotificationsLoadClicked() {
    if (!hasToken()) return;
    setError("");
    hideNotificationsMessage();

    setLoading("notifications", true);
    try {
      await loadNotifications();
    } catch (error) {
      setError(error && error.message ? error.message : "Failed loading notifications.");
    } finally {
      setLoading("notifications", false);
    }
  }

  async function onNotificationsSaveClicked() {
    if (!hasToken()) return;
    setError("");
    hideNotificationsMessage();

    setLoading("notifications", true);
    try {
      await adminFetch(
        ENDPOINTS.notifications,
        {
          method: "PUT",
          body: JSON.stringify(currentNotificationsConfigPayload())
        },
        { context: "Save notifications" }
      );
      await loadNotifications();
      await loadAudit();
      showNotificationsMessage("Notifications config saved.", false);
    } catch (error) {
      showNotificationsMessage(error && error.message ? error.message : "Failed saving notifications.", true);
    } finally {
      setLoading("notifications", false);
    }
  }

  async function onNotificationsTestClicked() {
    if (!hasToken()) return;
    setError("");
    hideNotificationsMessage();

    setLoading("notifications", true);
    try {
      var payload = await adminFetch(
        ENDPOINTS.notificationsTest,
        { method: "POST" },
        { context: "Send test notification" }
      );
      var dispatched = payload && typeof payload.dispatched === "number" ? payload.dispatched : 0;
      await loadAudit();
      showNotificationsMessage("Test queued. dispatched=" + dispatched + ".", false);
    } catch (error) {
      showNotificationsMessage(error && error.message ? error.message : "Failed sending test notification.", true);
    } finally {
      setLoading("notifications", false);
    }
  }

  function onNotificationFormSubmit(event) {
    event.preventDefault();
    if (!hasToken() || anyLoading()) return;

    hideNotificationsMessage();

    var values = collectNotificationFormValues();
    var validationMessage = validateNotificationForm(values);
    if (validationMessage) {
      showNotificationsMessage(validationMessage, true);
      return;
    }

    var payload = buildNotificationPayload(values);
    var endpoints = (state.data.notificationsConfig.endpoints || []).slice();

    if (state.ui.notificationEditId) {
      endpoints = endpoints.map(function (endpoint) {
        return endpoint && endpoint.id === state.ui.notificationEditId ? payload : endpoint;
      });
    } else {
      endpoints.push(payload);
    }

    state.data.notificationsConfig.endpoints = endpoints;
    renderNotificationsMeta();
    renderNotificationsList();
    applyNotificationAddMode();
    showNotificationsMessage("Endpoint staged. Save notifications to persist.", false);
  }

  function onNotificationDeleteClicked(endpointId) {
    var endpoints = state.data.notificationsConfig.endpoints || [];
    var endpoint = endpoints.find(function (item) {
      return item && item.id === endpointId;
    });
    if (!endpoint) return;

    state.data.notificationsConfig.endpoints = endpoints.filter(function (item) {
      return !item || item.id !== endpointId;
    });

    if (state.ui.notificationEditId === endpointId) {
      applyNotificationAddMode();
    }

    renderNotificationsMeta();
    renderNotificationsList();
    showNotificationsMessage("Endpoint removed from staged config. Save notifications to persist.", false);
  }

  async function onAuditRefreshClicked() {
    if (!hasToken()) return;
    setError("");

    setLoading("audit", true);
    try {
      await loadAudit();
    } catch (error) {
      setError(error && error.message ? error.message : "Failed loading audit log.");
    } finally {
      setLoading("audit", false);
    }
  }

  async function copyAuditRowJson(entry) {
    var serialized = JSON.stringify(entry);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(serialized);
      return;
    }

    var textarea = document.createElement("textarea");
    textarea.value = serialized;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }

  async function onModalConfirmClicked() {
    if (!state.modal.open || !state.modal.onConfirm) return;
    await state.modal.onConfirm();
  }

  function onTabClicked(tabName) {
    if (!tabName || !dom.tabPanels[tabName]) return;
    state.ui.activeTab = tabName;
    renderTabs();
  }

  function onDocumentKeyDown(event) {
    if (event.key === "Escape") {
      if (state.modal.open) {
        event.preventDefault();
        if (!state.ui.loading.modalAction) {
          closeConfirmModal();
        }
      }
      return;
    }

    if (event.key === "/") {
      var target = event.target;
      var isTypingContext = target && (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      );
      if (isTypingContext) return;
      event.preventDefault();
      dom.searchInput.focus();
      dom.searchInput.select();
    }
  }

  // --- event wiring ---------------------------------------------------------
  dom.tokenInput.addEventListener("input", onTokenInputChanged);
  dom.connectBtn.addEventListener("click", onConnectClicked);

  dom.searchInput.addEventListener("input", onSearchInputChanged);
  dom.groupFilter.addEventListener("change", onGroupFilterChanged);
  dom.unhealthyOnlyToggle.addEventListener("change", onUnhealthyToggleChanged);
  dom.sortSelect.addEventListener("change", onSortChanged);
  dom.clearFiltersBtn.addEventListener("click", onClearFiltersClicked);
  dom.secretsHealthFilterBtn.addEventListener("click", onSecretsFilterClicked);
  dom.newServiceBtn.addEventListener("click", onNewServiceClicked);

  dom.bulkSelectAllBtn.addEventListener("click", onBulkSelectAllClicked);
  dom.bulkEnableBtn.addEventListener("click", onBulkEnableClicked);
  dom.bulkDisableBtn.addEventListener("click", onBulkDisableClicked);

  dom.serviceListBody.addEventListener("click", function (event) {
    var groupToggle = event.target.closest("button[data-group-toggle]");
    if (groupToggle) {
      onServiceGroupToggle(groupToggle.getAttribute("data-group-toggle"));
      return;
    }

    var actionButton = event.target.closest("button[data-service-action]");
    if (actionButton) {
      var action = actionButton.getAttribute("data-service-action");
      var serviceId = actionButton.getAttribute("data-service-id");
      if (action === "toggle") {
        onServiceToggleClicked(serviceId);
        return;
      }
      if (action === "edit") {
        onServiceRowSelected(serviceId);
        return;
      }
      if (action === "delete") {
        onServiceDeleteClicked(serviceId);
      }
      return;
    }

    var row = event.target.closest("tr[data-service-id]");
    if (!row) return;
    if (event.target.closest("input,button,a,select,textarea,label")) return;
    onServiceRowSelected(row.getAttribute("data-service-id"));
  });

  dom.serviceListBody.addEventListener("change", function (event) {
    var checkbox = event.target.closest("input[data-service-select]");
    if (!checkbox) return;
    var serviceId = checkbox.getAttribute("data-service-select");
    onServiceBulkSelectionChanged(serviceId, !!checkbox.checked);
  });

  dom.serviceForm.addEventListener("submit", onServiceFormSubmit);
  dom.resetServiceFormBtn.addEventListener("click", onServiceFormReset);
  dom.cancelEditBtn.addEventListener("click", onServiceCancelEdit);
  dom.serviceDeleteBtn.addEventListener("click", onServiceDangerDeleteClicked);
  dom.serviceRunCheckBtn.addEventListener("click", onRunCheckClicked);

  serviceFields.auth_scheme.addEventListener("change", function () {
    onServiceFieldTouched("auth_scheme");
    setServiceAuthVisibility(true);
    renderActionState();
  });

  serviceFields.check_type.addEventListener("change", function () {
    maybeDefaultAuthForCheckType(serviceFields.check_type.value);
    onServiceFieldTouched("check_type");
  });

  serviceFields.check_type.addEventListener("input", function () {
    maybeDefaultAuthForCheckType(serviceFields.check_type.value);
    onServiceFieldTouched("check_type");
  });

  Object.keys(serviceFields).forEach(function (fieldName) {
    var field = serviceFields[fieldName];
    if (!field) return;
    field.addEventListener("input", function () {
      onServiceFieldTouched(fieldName);
    });
    field.addEventListener("change", function () {
      onServiceFieldTouched(fieldName);
    });
    field.addEventListener("blur", function () {
      onServiceFieldTouched(fieldName);
    });
  });

  dom.tabs.forEach(function (tabButton) {
    tabButton.addEventListener("click", function () {
      onTabClicked(tabButton.getAttribute("data-admin-tab"));
    });
  });

  dom.notificationsLoadBtn.addEventListener("click", onNotificationsLoadClicked);
  dom.notificationsSaveBtn.addEventListener("click", onNotificationsSaveClicked);
  dom.notificationsTestBtn.addEventListener("click", onNotificationsTestClicked);

  dom.notificationsEnabled.addEventListener("change", function () {
    state.data.notificationsConfig.enabled = !!dom.notificationsEnabled.checked;
    renderNotificationsMeta();
  });

  notificationFields.auth_scheme.addEventListener("change", function () {
    renderNotificationAuthVisibility(true);
    renderActionState();
  });

  dom.notificationForm.addEventListener("submit", onNotificationFormSubmit);
  dom.notificationResetBtn.addEventListener("click", function () {
    hideNotificationsMessage();
    if (state.ui.notificationEditId) {
      applyNotificationEditMode(state.ui.notificationEditId);
      return;
    }
    applyNotificationAddMode();
  });

  dom.notificationCancelEditBtn.addEventListener("click", function () {
    hideNotificationsMessage();
    applyNotificationAddMode();
  });

  dom.notificationsListBody.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-notification-action]");
    if (!button) return;
    if (!hasToken() || anyLoading()) return;

    var row = button.closest("tr[data-notification-id]");
    if (!row) return;
    var endpointId = row.getAttribute("data-notification-id");
    var action = button.getAttribute("data-notification-action");

    if (action === "edit") {
      applyNotificationEditMode(endpointId);
      return;
    }

    if (action === "delete") {
      onNotificationDeleteClicked(endpointId);
    }
  });

  dom.auditRefreshBtn.addEventListener("click", onAuditRefreshClicked);
  dom.auditActionFilter.addEventListener("change", renderAudit);
  dom.auditSearchInput.addEventListener("input", renderAudit);

  dom.auditTableBody.addEventListener("click", async function (event) {
    var copyButton = event.target.closest("button[data-audit-copy='1']");
    if (!copyButton) return;

    var row = copyButton.closest("tr[data-audit-index]");
    if (!row) return;

    var index = Number(row.getAttribute("data-audit-index"));
    var filtered = getFilteredAuditEntries();
    if (!isFinite(index) || index < 0 || index >= filtered.length) return;

    try {
      await copyAuditRowJson(filtered[index]);
      dom.auditListMeta.textContent = "Copied row JSON.";
    } catch (_err) {
      dom.auditListMeta.textContent = "Unable to copy row JSON.";
    }
  });

  dom.modalCancelBtn.addEventListener("click", function () {
    if (state.ui.loading.modalAction) return;
    closeConfirmModal();
  });

  dom.modalBackdrop.addEventListener("click", function (event) {
    if (event.target !== dom.modalBackdrop || state.ui.loading.modalAction) return;
    closeConfirmModal();
  });

  dom.modalRequireInput.addEventListener("input", updateModalConfirmState);
  dom.modalConfirmBtn.addEventListener("click", onModalConfirmClicked);

  document.addEventListener("keydown", onDocumentKeyDown);

  // --- initialization -------------------------------------------------------
  function initializeUiState() {
    state.auth.token = dom.tokenInput.value.trim();

    dom.searchInput.value = state.filters.search;
    dom.groupFilter.value = state.filters.group;
    dom.unhealthyOnlyToggle.checked = state.filters.onlyUnhealthy;
    dom.sortSelect.value = state.filters.sortBy;

    renderTabs();
    renderHeader();
    renderServices();
    applyNotificationAddMode();
    renderNotificationsMeta();
    renderNotificationsList();
    renderAudit();
    renderServiceEditor();
    closeConfirmModal();
    renderActionState();
  }

  initializeUiState();

  refreshPublicHealthPreview();

  setInterval(function () {
    refreshPublicHealthPreview().catch(function () {
      dom.healthNote.textContent = "Public health preview unavailable.";
      dom.healthNote.className = "admin-health-note is-warning";
    });
  }, HEALTH_POLL_INTERVAL);

  setInterval(function () {
    if (!state.auth.connected || !hasToken() || anyLoading()) return;
    loadAudit().catch(function () {
      dom.auditListMeta.textContent = "Failed to refresh audit entries.";
    });
  }, AUDIT_POLL_INTERVAL);
})();
