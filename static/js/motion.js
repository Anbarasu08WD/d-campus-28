/* D-campus motion layer. Progressive enhancement only: every page works without it. */
(function () {
  'use strict';
  var root = document.documentElement;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  root.classList.add('js');

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    /* 1. Scroll progress + sticky topbar shadow */
    var bar = document.createElement('div');
    bar.className = 'pl-progress';
    bar.setAttribute('aria-hidden', 'true');
    document.body.appendChild(bar);
    var topbar = document.querySelector('.topbar');
    var ticking = false;
    function onScroll() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        var max = root.scrollHeight - window.innerHeight;
        bar.style.transform = 'scaleX(' + (max > 0 ? Math.min(window.scrollY / max, 1) : 0) + ')';
        if (topbar) topbar.classList.toggle('is-stuck', window.scrollY > 4);
        ticking = false;
      });
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    /* 2. Scroll reveal with stagger for siblings */
    var groups = [
      '.metric-grid > *', '.attendance-stats > *', '.feature-grid > *',
      '.dashboard-stack > *', '.dashboard-grid > .panel', '.quick-links > *',
      '.page-content .panel', '.section-heading', '.trust-strip', '.bottom-cta',
      '.student-welcome', '.dashboard-header',
      '.lp-hero-copy > *', '.lp-forecast', '.lp-facts > div', '.lp-section-head', '.lp-steps > li', '.lp-split > *', '.lp-cta'
    ];
    var seen = new Set();
    var targets = [];
    groups.forEach(function (sel) {
      var nodes = document.querySelectorAll(sel);
      nodes.forEach(function (el, i) {
        if (seen.has(el)) return;
        seen.add(el);
        el.classList.add('pl-reveal');
        el.style.setProperty('--pl-delay', Math.min(i, 6) * 70 + 'ms');
        targets.push(el);
      });
    });
    if (reduce || !('IntersectionObserver' in window)) {
      targets.forEach(function (el) { el.classList.add('is-in'); });
    } else {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
        });
      }, { threshold: 0.08, rootMargin: '0px 0px -6% 0px' });
      targets.forEach(function (el) { io.observe(el); });
    }

    /* 3. Count-up for numeric metric values (keeps original text as the final state) */
    if (!reduce) {
      document.querySelectorAll('.metric-value, .stat-number, [data-count]').forEach(function (el) {
        var node = null;
        for (var i = 0; i < el.childNodes.length; i++) {
          if (el.childNodes[i].nodeType === 3 && /\d/.test(el.childNodes[i].nodeValue)) { node = el.childNodes[i]; break; }
        }
        if (!node) return;
        var raw = node.nodeValue;
        var m = raw.match(/-?\d+(?:\.\d+)?/);
        if (!m) return;
        var end = parseFloat(m[0]);
        var decimals = (m[0].split('.')[1] || '').length;
        var pre = raw.slice(0, m.index), post = raw.slice(m.index + m[0].length);
        var started = false;
        function run() {
          if (started) return; started = true;
          var t0 = performance.now(), dur = 1000;
          (function tick(now) {
            var p = Math.min((now - t0) / dur, 1);
            var eased = 1 - Math.pow(1 - p, 4);
            node.nodeValue = pre + (end * eased).toFixed(decimals) + post;
            if (p < 1) requestAnimationFrame(tick); else node.nodeValue = raw;
          })(t0);
        }
        if ('IntersectionObserver' in window) {
          var co = new IntersectionObserver(function (es) {
            if (es[0].isIntersecting) { run(); co.disconnect(); }
          }, { threshold: 0.3 });
          co.observe(el);
        } else { run(); }
      });
    }

    /* 4. Button ripple (buttons and link-buttons only; never blocks the click) */
    document.addEventListener('pointerdown', function (e) {
      if (reduce) return;
      var btn = e.target.closest('.button, .btn, .primary-button, .secondary-button, .outline-button');
      if (!btn) return;
      var r = btn.getBoundingClientRect();
      var size = Math.max(r.width, r.height);
      var dot = document.createElement('span');
      dot.className = 'pl-ripple';
      dot.style.width = dot.style.height = size + 'px';
      dot.style.left = (e.clientX - r.left - size / 2) + 'px';
      dot.style.top = (e.clientY - r.top - size / 2) + 'px';
      btn.appendChild(dot);
      setTimeout(function () { dot.remove(); }, 650);
    }, { passive: true });

    /* 5. Hero dashboard tilt (landing page, fine pointers only) */
    var hero = document.querySelector('.hero-visual');
    var mock = document.querySelector('.mock-dashboard');
    if (hero && mock && !reduce && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
      hero.addEventListener('pointermove', function (e) {
        var r = hero.getBoundingClientRect();
        var x = (e.clientX - r.left) / r.width - 0.5;
        var y = (e.clientY - r.top) / r.height - 0.5;
        mock.style.setProperty('--pl-ry', (x * 6).toFixed(2) + 'deg');
        mock.style.setProperty('--pl-rx', (-y * 6).toFixed(2) + 'deg');
      });
      hero.addEventListener('pointerleave', function () {
        mock.style.setProperty('--pl-ry', '0deg');
        mock.style.setProperty('--pl-rx', '0deg');
      });
    }

    /* 6a. Public menu (mobile) */
    var pubBtn = document.getElementById('public-menu-toggle');
    var pubNav = document.getElementById('public-nav');
    if (pubBtn && pubNav) {
      var setPub = function (open) {
        pubNav.classList.toggle('is-open', open);
        pubBtn.setAttribute('aria-expanded', String(open));
        pubBtn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      };
      pubBtn.addEventListener('click', function () { setPub(!pubNav.classList.contains('is-open')); });
      document.addEventListener('click', function (e) {
        if (pubNav.classList.contains('is-open') && !pubNav.contains(e.target) && !pubBtn.contains(e.target)) setPub(false);
      });
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setPub(false); });
      window.addEventListener('resize', function () { if (window.innerWidth > 760) setPub(false); });
    }

    /* 6b. App drawer (mobile): scroll lock, backdrop, Esc, close on navigate */
    var sb = document.getElementById('app-sidebar');
    var bd = document.getElementById('sidebar-backdrop');
    var mb = document.getElementById('mobile-menu-toggle');
    if (sb && bd) {
      var closeDrawer = function () {
        sb.classList.remove('is-open');
        if (mb) { mb.setAttribute('aria-expanded', 'false'); mb.setAttribute('aria-label', 'Open navigation menu'); }
      };
      new MutationObserver(function () {
        document.body.classList.toggle('nav-open', sb.classList.contains('is-open'));
      }).observe(sb, { attributes: true, attributeFilter: ['class'] });
      bd.addEventListener('click', closeDrawer);
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDrawer(); });
      sb.querySelectorAll('a').forEach(function (a) { a.addEventListener('click', closeDrawer); });
      window.addEventListener('resize', function () { if (window.innerWidth > 760) closeDrawer(); });
    }

    /* 6. Flash messages: auto-dismiss non-errors, animate out on close */
    document.querySelectorAll('.flash-message').forEach(function (msg) {
      var isError = msg.classList.contains('danger') || msg.classList.contains('error') || msg.classList.contains('warning');
      function leave() {
        if (!msg.isConnected) return;
        msg.classList.add('is-leaving');
        setTimeout(function () { msg.remove(); }, 260);
      }
      var close = msg.querySelector('.flash-dismiss');
      if (close) close.addEventListener('click', function (ev) { ev.stopImmediatePropagation(); leave(); }, true);
      if (!isError && !reduce) setTimeout(leave, 6000);
    });
  });
})();
