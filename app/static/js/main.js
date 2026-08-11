(function () {
  if (window.gsap && window.ScrollTrigger) {
    gsap.registerPlugin(ScrollTrigger);
  }

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isDesktop = window.matchMedia('(min-width: 900px)').matches && window.matchMedia('(hover: hover)').matches;

  document.body.classList.add('curtain-active');
  setTimeout(function () {
    document.body.classList.remove('curtain-active');
    const c = document.querySelector('.page-curtain');
    if (c) c.remove();
  }, 1700);

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

  const counter = document.getElementById('counter');
  const counterText = document.getElementById('counter-text');
  const counterMini = document.getElementById('counter-mini');
  const counterMiniN = document.getElementById('counter-mini-n');

  function animateNumber(el, target) {
    if (!el) return;
    const start = 0;
    const dur = 900;
    const t0 = performance.now();
    function tick(now) {
      const p = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      const v = Math.round(start + (target - start) * eased);
      el.textContent = v;
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  async function loadCounter() {
    try {
      const res = await fetch('/api/waitlist/count', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      const n = data.count || 0;
      if (n > 0) {
        if (counter && counterText) {
          counterText.innerHTML = '<strong>' + n + '</strong> ' + (n === 1 ? 'person has' : 'people have') + ' already joined the waitlist';
          counter.hidden = false;
        }
        if (counterMini && counterMiniN) {
          counterMini.hidden = false;
          animateNumber(counterMiniN, n);
        }
      }
    } catch (e) {}
  }
  loadCounter();

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
        loadCounter();
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

  if (window.gsap && window.ScrollTrigger && !reduceMotion) {
    document.querySelectorAll('.reveal').forEach(function (el) {
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight && r.bottom > 0) {
        el.classList.add('is-in');
      } else {
        ScrollTrigger.create({
          trigger: el,
          start: 'top 92%',
          onEnter: function () { el.classList.add('is-in'); },
          onEnterBack: function () { el.classList.add('is-in'); },
        });
      }
    });
    document.querySelectorAll('.reveal-stagger').forEach(function (el) {
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight && r.bottom > 0) {
        el.classList.add('is-in');
      } else {
        ScrollTrigger.create({
          trigger: el,
          start: 'top 92%',
          onEnter: function () { el.classList.add('is-in'); },
          onEnterBack: function () { el.classList.add('is-in'); },
        });
      }
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

    document.querySelectorAll('.section-label, .who h2, .features h2, .pricing h2, .faq h2, .cta h2').forEach(function (el) {
      if (!el.classList.contains('reveal')) el.classList.add('reveal');
    });

    document.querySelectorAll('.who-grid li, .feature-grid .feature, .pricing-grid .plan, .faq-item, .badge, .plan-tag').forEach(function (el) {
      if (!el.classList.contains('gs-reveal')) el.classList.add('gs-reveal');
    });

    if ('IntersectionObserver' in window) {
      const io2 = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('gs-in');
            io2.unobserve(entry.target);
          }
        });
      }, { threshold: 0, rootMargin: '0px 0px 100px 0px' });
      document.querySelectorAll('.gs-reveal:not(.gs-in)').forEach(function (el) { io2.observe(el); });
    }

    setTimeout(function () {
      document.querySelectorAll('.gs-reveal:not(.gs-in)').forEach(function (el) {
        const r = el.getBoundingClientRect();
        if (r.top < window.innerHeight + 200) el.classList.add('gs-in');
      });
    }, 4000);
  } else {
    document.querySelectorAll('.reveal, .reveal-stagger').forEach(function (el) { el.classList.add('is-in'); });
  }

  const card = document.querySelector('.showcase-card');
  if (card && isDesktop) {
    const wrap = card.parentElement;
    wrap.addEventListener('mousemove', function (e) {
      const r = wrap.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      card.style.transform = 'perspective(1400px) rotateX(' + (-y * 6) + 'deg) rotateY(' + (x * 8) + 'deg)';
    });
    wrap.addEventListener('mouseleave', function () {
      card.style.transform = 'perspective(1400px) rotateX(2deg)';
    });
  } else if (card) {
    card.style.transform = 'none';
  }

  if (window.gsap && !reduceMotion) {
    document.querySelectorAll('.hero .eyebrow, .hero .hero-title, .hero .hero-sub, .hero .signup-form, .hero .hero-meta').forEach(function (el, i) {
      gsap.from(el, {
        y: 30,
        opacity: 0,
        duration: 1,
        delay: 0.6 + i * 0.12,
        ease: 'power3.out',
        filter: 'blur(8px)',
        clearProps: 'filter',
      });
    });
    if (card) {
      gsap.from(card, {
        y: 60,
        opacity: 0,
        duration: 1.2,
        delay: 1.2,
        ease: 'power3.out',
        filter: 'blur(10px)',
        clearProps: 'filter',
      });
    }
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

  const GLYPHS = '!<>-_\\/[]{}—=+*^?#________';
  function scramble(el) {
    if (!el || el.dataset.scrambled) return;
    el.dataset.scrambled = '1';
  }

  const scrambleTargets = document.querySelectorAll('[data-scramble]');
  if (scrambleTargets.length) {
    if ('IntersectionObserver' in window) {
      const so = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            scramble(entry.target);
            so.unobserve(entry.target);
          }
        });
      }, { threshold: 0.5 });
      scrambleTargets.forEach(function (el) { so.observe(el); });
    } else {
      scrambleTargets.forEach(scramble);
    }
  }

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

  const cursorDot = document.querySelector('.cursor-dot');
  const cursorRing = document.querySelector('.cursor-ring');
  if (cursorDot && cursorRing && isDesktop && !reduceMotion) {
    let mx = window.innerWidth / 2, my = window.innerHeight / 2;
    let rx = mx, ry = my;
    let hidden = false;
    document.addEventListener('mousemove', function (e) { mx = e.clientX; my = e.clientY; });
    document.addEventListener('mouseleave', function () {
      cursorDot.classList.add('is-hidden');
      cursorRing.classList.add('is-hidden');
      hidden = true;
    });
    document.addEventListener('mouseenter', function () {
      cursorDot.classList.remove('is-hidden');
      cursorRing.classList.remove('is-hidden');
      hidden = false;
    });
    function tick() {
      rx += (mx - rx) * 0.18;
      ry += (my - ry) * 0.18;
      cursorDot.style.transform = 'translate3d(' + (mx - 3) + 'px,' + (my - 3) + 'px,0)';
      cursorRing.style.transform = 'translate3d(' + (rx - 16) + 'px,' + (ry - 16) + 'px,0)';
      requestAnimationFrame(tick);
    }
    tick();
    document.querySelectorAll('a, button, .faq-item summary, .who-grid li, .feature, .plan, .badge, .marquee-chip').forEach(function (el) {
      el.addEventListener('mouseenter', function () { cursorRing.classList.add('is-hover'); });
      el.addEventListener('mouseleave', function () { cursorRing.classList.remove('is-hover'); });
    });
  }

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

  const PROF = {
    consultant: {
      name: 'Aarav Mehta',
      role: 'Consultant · Odoo & Python',
      avatar: 'linear-gradient(135deg, #FF6B35, #FFB088)',
      tiles: [
        ['Case study', 'Inventory automation for a retail chain'],
        ['Case study', 'Custom CRM for a logistics startup'],
        ['Case study', 'Field service app, 12 states'],
      ],
    },
    chef: {
      name: 'Priya Iyer',
      role: 'Chef · South Indian fine dining',
      avatar: 'linear-gradient(135deg, #FFB088, #FFD2A0)',
      tiles: [
        ['Menu', '8-course Onam sadhya, plated for service'],
        ['Gallery', 'Plating — 240 covers, single seating'],
        ['Story', 'Why I source millets from Palakkad'],
      ],
    },
    student: {
      name: 'Riya Sharma',
      role: 'Student · IIT Madras, CS ’26',
      avatar: 'linear-gradient(135deg, #D2C0FF, #FFE4D2)',
      tiles: [
        ['Project', 'Real-time sign-language translator'],
        ['Paper', 'CNN paper, IEEE region 10, 2025'],
        ['Talk', "TEDx — 'My code doesn't work'"],
      ],
    },
    developer: {
      name: 'Karan Desai',
      role: 'Developer · Bengaluru',
      avatar: 'linear-gradient(135deg, #A0E4FF, #C0FFD2)',
      tiles: [
        ['OSS', 'graphql-shield · 6k stars · maintainer'],
        ['Talk', 'JSConf India 2024 — runtime hacking'],
        ['Build', 'TinySlack — 14kb Slack clone'],
      ],
    },
  };

  const tabs = document.querySelectorAll('.s-tab');
  const sName = document.getElementById('s-name');
  const sRole = document.getElementById('s-role');
  const sAvatar = document.getElementById('s-avatar');
  const sGrid = document.getElementById('s-grid');
  if (tabs.length && sName && sRole && sAvatar && sGrid) {
    function switchProf(prof) {
      const p = PROF[prof];
      if (!p) return;
      sName.textContent = p.name;
      sRole.textContent = p.role;
      sAvatar.style.background = p.avatar;
      sGrid.style.opacity = '0';
      sGrid.style.transform = 'translateY(8px)';
      setTimeout(function () {
        sGrid.innerHTML = p.tiles.map(function (t) {
          return '<div class="showcase-tile"><span class="tile-label">' + t[0] + '</span><strong>' + t[1] + '</strong></div>';
        }).join('');
        sGrid.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        sGrid.style.opacity = '1';
        sGrid.style.transform = 'translateY(0)';
      }, 200);
    }
    tabs.forEach(function (t) {
      t.addEventListener('click', function () {
        if (t.classList.contains('is-active')) return;
        tabs.forEach(function (x) { x.classList.remove('is-active'); });
        t.classList.add('is-active');
        switchProf(t.dataset.prof);
      });
    });

    document.querySelectorAll('.s-action').forEach(function (b) {
      b.addEventListener('click', function () {
        b.classList.add('is-flash');
        setTimeout(function () { b.classList.remove('is-flash'); }, 1200);
        if (b.textContent.indexOf('Copy') !== -1 && navigator.clipboard) {
          navigator.clipboard.writeText('foliospace.in/yourname').catch(function () {});
        }
      });
    });
  }

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
    { label: 'See live preview', hint: 'Action', icon: '◉', href: '.showcase' },
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
      cmdList.innerHTML = '<li class="cmd-palette-empty">No matches for "' + q + '"</li>';
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
})();