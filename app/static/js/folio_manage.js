(function () {

  var shareBtn = document.querySelector('[data-fm-share-popover]');
  var sharePanel = document.querySelector('[data-fm-share-popover-panel]');
  if (shareBtn && sharePanel) {
    var openLabel = shareBtn.textContent;
    var closeLabel = 'Close ✕';
    var setOpen = function (open) {
      if (open) {
        sharePanel.removeAttribute('hidden');
        shareBtn.setAttribute('aria-expanded', 'true');
        shareBtn.textContent = closeLabel;
      } else {
        sharePanel.setAttribute('hidden', '');
        shareBtn.setAttribute('aria-expanded', 'false');
        shareBtn.textContent = openLabel;
      }
    };
    shareBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var isOpen = shareBtn.getAttribute('aria-expanded') === 'true';
      setOpen(!isOpen);
    });
    document.addEventListener('click', function (e) {
      if (shareBtn.contains(e.target) || sharePanel.contains(e.target)) return;
      if (shareBtn.getAttribute('aria-expanded') === 'true') setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && shareBtn.getAttribute('aria-expanded') === 'true') {
        setOpen(false);
        shareBtn.focus();
      }
    });
  }

  var copyBtns = document.querySelectorAll('[data-fm-copy]');
  copyBtns.forEach(function (btn) {
    var resetTimer = null;
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      var text = btn.getAttribute('data-fm-copy') || '';
      if (!text) return;
      var done = function () {
        btn.classList.add('is-copied');
        var original = btn.textContent;
        btn.textContent = '✓ Copied';
        if (resetTimer) clearTimeout(resetTimer);
        resetTimer = setTimeout(function () {
          btn.classList.remove('is-copied');
          btn.textContent = original;
        }, 1600);
      };
      var fallback = function () {
        try {
          var ta = document.createElement('textarea');
          ta.value = text;
          ta.setAttribute('readonly', '');
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          done();
        } catch (err) {
          btn.textContent = 'Press ⌘C';
        }
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(fallback);
      } else {
        fallback();
      }
    });
  });

  var bioTextarea = document.querySelector('[data-fm-bio-counter]');
  var bioDisplay = document.querySelector('[data-fm-bio-counter-display]');
  if (bioTextarea && bioDisplay) {
    var max = parseInt(bioTextarea.getAttribute('maxlength') || '280', 10);
    var update = function () {
      var len = bioTextarea.value.length;
      bioDisplay.textContent = len + ' / ' + max;
      if (len >= Math.floor(max * 0.85)) {
        bioDisplay.classList.add('is-near');
      } else {
        bioDisplay.classList.remove('is-near');
      }
    };
    bioTextarea.addEventListener('input', update);
    update();
  }

  var savedFlash = document.querySelector('.fm-flash-ok');
  if (savedFlash && window.history && window.history.replaceState) {
    var url = new URL(window.location.href);
    if (url.searchParams.has('saved')) {
      url.searchParams.delete('saved');
      window.history.replaceState({}, '', url.pathname + (url.search ? url.search : '') + url.hash);
    }
  }


  var nameInput = document.querySelector('input[name="display_name"]');
  var roleInput = document.querySelector('input[name="role"]');
  var bioInput = document.querySelector('textarea[name="bio"]');
  var phoneInput = document.querySelector('input[name="phone"]');

  var liMirror = document.querySelector('[data-fm-li-mirror]');
  var autofillPanel = document.querySelector('[data-fm-autofill]');
  if (liMirror && autofillPanel) {
    var suggestion = { role: '', bio: '', phone: '' };
    var suggestionActive = false;

    var mirrorTitle = liMirror.querySelector('[data-fm-li-mirror-title]');
    var mirrorSummary = liMirror.querySelector('[data-fm-li-mirror-summary]');
    var mirrorPhone = liMirror.querySelector('[data-fm-li-mirror-phone]');
    var mirrorEmail = liMirror.querySelector('[data-fm-li-mirror-email]');
    var mirrorName = liMirror.querySelector('[data-fm-li-mirror-name]');

    var fillFromMirror = function () {
      var t = (mirrorTitle && mirrorTitle.value || '').trim();
      var s = (mirrorSummary && mirrorSummary.value || '').trim();
      var p = (mirrorPhone && mirrorPhone.value || '').trim();
      var e = (mirrorEmail && mirrorEmail.value || '').trim();
      var n = (mirrorName && mirrorName.value || '').trim();

      if (!t && !s && !p && !e && !n) return;

      var parts = [];
      if (t) parts.push({ kind: 'role', val: t.slice(0, 60) });
      if (s) parts.push({ kind: 'bio', val: s.slice(0, 280) });
      if (p) parts.push({ kind: 'phone', val: p });

      if (!parts.length) return;

      var currentEmpty = function () {
        return !roleInput.value.trim() && !bioInput.value.trim() && !phoneInput.value.trim();
      };

      if (parts.length < 1 || !currentEmpty()) {
        autofillPanel.removeAttribute('hidden');
        return;
      }

      for (var i = 0; i < parts.length; i++) {
        var part = parts[i];
        if (part.kind === 'role') suggestion.role = part.val;
        if (part.kind === 'bio') suggestion.bio = part.val;
        if (part.kind === 'phone') suggestion.phone = part.val;
      }
      suggestionActive = true;
      autofillPanel.removeAttribute('hidden');
    };

    var inputs = [mirrorTitle, mirrorSummary, mirrorPhone, mirrorEmail, mirrorName].filter(Boolean);
    inputs.forEach(function (inp) {
      inp.addEventListener('input', fillFromMirror);
      inp.addEventListener('change', fillFromMirror);
    });

    if (window.MutationObserver) {
      var mo = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var t = (muts[i].target).value;
          if (t) { fillFromMirror(); break; }
        }
      });
      inputs.forEach(function (inp) {
        if (inp) mo.observe(inp, { attributes: true, attributeFilter: ['value'] });
      });
    }

    var tryAttr = function () {
      if (window.getAttrVal) {
        var t = (window.getAttrVal(mirrorTitle) || '').trim();
        var s = (window.getAttrVal(mirrorSummary) || '').trim();
        var p = (window.getAttrVal(mirrorPhone) || '').trim();
        if (t || s || p) fillFromMirror();
      }
    };
    setTimeout(tryAttr, 800);
    setTimeout(tryAttr, 2500);

    var pollCount = 0;
    var pollTimer = setInterval(function () {
      pollCount++;
      var t = (mirrorTitle && mirrorTitle.value || '').trim();
      var s = (mirrorSummary && mirrorSummary.value || '').trim();
      var p = (mirrorPhone && mirrorPhone.value || '').trim();
      var e = (mirrorEmail && mirrorEmail.value || '').trim();
      var n = (mirrorName && mirrorName.value || '').trim();
      if (t || s || p || e || n) {
        fillFromMirror();
        clearInterval(pollTimer);
      } else if (pollCount > 12) {
        clearInterval(pollTimer);
      }
    }, 600);

    var applyBtn = autofillPanel.querySelector('[data-fm-autofill-apply]');
    var dismissBtn = autofillPanel.querySelector('[data-fm-autofill-dismiss]');
    if (applyBtn) {
      applyBtn.addEventListener('click', function (e) {
        e.preventDefault();
        if (!suggestionActive) {
          var t2 = (mirrorTitle && mirrorTitle.value || '').trim();
          var s2 = (mirrorSummary && mirrorSummary.value || '').trim();
          var p2 = (mirrorPhone && mirrorPhone.value || '').trim();
          if (t2) suggestion.role = t2.slice(0, 60);
          if (s2) suggestion.bio = s2.slice(0, 280);
          if (p2) suggestion.phone = p2;
        }
        if (suggestion.role && (!roleInput.value.trim())) roleInput.value = suggestion.role;
        if (suggestion.bio && (!bioInput.value.trim())) bioInput.value = suggestion.bio;
        if (suggestion.phone && (!phoneInput.value.trim())) phoneInput.value = suggestion.phone;
        autofillPanel.setAttribute('hidden', '');
        roleInput.dispatchEvent(new Event('input', { bubbles: true }));
        bioInput.dispatchEvent(new Event('input', { bubbles: true }));
        phoneInput.dispatchEvent(new Event('input', { bubbles: true }));
      });
    }
    if (dismissBtn) {
      dismissBtn.addEventListener('click', function (e) {
        e.preventDefault();
        autofillPanel.setAttribute('hidden', '');
        suggestionActive = false;
      });
    }
  }

})();