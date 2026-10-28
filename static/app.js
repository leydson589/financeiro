'use strict';
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/service-worker.js').catch(() => {});
}
const connection = document.getElementById('connection-status');
function updateConnection() {
  if (connection) connection.hidden = navigator.onLine;
}
window.addEventListener('online', updateConnection);
window.addEventListener('offline', updateConnection);
updateConnection();
for (const link of document.querySelectorAll('.navigation a')) {
  if (new URL(link.href).pathname === location.pathname) link.setAttribute('aria-current', 'page');
}
let installPrompt;
const installButton = document.getElementById('install-app');
window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault(); installPrompt = event;
  if (installButton) installButton.hidden = false;
});
if (installButton) installButton.addEventListener('click', async () => {
  if (!installPrompt) return;
  await installPrompt.prompt();
  installPrompt = undefined; installButton.hidden = true;
});
window.addEventListener('appinstalled', () => {
  installPrompt = undefined;
  if (installButton) installButton.hidden = true;
});
