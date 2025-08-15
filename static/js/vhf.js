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
  async function getStream(){
    if(streamUrl) return streamUrl;
    try{
      const s = await fetch('/api/settings').then(r=>r.json());
      const t = s.tournament;
      const all = await fetch('https://js9467.github.io/Brtourney/settings.json').then(r=>r.json());
      streamUrl = all[t]?.stream || all[t]?.fallback_stream || '';
    }catch(e){console.error('stream fetch failed',e);}
    return streamUrl;
  }
  async function play(){
    const url = await getStream();
    if(!url){alert('No VHF stream available.');return;}
    if(window.Hls && Hls.isSupported()){
      if(!hls) hls = new Hls();
      hls.loadSource(url);
      hls.attachMedia(audio);
      hls.on(Hls.Events.MANIFEST_PARSED,()=>{audio.play().catch(()=>{});});
    }else{
      audio.src = url;
      audio.play().catch(()=>{});
    }
    localStorage.setItem(STORAGE_PLAYING,'true');
    updateButton(true);
  }
  function stop(){
    audio.pause();
    localStorage.setItem(STORAGE_PLAYING,'false');
    updateButton(false);
  }
  async function toggle(){
    if(audio.paused) await play(); else stop();
  }
  function applyVolume(v){
    audio.volume = v/100;
    localStorage.setItem(STORAGE_VOLUME, v);
    updateVolumeDisplay(v);
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const btn = document.querySelector('[data-vhf-toggle]');
    const vol = document.querySelector('[data-vhf-volume]');
    if(btn) btn.addEventListener('click',toggle);
    if(vol) vol.addEventListener('input', e=>applyVolume(e.target.value));
    const savedVol = localStorage.getItem(STORAGE_VOLUME);
    const v = savedVol !== null ? Number(savedVol) : (vol?Number(vol.value):30);
    if(vol) { vol.value = v; updateVolumeDisplay(v); }
    applyVolume(v);
    if(localStorage.getItem(STORAGE_PLAYING)==='true'){
      play();
    }else updateButton(false);
  });
})();
