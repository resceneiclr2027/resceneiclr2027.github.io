const dialog = document.querySelector('.figure-dialog');
if (dialog && typeof dialog.showModal === 'function') {
  let trigger = null;
  const expanded = dialog.querySelector('[data-figure-expanded]');
  const original = dialog.querySelector('[data-figure-original]');
  for (const link of document.querySelectorAll('[data-figure-link]')) {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      trigger = link;
      expanded.src = link.href;
      expanded.alt = link.dataset.figureAlt || link.querySelector('img')?.alt || '';
      original.href = link.href;
      dialog.classList.toggle('architecture-open', link.dataset.figureKind === 'architecture');
      dialog.showModal();
      document.body.classList.add('figure-open');
    });
  }
  dialog.querySelector('[data-figure-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener('close', () => {
    document.body.classList.remove('figure-open');
    dialog.classList.remove('architecture-open');
    trigger?.focus({ preventScroll: true });
  });
}

const links = [...document.querySelectorAll('nav a')];
const carlaVideo = document.querySelector('.carla-video-figure video');
if (carlaVideo && 'matchMedia' in window) {
  const narrowVideo = window.matchMedia('(max-width: 480px)');
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    carlaVideo.autoplay = false;
    carlaVideo.pause();
  }
  const updateVideo = () => {
    const wasPlaying = !carlaVideo.paused;
    carlaVideo.poster = narrowVideo.matches
      ? 'assets/carla-authored-pair-mobile-poster.jpg'
      : 'assets/carla-authored-pair-poster.jpg';
    carlaVideo.load();
    if (wasPlaying) carlaVideo.play().catch(() => {});
  };
  updateVideo();
  narrowVideo.addEventListener?.('change', updateVideo);
}
if ('IntersectionObserver' in window) {
  const visible = new Set();
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) entry.isIntersecting ? visible.add(entry.target.id) : visible.delete(entry.target.id);
    const current = links.find(link => visible.has(link.hash.slice(1)));
    for (const link of links) current === link ? link.setAttribute('aria-current', 'location') : link.removeAttribute('aria-current');
  }, { rootMargin: '-120px 0px -40% 0px' });
  for (const link of links) {
    const section = document.querySelector(link.hash);
    if (section) observer.observe(section);
  }
}
