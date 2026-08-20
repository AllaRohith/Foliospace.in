(function () {
  var meta = document.querySelector('meta[name="razorpay-key"]');
  if (!meta) return;

  function getKey() {
    return meta.getAttribute('content') || '';
  }

  function resetBtn(btn, orig) {
    btn.disabled = false;
    btn.textContent = orig;
  }

  function showAlert(msg) {
    if (typeof alert !== 'undefined') alert(msg);
  }

  var currentCycle = 'monthly';

  var cycleButtons = document.querySelectorAll('.fm-bill-cycle-btn');
  cycleButtons.forEach(function (b) {
    b.addEventListener('click', function () {
      var cycle = b.getAttribute('data-cycle') || 'monthly';
      currentCycle = cycle;
      cycleButtons.forEach(function (other) {
        var on = other === b;
        other.classList.toggle('is-active', on);
        other.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      var main = document.getElementById('fm-bill-figure-main');
      if (main) main.setAttribute('data-cycle-view', cycle);
      var num = document.querySelector('[data-bill-cycle-num]');
      var unit = document.querySelector('[data-bill-cycle-unit]');
      var row = document.querySelector('[data-bill-cycle-row="after"]');
      var rowStrong = document.querySelector('[data-bill-cycle-row="after-strong"]');
      if (cycle === 'annual') {
        if (num) num.textContent = '₹1,499';
        if (unit) unit.textContent = '/year';
        if (row) row.textContent = 'After trial';
        if (rowStrong) rowStrong.textContent = '₹1,499/yr via UPI AutoPay';
      } else {
        if (num) num.textContent = '�149';
        if (unit) unit.textContent = '/month';
        if (row) row.textContent = 'After trial';
        if (rowStrong) rowStrong.textContent = '₹149/mo via UPI AutoPay';
      }
      var cta = document.getElementById('billing-cta');
      if (cta) {
        if (cycle === 'annual') {
          cta.textContent = 'Activate ₹1,499/yr AutoPay →';
          cta.setAttribute('data-billing-product', 'Pro — ₹1,499/yr via UPI AutoPay');
          cta.setAttribute('data-billing-cycle', 'annual');
        } else {
          cta.textContent = 'Activate ₹149/mo AutoPay →';
          cta.setAttribute('data-billing-product', 'Pro — ₹149/mo via UPI AutoPay');
          cta.setAttribute('data-billing-cycle', 'monthly');
        }
        cta.dataset._orig = cta.textContent;
      }
    });
  });

  var btn = document.getElementById('billing-cta');
  if (btn) {
    btn.dataset._orig = btn.textContent;
    btn.addEventListener('click', async function () {
      if (typeof Razorpay === 'undefined') {
        showAlert('Checkout is still loading. Refresh and try again.');
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Opening checkout…';
      try {
        var fd = new FormData();
        fd.append('period', currentCycle);
        var resp = await fetch('/dashboard/billing/subscribe', {
          method: 'POST',
          credentials: 'same-origin',
          body: fd,
        });
        if (!resp.ok) throw new Error('checkout-create-failed');
        var data = await resp.json();
        var options = {
          key: getKey(),
          name: 'FolioSpace',
          description: btn.getAttribute('data-billing-product') || 'Pro — ₹149/mo',
          subscription_id: data.subscription_id,
          prefill: {},
          notes: { kind: 'recurring', period: currentCycle },
          image: '/static/img/favicon.svg',
          handler: function () { window.location.reload(); },
          modal: {
            ondismiss: function () {
              resetBtn(btn, btn.dataset._orig || btn.textContent);
            },
          },
        };
        var rzp = new Razorpay(options);
        rzp.on('payment.failed', function (resp) {
          resetBtn(btn, btn.dataset._orig || btn.textContent);
          var desc = resp && resp.error && resp.error.description;
          showAlert('Payment failed: ' + (desc || 'unknown reason'));
        });
        rzp.open();
      } catch (err) {
        resetBtn(btn, btn.dataset._orig || btn.textContent);
        showAlert('Could not start checkout. Refresh and try again.');
      }
    });
  }

  var confirms = document.querySelectorAll('[data-billing-confirm]');
  confirms.forEach(function (b) {
    b.addEventListener('click', function (e) {
      var msg = b.getAttribute('data-billing-confirm');
      if (msg && typeof confirm !== 'undefined' && !confirm(msg)) {
        e.preventDefault();
      }
    });
  });
})();
