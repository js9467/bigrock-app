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

    // Followed boats
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
        logoEl.onerror = () => { logoEl.src = '/static/images/bigrock.webp'; };
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

  function loadFollowedBoats() {
    fetch('/followed-boats')
      .then(r => r.json())
      .then(boats => {
        const strip     = document.getElementById('nav-followed-strip');
        const container = document.getElementById('nav-followed-boats');
        if (!strip || !container) return;
        strip.style.display = boats.length ? 'flex' : 'none';
        container.innerHTML = boats
          .map(b => `<div class="followed-chip">&#127869; ${esc(b)} <button class="followed-chip-remove" onclick="window._navUnfollow(${JSON.stringify(b)})">&#x2715;</button></div>`)
          .join('');
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
