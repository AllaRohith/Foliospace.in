(function () {

  var match = (window.location.pathname || '').match(/^\/([^\/]+)\/manage\/?$/);
  var slug = match ? match[1] : '';

  var form = document.querySelector('[data-fm-links-add]');
  var status = document.querySelector('[data-fm-links-status]');
  var list = document.querySelector('[data-fm-links-list]');

  function setStatus(msg, kind) {
    if (!status) return;
    status.textContent = msg;
    status.removeAttribute('hidden');
    status.dataset.kind = kind || 'info';
  }

  function rowHTML(link) {
    var iconClass = 'fm-link-row-icon-' + (link.icon || 'link');
    var initial = ((link.icon || 'L')[0] || 'L').toUpperCase();
    var label = escapeHTML(link.label || 'Untitled');
    var url = escapeHTML(link.url || '');
    var lay = escapeHTML(link.layout || 'stack');
    return ''
      + '<li class="fm-link-row" data-fm-link-row data-link-id="' + link.id + '" data-layout="' + lay + '">'
      + '<button type="button" class="fm-link-row-handle" data-fm-link-handle aria-label="Reorder">⋮⋮</button>'
      + '<div class="fm-link-row-body">'
      + '<strong class="fm-link-row-label">' + label + '</strong>'
      + '<span class="fm-link-row-url">' + url + '</span>'
      + '</div>'
      + '<span class="fm-link-row-icon ' + iconClass + '" aria-hidden="true">' + initial + '</span>'
      + '<select class="fm-link-row-layout" data-fm-link-layout aria-label="Layout">'
      + '<option value="stack"' + (lay === 'stack' ? ' selected' : '') + '>Stack</option>'
      + '<option value="grid"' + (lay === 'grid' ? ' selected' : '') + '>Grid</option>'
      + '<option value="carousel"' + (lay === 'carousel' ? ' selected' : '') + '>Carousel</option>'
      + '</select>'
      + '<button type="button" class="fm-link-row-remove" data-fm-link-remove aria-label="Remove link">×</button>'
      + '</li>';
  }

  function escapeHTML(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!slug) return;
      var labelEl = form.querySelector('[data-fm-links-label]');
      var urlEl = form.querySelector('[data-fm-links-url]');
      var layoutEl = form.querySelector('[data-fm-links-layout]');
      var label = labelEl ? labelEl.value : '';
      var url = urlEl ? urlEl.value : '';
      var layout = layoutEl ? layoutEl.value : 'stack';
      if (!url || !/^https?:\/\//.test(url)) {
        setStatus('URL must start with http:// or https://', 'err');
        return;
      }
      setStatus('Adding…', 'info');
      fetch('/' + slug + '/manage/links', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: label, url: url, layout: layout })
      }).then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (j) {
          if (j && j.ok && j.link) {
            if (list) list.insertAdjacentHTML('beforeend', rowHTML(j.link));
            setStatus('Added ✓', 'ok');
            if (labelEl) labelEl.value = '';
            if (urlEl) urlEl.value = '';
          } else if (j && j.message === 'limit-reached') {
            setStatus('Free plan maxes out at 10. Upgrade to add more.', 'err');
          } else {
            setStatus('Add failed. Try again.', 'err');
          }
        }).catch(function () { setStatus('Add failed. Try again.', 'err'); });
    });
  }

  if (list) {
    list.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-fm-link-remove]');
      if (!btn) return;
      var row = btn.closest('[data-fm-link-row]');
      if (!row) return;
      var fid = row.dataset.linkId;
      if (!fid) return;
      if (!window.confirm('Remove this link?')) return;
      row.classList.add('is-removing');
      fetch('/' + slug + '/manage/links/' + fid, {
        method: 'DELETE',
        credentials: 'same-origin'
      }).then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (j) {
          if (j && j.ok) {
            row.parentNode.removeChild(row);
          } else {
            row.classList.remove('is-removing');
            window.alert('Could not remove.');
          }
        }).catch(function () {
          row.classList.remove('is-removing');
          window.alert('Network error.');
        });
    });

    list.addEventListener('change', function (e) {
      var sel = e.target.closest('[data-fm-link-layout]');
      if (!sel) return;
      var row = sel.closest('[data-fm-link-row]');
      if (!row) return;
      var fid = row.dataset.linkId;
      if (!fid) return;
      var layout = sel.value;
      row.dataset.layout = layout;
      fetch('/' + slug + '/manage/links/' + fid, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layout: layout })
      }).then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (j) {
          if (!j || !j.ok) {
            window.alert('Could not save layout. Refresh and retry.');
          }
        }).catch(function () {
          window.alert('Could not save layout.');
        });
    });
  }

  function setupDragDrop() {
    if (!list) return;
    var dragSrc = null;

    list.addEventListener('mousedown', function (e) {
      var handle = e.target.closest('[data-fm-link-handle]');
      if (!handle) return;
      var row = handle.closest('[data-fm-link-row]');
      if (!row) return;
      e.preventDefault();
      dragSrc = row;
      row.classList.add('is-dragging');
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp, { once: true });
    });

    function onMove(e) {
      if (!dragSrc) return;
      var target = document.elementFromPoint(e.clientX, e.clientY);
      if (!target) return;
      var overRow = target.closest('[data-fm-link-row]');
      if (!overRow || overRow === dragSrc) return;
      var rect = overRow.getBoundingClientRect();
      var before = (e.clientY - rect.top) < rect.height / 2;
      if (before) {
        overRow.parentNode.insertBefore(dragSrc, overRow);
      } else {
        overRow.parentNode.insertBefore(dragSrc, overRow.nextSibling);
      }
    }

    function onUp() {
      document.removeEventListener('mousemove', onMove);
      if (!dragSrc) return;
      dragSrc.classList.remove('is-dragging');
      dragSrc = null;
      var ordered = Array.prototype.slice.call(list.querySelectorAll('[data-fm-link-row]'))
        .map(function (r) { return r.dataset.linkId; })
        .filter(Boolean);
      fetch('/' + slug + '/manage/links/reorder', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ordered_ids: ordered })
      }).then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (j) { if (!j || !j.ok) window.alert('Could not save order.'); })
        .catch(function () { window.alert('Could not save order.'); });
    }
  }
  setupDragDrop();

})();
