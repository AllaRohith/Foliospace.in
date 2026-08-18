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

})();