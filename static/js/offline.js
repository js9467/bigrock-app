(function(){
  function goOffline(){
    window.location.href = '/offline';
  }
  // Only redirect when the browser fires a genuine offline event.
  // Do NOT check on page load — on boot, the network stack may not be
  // fully ready when Chromium starts, causing a false offline redirect.
  window.addEventListener('offline', goOffline);
})();
