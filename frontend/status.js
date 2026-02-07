// marcle.ai — status fetcher
// Progressive enhancement: page works without JS, status grid populates when API is reachable.

(function () {
  'use strict';

  const API_BASE = window.MARCLE_API_BASE || '';
  const STATUS_URL = API_BASE + '/api/status';
  const POLL_INTERVAL = 60000; // 60s

  const statusGrid = document.getElementById('status-grid');
  const serviceCount = document.getElementById('service-count');

  function renderStatusGrid(data) {
    if (!statusGrid) return;

    // Update overall indicator
    const dot = document.querySelector('.meta-dot');
    if (dot) {
      dot.className = 'meta-dot ' + (data.overall_status || 'unknown');
      const label = dot.parentElement;
      if (label) {
        label.innerHTML = '';
        label.appendChild(dot);
        label.appendChild(document.createTextNode(' systems ' + (data.overall_status || 'unknown')));
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
      var group = svc.group || '';
      return (
        '<div class="status-card">' +
          '<div class="status-card-header">' +
            '<span class="status-card-name">' + escapeHtml(svc.name) + '</span>' +
            '<span class="status-indicator ' + escapeHtml(svc.status) + '"></span>' +
          '</div>' +
          '<span class="status-card-detail">' + escapeHtml(group) + ' · ' + latency + '</span>' +
        '</div>'
      );
    }).join('');
  }

  function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  async function fetchStatus() {
    try {
      var resp = await fetch(STATUS_URL);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      var data = await resp.json();
      renderStatusGrid(data);
    } catch (err) {
      console.warn('[marcle] Status fetch failed:', err.message);
      if (statusGrid) {
        statusGrid.innerHTML =
          '<div class="status-placeholder">Status unavailable. API may be offline.</div>';
      }
    }
  }

  // Initial fetch
  fetchStatus();

  // Poll
  setInterval(fetchStatus, POLL_INTERVAL);
})();
