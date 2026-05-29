(function(){
  const STORAGE_PLAYING = 'vhfPlaying';
  const STORAGE_VOLUME = 'vhfVolume';
  let hls = null;
  let streamUrl = null;
  const audio = document.getElementById('radio-player') || (() => {
    const a = document.createElement('audio');
    a.id = 'radio-player';
    a.hidden = true;
    document.body.appendChild(a);
    return a;
  })();

  function updateButton(isPlaying){
    const btn = document.querySelector('[data-vhf-toggle]');
    if(btn) btn.textContent = isPlaying ? 'VHF OFF' : 'VHF ON';
  }
  function updateVolumeDisplay(v){
    const span = document.querySelector('[data-vhf-volume-display]');
    if(span) span.textContent = v + '%';
  }

  function disableControls(){
    const btn = document.querySelector('[data-vhf-toggle]');
    const vol = document.querySelector('[data-vhf-volume]');
    if(btn){
      btn.disabled = true;
      btn.textContent = 'NO VHF';
    }
    if(vol) vol.disabled = true;
  }

  async function getStream(){
    if(streamUrl !== null) return streamUrl;
    streamUrl = '';

    try{
      const s = await fetch('/api/settings').then(r=>r.json());
      const t = s.tournament;
      const data = await fetch('/api/tournaments').then(r=>r.json());
      streamUrl = (data?.tournaments?.[t])?.stream || '';
    }catch(e){console.error('stream fetch failed',e);}
    if(!streamUrl){
      disableControls();
      localStorage.setItem(STORAGE_PLAYING,'false');
    }

    return streamUrl;
  }
  async function play(){
    const url = await getStream();

    if(!url){return Promise.reject();}

    if(window.Hls && Hls.isSupported()){
      if(!hls) hls = new Hls();
      hls.loadSource(url);
      hls.attachMedia(audio);

    }else{
      audio.src = url;
    }
    const p = audio.play();
    localStorage.setItem(STORAGE_PLAYING,'true');
    updateButton(true);
    return p;

  }
  function stop(){
    audio.pause();
    localStorage.setItem(STORAGE_PLAYING,'false');
    updateButton(false);
  }
  async function toggle(){
    if(audio.paused) await play().catch(()=>{}); else stop();

  }
  function applyVolume(v){
    audio.volume = v/100;
    localStorage.setItem(STORAGE_VOLUME, v);
    updateVolumeDisplay(v);
  }
  function setupListeners(){
    const btn = document.querySelector('[data-vhf-toggle]');
    const vol = document.querySelector('[data-vhf-volume]');
    if(btn) btn.addEventListener('click',toggle);
    if(vol) vol.addEventListener('input', e=>applyVolume(e.target.value));

    getStream();

    const savedVol = localStorage.getItem(STORAGE_VOLUME);
    const v = savedVol !== null ? Number(savedVol) : (vol?Number(vol.value):30);
    if(vol) { vol.value = v; updateVolumeDisplay(v); }
    applyVolume(v);

    function resumeOnInteraction(){
      if(audio.paused && localStorage.getItem(STORAGE_PLAYING)==='true'){
        play().catch(()=>{});
      }
    }
    if(localStorage.getItem(STORAGE_PLAYING)==='true'){
      play().catch(()=>{
        if(localStorage.getItem(STORAGE_PLAYING)==='true'){
          document.addEventListener('click',resumeOnInteraction,{once:true});
          document.addEventListener('touchstart',resumeOnInteraction,{once:true});
        }
      });
    }else updateButton(false);
  }

  document.addEventListener('DOMContentLoaded',()=>{
    // If a nav-placeholder exists, the controls are injected async by nav.js.
    // Wait for the 'nav-ready' event before binding VHF listeners.
    if(document.getElementById('nav-placeholder')){
      document.addEventListener('nav-ready', setupListeners, {once:true});
    } else {
      setupListeners();
    }
  });
})();
