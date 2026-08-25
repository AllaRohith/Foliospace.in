(function () {

  var match = (window.location.pathname || '').match(/^\/([^\/]+)\/manage\/?$/);
  var slug = match ? match[1] : '';

  var dropzone = document.querySelector('[data-fm-avatar-dropzone]');
  var input = document.getElementById('fm-avatar-input');
  var progressEl = document.querySelector('[data-fm-avatar-progress]');
  var progressFill = document.querySelector('[data-fm-avatar-progress-fill]');
  var progressText = document.querySelector('[data-fm-avatar-progress-text]');
  var errorEl = document.querySelector('[data-fm-avatar-error]');
  var replaceBtn = document.querySelector('[data-fm-avatar-replace]');
  var removeBtn = document.querySelector('[data-fm-avatar-remove]');

  var MAX_BYTES = 2 * 1024 * 1024;
  var ALLOWED = ['image/jpeg', 'image/png', 'image/webp'];

  function showError(msg) {
    if (!errorEl) return;
    errorEl.textContent = msg;
    errorEl.removeAttribute('hidden');
  }

  function clearError() {
    if (!errorEl) return;
    errorEl.setAttribute('hidden', '');
    errorEl.textContent = '';
  }

  function validate(file) {
    if (!file) return 'No file selected.';
    if (ALLOWED.indexOf(file.type) === -1) return 'Only JPG, PNG, or WebP allowed.';
    if (file.size > MAX_BYTES) return 'Photo must be 2 MB or smaller.';
    return null;
  }

  function setProgress(pct, text) {
    if (!progressEl) return;
    progressEl.removeAttribute('hidden');
    if (progressFill) progressFill.style.width = pct + '%';
    if (progressText) progressText.textContent = text;
  }

  function hideProgress() {
    if (!progressEl) return;
    progressEl.setAttribute('hidden', '');
    if (progressFill) progressFill.style.width = '0%';
  }

  function startUpload(file) {
    if (!slug) {
      showError('Could not detect your folio URL. Reload and try again.');
      return;
    }
    clearError();
    var err = validate(file);
    if (err) { showError(err); return; }

    fetch('/' + slug + '/manage/avatar/sign', { credentials: 'same-origin' })
      .then(function (r) {
        return r.json().catch(function () { return {}; });
      })
      .then(function (sign) {
        if (!sign || !sign.ok) {
          if (sign && sign.message === 'uploads-disabled') {
            showError('Uploads are temporarily unavailable.');
          } else {
            showError('Uploads are temporarily unavailable.');
          }
          return null;
        }
        var fd = new FormData();
        fd.append('file', file);
        fd.append('api_key', sign.api_key);
        fd.append('timestamp', sign.timestamp);
        fd.append('signature', sign.signature);
        fd.append('upload_preset', sign.upload_preset);
        fd.append('folder', sign.folder);

        var xhr = new XMLHttpRequest();
        xhr.open('POST', 'https://api.cloudinary.com/v1_1/' + sign.cloud_name + '/image/upload');
        xhr.upload.onprogress = function (e) {
          if (!e.lengthComputable) return;
          setProgress(Math.round((e.loaded / e.total) * 100), 'Uploading…');
        };
        xhr.onload = function () {
          if (xhr.status < 200 || xhr.status >= 300) {
            showError('Upload failed. Try again.');
            hideProgress();
            return;
          }
          var body;
          try { body = JSON.parse(xhr.responseText); }
          catch (e) { showError('Upload response unreadable.'); hideProgress(); return; }
          var url = body.secure_url;
          var publicId = body.public_id;
          if (!url || !publicId) {
            showError('Upload response missing data.');
            hideProgress();
            return;
          }
          setProgress(100, 'Saving…');
          fetch('/' + slug + '/manage/avatar', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, public_id: publicId })
          }).then(function (r2) {
            return r2.json().catch(function () { return {}; });
          }).then(function (saved) {
            if (!saved || !saved.ok) {
              showError('Save failed. Try again.');
              hideProgress();
              return;
            }
            var thumb = document.querySelector('.fm-avatar-thumb');
            if (thumb && saved.url) {
              var bust = (saved.url.indexOf('?') === -1 ? '?' : '&') + 'v=' + Date.now();
              thumb.setAttribute('src', saved.url + bust);
            }
            try {
              document.dispatchEvent(new CustomEvent('fm:avatar-updated', { detail: { url: saved.url, public_id: saved.public_id } }));
            } catch (e) {}
            hideProgress();
          }).catch(function () {
            showError('Save failed. Try again.');
            hideProgress();
          });
        };
        xhr.onerror = function () {
          showError('Network error. Try again.');
          hideProgress();
        };
        xhr.send(fd);
      })
      .catch(function () {
        showError('Could not start upload. Reload and try again.');
      });
  }

  if (dropzone && input) {
    dropzone.addEventListener('click', function (e) {
      if (e.target && e.target.tagName === 'INPUT') return;
      input.click();
    });
    dropzone.addEventListener('dragover', function (e) {
      e.preventDefault();
      dropzone.classList.add('is-dragover');
    });
    dropzone.addEventListener('dragleave', function () {
      dropzone.classList.remove('is-dragover');
    });
    dropzone.addEventListener('drop', function (e) {
      e.preventDefault();
      dropzone.classList.remove('is-dragover');
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) startUpload(file);
    });
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      if (file) startUpload(file);
    });
  }

  if (replaceBtn) {
    replaceBtn.addEventListener('click', function () {
      var replacement = document.createElement('input');
      replacement.type = 'file';
      replacement.accept = 'image/jpeg,image/png,image/webp';
      replacement.addEventListener('change', function () {
        var file = replacement.files && replacement.files[0];
        if (file) startUpload(file);
      });
      replacement.click();
    });
  }

  if (removeBtn) {
    removeBtn.addEventListener('click', function () {
      if (!slug) return;
      if (!window.confirm('Remove your avatar? Visitors will see your initial instead.')) return;
      fetch('/' + slug + '/manage/avatar', {
        method: 'DELETE',
        credentials: 'same-origin',
      }).then(function (r) {
        return r.json().catch(function () { return {}; });
      }).then(function (j) {
        if (j && j.ok) window.location.reload();
        else showError('Could not remove. Try again.');
      }).catch(function () {
        showError('Could not remove. Try again.');
      });
    });
  }

})();
