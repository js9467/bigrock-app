(function(){
  function goOffline(){
    window.location.href = '/offline';
  }
  // Only redirect when the browser fires a genuine offline event.
  // Do NOT check on page load — on boot, the network stack may not be
  // fully ready when Chromium starts, causing a false offline redirect.
  window.addEventListener('offline', goOffline);
})();

// Add-to-Home-Screen nudge — mobile browser only, hidden once in standalone PWA mode
(function() {
  var isStandalone = window.navigator.standalone === true ||
                     window.matchMedia('(display-mode: standalone)').matches;
  if (isStandalone || sessionStorage.getItem('ath_dismissed')) return;
  if (window.innerWidth > 639) return;
  var isIOS     = /iphone|ipad|ipod/i.test(navigator.userAgent);
  var isAndroid = /android/i.test(navigator.userAgent);
  if (!isIOS && !isAndroid) return;

  var msg = isIOS
    ? 'Tap <strong>Share ↑</strong> then <strong>Add to Home Screen</strong> for the best experience'
    : 'Tap <strong>⋮</strong> then <strong>Add to Home Screen</strong> for the best experience';

  function injectBanner() {
    if (document.querySelector('.ath-banner')) return;
    var banner = document.createElement('div');
    banner.className = 'ath-banner';
    banner.innerHTML =
      '<span class="ath-icon">📲</span>' +
      '<span>' + msg + '</span>' +
      '<button class="ath-close" aria-label="Dismiss">✕</button>';
    banner.querySelector('.ath-close').addEventListener('click', function() {
      banner.remove();
      sessionStorage.setItem('ath_dismissed', '1');
    });
    var anchor = document.querySelector('header') || document.getElementById('nav-placeholder');
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(banner, anchor.nextSibling);
    } else {
      document.body.insertBefore(banner, document.body.firstChild);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectBanner);
  } else {
    injectBanner();
  }
  // Also re-try after nav.js swaps in the header
  document.addEventListener('nav-ready', injectBanner);
})();
