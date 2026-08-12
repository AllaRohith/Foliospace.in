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
    const launch = document.getElementById('launch');
    if (!launch) return;
    const target = new Date(launch.dataset.launch).getTime();
    const $d = document.getElementById('ld-d');
    const $h = document.getElementById('ld-h');
    const $m = document.getElementById('ld-m');
    const $s = document.getElementById('ld-s');
    if (!$d || !$h || !$m || !$s) return;
    function pad(n) { return String(Math.max(0, n)).padStart(2, '0'); }
    function rollDigit(el, newText) {
      if (el.textContent === newText) return;
      if (reduceMotion) { el.textContent = newText; return; }
      el.animate(
        [
          { transform: 'translateY(0)', opacity: 1 },
          { transform: 'translateY(-8px)', opacity: 0, offset: 0.5 },
          { transform: 'translateY(8px)', opacity: 0, offset: 0.501 },
          { transform: 'translateY(0)', opacity: 1 },
        ],
        { duration: 420, easing: 'ease-in-out' }
      );
      setTimeout(function () { el.textContent = newText; }, 210);
    }
    function tick() {
      const diff = Math.max(0, target - Date.now());
      const days = Math.floor(diff / 86400000);
      const hrs = Math.floor((diff % 86400000) / 3600000);
      const mins = Math.floor((diff % 3600000) / 60000);
      const secs = Math.floor((diff % 60000) / 1000);
      rollDigit($d, pad(days));
      rollDigit($h, pad(hrs));
      rollDigit($m, pad(mins));
      rollDigit($s, pad(secs));
      if (diff === 0) onLaunch();
    }
    let launched = (target - Date.now()) <= 0;
    if (launched) onLaunch();
    function onLaunch() {
      if (launched) return;
      launched = true;
      const lbl = launch.querySelector('.launch-label');
      const foot = launch.querySelector('.launch-foot');
      if (lbl) lbl.innerHTML = '<span class="launch-dot"></span> We\'re live';
      if (foot) foot.textContent = 'Welcome to FolioSpace';
      launch.style.borderColor = 'var(--accent)';
      fireConfetti();
    }
    function fireConfetti() {
      const wrap = document.createElement('div');
      wrap.className = 'confetti';
      const colors = ['#FF6B35', '#0F1419', '#FAF7F2', '#FFB088', '#E8E2D6', '#FF8A5B'];
      const n = 140;
      for (let i = 0; i < n; i++) {
        const p = document.createElement('span');
        p.className = 'confetti-piece';
        const left = Math.random() * 100;
        const dx = (Math.random() - 0.5) * 240;
        const rot = (Math.random() * 720) + 'deg';
        const dur = 2200 + Math.random() * 2200;
        const delay = Math.random() * 600;
        p.style.left = left + 'vw';
        p.style.background = colors[Math.floor(Math.random() * colors.length)];
        p.style.setProperty('--dx', dx + 'px');
        p.style.setProperty('--rot', rot);
        p.style.animationDuration = dur + 'ms';
        p.style.animationDelay = delay + 'ms';
        p.style.width = (6 + Math.random() * 8) + 'px';
        p.style.height = (10 + Math.random() * 14) + 'px';
        wrap.appendChild(p);
      }
      document.body.appendChild(wrap);
      setTimeout(function () { wrap.remove(); }, 6000);
    }
    tick();
    setInterval(tick, 1000);
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
        const micro = document.getElementById('signup-microcopy');
        if (micro) micro.textContent = '→ ' + n + ' already in · no spam · delete on request';
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

  const PROF = {
    chef: {
      url: 'priya-iyer',
      monogram: 'PI',
      name: 'Priya Iyer',
      role: 'Chef · South Indian fine dining · Bengaluru · since 2019',
      live: { views: 127, updated: 2, shares: 12 },
      cta: { label: 'Reserve a tasting menu', sub: 'Private dining · 8 covers · 8 PM' },
      body: function () {
        return ''
          + '<div class="pf pf-chef">'
          +   '<div class="pf-ticker">'
          +     '<span class="pf-ticker-item"><span class="pf-live-dot"></span><strong>' + PROF.chef.live.views + '</strong> viewing now</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Updated <strong>' + PROF.chef.live.updated + ' min</strong> ago</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Shared <strong>' + PROF.chef.live.shares + '</strong>× today</span>'
          +   '</div>'
          +   '<div class="pf-head">'
          +     '<div class="pf-monogram">' + PROF.chef.monogram + '</div>'
          +     '<div class="pf-head-meta">'
          +       '<h3 class="pf-name">' + PROF.chef.name + '</h3>'
          +       '<p class="pf-role">' + PROF.chef.role + '</p>'
          +     '</div>'
          +     '<span class="pf-rating" title="4.9 from 240 covers"><span class="pf-stars">★★★★★</span><span class="pf-rating-n">4.9</span></span>'
          +   '</div>'
          +   '<div class="pf-section-title">Signature dishes</div>'
          +   '<ul class="pf-menu">'
          +     '<li class="pf-dish-row" data-dish="01">'
          +       '<div class="pf-dish-head">'
          +         '<span class="pf-course">01</span>'
          +         '<span class="pf-dish">Nellore karam podi, gongura leaf</span>'
          +         '<span class="pf-tag">veg</span>'
          +         '<span class="pf-arrow">+</span>'
          +       '</div>'
          +       '<div class="pf-dish-detail"><em>The dish that put her on the map. Andhra lentil crumble, gongura greens, ghee tempering — plated on a banana-leaf tile. Featured at the 2023 Madras food festival.</em></div>'
          +     '</li>'
          +     '<li class="pf-dish-row" data-dish="02">'
          +       '<div class="pf-dish-head">'
          +         '<span class="pf-course">02</span>'
          +         '<span class="pf-dish">Palakkad millet risotto, morel</span>'
          +         '<span class="pf-tag">gf</span>'
          +         '<span class="pf-arrow">+</span>'
          +       '</div>'
          +       '<div class="pf-dish-detail"><em>Foxtail millet swapped in for arborio; finished with coconut milk and a wild morel shaved tableside. Born from a sabbatical in Kerala.</em></div>'
          +     '</li>'
          +     '<li class="pf-dish-row" data-dish="03">'
          +       '<div class="pf-dish-head">'
          +         '<span class="pf-course">03</span>'
          +         '<span class="pf-dish">Tellicherry pepper crab, appam</span>'
          +         '<span class="pf-arrow">+</span>'
          +       '</div>'
          +       '<div class="pf-dish-detail"><em>Malabar black pepper crab with a lacy rice appam. Coastal technique, plated as a tasting portion.</em></div>'
          +     '</li>'
          +     '<li class="pf-dish-row" data-dish="04">'
          +       '<div class="pf-dish-head">'
          +         '<span class="pf-course">04</span>'
          +         '<span class="pf-dish">8-course Onam sadhya, plated</span>'
          +         '<span class="pf-tag">signature</span>'
          +         '<span class="pf-arrow">+</span>'
          +       '</div>'
          +       '<div class="pf-dish-detail"><em>The signature. Banana-leaf sadhya reimagined as nine single-serve courses. Booking-only, six weeks out.</em></div>'
          +     '</li>'
          +   '</ul>'
          +   '<div class="pf-section-title">In the press</div>'
          +   '<div class="pf-press">'
          +     '<p class="pf-press-quote">“Reimagining the sadhya as fine dining without losing its soul.”</p>'
          +     '<p class="pf-press-meta">— Condé Nast Traveller · Best New Chef, Bengaluru 2024</p>'
          +   '</div>'
          +   '<a class="pf-cta" href="#"><span class="pf-cta-label">' + PROF.chef.cta.label + '</span><span class="pf-cta-sub">' + PROF.chef.cta.sub + '</span><span class="pf-cta-arrow">→</span></a>'
          + '</div>';
      }
    },
    developer: {
      url: 'karan-desai',
      monogram: 'KD',
      name: 'Karan Desai',
      role: 'Backend engineer · ex-Razorpay · Bengaluru',
      live: { views: 84, updated: 8, shares: 6 },
      cta: { label: 'View GitHub', sub: '@karan-desai · 14 public repos' },
      body: function () {
        return ''
          + '<div class="pf pf-dev">'
          +   '<div class="pf-ticker">'
          +     '<span class="pf-ticker-item"><span class="pf-live-dot"></span><strong>' + PROF.developer.live.views + '</strong> viewing now</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Updated <strong>' + PROF.developer.live.updated + ' min</strong> ago</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Shared <strong>' + PROF.developer.live.shares + '</strong>× today</span>'
          +   '</div>'
          +   '<div class="pf-head">'
          +     '<div class="pf-monogram">' + PROF.developer.monogram + '</div>'
          +     '<div class="pf-head-meta">'
          +       '<h3 class="pf-name">' + PROF.developer.name + '</h3>'
          +       '<p class="pf-role">' + PROF.developer.role + '</p>'
          +     '</div>'
          +     '<span class="pf-rating" title="4.8 from 32 collaborators"><span class="pf-stars">★★★★★</span><span class="pf-rating-n">4.8</span></span>'
          +   '</div>'
          +   '<div class="pf-section-title">Selected projects</div>'
          +   '<ul class="pf-proj-list">'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>graphql-shield</strong><span class="pf-proj-stars" data-count="6200">★ 0</span></div>'
          +       '<p class="pf-proj-desc">GraphQL permissions middleware. Used in production at Razorpay, Swiggy, Apollo.</p>'
          +     '</li>'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>edge-cache</strong><span class="pf-proj-stars" data-count="2400">★ 0</span></div>'
          +       '<p class="pf-proj-desc">Tiny edge-cache layer for Cloudflare Workers. Zero-config, 4 KB.</p>'
          +     '</li>'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>TinySlack</strong><span class="pf-proj-stars" data-count="14">★ 0</span></div>'
          +       '<p class="pf-proj-desc">Self-hosted Slack alternative in 600 lines of Go. Weekend project.</p>'
          +     '</li>'
          +   '</ul>'
          +   '<div class="pf-section-title">Speaking</div>'
          +   '<ul class="pf-talk-list">'
          +     '<li class="pf-talk-row"><span class="pf-talk-year">2025</span><span class="pf-talk-body"><strong>JSConf India</strong> · Runtime hacking for fun and profit</span></li>'
          +     '<li class="pf-talk-row"><span class="pf-talk-year">2024</span><span class="pf-talk-body"><strong>React India</strong> · Why your cache layer is wrong</span></li>'
          +   '</ul>'
          +   '<div class="pf-section-title">Now</div>'
          +   '<p class="pf-now">Building a real-time permission system for OpenAI tools. Reading <em>Designing Data-Intensive Applications</em> for the third time. Open to staff roles, remote-first.</p>'
          +   '<a class="pf-cta" href="#"><span class="pf-cta-label">' + PROF.developer.cta.label + '</span><span class="pf-cta-sub">' + PROF.developer.cta.sub + '</span><span class="pf-cta-arrow">→</span></a>'
          + '</div>';
      }
    },
    student: {
      url: 'riya-sharma',
      monogram: 'RS',
      name: 'Riya Sharma',
      role: 'CS undergraduate · IIT Madras · Class of 2026',
      live: { views: 53, updated: 14, shares: 4 },
      cta: { label: 'Send a message', sub: 'Open to SDE internships · Summer 2026' },
      body: function () {
        return ''
          + '<div class="pf pf-student">'
          +   '<div class="pf-ticker">'
          +     '<span class="pf-ticker-item"><span class="pf-live-dot"></span><strong>' + PROF.student.live.views + '</strong> viewing now</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Updated <strong>' + PROF.student.live.updated + ' min</strong> ago</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Shared <strong>' + PROF.student.live.shares + '</strong>× today</span>'
          +   '</div>'
          +   '<div class="pf-head">'
          +     '<div class="pf-monogram">' + PROF.student.monogram + '</div>'
          +     '<div class="pf-head-meta">'
          +       '<h3 class="pf-name">' + PROF.student.name + '</h3>'
          +       '<p class="pf-role">' + PROF.student.role + '</p>'
          +     '</div>'
          +     '<span class="pf-rating" title="9.12 CGPA · top 5%"><span class="pf-stars">★★★★★</span><span class="pf-rating-n">9.12</span></span>'
          +   '</div>'
          +   '<div class="pf-section-title">Experience</div>'
          +   '<ul class="pf-experience">'
          +     '<li class="pf-experience-row">'
          +       '<div class="pf-experience-head"><strong>Razorpay</strong><span class="pf-experience-meta">SDE Intern · May–Jul 2025</span></div>'
          +       '<p class="pf-experience-desc">Shipped a settlement reconciliation tool. Cut ops manual work by 6 hours/week.</p>'
          +     '</li>'
          +     '<li class="pf-experience-row">'
          +       '<div class="pf-experience-head"><strong>Google Summer of Code</strong><span class="pf-experience-meta">OpenCV · Summer 2024</span></div>'
          +       '<p class="pf-experience-desc">Contributed CUDA kernels to OpenCV’s stereo-matching module. Merged upstream.</p>'
          +     '</li>'
          +   '</ul>'
          +   '<div class="pf-section-title">Projects · 4 of 12</div>'
          +   '<ul class="pf-proj-list">'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>Real-time ISL translator</strong><span class="pf-proj-tag">22k MAU</span></div>'
          +       '<p class="pf-proj-desc">React Native + TensorFlow Lite. Built for an accessibility hackathon; still in use.</p>'
          +     '</li>'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>Edge-detect on 2G</strong><span class="pf-proj-tag">IEEE Region 10</span></div>'
          +       '<p class="pf-proj-desc">CNN-based edge detection that runs on a 2014 Android phone over 2G.</p>'
          +     '</li>'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>“My code doesn’t work”</strong><span class="pf-proj-tag">TEDx</span></div>'
          +       '<p class="pf-proj-desc">1,400-seat TEDx talk on debugging as a discipline. Mar 2025.</p>'
          +     '</li>'
          +   '</ul>'
          +   '<div class="pf-section-title">Achievements</div>'
          +   '<ul class="pf-achievement-list">'
          +     '<li>JEE Advanced 2022 · AIR 184</li>'
          +     '<li>MLH Spring 2025 · Top 50 Fellow</li>'
          +     '<li>Codeforces Specialist · 1,612</li>'
          +   '</ul>'
          +   '<a class="pf-cta" href="#"><span class="pf-cta-label">' + PROF.student.cta.label + '</span><span class="pf-cta-sub">' + PROF.student.cta.sub + '</span><span class="pf-cta-arrow">→</span></a>'
          + '</div>';
      }
    },
    consultant: {
      url: 'aarav-mehta',
      monogram: 'AM',
      name: 'Aarav Mehta',
      role: 'Independent Odoo & Python consultant · Mumbai',
      live: { views: 41, updated: 22, shares: 3 },
      cta: { label: 'Book a free 30-min call', sub: 'Next slot · Wed 4 PM IST' },
      body: function () {
        return ''
          + '<div class="pf pf-consultant">'
          +   '<div class="pf-ticker">'
          +     '<span class="pf-ticker-item"><span class="pf-live-dot"></span><strong>' + PROF.consultant.live.views + '</strong> viewing now</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Updated <strong>' + PROF.consultant.live.updated + ' min</strong> ago</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Shared <strong>' + PROF.consultant.live.shares + '</strong>× today</span>'
          +   '</div>'
          +   '<div class="pf-head">'
          +     '<div class="pf-monogram">' + PROF.consultant.monogram + '</div>'
          +     '<div class="pf-head-meta">'
          +       '<h3 class="pf-name">' + PROF.consultant.name + '</h3>'
          +       '<p class="pf-role">' + PROF.consultant.role + '</p>'
          +     '</div>'
          +     '<span class="pf-rating" title="4.9 from 18 retainer clients"><span class="pf-stars">★★★★★</span><span class="pf-rating-n">4.9</span></span>'
          +   '</div>'
          +   '<div class="pf-section-title">Who I work with</div>'
          +   '<p class="pf-blurb">Series-A and growth-stage Indian companies (₹10 Cr – ₹200 Cr ARR) that need a fractional CTO without a ₹40 Lakh salary. Engagements run 8–24 weeks.</p>'
          +   '<div class="pf-section-title">Selected engagements</div>'
          +   '<ul class="pf-cases">'
          +     '<li class="pf-case-row">'
          +       '<div class="pf-case-head"><strong>Inventory automation</strong><span class="pf-case-meta">Retail chain · 14 stores</span></div>'
          +       '<p class="pf-case-out" data-count="-42" data-prefix="-" data-suffix="% stockouts in 6 weeks">-0% stockouts in 6 weeks</p>'
          +     '</li>'
          +     '<li class="pf-case-row">'
          +       '<div class="pf-case-head"><strong>Custom CRM</strong><span class="pf-case-meta">Logistics startup · 8 users</span></div>'
          +       '<p class="pf-case-out">Shipped in 4 weeks · still in daily use 18 months later</p>'
          +     '</li>'
          +     '<li class="pf-case-row">'
          +       '<div class="pf-case-head"><strong>Field service app</strong><span class="pf-case-meta">240 technicians · 12 states</span></div>'
          +       '<p class="pf-case-out" data-count="3.8" data-suffix="× technician throughput">0× technician throughput</p>'
          +     '</li>'
          +   '</ul>'
          +   '<div class="pf-section-title">Testimonials</div>'
          +   '<p class="pf-press-quote">“Cut our month-end close from 9 days to 2. Worth every rupee.”</p>'
          +   '<p class="pf-press-meta">— Priya Krishnan · CFO, Kirana Direct (retail chain)</p>'
          +   '<a class="pf-cta" href="#"><span class="pf-cta-label">' + PROF.consultant.cta.label + '</span><span class="pf-cta-sub">' + PROF.consultant.cta.sub + '</span><span class="pf-cta-arrow">→</span></a>'
          + '</div>';
      }
    },
    designer: {
      url: 'ananya-bose',
      monogram: 'AB',
      name: 'Ananya Bose',
      role: 'Product designer · formerly Razorpay, CRED · Bengaluru',
      live: { views: 96, updated: 5, shares: 8 },
      cta: { label: 'View Dribbble', sub: '@ananya-bose · 142 shots' },
      body: function () {
        return ''
          + '<div class="pf pf-designer">'
          +   '<div class="pf-ticker">'
          +     '<span class="pf-ticker-item"><span class="pf-live-dot"></span><strong>' + PROF.designer.live.views + '</strong> viewing now</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Updated <strong>' + PROF.designer.live.updated + ' min</strong> ago</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Shared <strong>' + PROF.designer.live.shares + '</strong>× today</span>'
          +   '</div>'
          +   '<div class="pf-head">'
          +     '<div class="pf-monogram">' + PROF.designer.monogram + '</div>'
          +     '<div class="pf-head-meta">'
          +       '<h3 class="pf-name">' + PROF.designer.name + '</h3>'
          +       '<p class="pf-role">' + PROF.designer.role + '</p>'
          +     '</div>'
          +     '<span class="pf-rating" title="4.9 from 23 clients"><span class="pf-stars">★★★★★</span><span class="pf-rating-n">4.9</span></span>'
          +   '</div>'
          +   '<div class="pf-section-title">Selected work · 2023–25</div>'
          +   '<ul class="pf-proj-list">'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>Razorpay Merchant Dashboard</strong><span class="pf-proj-tag">2024</span></div>'
          +       '<p class="pf-proj-desc">Led redesign of the core payments dashboard. Settlements page adopted by 8M merchants.</p>'
          +     '</li>'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>Khata Book — credit line</strong><span class="pf-proj-tag">2023</span></div>'
          +       '<p class="pf-proj-desc">First end-to-end credit product for India’s 60M kirana stores.</p>'
          +     '</li>'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>Indian Railways — booking flow</strong><span class="pf-proj-tag">2025 · in progress</span></div>'
          +       '<p class="pf-proj-desc">Currently redesigning IRCTC. One of India’s most-trafficked products.</p>'
          +     '</li>'
          +   '</ul>'
          +   '<div class="pf-section-title">Recognition</div>'
          +   '<ul class="pf-achievement-list">'
          +     '<li>Awwwards · Site of the Day · 2024</li>'
          +     '<li>YourStory · 30 under 30 design · 2024</li>'
          +     '<li>Speaker · Adobe MAX India · 2025</li>'
          +   '</ul>'
          +   '<a class="pf-cta" href="#"><span class="pf-cta-label">' + PROF.designer.cta.label + '</span><span class="pf-cta-sub">' + PROF.designer.cta.sub + '</span><span class="pf-cta-arrow">→</span></a>'
          + '</div>';
      }
    },
    writer: {
      url: 'vikram-iyer',
      monogram: 'VI',
      name: 'Vikram Iyer',
      role: 'Independent journalist · Delhi · politics & cities',
      live: { views: 38, updated: 18, shares: 5 },
      cta: { label: 'Read the full archive', sub: '140 essays · since 2017' },
      body: function () {
        return ''
          + '<div class="pf pf-writer">'
          +   '<div class="pf-ticker">'
          +     '<span class="pf-ticker-item"><span class="pf-live-dot"></span><strong>' + PROF.writer.live.views + '</strong> viewing now</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Updated <strong>' + PROF.writer.live.updated + ' min</strong> ago</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Shared <strong>' + PROF.writer.live.shares + '</strong>× today</span>'
          +   '</div>'
          +   '<div class="pf-head">'
          +     '<div class="pf-monogram">' + PROF.writer.monogram + '</div>'
          +     '<div class="pf-head-meta">'
          +       '<h3 class="pf-name">' + PROF.writer.name + '</h3>'
          +       '<p class="pf-role">' + PROF.writer.role + '</p>'
          +     '</div>'
          +     '<span class="pf-rating" title="5 from 12 editors"><span class="pf-stars">★★★★★</span><span class="pf-rating-n">5.0</span></span>'
          +   '</div>'
          +   '<div class="pf-section-title">Latest essays</div>'
          +   '<ul class="pf-essay-list">'
          +     '<li class="pf-essay-row">'
          +       '<div class="pf-essay-head"><strong>The last street-vendor of Chandni Chowk</strong></div>'
          +       '<p class="pf-essay-meta">The Caravan · Aug 2026 · 14 min read</p>'
          +     '</li>'
          +     '<li class="pf-essay-row">'
          +       '<div class="pf-essay-head"><strong>What Mumbai’s coastal road got right</strong></div>'
          +       '<p class="pf-essay-meta">Mint · Jul 2026 · 9 min read</p>'
          +     '</li>'
          +     '<li class="pf-essay-row">'
          +       '<div class="pf-essay-head"><strong>Inside India’s new Parliament</strong></div>'
          +       '<p class="pf-essay-meta">The Atlantic · May 2026 · 22 min read</p>'
          +     '</li>'
          +   '</ul>'
          +   '<div class="pf-section-title">Bylines</div>'
          +   '<p class="pf-byline-grid">The Caravan · The Atlantic · Mint · Scroll · Hindustan Times · India Today</p>'
          +   '<a class="pf-cta" href="#"><span class="pf-cta-label">' + PROF.writer.cta.label + '</span><span class="pf-cta-sub">' + PROF.writer.cta.sub + '</span><span class="pf-cta-arrow">→</span></a>'
          + '</div>';
      }
    },
    photographer: {
      url: 'lakshmi-rao',
      monogram: 'LR',
      name: 'Lakshmi Rao',
      role: 'Editorial & wedding photographer · Mumbai',
      live: { views: 72, updated: 11, shares: 9 },
      cta: { label: 'Book a shoot', sub: '2026 dates open · reply within 24h' },
      body: function () {
        return ''
          + '<div class="pf pf-photographer">'
          +   '<div class="pf-ticker">'
          +     '<span class="pf-ticker-item"><span class="pf-live-dot"></span><strong>' + PROF.photographer.live.views + '</strong> viewing now</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Updated <strong>' + PROF.photographer.live.updated + ' min</strong> ago</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Shared <strong>' + PROF.photographer.live.shares + '</strong>× today</span>'
          +   '</div>'
          +   '<div class="pf-head">'
          +     '<div class="pf-monogram">' + PROF.photographer.monogram + '</div>'
          +     '<div class="pf-head-meta">'
          +       '<h3 class="pf-name">' + PROF.photographer.name + '</h3>'
          +       '<p class="pf-role">' + PROF.photographer.role + '</p>'
          +     '</div>'
          +     '<span class="pf-rating" title="4.9 from 86 couples"><span class="pf-stars">★★★★★</span><span class="pf-rating-n">4.9</span></span>'
          +   '</div>'
          +   '<div class="pf-section-title">Recent work</div>'
          +   '<ul class="pf-proj-list">'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>Vogue India — “Maharashtrian weddings”</strong><span class="pf-proj-tag">Editorial · Aug 2026</span></div>'
          +       '<p class="pf-proj-desc">12-page editorial spread shot over 4 days in Pune.</p>'
          +     '</li>'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>Aanya & Rohan — Udaipur</strong><span class="pf-proj-tag">Wedding · Apr 2026</span></div>'
          +       '<p class="pf-proj-desc">3-day wedding at the Oberoi Udaivilas. 4,200 final images.</p>'
          +     '</li>'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>“Mills of Mumbai” series</strong><span class="pf-proj-tag">Personal · ongoing</span></div>'
          +       '<p class="pf-proj-desc">Long-running documentary on Mumbai’s last cotton mills. 6 of 14 shot.</p>'
          +     '</li>'
          +   '</ul>'
          +   '<div class="pf-section-title">Recognition</div>'
          +   '<ul class="pf-achievement-list">'
          +     '<li>IPA · 2nd Place, Documentary · 2025</li>'
          +     '<li>Featured · National Geographic India · 2024</li>'
          +     '<li>Solo show · PhotoInk Gallery, Mumbai · 2023</li>'
          +   '</ul>'
          +   '<a class="pf-cta" href="#"><span class="pf-cta-label">' + PROF.photographer.cta.label + '</span><span class="pf-cta-sub">' + PROF.photographer.cta.sub + '</span><span class="pf-cta-arrow">→</span></a>'
          + '</div>';
      }
    },
    founder: {
      url: 'aditi-shah',
      monogram: 'AS',
      name: 'Aditi Shah',
      role: 'Indie maker · building Saaral, a Hindi reading app · Bengaluru',
      live: { views: 64, updated: 7, shares: 7 },
      cta: { label: 'Try the app', sub: 'Free · iOS + Android · 4.8 ★' },
      body: function () {
        return ''
          + '<div class="pf pf-founder">'
          +   '<div class="pf-ticker">'
          +     '<span class="pf-ticker-item"><span class="pf-live-dot"></span><strong>' + PROF.founder.live.views + '</strong> viewing now</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Updated <strong>' + PROF.founder.live.updated + ' min</strong> ago</span>'
          +     '<span class="pf-ticker-sep">·</span>'
          +     '<span class="pf-ticker-item">Shared <strong>' + PROF.founder.live.shares + '</strong>× today</span>'
          +   '</div>'
          +   '<div class="pf-head">'
          +     '<div class="pf-monogram">' + PROF.founder.monogram + '</div>'
          +     '<div class="pf-head-meta">'
          +       '<h3 class="pf-name">' + PROF.founder.name + '</h3>'
          +       '<p class="pf-role">' + PROF.founder.role + '</p>'
          +     '</div>'
          +     '<span class="pf-rating" title="4.8 from 6.2k users"><span class="pf-stars">★★★★★</span><span class="pf-rating-n">4.8</span></span>'
          +   '</div>'
          +   '<div class="pf-section-title">Products</div>'
          +   '<ul class="pf-proj-list">'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>Saaral · Hindi reading</strong><span class="pf-proj-stars" data-count="6200">★ 0</span></div>'
          +       '<p class="pf-proj-desc">A reading app for Hindi literature with one-tap dictionary. 6,200 paying users.</p>'
          +     '</li>'
          +     '<li class="pf-proj-row">'
          +       '<div class="pf-proj-head"><strong>Postcard · micro-blogs</strong><span class="pf-proj-tag">acquired</span></div>'
          +       '<p class="pf-proj-desc">A postcard-style microblog platform. Sold to an Indian media house in 2024.</p>'
          +     '</li>'
          +   '</ul>'
          +   '<div class="pf-section-title">Traction · 2026</div>'
          +   '<div class="pf-dev-row">'
          +     '<div class="pf-stat"><span class="pf-stat-num" data-count="42" data-prefix="₹" data-suffix="L">₹0L</span><span class="pf-stat-label">ARR · year 2</span></div>'
          +     '<div class="pf-stat"><span class="pf-stat-num" data-count="94" data-suffix="%">0%</span><span class="pf-stat-label">renewal rate</span></div>'
          +     '<div class="pf-stat"><span class="pf-stat-num" data-count="0" data-suffix="">0</span><span class="pf-stat-label">employees</span></div>'
          +   '</div>'
          +   '<div class="pf-section-title">Now</div>'
          +   '<p class="pf-now">Profitable since month 6. Adding a poetry-recitation feature. Considering a Hindi-English toggle. Email replies within 4 hours, always.</p>'
          +   '<a class="pf-cta" href="#"><span class="pf-cta-label">' + PROF.founder.cta.label + '</span><span class="pf-cta-sub">' + PROF.founder.cta.sub + '</span><span class="pf-cta-arrow">→</span></a>'
          + '</div>';
      }
    },
  };

  const showcaseBody = document.getElementById('showcase-body');
  const showcaseUrl = document.getElementById('s-url');
  const showcaseCaption = document.getElementById('showcase-caption');
  const tabs = Array.from(document.querySelectorAll('.s-tab'));
  const tabIndicator = document.querySelector('.s-tab-indicator');
  const tabGrid = document.querySelector('.showcase-tabs');

  function positionTabIndicator(tab) {
    if (!tabIndicator || !tab || !tabGrid) return;
    const gridRect = tabGrid.getBoundingClientRect();
    const tabRect = tab.getBoundingClientRect();
    tabIndicator.style.width = tabRect.width + 'px';
    tabIndicator.style.transform = 'translateX(' + (tabRect.left - gridRect.left) + 'px) translateY(' + (tabRect.top - gridRect.top) + 'px)';
    tabIndicator.style.height = tabRect.height + 'px';
  }

  if (tabs.length && showcaseBody) {
    function animateCount(el) {
      const target = parseFloat(el.dataset.count);
      const prefix = el.dataset.prefix || '';
      const suffix = el.dataset.suffix || '';
      if (!isFinite(target)) return;
      const dur = 900;
      const t0 = performance.now();
      const decimals = (String(target).split('.')[1] || '').length;
      function tick(now) {
        const p = Math.min(1, (now - t0) / dur);
        const eased = 1 - Math.pow(1 - p, 3);
        const v = target * eased;
        el.textContent = prefix + (decimals ? v.toFixed(decimals) : Math.round(v).toLocaleString('en-IN')) + suffix;
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }

    function wireCard() {
      showcaseBody.querySelectorAll('.pf-dish-row').forEach(function (row) {
        row.addEventListener('click', function () { row.classList.toggle('is-open'); });
      });
      showcaseBody.querySelectorAll('.pf-case-row').forEach(function (row) {
        row.addEventListener('click', function () { row.classList.toggle('is-open'); });
      });
      showcaseBody.querySelectorAll('[data-count]').forEach(animateCount);
    }

    function switchProf(prof) {
      const p = PROF[prof];
      if (!p) return;
      showcaseBody.style.transition = 'opacity 0.18s ease';
      showcaseBody.style.opacity = '0';
      showcaseBody.style.transform = 'translateY(6px)';
      setTimeout(function () {
        showcaseBody.innerHTML = p.body();
        showcaseBody.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        showcaseBody.style.opacity = '1';
        showcaseBody.style.transform = 'translateY(0)';
        if (showcaseUrl) showcaseUrl.textContent = 'foliospace.in/' + p.url;
        if (showcaseCaption) showcaseCaption.textContent = 'Fig. 1 — foliospace.in/' + p.url;
        wireCard();
      }, 200);
    }
    tabs.forEach(function (t) {
      t.addEventListener('click', function () {
        if (t.classList.contains('is-active')) return;
        tabs.forEach(function (x) { x.classList.remove('is-active'); });
        t.classList.add('is-active');
        positionTabIndicator(t);
        switchProf(t.dataset.prof);
      });
    });

    tabGrid && tabGrid.addEventListener('keydown', function (e) {
      const active = tabs.findIndex(function (t) { return t.classList.contains('is-active'); });
      if (active < 0) return;
      const cols = 4;
      let next = -1;
      if (e.key === 'ArrowRight') next = (active + 1) % tabs.length;
      else if (e.key === 'ArrowLeft') next = (active - 1 + tabs.length) % tabs.length;
      else if (e.key === 'ArrowDown') next = (active + cols) % tabs.length;
      else if (e.key === 'ArrowUp') next = (active - cols + tabs.length) % tabs.length;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = tabs.length - 1;
      if (next >= 0 && next !== active) {
        e.preventDefault();
        tabs[next].click();
        tabs[next].focus();
      }
    });

    window.addEventListener('resize', function () {
      const active = tabs.find(function (t) { return t.classList.contains('is-active'); });
      if (active) positionTabIndicator(active);
    });

    requestAnimationFrame(function () {
      const active = tabs.find(function (t) { return t.classList.contains('is-active'); });
      if (active) positionTabIndicator(active);
    });

    document.querySelectorAll('.s-action').forEach(function (b) {
      b.addEventListener('click', function () {
        b.classList.add('is-flash');
        setTimeout(function () { b.classList.remove('is-flash'); }, 1200);
        if (b.textContent.indexOf('Copy') !== -1 && navigator.clipboard) {
          navigator.clipboard.writeText(showcaseUrl ? showcaseUrl.textContent : 'foliospace.in/yourname').catch(function () {});
        }
      });
    });

    switchProf('chef');
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