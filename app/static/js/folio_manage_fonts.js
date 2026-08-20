(function () {

  var match = (window.location.pathname || '').match(/^\/([^\/]+)\/manage\/?$/);
  var slug = match ? match[1] : '';

  var MAX_BYTES = 1 * 1024 * 1024;
  var ALLOWED_EXT = ['ttf', 'otf', 'woff', 'woff2'];
  var ALLOWED_MIME = [
    'font/ttf', 'font/otf', 'font/woff', 'font/woff2',
    'application/font-ttf', 'application/font-otf', 'application/font-woff', 'application/font-woff2',
    'application/octet-stream'
  ];

  var drop = document.querySelector('[data-fm-fonts-drop]');
  var fileInput = document.getElementById('font-file-input');
  var nameInput = document.getElementById('font-name-input');
  var progressBox = document.querySelector('[data-fm-fonts-progress]');
  var progressBar = document.querySelector('[data-fm-fonts-progress-bar]');
  var progressLabel = document.querySelector('[data-fm-fonts-progress-label]');
  var status = document.querySelector('[data-fm-fonts-status]');
  var list = document.querySelector('[data-fm-fonts-list]');

  function setStatus(msg, kind) {
    if (!status) return;
    status.textContent = msg;
    status.removeAttribute('hidden');
    status.dataset.kind = kind || 'info';
  }

  function setProgress(pct) {
    if (!progressBox) return;
    progressBox.removeAttribute('hidden');
    if (progressBar) progressBar.style.width = pct + '%';
    if (progressLabel) progressLabel.textContent = pct + '%';
  }

  function hideProgress() {
    if (!progressBox) return;
    progressBox.setAttribute('hidden', '');
    if (progressBar) progressBar.style.width = '0%';
    if (progressLabel) progressLabel.textContent = '0%';
  }

  function extOf(name) {
    var m = (name || '').toLowerCase().match(/\.([a-z0-9]+)$/);
    return m ? m[1] : '';
  }

  function pickFile() {
    if (fileInput) fileInput.click();
  }

  if (drop) {
    drop.addEventListener('click', function (e) {
      if (e.target && e.target.tagName === 'INPUT') return;
      pickFile();
    });
    drop.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        pickFile();
      }
    });
    drop.setAttribute('tabindex', '0');
    drop.setAttribute('role', 'button');
    ['dragenter', 'dragover'].forEach(function (evt) {
      drop.addEventListener(evt, function (e) {
        e.preventDefault();
        e.stopPropagation();
        drop.classList.add('is-over');
      });
    });
    ['dragleave', 'drop'].forEach(function (evt) {
      drop.addEventListener(evt, function (e) {
        e.preventDefault();
        e.stopPropagation();
        drop.classList.remove('is-over');
      });
    });
    drop.addEventListener('drop', function (e) {
      var dt = e.dataTransfer;
      if (dt && dt.files && dt.files[0]) upload(dt.files[0]);
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', function () {
      if (fileInput.files && fileInput.files[0]) upload(fileInput.files[0]);
    });
  }

  function upload(file) {
    if (!slug) {
      setStatus('Slug missing — refresh.', 'err');
      return;
    }
    var ext = extOf(file.name);
    if (ALLOWED_EXT.indexOf(ext) < 0) {
      setStatus('Only .ttf .otf .woff .woff2 accepted.', 'err');
      return;
    }
    if (file.size > MAX_BYTES) {
      setStatus('File too big — keep under 1 MB.', 'err');
      return;
    }
    setStatus('Requesting signature…', 'info');
    setProgress(5);
    fetch('/' + slug + '/manage/fonts/sign', { credentials: 'same-origin' })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (j) {
        if (!j || !j.ok) {
          hideProgress();
          setStatus('Could not start upload. Refresh and retry.', 'err');
          return null;
        }
        setProgress(15);
        return uploadToCloudinary(file, j);
      })
      .then(function (result) {
        if (!result) return;
        setProgress(85);
        return saveToBackend(result);
      })
      .then(function (saved) {
        if (!saved) return;
        setProgress(100);
        setStatus('Submitted — awaiting admin review.', 'ok');
        setTimeout(function () { window.location.reload(); }, 900);
      })
      .catch(function () {
        hideProgress();
        setStatus('Upload failed. Try again.', 'err');
      });
  }

  function uploadToCloudinary(file, sig) {
    var url = sig.url || 'https://api.cloudinary.com/v1_1/' + sig.cloud_name + '/auto/upload';
    var fd = new FormData();
    fd.append('file', file);
    fd.append('api_key', sig.api_key);
    fd.append('timestamp', sig.timestamp);
    fd.append('signature', sig.signature);
    fd.append('folder', sig.folder);
    if (sig.public_id) fd.append('public_id', sig.public_id);
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open('POST', url);
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable) {
          var pct = Math.min(80, Math.round(15 + (e.loaded / e.total) * 65));
          setProgress(pct);
        }
      };
      xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            var body = JSON.parse(xhr.responseText);
            resolve({
              url: body.secure_url || body.url,
              public_id: body.public_id
            });
          } catch (e) {
            reject(e);
          }
        } else {
          reject(new Error('cloudinary ' + xhr.status));
        }
      };
      xhr.onerror = function () { reject(new Error('network')); };
      xhr.send(fd);
    });
  }

  function saveToBackend(result) {
    var body = {
      font_name: nameInput ? (nameInput.value || '').trim() || 'Untitled' : 'Untitled',
      url: result.url,
      public_id: result.public_id
    };
    return fetch('/' + slug + '/manage/fonts', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (j) {
        if (j && j.ok) return j.font;
        if (j && j.message === 'limit-reached') {
          hideProgress();
          setStatus('You already have 2 fonts. Delete one first.', 'err');
        } else if (j && j.message === 'pro-only') {
          hideProgress();
          setStatus('Custom fonts are Pro-only.', 'err');
        } else if (j && j.message === 'bad-url') {
          hideProgress();
          setStatus('Cloudinary URL rejected. Retry the upload.', 'err');
        } else {
          hideProgress();
          setStatus('Save failed. Try again.', 'err');
        }
        return null;
      });
  }

  if (list) {
    list.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-fm-fonts-remove]');
      if (!btn) return;
      var row = btn.closest('[data-fm-fonts-row]');
      if (!row) return;
      var fid = row.dataset.fontId;
      if (!fid) return;
      var ok = window.confirm('Remove this font? If it was approved, it stops loading on your folio.');
      if (!ok) return;
      row.classList.add('is-removing');
      fetch('/' + slug + '/manage/fonts/' + fid, {
        method: 'DELETE',
        credentials: 'same-origin'
      }).then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (j) {
          if (j && j.ok) {
            row.parentNode.removeChild(row);
          } else {
            row.classList.remove('is-removing');
            window.alert('Could not remove. Refresh and try again.');
          }
        }).catch(function () {
          row.classList.remove('is-removing');
          window.alert('Network error.');
        });
    });
  }

})();
