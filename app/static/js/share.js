/* FolioSpace — share / copy-to-clipboard helper.
 *
 * Wires [data-fm-copy] buttons in the owner manage UI (and anywhere else
 * a copy button is rendered). Falls back to a hidden <textarea>+execCommand
 * on older browsers. Fires a 'share_copy' GA4 event on success.
 */
(function () {
 var btn = document.querySelector('[data-fm-copy]') || document.querySelector('[data-share-copy]');
 if (!btn) return;
 var status = document.querySelector('[data-share-status]');
 var url = btn.getAttribute('data-fm-copy') || btn.getAttribute('data-share-copy') || '';
 var originalLabel = btn.textContent;

 btn.addEventListener('click', function () {
 if (!url) {
 if (status) status.textContent = 'No link to copy yet.';
 return;
 }
 var showCopied = function () {
 btn.textContent = 'Copied';
 btn.classList.add('is-copied');
 if (status) status.textContent = 'Link copied to clipboard.';
 if (typeof window.fsEvent === 'function') {
 window.fsEvent('share_copy', { method: 'clipboard_button' });
 }
 setTimeout(function () {
 btn.textContent = originalLabel;
 btn.classList.remove('is-copied');
 }, 2200);
 };
 if (navigator.clipboard && navigator.clipboard.writeText) {
 navigator.clipboard.writeText(url).then(showCopied, function () {
 if (status) status.textContent = 'Press Cmd+C / Ctrl+C to copy.';
 });
 } else {
 try {
 var ta = document.createElement('textarea');
 ta.value = url;
 ta.setAttribute('readonly', '');
 ta.style.position = 'absolute';
 ta.style.left = '-9999px';
 document.body.appendChild(ta);
 ta.select();
 document.execCommand('copy');
 document.body.removeChild(ta);
 showCopied();
 } catch (e) {
 if (status) status.textContent = 'Could not copy automatically.';
 }
 }
 });

 // Channel tracking — fire events on click of share links.
 var channels = document.querySelectorAll('[data-share-channel]');
 channels.forEach(function (a) {
 a.addEventListener('click', function () {
 if (typeof window.fsEvent !== 'function') return;
 var ch = a.getAttribute('data-share-channel') || 'unknown';
 window.fsEvent('share_click', { channel: ch });
 });
 });
})();