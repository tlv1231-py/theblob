// ═══════════════════════════════════════════════════════════════════════════
// VERTICAL STREAM — portrait renderer
//
// Sibling to home_nav.js, not a fork of it. That file is tuned for a wide
// stage and binds to Command Center DOM ids; this one owns a 1080x1920 stage
// and nothing else. Shared surface is the data contract only (nav_snapshots).
//
// Nothing here responds to input. The page is a capture target: it must look
// identical whether or not a cursor exists.
// ═══════════════════════════════════════════════════════════════════════════

(function() {
  var S = window._TND_STREAM;
  if (!S) return;

  var $ = function(id) { return document.getElementById(id); };

  // ── Letterbox ────────────────────────────────────────────────────────────
  // The stage never reflows. It scales as a unit so a 1080x1920 capture is
  // pixel-native and anything else is a clean fit.
  function fitStage() {
    var s = Math.min(window.innerWidth / S.stage.w, window.innerHeight / S.stage.h);
    $('stage').style.setProperty('--s', s);
  }
  fitStage();
  window.addEventListener('resize', fitStage);

  // ── Format ───────────────────────────────────────────────────────────────
  function usd(v, dp) {
    if (v == null || isNaN(v)) return '—';
    return '$' + Number(v).toLocaleString('en-US', {
      minimumFractionDigits: dp || 0, maximumFractionDigits: dp || 0 });
  }
  function signed(v, dp) {
    if (v == null || isNaN(v)) return '—';
    var n = Number(v);
    return (n >= 0 ? '+' : '−') + '$' + Math.abs(n).toLocaleString('en-US', {
      minimumFractionDigits: dp || 0, maximumFractionDigits: dp || 0 });
  }
  function pct(v, dp) {
    if (v == null || isNaN(v)) return '—';
    var n = Number(v);
    return (n >= 0 ? '+' : '−') + Math.abs(n).toFixed(dp == null ? 2 : dp) + '%';
  }
  function dirClass(v) { return v > 0.001 ? 'up' : (v < -0.001 ? 'down' : 'flat'); }

  // ── Clock / session ──────────────────────────────────────────────────────
  // NYSE hours. The calendar module is the source of truth for holidays, but
  // it lives server-side; this is a cosmetic session light, not a trade gate,
  // so a weekday+hours check is the honest scope. It can read OPEN on a
  // holiday — nothing downstream depends on it except the Blob's nap.
  function etParts() {
    var f = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', hour12: false,
      weekday: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit'
    }).formatToParts(new Date());
    var o = {};
    f.forEach(function(p) { o[p.type] = p.value; });
    return o;
  }
  function isMarketOpen() {
    var p = etParts();
    if (['Sat', 'Sun'].indexOf(p.weekday) >= 0) return false;
    var mins = parseInt(p.hour, 10) * 60 + parseInt(p.minute, 10);
    return mins >= 570 && mins < 960;          // 09:30 → 16:00 ET
  }
  function tickClock() {
    var p = etParts();
    $('hd-clock').textContent = p.hour + ':' + p.minute + ':' + p.second + ' ET';
    var open = isMarketOpen();
    var el = $('hd-sess');
    el.textContent = open ? 'MARKET OPEN' : 'MARKET CLOSED';
    el.className = 'hd-sess ' + (open ? 'open' : 'closed');
  }
  tickClock();
  setInterval(tickClock, 1000);

  // ── The Blob ─────────────────────────────────────────────────────────────
  // Wired per the BLOB.md table. He is the reason this page is watchable
  // rather than a screenshot, so he gets real state, not decoration.
  var blob = TNDBlob.create($('blobCanvas'), {
    grid: 48, fps: 10,          // 10fps is load-bearing — see BLOB.md.
    onAccent: function(rgb) {
      $('blob-bloom').style.background =
        'radial-gradient(circle, rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] +
        ',0.34), transparent 68%)';
    }
  });
  blob.start();

  function syncBlobMood() {
    // Transient moods own the character until they decay; don't stomp them.
    var m = blob.getMood();
    if (m === 'ALERT' || m === 'HAPPY' || m === 'SCARED') return;

    if (!isMarketOpen()) { blob.setMood('SLEEP'); return; }

    // Drawdown against the real configured limit, not a magic number.
    var ddLimit = S.limits.daily_dd * 100;
    if (state.dayPnlPct <= -ddLimit * 0.75) { blob.setMood('SCARED'); return; }
    if (state.dayPnlPct >= 1.0)             { blob.setMood('SMUG');   return; }
    blob.setMood('IDLE');
  }

  // ── State ────────────────────────────────────────────────────────────────
  var state = {
    nav:        S.nav,
    dayPnl:     S.day_pnl,
    dayPnlPct:  S.day_pnl_pct,
    pts:        (S.nav_pts || []).map(function(p) {
                  return { t: new Date(p.t).getTime(), v: Number(p.v) };
                }).filter(function(p) { return !isNaN(p.t) && !isNaN(p.v); }),
    seenEvTs:   null
  };

  // ── NAV block ────────────────────────────────────────────────────────────
  function renderHero() {
    $('hero-nav').textContent = usd(state.nav);
    var d = $('hero-day');
    d.textContent = signed(state.dayPnl) + '  ' + pct(state.dayPnlPct);
    d.className = 'nav-day ' + dirClass(state.dayPnlPct);

    $('chip-status').textContent = S.status || 'PAPER';
    $('chip-day').textContent = 'DAY ' + (S.monitoring_days || 0) + '/20';

    // Deliberately NOT (nav - starting_capital) / starting_capital. The NAV
    // series comes from nav_snapshots, which is keyed only by timestamp and is
    // written by whichever Alpaca wallet happens to be active in the browser —
    // so it is not denominated in the $100k model baseline, and that ratio
    // renders as a ~-72% "loss" that never happened. The pnl table's own
    // cumulative figure is the only honest strategy-scoped number here.
    var cum = Number(S.cumulative_pnl || 0);
    var ct = $('chip-total');
    ct.textContent = 'STRATEGY P&L  ' + signed(cum);
    ct.className = 'nav-sub ' + dirClass(cum);

    blob.setPnl(state.dayPnlPct);
    $('blob-mood').textContent = blob.getMood();
  }

  // ── NAV chart ────────────────────────────────────────────────────────────
  // Portrait rewrites the chart's job. The wide version can afford 30 days of
  // x-axis; inside an 870-wide safe box that's an unreadable smear, so this
  // shows the live session only.
  var cv = $('navCanvas'), cx = cv.getContext('2d');
  var WIN_MS = 8 * 3600 * 1000;   // trailing 8h — covers a full session

  // Assigning canvas.width/height reallocates the backing store and clears it,
  // so this only touches them when the size genuinely changed. Called every
  // frame; this page runs for hours unattended and must stay cheap.
  var _cvDim = { w: 0, h: 0 };
  function sizeCanvas() {
    var r = cv.getBoundingClientRect();
    var dpr = window.devicePixelRatio || 1;
    // getBoundingClientRect is post-transform; undo the stage scale so the
    // backing store matches stage pixels rather than screen pixels.
    var s = parseFloat(getComputedStyle($('stage')).getPropertyValue('--s')) || 1;
    var w = Math.round(r.width / s), h = Math.round(r.height / s);
    if (w !== _cvDim.w || h !== _cvDim.h) {
      _cvDim = { w: w, h: h };
      cv.width  = w * dpr;
      cv.height = h * dpr;
      cx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    return _cvDim;
  }

  function drawChart() {
    var dim = sizeCanvas(), W = dim.w, H = dim.h;
    if (!W || !H) return;
    var ML = 0, MR = 112, MT = 26, MB = 24;   // MR holds the live value tag
    cx.clearRect(0, 0, W, H);

    var pts = state.pts;
    if (pts.length < 2) {
      cx.fillStyle = '#3a1a4a';
      cx.font = '700 15px Consolas, monospace';
      cx.textAlign = 'center';
      cx.fillText('AWAITING NAV SNAPSHOTS', W / 2, H / 2);
      return;
    }

    var now = pts[pts.length - 1].t;
    var t0 = now - WIN_MS;
    var win = pts.filter(function(p) { return p.t >= t0; });
    if (win.length < 2) win = pts.slice(-2);

    var vs = win.map(function(p) { return p.v; });
    var lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs);
    var base = S.starting_capital;
    // Keep the baseline on screen when it's close — it's the reference the
    // whole number means anything against.
    if (base > lo * 0.985 && base < hi * 1.015) { lo = Math.min(lo, base); hi = Math.max(hi, base); }
    var pad = (hi - lo) * 0.22 || Math.max(hi * 0.002, 1);
    lo -= pad; hi += pad;

    var x0 = win[0].t, x1 = win[win.length - 1].t;
    var X = function(t) { return ML + (t - x0) / Math.max(1, x1 - x0) * (W - ML - MR); };
    var Y = function(v) { return MT + (hi - v) / Math.max(1e-9, hi - lo) * (H - MT - MB); };

    // Grid
    cx.strokeStyle = 'rgba(42,0,61,0.7)';
    cx.lineWidth = 1;
    for (var i = 0; i <= 3; i++) {
      var gy = MT + (H - MT - MB) * i / 3;
      cx.beginPath(); cx.moveTo(ML, gy); cx.lineTo(W - MR, gy); cx.stroke();
    }

    // Baseline
    if (base >= lo && base <= hi) {
      cx.strokeStyle = 'rgba(148,0,255,0.55)';
      cx.setLineDash([5, 5]);
      cx.beginPath(); cx.moveTo(ML, Y(base)); cx.lineTo(W - MR, Y(base)); cx.stroke();
      cx.setLineDash([]);
      cx.fillStyle = 'rgba(148,0,255,0.8)';
      cx.font = '700 11px Consolas, monospace';
      cx.textAlign = 'left';
      cx.fillText('START', W - MR + 8, Y(base) + 4);
    }

    var up = state.dayPnlPct >= 0;
    var col = up ? '#00ff9d' : '#ff3366';
    var rgb = up ? '0,255,157' : '255,51,102';

    // Area
    var grad = cx.createLinearGradient(0, MT, 0, H - MB);
    grad.addColorStop(0, 'rgba(' + rgb + ',0.26)');
    grad.addColorStop(1, 'rgba(' + rgb + ',0)');
    cx.beginPath();
    cx.moveTo(X(win[0].t), H - MB);
    win.forEach(function(p) { cx.lineTo(X(p.t), Y(p.v)); });
    cx.lineTo(X(win[win.length - 1].t), H - MB);
    cx.closePath();
    cx.fillStyle = grad; cx.fill();

    // Line + glow
    cx.beginPath();
    win.forEach(function(p, i) { i ? cx.lineTo(X(p.t), Y(p.v)) : cx.moveTo(X(p.t), Y(p.v)); });
    cx.strokeStyle = col;
    cx.lineWidth = 2.5;
    cx.lineJoin = cx.lineCap = 'round';
    cx.shadowColor = col; cx.shadowBlur = 16;
    cx.stroke();
    cx.shadowBlur = 0;

    // Live head
    var last = win[win.length - 1];
    var hx = X(last.t), hy = Y(last.v);
    var pulse = 0.5 + 0.5 * Math.sin(Date.now() / 380);
    cx.beginPath(); cx.arc(hx, hy, 4 + pulse * 3, 0, 7);
    cx.fillStyle = 'rgba(' + rgb + ',' + (0.28 - pulse * 0.13) + ')'; cx.fill();
    cx.beginPath(); cx.arc(hx, hy, 3.5, 0, 7);
    cx.fillStyle = col; cx.shadowColor = col; cx.shadowBlur = 12; cx.fill();
    cx.shadowBlur = 0;

    // Value tag
    cx.fillStyle = col;
    cx.font = '700 17px Consolas, monospace';
    cx.textAlign = 'left';
    cx.fillText(usd(last.v), W - MR + 8, hy + 6);

    // Time axis — two labels. More is noise at this width.
    cx.fillStyle = '#3a1a4a';
    cx.font = '700 11px Consolas, monospace';
    var hhmm = function(ms) {
      return new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York', hour12: false,
        hour: '2-digit', minute: '2-digit' }).format(new Date(ms));
    };
    cx.textAlign = 'left';  cx.fillText(hhmm(x0), ML, H - 10);
    cx.textAlign = 'right'; cx.fillText(hhmm(x1), W - MR, H - 10);

    $('chart-meta').textContent = win.length + ' PTS · ' + hhmm(x0) + '–' + hhmm(x1) + ' ET';
  }

  // ── Positions ────────────────────────────────────────────────────────────
  function renderPositions() {
    var list = $('pos-list');
    var ps = (S.positions || []).slice()
      .sort(function(a, b) { return (b.value || 0) - (a.value || 0); })
      .slice(0, 5);   // top-5 config — the stage has room for exactly this

    if (!ps.length) {
      list.innerHTML = '<div class="pos-empty">NO OPEN POSITIONS</div>';
      $('pos-meta').textContent = '—';
      return;
    }

    var gross = ps.reduce(function(s, p) { return s + (p.value || 0); }, 0);
    $('pos-meta').textContent = ps.length + ' OPEN · ' + usd(gross) + ' GROSS';

    list.innerHTML = ps.map(function(p) {
      var pc = Number(p.entry_pnl_pct || 0);
      var col = pc > 0.001 ? '#00ff9d' : (pc < -0.001 ? '#ff3366' : '#8060a0');

      // Clamp travel to the stop/target band from risk_limits: -5% stop is the
      // left wall, +10% target the right, entry dead centre.
      var frac = Math.max(-1, Math.min(1, pc >= 0 ? pc / 10 : pc / 5));
      var half = 50, w = Math.abs(frac) * half;
      var left = frac >= 0 ? half : half - w;

      return '' +
        '<div class="pos-row">' +
          '<div class="pos-sym">' + p.sym + '</div>' +
          '<div class="pos-qty">' + (p.qty || 0) + ' · ' + usd(p.value) + '</div>' +
          '<div class="pos-bar">' +
            '<i style="left:' + left + '%;width:' + w + '%;background:' + col + '"></i>' +
            '<span class="tick" style="left:50%"></span>' +
          '</div>' +
          '<div class="pos-pct ' + dirClass(pc) + '">' + pct(pc) + '</div>' +
        '</div>';
    }).join('');
  }

  // The feed and footer ticker are gone — they sat in the bottom 380, which
  // YouTube's chat occupies permanently. pollEvents() below still runs: fills
  // drive the Blob's ALERT mood even though nothing lists them any more.

  // ── Live poll ────────────────────────────────────────────────────────────
  // Same 10s cadence and same table as home_nav.js. Streamlit is never asked
  // to rerun; the stage mutates in place.
  function pollNav() {
    var since = new Date(Date.now() - 2 * 24 * 3600000).toISOString();
    fetch(S.supa.url + '/rest/v1/nav_snapshots?select=recorded_at,nav&recorded_at=gte.' +
          since + '&order=recorded_at.asc&limit=3000',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        var pts = rows.map(function(r) {
          var t = r.recorded_at;
          if (t && t.slice(-1) !== 'Z' && t.indexOf('+') < 0) t += 'Z';
          return { t: new Date(t).getTime(), v: Number(r.nav) };
        }).filter(function(p) { return !isNaN(p.t) && !isNaN(p.v); });
        if (!pts.length) return;

        var prevNav = state.nav;
        state.pts = pts;
        state.nav = pts[pts.length - 1].v;

        // Day P&L rebased off the session's first snapshot. Falls back to the
        // server-rendered figure overnight, when there's no session to rebase.
        var open = pts.find(function(p) { return isSameEtDay(p.t, Date.now()); });
        if (open) {
          state.dayPnl = state.nav - open.v;
          state.dayPnlPct = open.v ? state.dayPnl / open.v * 100 : 0;
        }

        if (Math.abs(state.nav - prevNav) > 0.005) {
          if (state.dayPnlPct >= 1.0 && state.nav > prevNav) blob.setMood('HAPPY', 14);
        }
        renderHero();
      })
      .catch(function() { /* stream stays up on a bad poll; next tick retries */ });
  }

  function isSameEtDay(a, b) {
    var f = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York' });
    return f.format(new Date(a)) === f.format(new Date(b));
  }

  // New fills wake the Blob up. This is the ALERT hook from BLOB.md.
  function pollEvents() {
    var since = new Date(Date.now() - 3 * 3600000).toISOString();
    fetch(S.supa.url + '/rest/v1/pipeline_events?select=event_type,symbol,message,detail,recorded_at' +
          '&recorded_at=gte.' + since + '&order=recorded_at.desc&limit=20',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        var newest = rows[0].recorded_at;
        if (state.seenEvTs && newest === state.seenEvTs) return;
        var firstRun = !state.seenEvTs;
        state.seenEvTs = newest;

        // Don't fire a mood on the first hydration — that history is old.
        if (!firstRun && ['ENTRY', 'EXIT', 'TRADE'].indexOf(rows[0].event_type) >= 0) {
          blob.setMood('ALERT', 12);
        }
      })
      .catch(function() {});
  }

  // ── Boot ─────────────────────────────────────────────────────────────────
  renderHero();
  renderPositions();
  drawChart();

  // The chart head pulses, so it needs its own repaint clock. 20fps is plenty
  // for a glow and keeps an unattended stream from cooking a CPU for hours.
  setInterval(drawChart, 50);
  setInterval(syncBlobMood, 1000);
  setInterval(pollNav, 10000);
  setInterval(pollEvents, 10000);
  window.addEventListener('resize', drawChart);
  pollNav();
  pollEvents();
})();
