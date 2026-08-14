(function () {
  
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isDesktop = window.matchMedia('(min-width: 900px)').matches && window.matchMedia('(hover: hover)').matches;

  (function () {
    if (reduceMotion) return;
    var targets = document.querySelectorAll('a[href^="#"]');
    targets.forEach(function (a) {
      a.addEventListener('click', function (e) {
        var href = a.getAttribute('href');
        if (!href || href.length <= 1) return;
        var target = document.querySelector(href);
        if (!target) return;
        e.preventDefault();
        var startY = window.pageYOffset;
        var endY = target.getBoundingClientRect().top + startY - 80;
        var distance = endY - startY;
        var duration = Math.min(900, Math.max(450, Math.abs(distance) * 0.4));
        var startTime = null;
        function step(ts) {
          if (startTime === null) startTime = ts;
          var p = Math.min(1, (ts - startTime) / duration);
          var eased = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
          window.scrollTo(0, startY + distance * eased);
          if (p < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      });
    });
  })();


  (function () {
    const cover = document.querySelector('.cover');
    const coverN = document.getElementById('cover-counter-n');
    if (!cover) return;

    function animateNumber(el, target) {
      if (!el) return;
      const start = parseInt(el.textContent || '0', 10) || 0;
      if (start === target) { el.textContent = String(target); return; }
      if (reduceMotion) { el.textContent = String(target); return; }
      const dur = 900;
      const t0 = performance.now();
      function tick(now) {
        const p = Math.min(1, (now - t0) / dur);
        const eased = 1 - Math.pow(1 - p, 3);
        const v = Math.round(start + (target - start) * eased);
        el.textContent = String(v);
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }

    async function loadStats() {
      try {
        const res = await fetch('/api/stats', { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        const n = parseInt(data.total, 10);
        if (!Number.isFinite(n)) return;
        animateNumber(coverN, n);
        const micro = document.getElementById('signup-microcopy');
        if (micro && n > 0) micro.textContent = '→ ' + n + ' already in · no spam · delete on request';
      } catch (e) {}
    }
    loadStats();
    setInterval(loadStats, 15000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) loadStats(); });
  })();

  const navWrap = document.querySelector('.nav-wrap');
  let lastScroll = 0;
  if (navWrap) {
    window.addEventListener('scroll', function () {
      const y = window.scrollY;
      if (y > 200 && y > lastScroll) {
        navWrap.classList.add('is-hidden');
      } else if (y < lastScroll || y < 100) {
        navWrap.classList.remove('is-hidden');
      }
      lastScroll = y;
    }, { passive: true });
  }

  const aura = document.querySelector('.cursor-aura');
  if (aura) aura.remove();

  const savedTheme = localStorage.getItem('fs-theme');
  if (savedTheme === 'dark') document.body.classList.add('dark');

  document.querySelectorAll('[data-split]').forEach(function (el) {
    const text = el.textContent;
    el.textContent = '';
    Array.from(text).forEach(function (ch) {
      const span = document.createElement('span');
      span.className = ch === ' ' ? 'wh' : 'ch';
      span.textContent = ch;
      el.appendChild(span);
    });
  });
  setTimeout(function () {
    document.querySelectorAll('[data-split]').forEach(function (el) {
      el.classList.add('is-split');
      el.querySelectorAll('.ch').forEach(function (c, i) {
        c.style.animationDelay = (i * 0.025) + 's';
      });
    });
  }, 900);

  function animateCount(el) {
    const target = parseFloat(el.dataset.count);
    if (isNaN(target)) return;
    const dur = 1400;
    const t0 = performance.now();
    function tick(now) {
      const p = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      const v = Math.round(target * eased);
      el.textContent = v;
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }
  document.querySelectorAll('.stat').forEach(function (stat) {
    if ('IntersectionObserver' in window) {
      const so = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            stat.classList.add('is-in');
            stat.querySelectorAll('[data-count]').forEach(animateCount);
            so.unobserve(stat);
          }
        });
      }, { threshold: 0.4 });
      so.observe(stat);
    }
  });

  (function () {
    const wrap = document.querySelector('.h-track-wrap');
    const track = document.querySelector('.h-track');
    if (!wrap || !track) return;
    track.style.animation = 'marquee 60s linear infinite';
    const clone = track.innerHTML;
    track.insertAdjacentHTML('beforeend', clone);
    track.style.width = 'max-content';
  })();

  (function () {
    const canvas = document.getElementById('hero-canvas');
    if (canvas) canvas.remove();
  })();

  const konami = ['ArrowUp','ArrowUp','ArrowDown','ArrowDown','ArrowLeft','ArrowRight','ArrowLeft','ArrowRight','b','a'];
  let kIdx = 0;
  (function () {
    const story = document.getElementById('story');
    if (!story) return;
    const steps = story.querySelectorAll('.story-step');
    function update() {
      const r = story.getBoundingClientRect();
      const vh = window.innerHeight;
      const traveled = -r.top;
      const total = Math.max(1, r.height - vh * 0.4);
      const ratio = Math.min(1, Math.max(0, traveled / total));
      const idx = Math.min(steps.length - 1, Math.max(0, Math.floor(ratio * steps.length)));
      steps.forEach(function (s, i) { s.classList.toggle('is-active', i === idx); });
    }
    window.addEventListener('scroll', update, { passive: true });
    update();
  })();

  document.addEventListener('keydown', function (e) {
    if (e.key === konami[kIdx]) {
      kIdx++;
      if (kIdx === konami.length) {
        kIdx = 0;
        document.body.classList.toggle('fs-konami');
        const msg = document.createElement('div');
        msg.textContent = '🎉 Konami unlocked — you get 50% off launch pricing forever.';
        Object.assign(msg.style, {
          position: 'fixed', top: '20px', left: '50%', transform: 'translateX(-50%)',
          padding: '12px 18px', background: '#0F1419', color: '#FAF7F2',
          borderRadius: '999px', fontSize: '14px', fontWeight: '600', zIndex: '999',
          boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
        });
        document.body.appendChild(msg);
        setTimeout(function () { msg.style.transition = 'opacity 0.4s'; msg.style.opacity = '0'; setTimeout(function () { msg.remove(); }, 500); }, 3500);
      }
    } else {
      kIdx = e.key === konami[0] ? 1 : 0;
    }
  });

  async function reloadCoverCounter() {
    try {
      const res = await fetch('/api/stats', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      const n = parseInt(data.total, 10);
      if (!Number.isFinite(n) || n <= 0) return;
      const micro = document.getElementById('signup-microcopy');
      if (micro) micro.textContent = '→ ' + n + ' already in · no spam · delete on request';
    } catch (e) {}
  }

  const form = document.getElementById('join');
  if (form) {
    const msg = document.getElementById('form-msg');
    const button = form.querySelector('button[type="submit"]');
    function setMsg(text, kind) {
      msg.textContent = text;
      msg.classList.remove('ok', 'err');
      if (kind) msg.classList.add(kind);
    }
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      const data = new FormData(form);
      const original = button.textContent;
      button.disabled = true;
      button.textContent = 'Joining…';
      setMsg('', null);
      try {
        const res = await fetch('/api/waitlist/join', { method: 'POST', body: data });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) { setMsg(body.detail || 'Something went wrong. Try again.', 'err'); return; }
        setMsg(body.message || "You're in.", 'ok');
        form.reset();
        reloadCoverCounter();
      } catch (err) {
        setMsg('Network error. Try again.', 'err');
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    });
  }

  document.querySelectorAll('.btn').forEach(function (btn) {
    btn.addEventListener('mousemove', function (e) {
      const r = btn.getBoundingClientRect();
      btn.style.setProperty('--mx', ((e.clientX - r.left) / r.width) * 100 + '%');
      btn.style.setProperty('--my', ((e.clientY - r.top) / r.height) * 100 + '%');
    });
  });

  if (reduceMotion) {
    document.querySelectorAll('.reveal, .reveal-stagger').forEach(function (el) { el.classList.add('is-in'); });
  } else {
    document.querySelectorAll('.reveal, .reveal-stagger').forEach(function (el) {
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight && r.bottom > 0) el.classList.add('is-in');
    });

    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-in');
            io.unobserve(entry.target);
          }
        });
      }, { threshold: 0, rootMargin: '0px 0px 200px 0px' });
      document.querySelectorAll('.reveal:not(.is-in), .reveal-stagger:not(.is-in)').forEach(function (el) {
        io.observe(el);
      });
    }

    setTimeout(function () {
      document.querySelectorAll('.reveal:not(.is-in), .reveal-stagger:not(.is-in)').forEach(function (el) {
        el.classList.add('is-in');
      });
    }, 4000);
  }

  const progress = document.querySelector('.scroll-progress');
  if (progress) {
    let ticking = false;
    function update() {
      const h = document.documentElement;
      const max = h.scrollHeight - h.clientHeight;
      const pct = max > 0 ? (h.scrollTop / max) * 100 : 0;
      progress.style.width = pct + '%';
      ticking = false;
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { requestAnimationFrame(update); ticking = true; }
    }, { passive: true });
    update();
  }

  (function () {
    if (reduceMotion) return;
    const sections = document.querySelectorAll('main > section');
    if (!sections.length) return;
    let depthTick = false;
    function updateDepth() {
      const vh = window.innerHeight;
      sections.forEach(function (s) {
        const r = s.getBoundingClientRect();
        const center = r.top + r.height / 2;
        const vpCenter = vh / 2;
        const dist = (center - vpCenter) / vh;
        const absDist = Math.min(0.8, Math.abs(dist));
        const z = -absDist * 40;
        const scale = 1 - absDist * 0.015;
        s.style.transform = 'translateZ(' + z + 'px) scale(' + scale + ')';
      });
      depthTick = false;
    }
    window.addEventListener('scroll', function () {
      if (!depthTick) {
        requestAnimationFrame(updateDepth);
        depthTick = true;
      }
    }, { passive: true });
    updateDepth();
  })();

  document.querySelectorAll('.magnetic').forEach(function (btn) {
    btn.addEventListener('mousemove', function (e) {
      const r = btn.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const dx = (e.clientX - cx) * 0.25;
      const dy = (e.clientY - cy) * 0.25;
      btn.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
    });
    btn.addEventListener('mouseleave', function () { btn.style.transform = ''; });
    btn.addEventListener('click', function (e) {
      const r = btn.getBoundingClientRect();
      const ripple = document.createElement('span');
      ripple.className = 'ripple';
      const size = Math.max(r.width, r.height);
      ripple.style.width = ripple.style.height = size + 'px';
      ripple.style.left = (e.clientX - r.left - size / 2) + 'px';
      ripple.style.top = (e.clientY - r.top - size / 2) + 'px';
      btn.appendChild(ripple);
      setTimeout(function () { ripple.remove(); }, 700);
    });
  });

  document.querySelectorAll('.faq-item').forEach(function (item) {
    const body = item.querySelector('.faq-body');
    if (!body) return;
    item.addEventListener('toggle', function () {
      if (item.open) {
        body.style.animation = 'none';
        void body.offsetHeight;
        body.style.animation = '';
      }
    });
  });

  const burger = document.querySelector('.nav-burger');
  const navLinks = document.querySelector('.nav-links');
  if (burger && navLinks) {
    burger.addEventListener('click', function () {
      const open = burger.classList.toggle('is-open');
      navLinks.classList.toggle('is-open', open);
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    navLinks.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () {
        burger.classList.remove('is-open');
        navLinks.classList.remove('is-open');
        burger.setAttribute('aria-expanded', 'false');
      });
    });
  }

  const CMD_ACTIONS = [
    { label: 'Hero — top of page', hint: 'Nav', icon: '↑', href: '#top' },
    { label: 'Who it\'s for', hint: 'Section', icon: 'W', href: '#who' },
    { label: 'Features', hint: 'Section', icon: 'F', href: '#features' },
    { label: 'Pricing', hint: 'Section', icon: '₹', href: '#pricing', accent: true },
    { label: 'FAQ', hint: 'Section', icon: '?', href: '.faq' },
    { label: 'Join the waitlist', hint: 'Action', icon: '→', href: '#join', accent: true },
    { label: 'See the cover story', hint: 'Action', icon: '◉', href: '.cover' },
    { label: 'Scroll to top', hint: 'Action', icon: '↑', action: 'scrollTop' },
    { label: 'Toggle dark mode', hint: 'Theme', icon: '◐', action: 'theme' },
  ];

  const fab = document.querySelector('.cmd-k-fab');
  const palette = document.querySelector('.cmd-palette');
  const cmdInput = document.getElementById('cmd-input');
  const cmdList = document.getElementById('cmd-list');

  function openPalette() {
    if (!palette) return;
    palette.classList.add('is-open');
    palette.setAttribute('aria-hidden', 'false');
    if (cmdInput) { cmdInput.value = ''; renderList(''); setTimeout(function () { cmdInput.focus(); }, 50); }
  }
  function closePalette() {
    if (!palette) return;
    palette.classList.remove('is-open');
    palette.setAttribute('aria-hidden', 'true');
  }

  let activeIdx = 0;
  function renderList(q) {
    if (!cmdList) return;
    const filtered = CMD_ACTIONS.filter(function (a) { return a.label.toLowerCase().includes(q.toLowerCase()); });
    if (!filtered.length) {
      cmdList.innerHTML = '<li class="cmd-palette-empty">No matches for “</li>';
      const span = document.createElement('span');
      span.textContent = q;
      cmdList.lastElementChild.appendChild(span);
      const tail = document.createElement('span');
      tail.textContent = '”';
      cmdList.lastElementChild.appendChild(tail);
      return;
    }
    activeIdx = 0;
    cmdList.innerHTML = filtered.map(function (a, i) {
      return '<li class="cmd-palette-item ' + (i === 0 ? 'is-active' : '') + '" data-i="' + i + '">' +
        '<span class="icon ' + (a.accent ? 'accent' : '') + '">' + a.icon + '</span>' +
        '<span class="label">' + a.label + '</span>' +
        '<span class="hint">' + a.hint + '</span>' +
        '</li>';
    }).join('');
    cmdList.querySelectorAll('.cmd-palette-item').forEach(function (li) {
      li.addEventListener('click', function () { runAction(filtered[parseInt(li.dataset.i, 10)]); });
    });
  }
  function runAction(a) {
    if (!a) return;
    closePalette();
    if (a.action === 'theme') {
      document.body.classList.toggle('dark');
      localStorage.setItem('fs-theme', document.body.classList.contains('dark') ? 'dark' : 'light');
      return;
    }
    if (a.action === 'scrollTop') { window.scrollTo({ top: 0, behavior: 'smooth' }); return; }
    if (a.href) {
      const el = document.querySelector(a.href);
      if (el) { el.scrollIntoView({ behavior: 'smooth' }); return; }
    }
  }

  if (fab) fab.addEventListener('click', openPalette);
  if (palette) {
    palette.querySelector('.cmd-palette-backdrop').addEventListener('click', closePalette);
  }
  if (cmdInput) {
    cmdInput.addEventListener('input', function () { renderList(cmdInput.value); });
    cmdInput.addEventListener('keydown', function (e) {
      const items = cmdList.querySelectorAll('.cmd-palette-item');
      if (e.key === 'ArrowDown') { e.preventDefault(); activeIdx = Math.min(items.length - 1, activeIdx + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); activeIdx = Math.max(0, activeIdx - 1); }
      else if (e.key === 'Enter') { e.preventDefault(); runAction(CMD_ACTIONS.filter(function (a) { return a.label.toLowerCase().includes(cmdInput.value.toLowerCase()); })[activeIdx]); return; }
      else if (e.key === 'Escape') { closePalette(); return; }
      items.forEach(function (li, i) { li.classList.toggle('is-active', i === activeIdx); });
    });
  }
  (function () {
    const nav = document.querySelector('.nav');
    const indicator = document.querySelector('.nav-indicator');
    const links = document.querySelectorAll('.nav-link[data-section]');
    if (!nav || !indicator || !links.length) return;

    const sections = Array.from(links).map(function (a) {
      return { link: a, target: document.getElementById(a.dataset.section) };
    }).filter(function (s) { return s.target; });

    let activeIdx = -1;

    function moveIndicator(link) {
      if (!link || activeIdx === -1 && !link) return;
      const r = link.getBoundingClientRect();
      const nr = nav.getBoundingClientRect();
      indicator.style.width = r.width + 'px';
      indicator.style.left = (r.left - nr.left) + 'px';
    }

    function setActive(idx) {
      if (idx === activeIdx) return;
      activeIdx = idx;
      links.forEach(function (l, i) { l.classList.toggle('is-active', i === idx); });
      if (idx >= 0) moveIndicator(sections[idx].link);
      else indicator.style.opacity = '0';
    }

    if ('IntersectionObserver' in window) {
      const obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          const idx = sections.findIndex(function (s) { return s.target === e.target; });
          if (idx === -1) return;
          if (e.isIntersecting && e.intersectionRatio > 0.15) setActive(idx);
        });
      }, { threshold: [0, 0.15, 0.3, 0.6] });
      sections.forEach(function (s) { obs.observe(s.target); });
    }

    links.forEach(function (l) {
      l.addEventListener('mouseenter', function () { moveIndicator(l); });
      l.addEventListener('focus', function () { moveIndicator(l); });
    });

    nav.addEventListener('mouseleave', function () {
      if (activeIdx >= 0) moveIndicator(sections[activeIdx].link);
      else indicator.style.opacity = '0';
    });

    window.addEventListener('scroll', function () {
      const scrolled = window.scrollY > 80;
      nav.dataset.state = scrolled ? 'scrolled' : 'top';
    }, { passive: true });
  })();

  (function () {
    const hero = document.querySelector('.hero');
    if (!hero || !isDesktop) return;
    if (reduceMotion) return;
    let mx = 0, my = 0;
    let raf = null;
    function apply() {
      hero.style.setProperty('--mx', mx + 'px');
      hero.style.setProperty('--my', my + 'px');
      raf = null;
    }
    hero.addEventListener('mousemove', function (e) {
      const r = hero.getBoundingClientRect();
      mx = e.clientX - r.left;
      my = e.clientY - r.top;
      hero.classList.add('is-cursor-on');
      if (!raf) raf = requestAnimationFrame(apply);
    });
    hero.addEventListener('mouseleave', function () {
      hero.classList.remove('is-cursor-on');
    });
  })();

  (function () {
    const toggle = document.getElementById('pricing-toggle');
    if (!toggle) return;
    const buttons = toggle.querySelectorAll('button');
    buttons.forEach(function (b) {
      b.addEventListener('click', function () {
        if (b.classList.contains('is-on')) return;
        buttons.forEach(function (x) { x.classList.remove('is-on'); });
        b.classList.add('is-on');
        const cycle = b.dataset.cycle;
        document.querySelectorAll('.price.is-monthly, .price.is-yearly, .price-sub.is-monthly, .price-sub.is-yearly').forEach(function (el) {
          if (el.classList.contains('is-monthly')) {
            el.classList.toggle('is-hidden', cycle !== 'monthly');
          } else {
            el.classList.toggle('is-hidden', cycle !== 'yearly');
          }
        });
      });
    });
  })();

  (function () {
    const btn = document.getElementById('share-float');
    const pricing = document.getElementById('pricing');
    if (!btn || !pricing) return;
    let visible = false;
    let lastState = false;
    function update() {
      const r = pricing.getBoundingClientRect();
      const inView = r.top < window.innerHeight && r.bottom > 0;
      if (inView !== lastState) {
        lastState = inView;
        btn.classList.toggle('is-on', inView);
      }
    }
    window.addEventListener('scroll', update, { passive: true });
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      const text = encodeURIComponent('Check out FolioSpace — a portfolio link that loads fast on WhatsApp: https://foliospace.in');
      window.open('https://wa.me/?text=' + text, '_blank');
    });
    update();
  })();

  (function () {
    const orbits = document.querySelector('.orbits');
    if (!orbits) return;
    const obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting && e.intersectionRatio > 0.3) {
          orbits.classList.add('is-on');
          obs.unobserve(orbits);
        }
      });
    }, { threshold: [0, 0.3, 0.6] });
    obs.observe(orbits);
  })();

  (function () {
    const workshop = document.getElementById('workshop');
    if (!workshop) return;
    const obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting && e.intersectionRatio > 0.3) {
          workshop.classList.add('is-on');
          obs.unobserve(workshop);
        }
      });
    }, { threshold: [0, 0.3, 0.6] });
    obs.observe(workshop);
  })();

  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (palette.classList.contains('is-open')) closePalette(); else openPalette();
    } else if (e.key === 'Escape' && palette.classList.contains('is-open')) {
      closePalette();
    }
  });
  renderList('');

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) {
      document.querySelectorAll('.reveal:not(.is-in), .reveal-stagger:not(.is-in)').forEach(function (el) {
        const r = el.getBoundingClientRect();
        if (r.top < window.innerHeight + 200 && r.bottom > -200) {
          el.classList.add('is-in');
        }
      });
    }
  });

  const rhSection = document.getElementById('rh-section');
  const rhPage = document.getElementById('rh-page');
  const rhSections = Array.from(document.querySelectorAll('section[data-rh-section]'));
  function updateRunningHead() {
    const vh = window.innerHeight;
    let active = rhSections[0];
    let bestRatio = 0;
    rhSections.forEach(function (s) {
      const r = s.getBoundingClientRect();
      const visible = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
      const ratio = visible / Math.min(r.height, vh);
      if (ratio > bestRatio) { bestRatio = ratio; active = s; }
    });
    if (active) {
      rhSection.textContent = active.getAttribute('data-rh-section');
      rhPage.textContent = 'Page ' + active.getAttribute('data-rh-page');
    }
  }
  if (rhSection && rhPage && rhSections.length) {
    updateRunningHead();
    let raf = null;
    window.addEventListener('scroll', function () {
      if (raf) return;
      raf = requestAnimationFrame(function () { raf = null; updateRunningHead(); });
    }, { passive: true });
    window.addEventListener('resize', updateRunningHead);
  }
})();