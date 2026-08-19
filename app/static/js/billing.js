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

  var btn = document.getElementById('billing-cta');
  if (btn) {
    var orig = btn.textContent;
    btn.addEventListener('click', async function () {
      if (typeof Razorpay === 'undefined') {
        showAlert('Checkout is still loading. Refresh and try again.');
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Opening checkout…';
      try {
        var resp = await fetch('/dashboard/billing/subscribe', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: '',
        });
        if (!resp.ok) throw new Error('checkout-create-failed');
        var data = await resp.json();
        var options = {
          key: getKey(),
          name: 'FolioSpace',
          description: btn.getAttribute('data-billing-product') || 'Pro — ₹149/mo',
          subscription_id: data.subscription_id,
          prefill: {},
          notes: { kind: 'recurring' },
          image: '/static/img/favicon.svg',
          handler: function () { window.location.reload(); },
          modal: {
            ondismiss: function () {
              resetBtn(btn, orig);
            },
          },
        };
        var rzp = new Razorpay(options);
        rzp.on('payment.failed', function (resp) {
          resetBtn(btn, orig);
          var desc = resp && resp.error && resp.error.description;
          showAlert('Payment failed: ' + (desc || 'unknown reason'));
        });
        rzp.open();
      } catch (err) {
        resetBtn(btn, orig);
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
