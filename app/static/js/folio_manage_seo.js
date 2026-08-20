(function () {

  var match = (window.location.pathname || '').match(/^\/([^\/]+)\/manage\/?$/);
  var slug = match ? match[1] : '';

  var saveBtn = document.querySelector('[data-fm-seo-save]');
  var status = document.querySelector('[data-fm-seo-status]');

  function setStatus(msg, kind) {
    if (!status) return;
    status.textContent = msg;
    status.removeAttribute('hidden');
    status.dataset.kind = kind || 'info';
  }

  function submit() {
    if (!slug) return;
    var titleEl = document.getElementById('seo-title');
    var descEl = document.getElementById('seo-description');
    var ogEl = document.getElementById('og-image-url');
    var data = {
      seo_title: titleEl ? titleEl.value : '',
      seo_description: descEl ? descEl.value : '',
      og_image_override_url: ogEl ? ogEl.value : ''
    };
    setStatus('Saving…', 'info');
    fetch('/' + slug + '/manage/seo', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    }).then(function (r) {
      return r.json().catch(function () { return {}; });
    }).then(function (j) {
      if (j && j.ok) {
        setStatus('Saved ✓', 'ok');
      } else {
        setStatus('Save failed. Try again.', 'err');
      }
    }).catch(function () {
      setStatus('Save failed. Try again.', 'err');
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener('click', function (e) {
      e.preventDefault();
      submit();
    });
  }

})();