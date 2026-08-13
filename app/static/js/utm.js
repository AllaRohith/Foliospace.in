(function () {
  var STORAGE_KEY = 'fs_utm';
  var TTL_DAYS = 30;
  var TTL_MS = TTL_DAYS * 24 * 60 * 60 * 1000;

  function clean(value) {
    if (!value) return '';
    var v = String(value).trim().toLowerCase();
    return v.replace(/[^a-z0-9_./\-]/g, '').slice(0, 64);
  }

  function readUrl() {
    try {
      var sp = new URLSearchParams(window.location.search);
      return {
        utm_source: clean(sp.get('utm_source')),
        utm_medium: clean(sp.get('utm_medium')),
        utm_campaign: clean(sp.get('utm_campaign'))
      };
    } catch (err) {
      return { utm_source: '', utm_medium: '', utm_campaign: '' };
    }
  }

  function readStored() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      var obj = JSON.parse(raw);
      if (!obj || typeof obj !== 'object') return null;
      if (Date.now() - (obj.ts || 0) > TTL_MS) return null;
      return obj;
    } catch (err) {
      return null;
    }
  }

  function persist(values) {
    if (!values.utm_source && !values.utm_medium && !values.utm_campaign) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
        utm_source: values.utm_source || '',
        utm_medium: values.utm_medium || '',
        utm_campaign: values.utm_campaign || '',
        ts: Date.now()
      }));
    } catch (err) {}
  }

  function current() {
    var fresh = readUrl();
    if (fresh.utm_source || fresh.utm_medium || fresh.utm_campaign) {
      persist(fresh);
      return fresh;
    }
    var stored = readStored();
    if (stored) {
      return {
        utm_source: stored.utm_source || '',
        utm_medium: stored.utm_medium || '',
        utm_campaign: stored.utm_campaign || ''
      };
    }
    return { utm_source: '', utm_medium: '', utm_campaign: '' };
  }

  function ensureField(form, name, value) {
    if (!value) return;
    var el = form.querySelector('input[name="' + name + '"]');
    if (!el) {
      el = document.createElement('input');
      el.type = 'hidden';
      el.name = name;
      el.autocomplete = 'off';
      form.appendChild(el);
    }
    el.value = value;
  }

  function bind() {
    var utm = current();
    document.addEventListener('submit', function (e) {
      var form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      var action = (form.getAttribute('action') || '').toLowerCase();
      if (action && action.indexOf('/api/waitlist/join') === -1) return;
      if (!form.querySelector('input[name="email"]')) return;
      ensureField(form, 'utm_source', utm.utm_source);
      ensureField(form, 'utm_medium', utm.utm_medium);
      ensureField(form, 'utm_campaign', utm.utm_campaign);
    }, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
