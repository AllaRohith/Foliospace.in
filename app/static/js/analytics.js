/* FolioSpace — GA4 custom-event tracker.
 *
 * Lazy-loads gtag.js (already initialized in gtag-init.min.js), then
 * forwards named events with safe parameters. Never sends PII.
 *
 * Public API:
 *   window.fsEvent('event_name', { key: 'value', ... })
 *
 * Backend integration:
 *   - All router endpoints can fire events by emitting a small
 *     <script> tag with data-fs-event="event_name" + data-fs-* params.
 *   - This file picks them up on DOMContentLoaded and clears the tag.
 */
(function () {
 var SAFE_KEY = /^[a-z][a-z0-9_]{0,39}$/;
 var SAFE_VAL_MAX = 96;

 function push(name, params) {
 if (typeof window.gtag !== 'function') return;
 if (!SAFE_KEY.test(String(name || ''))) return;
 var safe = {};
 try {
 var src = params || {};
 for (var k in src) {
 if (!Object.prototype.hasOwnProperty.call(src, k)) continue;
 if (!SAFE_KEY.test(k)) continue;
 var v = src[k];
 if (v == null) continue;
 if (typeof v === 'number') {
 safe[k] = Math.abs(v) < 1e15 ? v : 0;
 } else {
 var s = String(v).slice(0, SAFE_VAL_MAX);
 safe[k] = s;
 }
 }
 } catch (e) { return; }
 try { window.gtag('event', name, safe); } catch (e) { /* swallow */ }
 }

 window.fsEvent = push;

 function bindOnce() {
 var nodes = document.querySelectorAll('[data-fs-event]');
 if (!nodes.length) return;
 nodes.forEach(function (el) {
 var name = el.getAttribute('data-fs-event');
 if (!SAFE_KEY.test(name || '')) return;
 var params = {};
 for (var i = 0; i < el.attributes.length; i++) {
 var a = el.attributes[i];
 if (!a || !a.name) continue;
 var m = /^data-fs-(.+)$/.exec(a.name);
 if (!m || m[1] === 'event') continue;
 params[m[1]] = a.value;
 }
 push(name, params);
 el.removeAttribute('data-fs-event');
 });
 }

 if (document.readyState === 'loading') {
 document.addEventListener('DOMContentLoaded', bindOnce, { once: true });
 } else {
 bindOnce();
 }
 })();