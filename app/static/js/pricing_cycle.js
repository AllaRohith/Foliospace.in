/**
 * pricing_cycle.js — Monthly/Annual cycle toggle for /pricing.
 *
 * Reads the displayed amounts from data-* attributes the Jinja layer
 * already renders. Has no hardcoded prices so the single-source-of-truth
 * (app/pricing.py) keeps working without a JS rebuild.
 *
 * Loaded with `defer` from pricing.html so it never blocks first paint.
 */
(function () {
  var buttons = document.querySelectorAll('.pricing-cycle-btn');
  if (!buttons.length) return;
  buttons.forEach(function (b) {
    b.addEventListener('click', function () {
      var cycle = b.getAttribute('data-cycle') || 'monthly';
      buttons.forEach(function (other) {
        var on = other === b;
        other.classList.toggle('is-active', on);
        other.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      var main = document.getElementById('pricing-figure-main');
      if (main) main.setAttribute('data-cycle-view', cycle);
      var num = document.querySelector('[data-pricing-cycle-num]');
      var unit = document.querySelector('[data-pricing-cycle-unit]');
      var rowStrong = document.querySelector('[data-pricing-cycle-row="after-strong"]');
      if (cycle === 'annual') {
        if (num && num.getAttribute('data-annual')) num.textContent = num.getAttribute('data-annual');
        if (unit) unit.textContent = '/year';
        if (rowStrong && rowStrong.getAttribute('data-annual')) rowStrong.textContent = rowStrong.getAttribute('data-annual');
      } else {
        if (num && num.getAttribute('data-monthly')) num.textContent = num.getAttribute('data-monthly');
        if (unit) unit.textContent = '/month';
        if (rowStrong && rowStrong.getAttribute('data-monthly')) rowStrong.textContent = rowStrong.getAttribute('data-monthly');
      }
    });
  });
})();
