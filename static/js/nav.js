document.addEventListener('DOMContentLoaded', () => {
  const placeholder = document.getElementById('nav-placeholder');
  if (!placeholder) return;

  fetch('/static/components/nav.html')
    .then(res => res.text())
    .then(html => {
      // Replace placeholder with the header element
      const tmp = document.createElement('div');
      tmp.innerHTML = html.trim();
      const headerEl = tmp.firstElementChild;
      placeholder.replaceWith(headerEl);

      // Signal vhf.js that controls are now in the DOM
      document.dispatchEvent(new CustomEvent('nav-ready'));

      initHeader();
    })
    .catch(err => console.error('Failed to load navigation', err));

  function initHeader() {
    // Highlight current active page
    const path = window.location.pathname;
    document.querySelectorAll('.header-nav-btn[data-page]').forEach(btn => {
      const page = btn.dataset.page;
      const active =
        (page === 'home'         && path === '/') ||
        (page === 'participants' && path.includes('participants')) ||
        (page === 'leaderboard'  && path.includes('leaderboard')) ||
        (page === 'releases'     && path.includes('release')) ||
        (page === 'settings'     && path.includes('settings'));
      if (active) btn.classList.add('is-active');
    });

    // Version
    fetch('/api/version')
      .then(r => r.json())
      .then(d => {
        const el = document.getElementById('nav-version');
        if (el && d.version) el.textContent = d.version;
      })
      .catch(() => {});

    // Tournament + brand
    loadTournamentInfo();

    // Stats pills: enrolled count, boats today, followed boats
    loadEnrolledCount();
    setInterval(loadEnrolledCount, 5 * 60 * 1000);

    loadBoatsToday();
    setInterval(loadBoatsToday, 5 * 60 * 1000);

    loadFollowedBoats();
    setInterval(loadFollowedBoats, 10000);

    // Offline ticker
    if (!navigator.onLine) {
      showTicker('&#128225; Offline &mdash; <a href="/settings-page">Connect to Wi-Fi</a>');
    }

    // Mirror VHF playing state to live badge and pod glow
    const vhfBtn = document.querySelector('[data-vhf-toggle]');
    if (vhfBtn) {
      new MutationObserver(() => {
        const playing = vhfBtn.textContent.trim() === 'VHF OFF';
        const live = document.getElementById('nav-vhf-live');
        const pod  = document.getElementById('nav-vhf-pod');
        if (live) live.style.display = playing ? '' : 'none';
        if (pod)  pod.classList.toggle('vhf-active', playing);
        vhfBtn.classList.toggle('is-playing', playing);
      }).observe(vhfBtn, { characterData: true, childList: true });
    }
  }

  function loadTournamentInfo() {
    Promise.all([
      fetch('/api/settings').then(r => r.json()).catch(() => ({})),
      fetch('/api/tournaments').then(r => r.json()).catch(() => ({}))
    ]).then(([settings, tourData]) => {
      const t    = settings.tournament || '';
      const info = (tourData.tournaments || {})[t] || {};

      const nameEl = document.getElementById('nav-tournament-name');
      if (nameEl) nameEl.textContent = t || 'No Tournament Selected';

      const logoEl = document.getElementById('nav-logo');
      if (logoEl && info.logo) {
        logoEl.src = info.logo;
        logoEl.onerror = () => { logoEl.src = '/static/images/bigrock.png'; };
      }

      const dateEl = document.getElementById('nav-tournament-date');
      if (dateEl && info.label) dateEl.textContent = info.label;

      const color = info.color || '#002855';
      document.documentElement.style.setProperty('--brand-color', color);

      if (settings.data_source === 'demo') {
        const badge = document.getElementById('nav-demo-badge');
        if (badge) badge.style.display = '';
        showTicker('&#127869; DEMO MODE &mdash; Events from a prior tournament. <a href="/settings-page">Switch to Live</a>');
      }
    });
  }

  function loadEnrolledCount() {
    fetch('/api/enrolled-count')
      .then(r => r.json())
      .then(d => {
        const el = document.getElementById('nav-enrolled-count');
        if (el) el.textContent = d.count != null ? d.count : '?';
      })
      .catch(() => {});
  }

  function loadBoatsToday() {
    fetch('/api/boats-today')
      .then(r => r.json())
      .then(d => {
        const countEl = document.getElementById('nav-today-count');
        const drawer  = document.getElementById('nav-today-boats');
        const count   = d.count || 0;
        const boats   = d.boats || [];
        if (countEl) countEl.textContent = count;
        if (drawer) {
          drawer.innerHTML = boats.length
            ? boats.map(b => `<span class="stats-boat-chip stats-chip-today">${esc(b)}</span>`).join('')
            : '<span class="stats-empty">No boats reported fishing today yet</span>';
        }
      })
      .catch(() => {});
  }

  function loadFollowedBoats() {
    fetch('/followed-boats')
      .then(r => r.json())
      .then(boats => {
        const countEl = document.getElementById('nav-followed-count');
        const drawer  = document.getElementById('nav-watching-boats');
        if (countEl) countEl.textContent = boats.length;
        if (drawer) {
          drawer.innerHTML = boats.length
            ? boats.map(b =>
                `<span class="stats-boat-chip stats-chip-watching">${esc(b)} <button class="stats-unfollow-btn" onclick="window._navUnfollow(${JSON.stringify(b)})">&#x2715;</button></span>`
              ).join('')
            : '<span class="stats-empty">No boats followed yet</span>';
        }
      })
      .catch(() => {});
  }

  window._navUnfollow = function(boat) {
    fetch('/followed-boats/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boat })
    })
      .then(r => r.json())
      .then(d => { if (d.status === 'ok') loadFollowedBoats(); })
      .catch(() => {});
  };

  let _activePill = null;
  let _enrolledBoatsLoaded = false;

  window._navTogglePill = function(name) {
    const drawerWrap   = document.getElementById('nav-stats-drawer');
    const panels = {
      enrolled: document.getElementById('nav-drawer-enrolled'),
      today:    document.getElementById('nav-drawer-today'),
      watching: document.getElementById('nav-drawer-watching'),
    };
    const pills = {
      enrolled: document.getElementById('nav-pill-enrolled'),
      today:    document.getElementById('nav-pill-today'),
      watching: document.getElementById('nav-pill-watching'),
    };

    if (_activePill === name) {
      // Close
      _activePill = null;
      if (drawerWrap) drawerWrap.style.display = 'none';
      Object.values(panels).forEach(p => { if (p) p.style.display = 'none'; });
      Object.values(pills).forEach(p => { if (p) p.classList.remove('active'); });
      return;
    }

    // Open new, close others
    _activePill = name;
    if (drawerWrap) drawerWrap.style.display = 'flex';
    Object.entries(panels).forEach(([key, p]) => {
      if (p) p.style.display = key === name ? '' : 'none';
    });
    Object.entries(pills).forEach(([key, p]) => {
      if (p) p.classList.toggle('active', key === name);
    });

    // Lazy-load enrolled boats list on first open
    if (name === 'enrolled' && !_enrolledBoatsLoaded) {
      const drawer = document.getElementById('nav-enrolled-boats');
      if (drawer) {
        drawer.innerHTML = '<span class="stats-empty">Loading\u2026</span>';
        fetch('/participants_data')
          .then(r => r.json())
          .then(d => {
            const list = Array.isArray(d) ? d : (d.participants || []);
            const MAX  = 18;
            if (!list.length) {
              drawer.innerHTML = '<span class="stats-empty">No participants found</span>';
              return;
            }
            const chips = list.slice(0, MAX).map(p => `<span class="stats-boat-chip">${esc(p.boat || p.name || '')}</span>`).join('');
            const more  = list.length > MAX ? `<span class="stats-more">+${list.length - MAX} more</span>` : '';
            drawer.innerHTML = chips + more;
            _enrolledBoatsLoaded = true;
          })
          .catch(() => {
            const drawer2 = document.getElementById('nav-enrolled-boats');
            if (drawer2) drawer2.innerHTML = '<span class="stats-empty">Could not load participants</span>';
          });
      }
    }
  };

  function showTicker(msg) {
    const bar   = document.getElementById('nav-ticker-bar');
    const track = document.getElementById('nav-ticker-track');
    if (!bar || !track) return;
    track.innerHTML = msg;
    bar.style.display = '';
  }

  function esc(s) {
    return (s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
});

// Register service worker for PWA support on all pages
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

// Dismiss wvkbd virtual keyboard when the user taps outside an input field.
// On touch kiosks the blur event is unreliable, so we use a global touchstart
// listener instead.  This fires on every page since nav.js is loaded everywhere.
(function () {
  const INPUT_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
  let _kbdVisible = false;
  let _hideTimer  = null;

  document.addEventListener('touchstart', function (e) {
    const tag = e.target && e.target.tagName;
    if (INPUT_TAGS.has(tag)) {
      // Tapped an input — keyboard should be (or will be) visible
      _kbdVisible = true;
      clearTimeout(_hideTimer);
    } else if (_kbdVisible) {
      // Tapped outside an input — dismiss keyboard after a short delay
      // so that a blur→focus transition (moving between inputs) doesn't flicker
      clearTimeout(_hideTimer);
      _hideTimer = setTimeout(function () {
        fetch('/hide_keyboard', { method: 'POST' }).catch(function () {});
        _kbdVisible = false;
      }, 150);
    }
  }, { passive: true });

  // Also track when an input gains focus so we know keyboard should be up
  document.addEventListener('focusin', function (e) {
    if (INPUT_TAGS.has(e.target && e.target.tagName)) {
      _kbdVisible = true;
      clearTimeout(_hideTimer);
    }
  });

  // And when focus leaves all inputs entirely
  document.addEventListener('focusout', function (e) {
    if (INPUT_TAGS.has(e.target && e.target.tagName)) {
      clearTimeout(_hideTimer);
      _hideTimer = setTimeout(function () {
        // Only hide if focus has not moved to another input
        const active = document.activeElement;
        if (!active || !INPUT_TAGS.has(active.tagName)) {
          fetch('/hide_keyboard', { method: 'POST' }).catch(function () {});
          _kbdVisible = false;
        }
      }, 300);
    }
  });
}());
