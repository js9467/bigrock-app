(function(){
  function post(url){
    fetch(url,{method:'POST'}).catch(()=>{});
  }
  function show(){ post('/launch_keyboard'); }
  function hide(){ post('/hide_keyboard'); }
  function isEditable(el){
    if(!el) return false;
    const tag=el.tagName;
    return tag==='INPUT' || tag==='TEXTAREA' || el.isContentEditable;
  }
  document.addEventListener('focusin',e=>{ if(isEditable(e.target)) show(); });
  document.addEventListener('focusout',e=>{
    if(isEditable(e.target)){
      setTimeout(()=>{const a=document.activeElement; if(!isEditable(a)) hide();},100);
    }
  });
})();
