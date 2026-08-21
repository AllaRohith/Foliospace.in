(function () {

  var match = (window.location.pathname || '').match(/^\/([^\/]+)\/manage\/?$/);
  var slug = match ? match[1] : '';

  var rowsEl = document.querySelector('[data-fm-work-rail-rows]');
  var addBtn = document.querySelector('[data-fm-work-rail-add]');
  var saveBtn = document.querySelector('[data-fm-work-rail-save]');
  var status = document.querySelector('[data-fm-work-rail-status]');

  if (!rowsEl) return;

  function setStatus(msg, kind) {
    if (!status) return;
    status.textContent = msg;
    status.removeAttribute('hidden');
    status.dataset.kind = kind || 'info';
  }

  function rowTemplate(title, body) {
    var row = document.createElement('div');
    row.className = 'fm-work-rail-row';
    row.setAttribute('data-fm-work-rail-row', '');
    row.innerHTML =
      '<label class="fm-work-rail-cell fm-work-rail-cell-title">' +
        '<span class="fm-visually-hidden">Title</span>' +
        '<input type="text" maxlength="60" placeholder="e.g. Brand systems" data-fm-work-rail-title />' +
      '</label>' +
      '<label class="fm-work-rail-cell fm-work-rail-cell-body">' +
        '<span class="fm-visually-hidden">Body</span>' +
        '<input type="text" maxlength="120" placeholder="e.g. Logos, type, decks" data-fm-work-rail-body />' +
      '</label>' +
      '<button type="button" class="fm-work-rail-remove" data-fm-work-rail-remove aria-label="Remove row">×</button>';
    var inputs = row.querySelectorAll('input');
    if (title) inputs[0].value = title;
    if (body) inputs[1].value = body;
    return row;
  }

  function collectRows() {
    var rows = rowsEl.querySelectorAll('[data-fm-work-rail-row]');
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var t = rows[i].querySelector('[data-fm-work-rail-title]');
      var b = rows[i].querySelector('[data-fm-work-rail-body]');
      var title = t ? t.value.trim() : '';
      var body = b ? b.value.trim() : '';
      if (!title && !body) continue;
      out.push({ title: title, body: body });
    }
    return out;
  }

  if (addBtn) {
    addBtn.addEventListener('click', function (e) {
      e.preventDefault();
      var current = rowsEl.querySelectorAll('[data-fm-work-rail-row]').length;
      if (current >= 30) {
        setStatus('Maximum 30 rows.', 'err');
        return;
      }
      var row = rowTemplate('', '');
      rowsEl.appendChild(row);
      var first = row.querySelector('input');
      if (first) first.focus();
    });
  }

  rowsEl.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-fm-work-rail-remove]');
    if (!btn) return;
    e.preventDefault();
    var rows = rowsEl.querySelectorAll('[data-fm-work-rail-row]');
    if (rows.length <= 1) {
      var inputs = btn.closest('[data-fm-work-rail-row]').querySelectorAll('input');
      for (var i = 0; i < inputs.length; i++) inputs[i].value = '';
      setStatus('Row cleared.', 'info');
      return;
    }
    var row = btn.closest('[data-fm-work-rail-row]');
    if (row && row.parentNode) row.parentNode.removeChild(row);
  });

  function submit() {
    if (!slug) return;
    var rows = collectRows();
    setStatus('Saving…', 'info');
    fetch('/' + slug + '/manage/work-rail', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: rows })
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