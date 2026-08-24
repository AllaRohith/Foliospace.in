(function () {
  'use strict';

  // Bail early if WebAuthn isn't supported. Don't error; just leave CTAs inert.
  var hasWebAuthn = !!(window.PublicKeyCredential && navigator.credentials && typeof navigator.credentials.get === 'function');
  if (!hasWebAuthn) {
    document.querySelectorAll('[data-passkey-login], [data-passkey-register], [data-passkey-revoke]').forEach(function (btn) {
      btn.disabled = true;
      btn.title = 'Passkeys are not supported in this browser.';
    });
    return;
  }

  // Detect passkey support (synchronous hint; helps analytics).
  try {
    if (window.PublicKeyCredential && typeof PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable === 'function') {
      PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable().then(function (yes) {
        if (!yes) {
          document.querySelectorAll('[data-passkey-login], [data-passkey-register]').forEach(function (btn) {
            btn.title = 'No fingerprint / face / PIN authenticator on this device.';
          });
        }
      }).catch(function () {});
    }
  } catch (e) {}

  // ── base64url helpers (Uint8Array ↔ string) ───────────────────────────────────────────────────────────────────────────

  function b64uToBytes(s) {
    s = String(s || '');
    var pad = s.length % 4 === 0 ? '' : '='.repeat(4 - (s.length % 4));
    var b64 = (s + pad).replace(/-/g, '+').replace(/_/g, '/');
    var bin = atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function bytesToB64u(arr) {
    var bytes = arr instanceof ArrayBuffer ? new Uint8Array(arr) : (arr || []);
    var bin = '';
    var chunk = 0x8000;
    for (var i = 0; i < bytes.length; i += chunk) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  // ── DOM helpers ──────────────────────────────────────────────────────────────────────────────────────────────────────

  function setErr(scope, msg) {
    var el = (scope || document).querySelector('[data-passkey-error]');
    if (!el) return;
    if (!msg) { el.textContent = ''; return; }
    el.textContent = msg;
  }

  function clearErr(scope) { setErr(scope, ''); }

  function setBusy(btn, busy, label) {
    if (!btn) return;
    btn.disabled = !!busy;
    if (label) btn.textContent = label;
  }

  function reloadWithParam(name, value) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set(name, value);
      window.location.assign(url.toString());
    } catch (e) {
      window.location.reload();
    }
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
    });
  }

  function fireEvent(name, params) {
    try { if (typeof window.fsEvent === 'function') window.fsEvent(name, params || {}); }
    catch (e) {}
  }

  // ── Convert server JSON options into the typed PublicKeyCredentialDescriptor shape ─────────────────────

  function toPublicKey(opts) {
    var pk = {
      challenge: b64uToBytes(opts.challenge),
      userVerification: opts.userVerification || 'required',
      timeout: opts.timeout || 300000
    };
    if (opts.rpId) pk.rpId = opts.rpId;
    if (Array.isArray(opts.allowCredentials) && opts.allowCredentials.length) {
      pk.allowCredentials = opts.allowCredentials.map(function (c) {
        var d = { type: 'public-key', id: b64uToBytes(c.id) };
        if (Array.isArray(c.transports) && c.transports.length) d.transports = c.transports;
        return d;
      });
    }
    return pk;
  }

  function toRegistrationOptions(opts) {
    var pk = {
      challenge: b64uToBytes(opts.challenge),
      rp: { id: opts.rp.id, name: opts.rp.name },
      user: {
        id: b64uToBytes(opts.user.id),
        name: opts.user.name,
        displayName: opts.user.displayName
      },
      pubKeyCredParams: opts.pubKeyCredParams || [
        { type: 'public-key', alg: -7 },
        { type: 'public-key', alg: -257 },
        { type: 'public-key', alg: -8 }
      ],
      timeout: opts.timeout || 300000
    };
    if (opts.attestation) pk.attestation = opts.attestation;
    if (opts.authenticatorSelection) pk.authenticatorSelection = opts.authenticatorSelection;
    if (Array.isArray(opts.excludeCredentials) && opts.excludeCredentials.length) {
      pk.excludeCredentials = opts.excludeCredentials.map(function (c) {
        var d = { type: 'public-key', id: b64uToBytes(c.id) };
        if (Array.isArray(c.transports) && c.transports.length) d.transports = c.transports;
        return d;
      });
    }
    return pk;
  }

  // ── Credential → JSON serializer (only ArrayBuffer fields, no clientDataJSON decode) ─────────────────────────

  function credentialToJSON(cred) {
    if (!cred) return null;
    var r = cred.response || {};
    var response = {
      clientDataJSON: bytesToB64u(r.clientDataJSON),
      authenticatorData: bytesToB64u(r.authenticatorData),
      signature: bytesToB64u(r.signature)
    };
    if (r.userHandle) {
      response.userHandle = bytesToB64u(r.userHandle);
    }
    return {
      id: cred.id,
      rawId: bytesToB64u(cred.rawId),
      type: cred.type,
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
      response: response
    };
  }

  function attestationToJSON(cred) {
    if (!cred) return null;
    var r = cred.response || {};
    var out = {
      id: cred.id,
      rawId: bytesToB64u(cred.rawId),
      type: cred.type,
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
      response: {
        clientDataJSON: bytesToB64u(r.clientDataJSON),
        attestationObject: bytesToB64u(r.attestationObject)
      }
    };
    return out;
  }

  // ── Login handler ────────────────────────────────────────────────────────────────────────────────────────────

  function passkeyLogin(btn) {
    var scope = btn.closest('.auth-split-form, .welcome-main, .dash-app, body') || document;
    clearErr(scope);
    var orig = btn.dataset.passkeyOrig || btn.innerHTML;
    btn.dataset.passkeyOrig = orig;
    setBusy(btn, true, 'Waiting for passkey…');
    var startedAt = Date.now();

    // Step 1: GET discoverable-credential challenge (no email).
    fetch('/passkey/login/begin', { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        if (!r.ok) {
          return r.json().then(function (d) { throw new Error((d && d.message) || 'Could not start.'); });
        }
        return r.json();
      })
      .then(function (envelope) {
        if (!envelope || !envelope.options) throw new Error('Bad response from server.');
        var pk = toPublicKey(envelope.options);
        return navigator.credentials.get({ publicKey: pk });
      })
      .then(function (cred) {
        if (!cred) throw new Error('No credential returned.');
        var assertion = credentialToJSON(cred);
        return postJSON('/passkey/login/complete', { assertion: assertion });
      })
      .then(function (res) {
        if (res && res.ok && res.data && res.data.redirect) {
          fireEvent('passkey_login', { success: true, ms: Date.now() - startedAt });
          window.location.assign(res.data.redirect);
          return;
        }
        throw new Error((res && res.data && res.data.message) || 'Sign-in failed.');
      })
      .catch(function (err) {
        // User cancelled the platform UI — silent abort.
        if (err && err.name === 'NotAllowedError') {
          fireEvent('passkey_login', { success: false, cancelled: true });
          return;
        }
        var msg = (err && err.message) || 'Could not sign in.';
        setErr(scope, msg);
        fireEvent('passkey_login', { success: false });
        try { console.error('passkey login failed:', err); } catch (e) {}
      })
      .then(function () { setBusy(btn, false); btn.innerHTML = orig; }, function () { setBusy(btn, false); btn.innerHTML = orig; });
  }

  // ── Register handler ──────────────────────────────────────────────────────────────────────────────────────

  function passkeyRegister(btn) {
    var scope = btn.closest('.welcome-main, .dash-app, body') || document;
    clearErr(scope);
    var orig = btn.dataset.passkeyOrig || btn.innerHTML;
    btn.dataset.passkeyOrig = orig;
    setBusy(btn, true, 'Waiting…');

    postJSON('/passkey/register/begin', {})
      .then(function (res) {
        if (!res.ok || !res.data || !res.data.options) {
          var code = (res && res.data && res.data.code) || '';
          var msg = (res && res.data && res.data.message) || 'Could not start.';
          if (code === 'unverified_email') msg = 'Verify your email first.';
          if (code === 'already_enrolled') msg = 'You already have a passkey. Remove it first.';
          throw new Error(msg);
        }
        var pk = toRegistrationOptions(res.data.options);
        return navigator.credentials.create({ publicKey: pk });
      })
      .then(function (cred) {
        if (!cred) throw new Error('No credential returned.');
        var att = attestationToJSON(cred);
        return postJSON('/passkey/register/complete', { attestation: att });
      })
      .then(function (res) {
        if (res && res.ok && res.data && res.data.redirect) {
          fireEvent('passkey_register', { success: true });
          window.location.assign(res.data.redirect);
          return;
        }
        throw new Error((res && res.data && res.data.message) || 'Could not register.');
      })
      .catch(function (err) {
        if (err && err.name === 'NotAllowedError') {
          fireEvent('passkey_register', { success: false, cancelled: true });
          return;
        }
        var msg = (err && err.message) || 'Could not register passkey.';
        setErr(scope, msg);
        fireEvent('passkey_register', { success: false });
        try { console.error('passkey register failed:', err); } catch (e) {}
      })
      .then(function () { setBusy(btn, false); btn.innerHTML = orig; }, function () { setBusy(btn, false); btn.innerHTML = orig; });
  }

  // ── Revoke handler ────────────────────────────────────────────────────────────────────────────────────────

  function passkeyRevoke(btn) {
    var credId = btn.getAttribute('data-passkey-revoke');
    if (!credId) return;
    var scope = btn.closest('.dash-app, body') || document;
    clearErr(scope);
    var orig = btn.textContent;
    if (!window.confirm('Remove this passkey? Email + password will still work.')) return;
    setBusy(btn, true, 'Removing…');

    fetch('/dashboard/passkey/' + encodeURIComponent(credId), {
      method: 'DELETE',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    })
      .then(function (r) {
        if (!r.ok) throw new Error('Could not remove.');
        return r.json();
      })
      .then(function () {
        fireEvent('passkey_revoke', { success: true });
        reloadWithParam('saved', 'revoked');
      })
      .catch(function (err) {
        var msg = (err && err.message) || 'Could not remove passkey.';
        setErr(scope, msg);
        fireEvent('passkey_revoke', { success: false });
        try { console.error('passkey revoke failed:', err); } catch (e) {}
        setBusy(btn, false, orig);
      });
  }

  // ── Wire up ────────────────────────────────────────────────────────────────────────────────────────────────

  function wire() {
    document.querySelectorAll('[data-passkey-login]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        passkeyLogin(btn);
      });
    });
    document.querySelectorAll('[data-passkey-register]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        passkeyRegister(btn);
      });
    });
    document.querySelectorAll('[data-passkey-revoke]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        passkeyRevoke(btn);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
