function toggleMenu(){
  var nav = document.getElementById('nav');
  if(nav){ nav.classList.toggle('show'); }
}

// Smooth scrolling for in-page anchors
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href^="#"]');
  if(a){
    const id = a.getAttribute('href').substring(1);
    const el = document.getElementById(id);
    if(el){ e.preventDefault(); el.scrollIntoView({behavior:'smooth'}); }
  }
  // Floating success flash
  const flashWrap = document.getElementById('flashWrap');
  if(flashWrap){
    const flashes = Array.from(flashWrap.querySelectorAll('.flash'));
    // Only support close action; do not float success (success hidden in template)
    flashes.forEach(f => {
      const btn = f.querySelector('.flash-close');
      if(btn){ btn.addEventListener('click', () => f.remove()); }
    });
  }
});

// Product gallery thumbs interactions
document.addEventListener('DOMContentLoaded', () => {
  const thumbs = document.getElementById('thumbs');
  const hero = document.getElementById('heroImg');
  if(thumbs && hero){
    const imgs = thumbs.querySelectorAll('img');
    const prev = document.querySelector('.thumbs-nav.prev');
    const next = document.querySelector('.thumbs-nav.next');
    if(imgs.length){ imgs[0].classList.add('active'); }
    imgs.forEach(img => {
      img.addEventListener('click', () => {
        hero.src = img.src;
        imgs.forEach(i => i.classList.remove('active'));
        img.classList.add('active');
      });
    });
    const step = 140;
    if(prev){ prev.addEventListener('click', () => thumbs.scrollBy({left: -step, behavior: 'smooth'})); }
    if(next){ next.addEventListener('click', () => thumbs.scrollBy({left: step, behavior: 'smooth'})); }
  }
  // Welcome toast (show once per session)
  const toast = document.getElementById('welcomeToast');
  if(toast){
    const closeBtn = toast.querySelector('.toast-close');
    const shown = sessionStorage.getItem('welcomed');
    function hide(){ toast.classList.remove('show'); }
    function show(){ toast.classList.add('show'); }
    if(!shown){
      setTimeout(show, 300); // small delay after load
      sessionStorage.setItem('welcomed', '1');
    }
    if(closeBtn){ closeBtn.addEventListener('click', hide); }
    // Close when clicking backdrop (outside inner)
    toast.addEventListener('click', (e) => {
      if(e.target === toast){ hide(); }
    });
    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if(e.key === 'Escape') hide();
    });
  }
  // Expandable admin cards
  document.querySelectorAll('.dash-card').forEach(card => {
    card.addEventListener('click', () => {
      const link = card.getAttribute('data-link');
      if(link){
        window.location.href = link;
        return;
      }
      // set active card
      document.querySelectorAll('.dash-card').forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      // show target panel, hide others
      const target = card.getAttribute('data-target');
      document.querySelectorAll('.dash-panel').forEach(p => p.classList.remove('show'));
      if(target){
        const el = document.querySelector(target);
        if(el){ el.classList.add('show'); }
      }
    });
  });
});
