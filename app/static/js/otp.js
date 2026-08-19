(function () {
  var form = document.querySelector('[data-otp-form]');
  if (!form) return;

  var cells = Array.prototype.slice.call(form.querySelectorAll('[data-otp-cell]'));
  var hidden = form.querySelector('[data-otp-hidden]');
  var submit = form.querySelector('[data-otp-submit]');
  var firstCell = cells[0];

  if (cells.length === 0 || !hidden || !submit) return;

  function readCode() {
    var value = '';
    for (var i = 0; i < cells.length; i++) {
      value += (cells[i].value || '').replace(/\D/g, '').slice(0, 1);
    }
    hidden.value = value;
    if (value.length === cells.length) {
      submit.removeAttribute('disabled');
      submit.classList.add('is-ready');
    } else {
      submit.setAttribute('disabled', '');
      submit.classList.remove('is-ready');
    }
    return value;
  }

  function focusCell(idx) {
    if (idx < 0) idx = 0;
    if (idx >= cells.length) idx = cells.length - 1;
    var cell = cells[idx];
    if (cell && typeof cell.focus === 'function') {
      cell.focus();
      try { cell.setSelectionRange(1, 1); } catch (e) {}
    }
  }

  cells.forEach(function (cell, idx) {
    cell.addEventListener('input', function (e) {
      var raw = (cell.value || '').replace(/\D/g, '');
      cell.value = raw.slice(0, 1);
      if (cell.value && idx < cells.length - 1) {
        focusCell(idx + 1);
      }
      readCode();
    });

    cell.addEventListener('keydown', function (e) {
      var key = e.key || e.keyCode;
      if (key === 'Backspace' || key === 8) {
        if (!cell.value && idx > 0) {
          var prev = cells[idx - 1];
          prev.value = '';
          focusCell(idx - 1);
          readCode();
          e.preventDefault();
        } else if (cell.value) {
          cell.value = '';
          readCode();
        }
      } else if (key === 'ArrowLeft' || key === 37) {
        focusCell(idx - 1);
        e.preventDefault();
      } else if (key === 'ArrowRight' || key === 39) {
        focusCell(idx + 1);
        e.preventDefault();
      } else if (key === 'Home' || key === 36) {
        focusCell(0);
        e.preventDefault();
      } else if (key === 'End' || key === 35) {
        focusCell(cells.length - 1);
        e.preventDefault();
      }
    });

    cell.addEventListener('focus', function () {
      try { cell.setSelectionRange(1, 1); } catch (e) {}
    });

    cell.addEventListener('paste', function (e) {
      e.preventDefault();
      var data = (e.clipboardData || window.clipboardData || {}).getData('text') || '';
      var digits = data.replace(/\D/g, '').split('');
      var idx2 = idx;
      for (var j = 0; j < digits.length && idx2 < cells.length; j++, idx2++) {
        cells[idx2].value = digits[j];
      }
      var lastFilled = Math.min(idx2 - 1, cells.length - 1);
      focusCell(Math.max(lastFilled, idx + 1));
      readCode();
    });
  });

  form.addEventListener('submit', function (e) {
    var code = readCode();
    if (code.length !== cells.length) {
      e.preventDefault();
      focusCell(code.length);
    }
  });

  if (firstCell && document.activeElement === document.body) {
    firstCell.focus();
  }

  var resendBtn = document.querySelector('[data-resend-btn]');
  var countdownEl = document.querySelector('[data-resend-countdown]');
  if (resendBtn && countdownEl && resendBtn.hasAttribute('disabled')) {
    var remaining = parseInt(countdownEl.textContent || '0', 10) || 0;
    var timer = setInterval(function () {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(timer);
        resendBtn.removeAttribute('disabled');
        resendBtn.textContent = 'Resend code';
      } else {
        countdownEl.textContent = String(remaining);
      }
    }, 1000);
  }
})();