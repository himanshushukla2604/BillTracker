// Apply the saved (or system) theme before first paint to avoid a flash.
try {
  var t = localStorage.getItem('ft-theme');
  var dark = t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.classList.toggle('dark', dark);
} catch (e) { /* storage blocked: the stylesheet's default applies */ }
