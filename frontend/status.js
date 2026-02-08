// marcle.ai — status fetcher
// Progressive enhancement: page works without JS, status grid populates when API is reachable.

(function () {
  'use strict';

  const API_BASE = window.MARCLE_API_BASE || '';
  const STATUS_URL = API_BASE + '/api/status';
  const OVERVIEW_URL = API_BASE + '/api/overview';
  const SERVICE_DETAILS_BASE = API_BASE + '/api/services/';
  const INCIDENTS_URL = API_BASE + '/api/incidents?limit=50';
  const POLL_INTERVAL = 60000; // 60s
  const DRAWER_INCIDENT_LIMIT = 10;
  const GLOBAL_INCIDENTS_CACHE_MS = 60000;

  const statusGrid = document.getElementById('status-grid');
  const serviceCount = document.getElementById('service-count');
  const overviewShell = document.getElementById('overview-shell');
  const overviewTotal = document.getElementById('overview-total');
  const healthyCount = document.getElementById('count-healthy');
  const degradedCount = document.getElementById('count-degraded');
  const downCount = document.getElementById('count-down');
  const unknownCount = document.getElementById('count-unknown');
  const overviewLastUpdated = document.getElementById('overview-last-updated');
  const overviewCacheAge = document.getElementById('overview-cache-age');
  const incidentBanner = document.getElementById('incident-banner');
  const drawerBackdrop = document.getElementById('service-drawer-backdrop');
  const drawerPanel = document.getElementById('service-drawer');
  const drawerCloseButton = document.getElementById('drawer-close');
  const drawerTitle = document.getElementById('drawer-title');
  const drawerStatusPill = document.getElementById('drawer-status-pill');
  const drawerLoading = document.getElementById('drawer-loading');
  const drawerError = document.getElementById('drawer-error');
  const drawerBody = document.getElementById('drawer-body');
  const drawerFieldStatus = document.getElementById('drawer-field-status');
  const drawerFieldLatency = document.getElementById('drawer-field-latency');
  const drawerFieldLastChecked = document.getElementById('drawer-field-last-checked');
  const drawerFieldLastChanged = document.getElementById('drawer-field-last-changed');
  const drawerFlappingWrap = document.getElementById('drawer-flapping-wrap');
  const drawerDescriptionWrap = document.getElementById('drawer-description-wrap');
  const drawerDescription = document.getElementById('drawer-description');
  const drawerOpenLink = document.getElementById('drawer-open-link');
  const drawerIncidents = document.getElementById('drawer-incidents');
  const drawerIncidentsEmpty = document.getElementById('drawer-incidents-empty');

  var latestStatusData = null;
  var latestOverviewData = null;
  var latestGlobalIncidents = null;
  var latestGlobalIncidentsFetchedAt = 0;
  var selectedServiceId = null;
  var drawerRequestToken = 0;
  var lastFocusedElement = null;
  var drawerHasRenderedContent = false;

  function renderStatusGrid(data, overview) {
    if (!statusGrid) return;
    var overviewByService = buildOverviewIndex(overview);

    // Update overall indicator
    const dot = document.querySelector('.meta-dot');
    if (dot) {
      var overallStatus = normalizeStatus(data.overall_status || 'unknown');
      dot.className = 'meta-dot ' + overallStatus;
      const label = dot.parentElement;
      if (label) {
        label.innerHTML = '';
        label.appendChild(dot);
        label.appendChild(document.createTextNode(' systems ' + overallStatus));
      }
    }

    // Update service count
    if (serviceCount && data.services) {
      serviceCount.textContent = data.services.length + ' services tracked';
    }

    // Render cards
    if (!data.services || data.services.length === 0) {
      statusGrid.innerHTML = '<div class="status-placeholder">No services reported.</div>';
      return;
    }

    statusGrid.innerHTML = data.services.map(function (svc) {
      var latency = svc.latency_ms != null ? svc.latency_ms + 'ms' : '—';
      var checked = svc.last_checked ? formatRelativeTime(svc.last_checked) : '—';
      var group = svc.group || 'service';
      var statusValue = normalizeStatus(svc.status);
      var statusLabel = titleCaseStatus(statusValue);
      var changeLabel = getChangeLabel(svc, overviewByService[svc.id]);
      var changeMarkup = changeLabel
        ? '<span class="status-card-change">' + escapeHtml(changeLabel) + '</span>'
        : '';
      var serviceId = svc.id || '';
      var serviceName = svc.name || serviceId || 'Unknown service';
      var iconValue = serviceIconForCard(svc);
      return (
        '<button type="button" class="status-card status-card-button" data-service-id="' + escapeAttribute(serviceId) + '" data-status="' + escapeAttribute(statusValue) + '" aria-label="Open details for ' + escapeAttribute(serviceName) + ' — status: ' + escapeAttribute(statusLabel) + '">' +
          '<div class="status-card-top">' +
            '<div class="status-card-main">' +
              '<span class="status-card-icon" aria-hidden="true">' + escapeHtml(iconValue) + '</span>' +
              '<div class="status-card-title-wrap">' +
                '<span class="status-card-name">' + escapeHtml(serviceName) + '</span>' +
                '<span class="status-card-group">' + escapeHtml(group) + '</span>' +
              '</div>' +
            '</div>' +
            '<div class="status-card-status-wrap">' +
              '<span class="status-card-status-pill ' + escapeHtml(statusValue) + '">' + escapeHtml(statusLabel) + '</span>' +
              '<span class="status-indicator ' + escapeHtml(statusValue) + '" aria-hidden="true"></span>' +
            '</div>' +
          '</div>' +
          '<div class="status-card-meta">' +
            '<span class="status-card-latency">Latency ' + escapeHtml(latency) + '</span>' +
            '<span class="status-card-checked">Checked ' + escapeHtml(checked) + '</span>' +
          '</div>' +
          changeMarkup +
        '</button>'
      );
    }).join('');
  }

  function renderOverview(statusData, overviewData) {
    if (!overviewShell) return;

    if (!overviewData) {
      overviewShell.classList.add('is-hidden');
      return;
    }

    overviewShell.classList.remove('is-hidden');

    // Determine overall status for accent
    var overall = (overviewData.overall_status || (statusData && statusData.overall_status) || 'unknown');

    // Apply accent to overview cards
    var overviewCards = overviewShell.querySelectorAll('.overview-card');
    overviewCards.forEach(function (card) {
      card.classList.remove('accent-healthy', 'accent-degraded', 'accent-down', 'accent-unknown');
      card.classList.add('accent-' + overall);
    });

    var counts = overviewData.counts || {};
    if (overviewTotal) {
      var total = counts.total != null ? counts.total : (statusData && statusData.services ? statusData.services.length : 0);
      overviewTotal.textContent = total + ' services';
    }
    if (healthyCount) healthyCount.textContent = 'healthy ' + (counts.healthy || 0);
    if (degradedCount) degradedCount.textContent = 'degraded ' + (counts.degraded || 0);
    if (downCount) downCount.textContent = 'down ' + (counts.down || 0);
    if (unknownCount) unknownCount.textContent = 'unknown ' + (counts.unknown || 0);

    var updatedAt = overviewData.last_refresh_at || (statusData ? statusData.generated_at : null);
    if (overviewLastUpdated) {
      overviewLastUpdated.textContent = 'Last updated ' + formatAbsoluteTime(updatedAt);
    }

    if (overviewCacheAge) {
      if (typeof overviewData.cache_age_seconds === 'number') {
        overviewCacheAge.textContent = 'Cache age ' + humanizeDuration(overviewData.cache_age_seconds);
      } else {
        overviewCacheAge.textContent = 'Cache age —';
      }
    }

    renderIncidentBanner(statusData, overviewData.last_incident || null);
  }

  function renderIncidentBanner(statusData, incident) {
    if (!incidentBanner) return;
    if (!incident || !incident.service_id || !incident.from || !incident.to || !incident.at) {
      incidentBanner.classList.add('is-hidden');
      incidentBanner.textContent = '';
      return;
    }

    var ageSeconds = secondsSinceIso(incident.at);
    var ago = ageSeconds == null ? 'unknown time' : humanizeDuration(ageSeconds) + ' ago';
    var serviceName = serviceNameForId(statusData, incident.service_id);
    incidentBanner.textContent = 'Incident: ' + serviceName + ' changed ' + titleCaseStatus(incident.from) + ' \u2192 ' + titleCaseStatus(incident.to) + ' (' + ago + ')';

    // Apply severity styling
    var bannerClass = classifyIncident(incident);
    incidentBanner.className = 'incident-banner';
    if (bannerClass === 'incident--bad') {
      incidentBanner.classList.add('banner--bad');
    } else if (bannerClass === 'incident--recovery') {
      incidentBanner.classList.add('banner--recovery');
    } else if (incident.to === 'degraded') {
      incidentBanner.classList.add('banner--degraded');
    }
  }

  function buildOverviewIndex(overviewData) {
    var index = {};
    if (!overviewData || !Array.isArray(overviewData.services)) return index;
    overviewData.services.forEach(function (service) {
      if (!service || !service.id) return;
      index[service.id] = service;
    });
    return index;
  }

  function getChangeLabel(statusService, overviewService) {
    if (!statusService || !overviewService || !overviewService.last_changed_at) {
      return '';
    }
    var ageSeconds = secondsSinceIso(overviewService.last_changed_at);
    if (ageSeconds == null) return '';
    if (overviewService.last_status === statusService.status) {
      return 'Stable ' + humanizeDuration(ageSeconds);
    }
    return 'Changed ' + humanizeDuration(ageSeconds) + ' ago';
  }

  function serviceNameForId(statusData, serviceId) {
    if (!statusData || !Array.isArray(statusData.services)) return serviceId;
    for (var i = 0; i < statusData.services.length; i += 1) {
      var service = statusData.services[i];
      if (service && service.id === serviceId) {
        return service.name || serviceId;
      }
    }
    return serviceId;
  }

  function formatAbsoluteTime(isoTimestamp) {
    var date = parseIso(isoTimestamp);
    if (!date) return '—';
    return date.toLocaleString();
  }

  function secondsSinceIso(isoTimestamp) {
    var date = parseIso(isoTimestamp);
    if (!date) return null;
    return Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  }

  function parseIso(value) {
    if (!value || typeof value !== 'string') return null;
    var date = new Date(value);
    if (isNaN(date.getTime())) return null;
    return date;
  }

  function humanizeDuration(totalSeconds) {
    var seconds = Math.max(0, Math.floor(totalSeconds || 0));
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h';
    return Math.floor(seconds / 86400) + 'd';
  }

  function formatRelativeTime(isoTimestamp) {
    var ageSeconds = secondsSinceIso(isoTimestamp);
    if (ageSeconds == null) return '—';
    return humanizeDuration(ageSeconds) + ' ago';
  }

  function formatTimestampWithRelative(isoTimestamp) {
    var absolute = formatAbsoluteTime(isoTimestamp);
    var relative = formatRelativeTime(isoTimestamp);
    if (absolute === '—' || relative === '—') return absolute;
    return absolute + ' (' + relative + ')';
  }

  function normalizeStatus(statusValue) {
    if (!statusValue || typeof statusValue !== 'string') return 'unknown';
    var lowered = statusValue.toLowerCase();
    if (lowered === 'healthy' || lowered === 'degraded' || lowered === 'down' || lowered === 'unknown') {
      return lowered;
    }
    return 'unknown';
  }

  function titleCaseStatus(statusValue) {
    var normalized = normalizeStatus(statusValue);
    return normalized.charAt(0).toUpperCase() + normalized.slice(1);
  }

  function serviceIconForCard(service) {
    if (service && typeof service.icon === 'string' && service.icon.trim()) {
      var iconValue = service.icon.trim();
      var iconChars = Array.from(iconValue);
      if (iconChars.length > 0) {
        return iconChars.slice(0, 2).join('');
      }
    }
    var fallback = '';
    if (service) {
      fallback = service.name || service.id || '';
    }
    var firstChar = Array.from((fallback || '').trim())[0] || '?';
    return firstChar.toUpperCase();
  }

  function statusSeverity(status) {
    if (status === 'healthy') return 0;
    if (status === 'unknown') return 1;
    if (status === 'degraded') return 2;
    if (status === 'down') return 3;
    return null;
  }

  function classifyIncident(incident) {
    if (!incident) return 'incident--neutral';
    var from = statusSeverity(incident.from);
    var to = statusSeverity(incident.to);
    if (from == null || to == null || from === to) return 'incident--neutral';
    return to > from ? 'incident--bad' : 'incident--recovery';
  }

  function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function escapeAttribute(str) {
    return escapeHtml(str);
  }

  async function fetchJson(url) {
    var resp = await fetch(url);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    return await resp.json();
  }

  function renderStatusUnavailable() {
    if (statusGrid) {
      statusGrid.innerHTML =
        '<div class="status-placeholder">Status unavailable. API may be offline.</div>';
    }
  }

  function serviceFromStatus(serviceId) {
    if (!latestStatusData || !Array.isArray(latestStatusData.services)) return null;
    for (var i = 0; i < latestStatusData.services.length; i += 1) {
      var service = latestStatusData.services[i];
      if (service && service.id === serviceId) return service;
    }
    return null;
  }

  function showDrawerLoading() {
    if (drawerLoading) drawerLoading.style.display = '';
    if (drawerBody) drawerBody.classList.add('is-hidden');
  }

  function hideDrawerLoading() {
    if (drawerLoading) drawerLoading.style.display = 'none';
  }

  function setDrawerError(message) {
    if (!drawerError) return;
    if (!message) {
      drawerError.textContent = '';
      drawerError.classList.add('is-hidden');
      return;
    }
    drawerError.textContent = message;
    drawerError.classList.remove('is-hidden');
  }

  function setDrawerHeader(title, statusValue) {
    if (drawerTitle) {
      drawerTitle.textContent = title || 'Service Details';
    }
    var normalizedStatus = normalizeStatus(statusValue);
    if (drawerStatusPill) {
      drawerStatusPill.className = 'drawer-status-pill ' + normalizedStatus;
      drawerStatusPill.textContent = titleCaseStatus(normalizedStatus);
    }
    // Apply accent to header
    var header = drawerPanel ? drawerPanel.querySelector('.service-drawer-header') : null;
    if (header) {
      header.classList.remove('accent-healthy', 'accent-degraded', 'accent-down', 'accent-unknown');
      header.classList.add('accent-' + normalizedStatus);
    }
  }

  function renderDrawerFields(service) {
    if (!service) return;
    setDrawerHeader(service.name || service.id || 'Service Details', service.status);
    if (drawerFieldStatus) {
      var normalizedStatus = normalizeStatus(service.status);
      drawerFieldStatus.className = 'drawer-value drawer-value-status ' + normalizedStatus;
      drawerFieldStatus.textContent = titleCaseStatus(normalizedStatus);
    }
    if (drawerFieldLatency) {
      drawerFieldLatency.textContent = service.latency_ms != null ? service.latency_ms + 'ms' : '—';
    }
    if (drawerFieldLastChecked) {
      drawerFieldLastChecked.textContent = formatTimestampWithRelative(service.last_checked);
    }
    if (drawerFieldLastChanged) {
      var changedLabel = formatRelativeTime(service.last_changed_at);
      drawerFieldLastChanged.textContent = changedLabel === '—' ? '—' : changedLabel;
    }
    if (drawerFlappingWrap) {
      if (service.flapping) {
        drawerFlappingWrap.classList.remove('is-hidden');
      } else {
        drawerFlappingWrap.classList.add('is-hidden');
      }
    }
    if (drawerDescriptionWrap && drawerDescription) {
      if (service.description) {
        drawerDescription.textContent = service.description;
        drawerDescriptionWrap.classList.remove('is-hidden');
      } else {
        drawerDescription.textContent = '';
        drawerDescriptionWrap.classList.add('is-hidden');
      }
    }
    if (drawerOpenLink) {
      if (service.url) {
        drawerOpenLink.href = service.url;
        drawerOpenLink.classList.remove('is-hidden');
      } else {
        drawerOpenLink.removeAttribute('href');
        drawerOpenLink.classList.add('is-hidden');
      }
    }
  }

  function renderDrawerIncidents(incidents) {
    if (!drawerIncidents || !drawerIncidentsEmpty) return;

    if (!Array.isArray(incidents) || incidents.length === 0) {
      drawerIncidents.innerHTML = '';
      drawerIncidentsEmpty.classList.remove('is-hidden');
      return;
    }

    drawerIncidentsEmpty.classList.add('is-hidden');
    drawerIncidents.innerHTML = incidents.slice(0, DRAWER_INCIDENT_LIMIT).map(function (incident) {
      var fromStatus = incident && incident.from ? titleCaseStatus(incident.from) : 'Unknown';
      var toStatus = incident && incident.to ? titleCaseStatus(incident.to) : 'Unknown';
      var incidentClass = classifyIncident(incident);
      var relative = incident && incident.at ? formatRelativeTime(incident.at) : 'unknown time';
      return (
        '<li class="drawer-incident ' + incidentClass + '">' +
          '<span class="drawer-incident-flow">' + escapeHtml(fromStatus) + ' \u2192 ' + escapeHtml(toStatus) + '</span>' +
          '<span class="drawer-incident-time">' + escapeHtml(relative) + '</span>' +
        '</li>'
      );
    }).join('');
  }

  async function fetchGlobalIncidents() {
    var now = Date.now();
    if (latestGlobalIncidents && (now - latestGlobalIncidentsFetchedAt) < GLOBAL_INCIDENTS_CACHE_MS) {
      return latestGlobalIncidents;
    }
    try {
      var incidents = await fetchJson(INCIDENTS_URL);
      if (Array.isArray(incidents)) {
        latestGlobalIncidents = incidents;
        latestGlobalIncidentsFetchedAt = now;
        return incidents;
      }
    } catch (err) {
      console.warn('[marcle] Global incidents fetch failed:', err.message);
    }
    return latestGlobalIncidents || [];
  }

  async function resolveIncidentsForService(serviceId, preferredIncidents) {
    if (Array.isArray(preferredIncidents) && preferredIncidents.length > 0) {
      return preferredIncidents;
    }
    var incidents = await fetchGlobalIncidents();
    return incidents.filter(function (incident) {
      return incident && incident.service_id === serviceId;
    });
  }

  async function refreshDrawerDetails(serviceId, silent) {
    if (!serviceId || !drawerBackdrop || drawerBackdrop.classList.contains('is-hidden')) return;

    var requestToken = ++drawerRequestToken;
    if (!silent) {
      showDrawerLoading();
      setDrawerError('');
    }

    try {
      var payload = await fetchJson(SERVICE_DETAILS_BASE + encodeURIComponent(serviceId));
      if (requestToken !== drawerRequestToken || selectedServiceId !== serviceId) return;

      if (!payload || typeof payload !== 'object' || !payload.service) {
        throw new Error('Malformed details payload');
      }
      var incidents = await resolveIncidentsForService(serviceId, payload.recent_incidents);
      if (requestToken !== drawerRequestToken || selectedServiceId !== serviceId) return;

      renderDrawerFields(payload.service);
      renderDrawerIncidents(incidents);
      hideDrawerLoading();
      setDrawerError('');
      if (drawerBody) {
        drawerBody.classList.remove('is-hidden');
      }
      drawerHasRenderedContent = true;
    } catch (err) {
      if (requestToken !== drawerRequestToken || selectedServiceId !== serviceId) return;
      hideDrawerLoading();
      setDrawerError('Unable to load service details right now.');
      if (!drawerHasRenderedContent && drawerBody) {
        drawerBody.classList.add('is-hidden');
      }
    }
  }

  function openServiceDrawer(serviceId) {
    if (!serviceId || !drawerBackdrop) return;
    selectedServiceId = serviceId;
    drawerHasRenderedContent = false;
    lastFocusedElement = document.activeElement;

    var statusService = serviceFromStatus(serviceId);
    setDrawerHeader(
      statusService && statusService.name ? statusService.name : serviceId,
      statusService && statusService.status ? statusService.status : 'unknown'
    );
    showDrawerLoading();
    setDrawerError('');
    if (drawerIncidents) drawerIncidents.innerHTML = '';
    if (drawerIncidentsEmpty) drawerIncidentsEmpty.classList.add('is-hidden');

    drawerBackdrop.hidden = false;
    drawerBackdrop.classList.remove('is-hidden');
    drawerBackdrop.setAttribute('aria-hidden', 'false');
    document.body.classList.add('drawer-open');

    if (drawerCloseButton) {
      drawerCloseButton.focus();
    }
    refreshDrawerDetails(serviceId, false);
  }

  function closeServiceDrawer() {
    if (!drawerBackdrop) return;
    selectedServiceId = null;
    drawerRequestToken += 1;
    drawerBackdrop.classList.add('is-hidden');
    drawerBackdrop.setAttribute('aria-hidden', 'true');
    drawerBackdrop.hidden = true;
    document.body.classList.remove('drawer-open');

    if (
      lastFocusedElement &&
      typeof lastFocusedElement.focus === 'function' &&
      document.contains(lastFocusedElement)
    ) {
      lastFocusedElement.focus();
    }
    lastFocusedElement = null;
  }

  function getDrawerFocusableElements() {
    if (!drawerPanel) return [];
    var selectors = [
      'a[href]',
      'button:not([disabled])',
      '[tabindex]:not([tabindex="-1"])'
    ].join(',');
    return Array.prototype.slice.call(drawerPanel.querySelectorAll(selectors)).filter(function (el) {
      return !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true' && el.offsetParent !== null;
    });
  }

  function onDrawerKeydown(evt) {
    if (evt.key !== 'Tab') return;
    var focusable = getDrawerFocusableElements();
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

  function onGridClick(evt) {
    if (!statusGrid) return;
    var trigger = evt.target.closest('[data-service-id]');
    if (!trigger || !statusGrid.contains(trigger)) return;
    evt.preventDefault();
    var serviceId = trigger.getAttribute('data-service-id');
    openServiceDrawer(serviceId);
  }

  function onBackdropClick(evt) {
    if (evt.target === drawerBackdrop) {
      closeServiceDrawer();
    }
  }

  function onDocumentKeydown(evt) {
    if (evt.key === 'Escape' && drawerBackdrop && !drawerBackdrop.classList.contains('is-hidden')) {
      evt.preventDefault();
      closeServiceDrawer();
    }
  }

  async function refreshDashboard() {
    var results = await Promise.allSettled([
      fetchJson(STATUS_URL),
      fetchJson(OVERVIEW_URL),
    ]);

    if (results[0].status === 'fulfilled') {
      latestStatusData = results[0].value;
    } else {
      console.warn('[marcle] Status fetch failed:', results[0].reason && results[0].reason.message);
      if (!latestStatusData) {
        renderStatusUnavailable();
      }
    }

    if (results[1].status === 'fulfilled') {
      latestOverviewData = results[1].value;
    } else {
      console.warn('[marcle] Overview fetch failed:', results[1].reason && results[1].reason.message);
      latestOverviewData = null;
    }

    if (latestStatusData) {
      renderStatusGrid(latestStatusData, latestOverviewData);
      renderOverview(latestStatusData, latestOverviewData);
      if (selectedServiceId) {
        var stillPresent = serviceFromStatus(selectedServiceId);
        if (stillPresent) {
          refreshDrawerDetails(selectedServiceId, true);
        } else {
          closeServiceDrawer();
        }
      }
      return;
    }

    try {
      // fallback in case previous status call failed and no cached UI data exists
      latestStatusData = await fetchJson(STATUS_URL);
      renderStatusGrid(latestStatusData, latestOverviewData);
      renderOverview(latestStatusData, latestOverviewData);
      if (selectedServiceId) {
        refreshDrawerDetails(selectedServiceId, true);
      }
    } catch (err) {
      console.warn('[marcle] Status fallback fetch failed:', err.message);
      renderStatusUnavailable();
    }
  }

  if (statusGrid) {
    statusGrid.addEventListener('click', onGridClick);
  }
  if (drawerCloseButton) {
    drawerCloseButton.addEventListener('click', closeServiceDrawer);
  }
  if (drawerBackdrop) {
    drawerBackdrop.addEventListener('click', onBackdropClick);
  }
  if (drawerPanel) {
    drawerPanel.addEventListener('keydown', onDrawerKeydown);
  }
  document.addEventListener('keydown', onDocumentKeydown);

  // Initial fetch
  refreshDashboard();

  // Poll
  setInterval(refreshDashboard, POLL_INTERVAL);
})();
