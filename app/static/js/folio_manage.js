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
  var avatarInput = document.querySelector('input[name="avatar_url"]');
  var toggleInput = document.querySelector('input[name="is_public"]');

  var previewName = document.querySelector('[data-fm-preview-name]');
  var previewRole = document.querySelector('[data-fm-preview-role]');
  var previewBio = document.querySelector('[data-fm-preview-bio]');
  var previewCta = document.querySelector('[data-fm-preview-cta]');
  var previewAvatar = document.querySelector('[data-fm-preview-avatar]');
  var previewFallback = document.querySelector('[data-fm-preview-fallback]');
  var previewHint = document.querySelector('.fm-preview-hint');

  if (previewName && nameInput) {
    var debounceTimer = null;

    var setInitial = window.getComputedStyle ? window.getComputedStyle(previewName).color : null;

    var sanitizeDigits = function (s) {
      return (s || '').replace(/[^0-9]/g, '');
    };

    var validUrl = function (s) {
      if (!s) return false;
      try {
        var u = new URL(s);
        return u.protocol === 'http:' || u.protocol === 'https:';
      } catch (e) {
        return false;
      }
    };

    var initial = function (s) {
      var trimmed = (s || '').trim();
      return trimmed ? trimmed.charAt(0).toUpperCase() : '?';
    };

    var updatePreview = function () {
      var name = nameInput.value.trim();
      var role = roleInput ? roleInput.value.trim() : '';
      var bio = bioInput ? bioInput.value : '';
      var phone = phoneInput ? phoneInput.value.trim() : '';
      var avatar = avatarInput ? avatarInput.value.trim() : '';

      previewName.textContent = name || 'Your name';

      if (role) {
        previewRole.textContent = role;
        previewRole.removeAttribute('hidden');
      } else {
        previewRole.setAttribute('hidden', '');
      }

      if (bio && bio.trim()) {
        previewBio.textContent = bio;
        previewBio.removeAttribute('hidden');
      } else {
        previewBio.setAttribute('hidden', '');
        previewBio.textContent = '';
      }

      if (phone && sanitizeDigits(phone).length >= 6) {
        var digits = sanitizeDigits(phone);
        previewCta.setAttribute('href', 'https://wa.me/' + digits);
        previewCta.textContent = 'WhatsApp →';
        previewCta.removeAttribute('hidden');
      } else {
        previewCta.setAttribute('hidden', '');
      }

      if (validUrl(avatar)) {
        previewAvatar.src = avatar;
        previewAvatar.removeAttribute('hidden');
        previewFallback.setAttribute('hidden', '');
      } else {
        previewAvatar.removeAttribute('src');
        previewAvatar.setAttribute('hidden', '');
        previewFallback.textContent = initial(name);
        previewFallback.removeAttribute('hidden');
      }
    };

    var schedule = function () {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(updatePreview, 120);
    };

    [nameInput, roleInput, bioInput, phoneInput, avatarInput].forEach(function (el) {
      if (el) el.addEventListener('input', schedule);
    });

    if (toggleInput && previewHint) {
      var setHint = function (isLive) {
        while (previewHint.firstChild) previewHint.removeChild(previewHint.firstChild);
        var dot = document.createElement('span');
        dot.className = 'fm-preview-dot' + (isLive ? ' is-live' : '');
        var text = document.createTextNode(isLive ? ' Live — others see this now' : ' Preview — only you see this until you toggle public');
        previewHint.appendChild(dot);
        previewHint.appendChild(text);
      };
      toggleInput.addEventListener('change', function () {
        setHint(toggleInput.checked);
      });
    }

    updatePreview();
  }

})();