// Load the visualization bundle only on the concept page.
(() => {
  if (!document.querySelector('.visual-storyboard')) return;
  const source = document.currentScript.src;
  const script = document.createElement('script');
  script.src = new URL('storyboard.bundle.js', source).href;
  script.async = true;
  document.head.append(script);
})();
