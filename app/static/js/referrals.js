/* FolioSpace — referrals dashboard helper.
 3  *
 4  * Wires the copy-link button (data-referral-copy) and emits a 'share_copy'
 5  * GA4 event on success. Mirrors the pattern in app/static/js/share.js so
 6  * the rest of the dashboard keeps one mental model.
 7  */
(function () {
 var copyBtn = document.querySelector('[data-referral-copy]');
 var status = document.querySelector('[data-referral-copy-status]');

 function showCopied() {
 if (!copyBtn) return;
 var label = copyBtn.querySelector('.referral-copy-label') || copyBtn;
 var original = label.textContent;
 label.textContent = 'Copied';
 copyBtn.classList.add('is-copied');
 if (status) status.textContent = 'Link copied to clipboard.';
 if (typeof window.fsEvent === 'function') {
 window.fsEvent('share_copy', { method: 'referral_clipboard' });
 }
 setTimeout(function () {
 label.textContent = original;
 copyBtn.classList.remove('is-copied');
 if (status) status.textContent = '';
 }, 2200);
 }

 function fallbackCopy(text) {
 try {
 var ta = document.createElement('textarea');
 ta.value = text;
 ta.setAttribute('readonly', '');
 ta.style.position = 'absolute';
 ta.style.left = '-9999px';
 document.body.appendChild(ta);
 ta.select();
 document.execCommand('copy');
 document.body.removeChild(ta);
 showCopied();
 return true;
 } catch (e) {
 if (status) status.textContent = 'Could not copy automatically.';
 return false;
 }
 }

 if (copyBtn) {
 copyBtn.addEventListener('click', function () {
 var url = copyBtn.getAttribute('data-referral-copy-value') || '';
 if (!url) {
 if (status) status.textContent = 'No link to copy yet.';
 return;
 }
 if (navigator.clipboard && navigator.clipboard.writeText) {
 navigator.clipboard.writeText(url).then(showCopied, function () {
 fallbackCopy(url);
 });
 } else {
 fallbackCopy(url);
 }
 });
 }

 var shareLinks = document.querySelectorAll('[data-share-channel]');
 shareLinks.forEach(function (a) {
 a.addEventListener('click', function () {
 if (typeof window.fsEvent !== 'function') return;
 var ch = a.getAttribute('data-share-channel') || 'unknown';
 window.fsEvent('share_click', { channel: ch });
 });
 });
})();