(function () {
  var meta = document.querySelector('meta[name="razorpay-key"]');
  if (!meta) return;

  function getKey() {
    return meta.getAttribute('content') || '';
  }

  function showError(btn, orig, msg) {
    btn.disabled = false;
    btn.textContent = orig;
    if (typeof alert !== 'undefined') alert(msg);
  }

  var buttons = document.querySelectorAll('[data-billing-action]');
  buttons.forEach(function (btn) {
    btn.addEventListener('click', async function () {
      if (typeof RazorpayCheckout === 'undefined') {
        alert('Checkout is still loading. Refresh and try again.');
        return;
      }
      var kind = btn.getAttribute('data-billing-action');
      if (kind !== 'setup' && kind !== 'recurring') return;
      var orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Opening checkout…';
      try {
        var form = new FormData();
        form.append('type', kind);
        var resp = await fetch('/dashboard/billing/subscribe', {
          method: 'POST',
          body: form,
          credentials: 'same-origin',
        });
        if (!resp.ok) throw new Error('checkout-create-failed');
        var data = await resp.json();
        var options = {
          key: getKey(),
          name: 'FolioSpace',
          description: kind === 'setup' ? 'Pro setup fee' : 'Pro — ₹99/mo via UPI AutoPay',
          prefill: {},
          notes: { kind: kind },
          image: '/static/img/favicon.svg',
          config: {
            display: {
              blocks: {
                banks: {
                  name: 'Pay via UPI',
                  instruments: [{ method: 'upi' }],
                },
              },
              sequence: ['block.banks'],
              preferences: { show_default_blocks: false },
            },
          },
          handler: function () { window.location.reload(); },
          modal: {
            ondismiss: function () {
              btn.disabled = false;
              btn.textContent = orig;
            },
          },
        };
        if (kind === 'setup') {
          options.order_id = data.order_id;
          options.amount = data.amount || 17700;
          options.currency = data.currency || 'INR';
        } else {
          options.subscription_id = data.subscription_id;
        }
        RazorpayCheckout.open(options, function () {});
      } catch (err) {
        showError(btn, orig, 'Could not start checkout. Refresh and try again.');
      }
    });
  });

  var confirms = document.querySelectorAll('[data-billing-confirm]');
  confirms.forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      var msg = btn.getAttribute('data-billing-confirm');
      if (msg && typeof confirm !== 'undefined' && !confirm(msg)) {
        e.preventDefault();
      }
    });
  });
})();