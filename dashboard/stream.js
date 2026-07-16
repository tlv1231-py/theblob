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

  // ── Background — the room he broadcasts from ─────────────────────────────
  // Atmosphere only: it fills the reserved bands and could be cropped to the
  // safe box with zero loss of meaning. It reacts to the same feed the Blob
  // does, so the scene is watching the same trades the viewer is.
  var bg = TNDBg.create($('bgCanvas'), { fps: 24 });
  bg.start();

  function syncBlobMood() {
    // Transient moods own the character until they decay; don't stomp them.
    var m = blob.getMood();
    if (m === 'ALERT' || m === 'HAPPY' || m === 'SCARED') return;

    // He sleeps when THE SYSTEM is idle, not when NYSE is shut. The crypto
    // strategy trades ~9x/min around the clock; gating on market hours had him
    // asleep through 1,056 trades in two hours, which is the opposite of the
    // point. Equity hours are shown in the status strip, not in his eyelids.
    if (!isSystemLive()) { blob.setMood('SLEEP'); return; }

    // Drawdown against the real configured limit, not a magic number.
    // SCARED is reserved for genuine risk: the crypto book closes nearly every
    // position at a small timeout loss, so reacting to any loss would leave him
    // permanently terrified and the state would stop meaning anything.
    var ddLimit = S.limits.daily_dd * 100;
    if (state.dayPnlPct <= -ddLimit * 0.75) { blob.setMood('SCARED'); return; }
    if (state.dayPnlPct >= 1.0)             { blob.setMood('SMUG');   return; }
    blob.setMood('IDLE');
  }

  // Alive = the pipeline emitted anything recently. UPDATE ("scan complete")
  // lands every ~10s while the engine runs, so a 90s window is a generous
  // heartbeat that still notices a genuinely stopped pipeline.
  function isSystemLive() {
    return state.lastEventMs > 0 && (Date.now() - state.lastEventMs) < 90000;
  }

  // Show what he just reacted to. Without this a mood change is ambiguous —
  // the viewer sees him twitch and cannot tell why, which reads as random
  // rather than responsive.
  function flashTrade(dir, sym, pnl) {
    var el = $('trade-flash');
    if (!el) return;
    var win = pnl != null && pnl > 0;
    el.textContent = (dir === 'ENTER' ? '▲ ENTER ' : '✗ EXIT ') + sym +
                     (pnl != null ? '  ' + (win ? '+' : '−') + '$' + Math.abs(pnl).toFixed(2) : '');
    el.className = 'trade-flash show ' + (dir === 'ENTER' ? 'enter' : (win ? 'win' : 'loss'));
    clearTimeout(el._t);
    el._t = setTimeout(function() { el.className = 'trade-flash'; }, 2600);
  }

  // ── State ────────────────────────────────────────────────────────────────
  var state = {
    nav:        S.nav,
    dayPnl:     S.day_pnl,
    dayPnlPct:  S.day_pnl_pct,
    pts:        (S.nav_pts || []).map(function(p) {
                  return { t: new Date(p.t).getTime(), v: Number(p.v) };
                }).filter(function(p) { return !isNaN(p.t) && !isNaN(p.v); }),
    seenEvTs:    null,
    lastEventMs: 0     // heartbeat — drives isSystemLive(), see syncBlobMood
  };

  // ── The number ───────────────────────────────────────────────────────────
  // Ported from the Command Center's wallet slot (home_nav.js _animateWallet /
  // _updateWalletSlot). Two behaviours, both load-bearing:
  //
  //   ROLL. The value never jumps — it eases from whatever is on screen to the
  //   new figure over 700ms. On a 24/7 stream this is the difference between a
  //   number that looks live and one that looks like a screenshot that
  //   occasionally changes.
  //
  //   FLASH SCALED TO SIGNIFICANCE. Colour intensity is measured against the
  //   MEDIAN of the last 30 moves, not a fixed threshold — so a routine tick
  //   glows faintly and a genuinely big move blazes. A fixed threshold would
  //   either flash constantly (meaningless) or almost never (invisible).
  var _navTimer = null, _navShown = null, _navPrev = null;
  var _navMags = [], _navFlashT = null;

  // setInterval, NOT requestAnimationFrame — even though the Command Center's
  // version uses rAF. Measured: rAF never fires inside this component iframe at
  // all, so the ported code left the number frozen at "$—" while every
  // textContent-driven element rendered fine. rAF is throttled or suspended
  // whenever the page isn't considered visible, which is exactly what a
  // headless Chromium on a virtual display looks like — so this would have been
  // dead on the actual capture even if it had worked here. This is the same
  // reasoning BLOB.md gives for the Blob's 10fps setInterval; timers survive
  // conditions rAF does not, and this page's whole job is to run unwatched.
  function animateNav(toVal) {
    var el = $('hero-nav');
    if (!el) return;
    var from = _navShown !== null ? _navShown : toVal;
    clearInterval(_navTimer);
    var t0 = Date.now(), DUR = 700, STEP = 33;   // ~30fps: one textContent write
    _navTimer = setInterval(function() {
      var t = Math.min((Date.now() - t0) / DUR, 1);
      t = 1 - Math.pow(1 - t, 3);                 // ease-out cubic
      var cur = from + (toVal - from) * t;
      _navShown = cur;
      el.textContent = '$' + cur.toLocaleString('en-US',
        { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (t >= 1) { _navShown = toVal; clearInterval(_navTimer); _navTimer = null; }
    }, STEP);
  }

  function updateNav(nav) {
    if (!nav) return;
    var el = $('hero-nav');
    if (el && _navPrev !== null && nav !== _navPrev) {
      var delta = nav - _navPrev, mag = Math.abs(delta);
      if (mag > 0.01) {
        _navMags.push(mag);
        if (_navMags.length > 30) _navMags.shift();
        // Floor at 0.15 so even a tiny tick registers; 1.0 at a median-or-bigger move.
        var intensity = 0.15;
        if (_navMags.length >= 3) {
          var sorted = _navMags.slice().sort(function(a, b) { return a - b; });
          var median = sorted[Math.floor(sorted.length / 2)];
          if (median > 0) intensity = Math.min(1, 0.15 + (mag / median) * 0.85);
        }
        var rgb = delta > 0 ? '0,255,157' : '255,51,102';
        var glow = 'rgba(' + rgb + ',' + (intensity * 0.7) + ')';
        el.style.color = 'rgba(' + rgb + ',' + intensity + ')';
        el.style.textShadow = '0 0 24px ' + glow + ', 0 0 8px ' + glow;
        clearTimeout(_navFlashT);
        _navFlashT = setTimeout(function() {
          el.style.color = ''; el.style.textShadow = '';   // back to the CSS stack
        }, 750);                                            // matches the roll
      }
    }
    _navPrev = nav;
    animateNav(nav);
  }

  // ── NAV block ────────────────────────────────────────────────────────────
  function renderHero() {
    updateNav(state.nav);
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

  // The NAV chart is GONE — "he's the streamer, not the charts". It also
  // freed a 20fps canvas repaint, which is the budget the animated
  // background now spends. state.pts is still maintained: the NAV number and
  // day P&L are derived from it, they just aren't plotted any more.

  // ═══════════════════════════════════════════════════════════════════════
  // ARCADE SOUNDS
  // Square-wave WebAudio, ported from home_nav.js so both surfaces share one
  // sonic language. Synthesised rather than sampled: no asset to inline, and
  // a square wave IS the 8-bit sound.
  //
  //   acquisition -> neutral blip      (330->440, flat, no verdict)
  //   gain        -> ascending arp     (E5 G5 B5, bright)
  //   loss        -> descending bloop  (G4 Eb4 Bb3, lowpassed, muted)
  //
  // AUTOPLAY: browsers suspend AudioContext until a user gesture. An OBS
  // browser source generally autoplays, but a plain tab stays silent until
  // clicked — hence the gesture unlock below. Never assume sound is audible.
  // ═══════════════════════════════════════════════════════════════════════
  var SFX = (function() {
    var ctx = null, ready = false;
    function init() {
      if (ctx) return;
      try {
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        ctx.resume().then(function() { ready = true; }).catch(function() {});
      } catch (e) {}
    }
    // Any gesture unlocks. Harmless if it never comes (OBS won't need it).
    ['pointerdown', 'keydown', 'touchstart'].forEach(function(ev) {
      window.addEventListener(ev, function once() {
        init();
        if (ctx && ctx.state === 'suspended') ctx.resume();
        ready = true;
      }, { once: true });
    });
    init();

    function play(notes, vol, lowpass) {
      if (!ctx) return;
      if (ctx.state === 'suspended') { ctx.resume(); return; }
      try {
        notes.forEach(function(n) {
          var osc = ctx.createOscillator(), g = ctx.createGain();
          osc.type = 'square';
          osc.frequency.value = n[0];
          var t = ctx.currentTime + n[1];
          g.gain.setValueAtTime(0, t);
          g.gain.linearRampToValueAtTime(vol, t + 0.006);
          g.gain.exponentialRampToValueAtTime(0.0001, t + 0.11);
          if (lowpass) {
            var lp = ctx.createBiquadFilter();
            lp.type = 'lowpass'; lp.frequency.value = 700;
            osc.connect(lp); lp.connect(g);
          } else {
            osc.connect(g);
          }
          g.connect(ctx.destination);
          osc.start(t); osc.stop(t + 0.13);
        });
      } catch (e) {}
    }
    return {
      entry: function() { play([[330, 0], [440, 0.055]], 0.055, false); },
      win:   function() { play([[659, 0], [784, 0.07], [988, 0.14]], 0.07, false); },
      loss:  function() { play([[392, 0], [311, 0.07], [233, 0.14]], 0.055, true); },
      isReady: function() { return ready && ctx && ctx.state === 'running'; }
    };
  })();

  // ═══════════════════════════════════════════════════════════════════════
  // HOLDINGS — one board for the whole book
  // Crypto (crypto_positions, server-written) and equity (positions_data)
  // become identical cabinet slots. They differ by badge and by where their
  // live price comes from, not by living in separate widgets.
  // ═══════════════════════════════════════════════════════════════════════

  var SEGS = 16;   // meter resolution. Low on purpose: chunky reads as 8-bit.

  // Matches _TILE_BADGES in home_nav.js so a symbol carries the same glyph on
  // both surfaces. A viewer should never have to relearn the iconography.
  var BADGES = {
    momentum: '▲▲', crypto: '◈', crypto_momentum: '◈', user: '◎',
    daytrader: '⊕', reversion: '⇌', sentiment: '◉', volatility: '⚡', factor: '✦'
  };

  // CoinGecko ids — free, no auth, no key. Same map home_nav.js uses.
  var CG_MAP = {
    'BTC/USD': 'bitcoin', 'ETH/USD': 'ethereum', 'SOL/USD': 'solana',
    'AVAX/USD': 'avalanche-2', 'LINK/USD': 'chainlink', 'DOGE/USD': 'dogecoin',
    'BCH/USD': 'bitcoin-cash', 'XTZ/USD': 'tezos', 'CRV/USD': 'curve-dao-token',
    'UNI/USD': 'uniswap', 'ADA/USD': 'cardano', 'MATIC/USD': 'matic-network',
    'DOT/USD': 'polkadot'
  };
  var cgPrice = {};   // sym -> live USD price

  // Merge both books into one uniform shape. Everything downstream reads this
  // and never needs to know which table a row came from.
  function book() {
    var out = [];
    (S.positions || []).forEach(function(p) {
      out.push({
        sym: p.sym, qty: p.qty, entry: p.entry_price, price: p.price,
        stop: p.stop_price, target: p.target_price,
        strategy: p.strategy || 'momentum', isCrypto: false
      });
    });
    (S.crypto || []).forEach(function(c) {
      out.push({
        sym: c.sym, qty: c.qty, entry: c.entry_price,
        price: cgPrice[c.sym] || 0,       // live, or 0 until CoinGecko answers
        stop: c.stop_price, target: c.target_price,
        strategy: c.strategy || 'crypto', isCrypto: true
      });
    });
    return out;
  }

  function qtyStr(q) {
    var n = Number(q || 0);
    if (n >= 1000) return Math.round(n).toLocaleString('en-US');
    if (n >= 1)    return n.toFixed(2);
    return n.toFixed(4);
  }
  function priceStr(v) {
    var n = Number(v || 0);
    if (n >= 1000) return '$' + Math.round(n).toLocaleString('en-US');
    if (n >= 1)    return '$' + n.toFixed(2);
    return '$' + n.toFixed(4);
  }

  function renderPositions() {
    var list = $('pos-list');
    var ps = book().slice(0, 14);   // 2 cols x 7 rows — the board's exact size

    if (!ps.length) {
      list.innerHTML = '<div class="pos-empty">NO OPEN POSITIONS</div>';
      $('pos-meta').textContent = '—';
      return;
    }

    var known = 0, wins = 0, gross = 0;
    ps.forEach(function(p) {
      gross += (p.price || p.entry || 0) * (p.qty || 0);
      if (p.price > 0 && p.entry > 0) { known++; if (p.price > p.entry) wins++; }
    });
    $('pos-meta').textContent = wins + '/' + known + ' UP  ·  ' +
                                ps.length + ' OPEN  ·  ' + usd(gross) + ' GROSS';

    list.innerHTML = ps.map(function(p) {
      var live = p.price > 0 && p.entry > 0;
      var pc   = live ? (p.price - p.entry) / p.entry * 100 : 0;
      var abs  = live ? (p.price - p.entry) * (p.qty || 0) : 0;
      var col  = !live ? '#8060a0'
               : (pc > 0.001 ? '#00ff9d' : (pc < -0.001 ? '#ff3366' : '#8060a0'));

      // Normalise against THIS position's real stop/target band rather than a
      // fixed percentage. Crypto runs a ~0.3% stop and equity 5% — one shared
      // percentage scale would peg every crypto tile at full deflection.
      var frac = 0;
      if (live && p.stop > 0 && p.target > 0) {
        frac = p.price >= p.entry
          ? Math.min(1, (p.price - p.entry) / Math.max(1e-9, p.target - p.entry))
          : Math.max(-1, -(p.entry - p.price) / Math.max(1e-9, p.entry - p.stop));
      }
      var mid = SEGS / 2;
      var lit = Math.round(Math.abs(frac) * mid);

      var segs = '';
      for (var i = 0; i < SEGS; i++) {
        var on, tip = false;
        if (frac >= 0) { on = i >= mid && i < mid + lit;  tip = on && i === mid + lit - 1; }
        else           { on = i < mid  && i >= mid - lit; tip = on && i === mid - lit; }
        segs += '<span class="t-seg' + (on ? ' on' : '') + (tip ? ' tip' : '') +
                (i === mid ? ' entry' : '') + '"></span>';
      }

      // Alarm only on a genuine stop breach — see .tile.danger in stream.css.
      var breached = live && p.stop > 0 && p.price <= p.stop;

      return '' +
        '<div class="tile' + (breached ? ' danger' : '') + '" data-sym="' + p.sym +
             '" style="--tc:' + col + '">' +
          '<div class="t-top">' +
            '<span class="t-name">' +
              '<span class="t-badge' + (p.isCrypto ? ' crypto' : '') + '">' +
                (BADGES[p.strategy] || BADGES.momentum) + '</span>' +
              '<span class="t-sym">' + p.sym.replace('/USD', '') + '</span>' +
            '</span>' +
            '<span class="t-pct">' + (live ? pct(pc, 1) : '· ·') + '</span>' +
          '</div>' +
          '<div class="t-bot">' +
            '<span class="t-entry">' + qtyStr(p.qty) + ' @ ' + priceStr(p.entry) + '</span>' +
            '<span class="t-abs">' + (live ? signed(abs, 2) : '—') + '</span>' +
          '</div>' +
          '<div class="t-meter">' + segs + '</div>' +
        '</div>';
    }).join('');
  }

  // Live crypto marks. CoinGecko is free and unauthenticated but rate-limits
  // hard, so this stays at 15s — the tiles are a P&L read, not a tape.
  function pollCryptoPrices() {
    var syms = (S.crypto || []).map(function(c) { return c.sym; })
                 .filter(function(s) { return CG_MAP[s]; });
    if (!syms.length) return;
    var ids = syms.map(function(s) { return CG_MAP[s]; }).join(',');
    fetch('https://api.coingecko.com/api/v3/simple/price?ids=' + ids + '&vs_currencies=usd')
      .then(function(r) { return r.json(); })
      .then(function(j) {
        if (!j || typeof j !== 'object') return;
        var got = 0;
        syms.forEach(function(s) {
          var v = j[CG_MAP[s]] && j[CG_MAP[s]].usd;
          if (v) { cgPrice[s] = Number(v); got++; }
        });
        if (got) renderPositions();
      })
      .catch(function() { /* tiles fall back to '· ·' until a poll lands */ });
  }

  // The book turns over ~9x/min, so the seeded crypto list goes stale within
  // seconds. Re-read the live table whenever a trade lands rather than on a
  // timer — the event IS the invalidation signal.
  var _refreshT = 0;
  function refreshCrypto() {
    if (Date.now() - _refreshT < 2000) return;   // coalesce trade bursts
    _refreshT = Date.now();
    fetch(S.supa.url + '/rest/v1/crypto_positions?select=symbol,qty,entry_price,' +
          'stop_price,target_price,entered_at,strategy',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows)) return;
        S.crypto = rows.map(function(r) {
          return {
            sym: r.symbol, qty: Number(r.qty || 0),
            entry_price: Number(r.entry_price || 0),
            stop_price: Number(r.stop_price || 0),
            target_price: Number(r.target_price || 0),
            entered_at: r.entered_at, strategy: r.strategy || 'crypto',
            is_crypto: true
          };
        });
        renderPositions();
        spawnNewTiles();   // any slot that just arrived flies in from him
      })
      .catch(function() {});
  }

  // ═══════════════════════════════════════════════════════════════════════
  // STREAM EVENT BUS — donations, subs, raids, and simulated anything
  // Stream HQ writes to stream_events; this consumes. Only `released` rows are
  // eligible: a queued row is still cancellable and must never reach air.
  // Each row is claimed by stamping consumed_at, which is also what lets HQ
  // prove an event actually landed rather than assuming it did.
  // ═══════════════════════════════════════════════════════════════════════

  // ═══════════════════════════════════════════════════════════════════════
  // THE ANNOUNCER — Gameboy dialogue box above the Blob's head
  //
  // A QUEUE, not a swap. Donations arrive in bursts (a raid, a dono train),
  // and a burst that overwrites itself shows the viewer nothing — the one
  // moment you most need legible is the one that collides. Each event gets its
  // own beat: type it out, hold, advance, and show a depth badge so a viewer
  // knows more is coming.
  //
  // Colour follows the language already established on the board: green is
  // money, pink is identity, cyan is activity. A viewer who has learned the
  // tiles already knows how to read this.
  // ═══════════════════════════════════════════════════════════════════════
  var ANN = {
    donation:        { c: '#00ff9d', i: '♥', verb: 'DONATED' },
    superchat:       { c: '#00ff9d', i: '♥', verb: 'SUPERCHATTED' },
    supersticker:    { c: '#00ff9d', i: '♥', verb: 'SENT A STICKER' },
    bits:            { c: '#00ff9d', i: '◆', verb: 'CHEERED' },
    membership_gift: { c: '#ff00cc', i: '♦', verb: 'GIFTED' },
    subscription:    { c: '#ff00cc', i: '★', verb: 'SUBSCRIBED' },
    follow:          { c: '#00e5ff', i: '◈', verb: 'FOLLOWED' },
    raid:            { c: '#9400ff', i: '⚡', verb: 'RAIDED' },
    chat:            { c: '#8060a0', i: '·', verb: '' },
    risk_breach:     { c: '#ff3366', i: '⚠', verb: '' }
  };

  function money(p) {
    if (p.amount == null) return '';
    var n = Number(p.amount);
    return '$' + (n % 1 === 0 ? n.toFixed(0) : n.toFixed(2));
  }

  // ── The house format ─────────────────────────────────────────────────────
  //   {USER} just {ACTIONED} {AMOUNT} !!!
  //
  // One shape for every event, so the box is recognisable before it is read —
  // a returning viewer clocks "someone did a thing" from the silhouette alone
  // and only then reads who and how much. "just" keeps it present-tense; the
  // !!! is the brand, and it is on every event so its absence would read as a
  // different kind of message rather than a quieter one.
  //
  // The verb is the variable. AMOUNT is omitted where there is none rather
  // than padded with a zero — "MIKE88 just SUBSCRIBED !!!" is the whole line.
  var VERB = {
    donation:        'DONATED',
    superchat:       'SUPERCHATTED',
    supersticker:    'STICKERED',
    bits:            'CHEERED',
    membership_gift: 'GIFTED',
    subscription:    'SUBSCRIBED',
    follow:          'FOLLOWED',
    raid:            'RAIDED',
    chat:            'SAID'
  };

  function amountFor(type, p) {
    switch (type) {
      case 'donation':
      case 'superchat':
      case 'supersticker':    return money(p);
      case 'bits':            return (p.amount || 0) + ' BITS';
      case 'membership_gift': return (p.count || 1) + 'x';
      case 'raid':            return '+' + (p.viewers || 0);
      default:                return '';
    }
  }

  function headline(type, p) {
    if (type === 'risk_breach') return 'RISK BREACH — ' + (p.limit || '') + ' !!!';
    var who = (p.from || 'SOMEONE').toUpperCase();
    var verb = VERB[type] || 'DID SOMETHING';
    var amt = amountFor(type, p);
    return who + ' just ' + verb + (amt ? ' ' + amt : '') + ' !!!';
  }

  var annQ = [], annBusy = false, annTypeT = null, annHoldT = null;

  function annPush(type, payload) {
    if (!ANN[type]) return;
    annQ.push({ type: type, p: payload || {} });
    if (annQ.length > 6) annQ.splice(0, annQ.length - 6);  // drop the oldest
    if (!annBusy) annNext();
    annBadge();
  }

  function annBadge() {
    var b = $('ev-badge');
    if (!b) return;
    var n = annQ.length;
    b.textContent = n > 0 ? '+' + n + ' MORE' : '';
    b.className = 'ev-badge' + (n > 0 ? ' on' : '');
  }

  function annNext() {
    var lcd = $('ev-lcd');
    if (!lcd) return;
    if (!annQ.length) {
      annBusy = false;
      lcd.classList.add('idle');
      $('ev-more').className = 'ev-more';
      annBadge();
      return;
    }
    annBusy = true;
    var ev = annQ.shift();
    annBadge();

    var cfg = ANN[ev.type];
    lcd.classList.remove('idle');
    lcd.style.setProperty('--ev-c', cfg.c);
    $('ev-icon').textContent = cfg.i;
    $('ev-more').className = 'ev-more';

    // Money hits the panel itself, not just the text.
    if (cfg.c === '#00ff9d') {
      lcd.classList.remove('pop'); void lcd.offsetWidth; lcd.classList.add('pop');
    }

    var head = headline(ev.type, ev.p);
    var msg  = (ev.p.message || '').slice(0, 46);
    var hEl = $('ev-head'), mEl = $('ev-msg');
    hEl.textContent = ''; mEl.textContent = '';

    // Typewriter. ~26ms/char is DMG cadence — fast enough not to stall a
    // stream, slow enough that the reveal reads as a machine speaking.
    var i = 0;
    clearInterval(annTypeT); clearTimeout(annHoldT);
    annTypeT = setInterval(function() {
      if (i < head.length) {
        hEl.textContent += head[i++];
      } else if (i - head.length < msg.length) {
        mEl.textContent += msg[i++ - head.length];
      } else {
        clearInterval(annTypeT);
        $('ev-more').className = 'ev-more on';
        // Hold longer when nothing is waiting, so a lone event can be read;
        // shorter during a burst so the queue drains.
        annHoldT = setTimeout(annNext, annQ.length ? 1400 : 3200);
      }
    }, 26);
  }

  // Money reads as a win regardless of size; the Blob's amplitude carries the
  // size. Non-money social events are ALERT — real, but not a verdict.
  var EVENT_MOOD = {
    donation:        { mood: 'HAPPY', sfx: 'win',   label: '♥ DONO' },
    superchat:       { mood: 'HAPPY', sfx: 'win',   label: '♥ SUPERCHAT' },
    supersticker:    { mood: 'HAPPY', sfx: 'win',   label: '♥ STICKER' },
    membership_gift: { mood: 'HAPPY', sfx: 'win',   label: '♥ GIFTED' },
    bits:            { mood: 'HAPPY', sfx: 'win',   label: '♥ BITS' },
    subscription:    { mood: 'ALERT', sfx: 'entry', label: '★ SUB' },
    follow:          { mood: 'ALERT', sfx: 'entry', label: '★ FOLLOW' },
    raid:            { mood: 'ALERT', sfx: 'entry', label: '★ RAID' },
    chat:            { mood: 'ALERT', sfx: null,    label: '· CHAT' },
    trade_enter:     { mood: 'ALERT', sfx: 'entry', label: '▲ ENTER' },
    trade_exit:      { mood: null,    sfx: null,    label: '✗ EXIT' },
    risk_breach:     { mood: 'SCARED', sfx: 'loss', label: '⚠ RISK' }
  };

  function applyStreamEvent(ev) {
    var p = ev.payload || {};
    var cfg = EVENT_MOOD[ev.event_type];
    if (!cfg) return;

    // trade_exit's verdict comes from its pnl, not its type.
    var mood = cfg.mood, sfx = cfg.sfx;
    if (ev.event_type === 'trade_exit') {
      var win = Number(p.pnl || 0) > 0;
      mood = win ? 'HAPPY' : 'ALERT';
      sfx  = win ? 'win' : 'loss';
    }

    if (mood) blob.setMood(mood, mood === 'HAPPY' ? 26 : 18);
    if (sfx && SFX[sfx]) SFX[sfx]();
    // Money gets a bigger, brighter wave than a trade — a viewer paying is the
    // loudest thing that happens on this stream.
    bg.pulse(cfg.c === '#00ff9d' ? 'money' : (sfx === 'loss' ? 'loss' : 'enter'), 0.30);

    // Trades speak through the flash under his chin; stream events get the
    // announcer over his head. Keeping the two channels separate is what lets
    // a viewer tell "the bot did something" from "a person did something".
    if (ev.event_type === 'trade_enter' || ev.event_type === 'trade_exit') {
      flashTrade(ev.event_type === 'trade_enter' ? 'ENTER' : 'EXIT',
                 p.symbol || '', p.pnl != null ? Number(p.pnl) : null);
      if (p.symbol) hitTile(p.symbol);
    } else {
      annPush(ev.event_type, p);
    }
    $('blob-mood').textContent = blob.getMood();
  }

  // BROADCAST, not a work queue. Every renderer shows every event.
  //
  // This used to claim rows (consumed_at IS NULL + PATCH to consumed), which
  // made the first poller win and every other renderer see nothing. That is
  // wrong for a stream: the encoder's headless Chromium and the operator's own
  // browser are BOTH rendering this page, and they would race — each event
  // landing on exactly one of them, at random. A stream event must go to air
  // everywhere. Each renderer now tracks its own high-water mark instead.
  //
  // release_at is the gate, not the status: a queued event fires ON ITS OWN
  // when the countdown expires. HQ's "Release" simply pulls release_at to now.
  // Cancelled rows are excluded and never air.
  var lastEvId = Number(S.last_event_id || 0);

  function pollStreamEvents() {
    var now = new Date().toISOString();
    fetch(S.supa.url + '/rest/v1/stream_events?select=id,event_type,source,payload' +
          '&status=in.(queued,released)' +
          '&release_at=lte.' + encodeURIComponent(now) +
          '&id=gt.' + lastEvId +
          '&order=id.asc&limit=10',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        rows.forEach(function(ev, i) {
          if (ev.id > lastEvId) lastEvId = ev.id;
          // Stagger a burst so ten events don't collapse into one frame. The
          // announcer queues them anyway; this keeps the Blob's moods readable.
          setTimeout(function() { applyStreamEvent(ev); }, i * 900);

          // Stamp delivery for HQ's benefit only — proof it aired, NOT a lock.
          // consumed_at ONLY. Writing status here would be a claim in disguise:
          // the read query filters on status, so flipping it to 'consumed'
          // would yank the row out of every OTHER renderer's query and we would
          // be right back to first-poller-wins. Status is intent (queued /
          // cancelled); consumed_at is the fact that it reached air.
          fetch(S.supa.url + '/rest/v1/stream_events?id=eq.' + ev.id +
                '&consumed_at=is.null', {
            method: 'PATCH',
            headers: {
              apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key,
              'Content-Type': 'application/json', Prefer: 'return=minimal'
            },
            body: JSON.stringify({ consumed_at: new Date().toISOString() })
          }).catch(function() {});
        });
      })
      .catch(function() {});
  }

  // TEMP: the YouTube filter's runtime switch. Stream HQ writes
  // strategy_params.yt_overlay; this applies it without a reload, which is the
  // whole point — HQ and this page are different browsers, so a server-side
  // gate could only take effect on refresh. Remove alongside yt_overlay.js.
  function pollYtOverlay() {
    if (!window._ytToggle) return;
    fetch(S.supa.url + '/rest/v1/strategy_params?strategy=eq.stream' +
          '&param=eq.yt_overlay&select=value',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows)) return;
        // No row means never configured — keep the server-rendered default
        // rather than guessing.
        if (!rows.length) return;
        window._ytToggle(rows[0].value !== '0');
      })
      .catch(function() {});
  }

  // Heartbeat. This is the ONLY way to catch the failure that kills this setup:
  // Streamlit drops the idle websocket, the page freezes, and the encoder keeps
  // pushing a dead screenshot to YouTube for hours. Nothing outside the render
  // can tell — so the render reports on itself.
  var _beats = 0;
  function beat() {
    _beats++;
    fetch(S.supa.url + '/rest/v1/stream_health', {
      method: 'POST',
      headers: {
        apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key,
        'Content-Type': 'application/json', Prefer: 'return=minimal'
      },
      body: JSON.stringify({
        component: 'stream_page',
        status: isSystemLive() ? 'ok' : 'degraded',
        detail: {
          beats: _beats,
          nav: Math.round(state.nav),
          mood: blob.getMood(),
          tiles: document.querySelectorAll('.tile').length,
          audio: SFX.isReady() ? 'on' : 'blocked'
        },
        recorded_at: new Date().toISOString()
      })
    }).catch(function() {});
  }

  // The slot that just traded acknowledges it, so a fill is legible on the
  // board and not only on the Blob.
  function hitTile(sym) {
    var el = document.querySelector('.tile[data-sym="' + sym + '"]');
    if (!el) return;
    el.classList.remove('hit');
    void el.offsetWidth;          // reflow so the animation can retrigger
    el.classList.add('hit');
  }

  // ── Terminal strips ──────────────────────────────────────────────────────
  // A clone of the Command Center's feed, parked in the reserved bands where
  // YouTube will cover half of it. That is fine and intended: this is texture,
  // not a readout. It is fed from the pipeline_events poll that already runs
  // for the Blob's moods, so it adds zero queries.
  var termSeen = null, termLines = [];
  var TERM_MAX = 9;

  function termClass(msg, type) {
    if (type !== 'TRADE') return 'tl-sys';
    if ((msg || '').indexOf('ENTER') >= 0) return 'tl-enter';
    var m = (msg || '').match(/pnl\s+([+-]?[\d.]+)/);
    return (m && parseFloat(m[1]) > 0) ? 'tl-win' : 'tl-loss';
  }

  // Strip the engine's own glyphs and padding — at this size and opacity the
  // line has to survive being read in peripheral vision.
  function termText(r) {
    var m = (r.message || '').replace(/^[▲✗✓▸]\s*/, '');
    return m.length > 62 ? m.slice(0, 62) + '…' : m;
  }

  function pushTerm(rows) {
    rows.forEach(function(r) {
      termLines.unshift({
        t: new Date(r.recorded_at + (r.recorded_at.slice(-1) === 'Z' ? '' : 'Z')),
        cls: termClass(r.message, r.event_type),
        tag: r.event_type === 'TRADE' ? 'TRD' : 'SYS',
        sym: r.symbol || '',
        msg: termText(r)
      });
    });
    if (termLines.length > TERM_MAX * 2) termLines.length = TERM_MAX * 2;
    renderTerm();
  }

  function renderTerm() {
    var hhmm = function(d) {
      return isNaN(d.getTime()) ? '--:--:--' : new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York', hour12: false,
        hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(d);
    };
    var html = function(list) {
      return list.map(function(l) {
        return '<div class="term-line"><span class="tl-t">' + hhmm(l.t) + '</span>' +
               '<span class="tl-tag ' + l.cls + '">' + l.tag + '</span>' +
               (l.sym ? '<span class="tl-sym">' + l.sym + '</span>' : '') +
               '<span class="' + l.cls + '">' + l.msg + '</span></div>';
      }).join('');
    };
    // Two strips, different slices — top and bottom are never the same text,
    // so a viewer who notices both sees a feed, not a mirror.
    var top = $('term-top'), bot = $('term-bot');
    if (top) top.innerHTML = html(termLines.slice(0, TERM_MAX));
    if (bot) bot.innerHTML = html(termLines.slice(TERM_MAX, TERM_MAX * 2));
  }

  // ── Agency ───────────────────────────────────────────────────────────────
  // Making the Blob look like he is DOING this rather than reacting to it.
  // The whole trick is sequence: he moves first, the board answers ~220ms
  // later. Same events, same data — but cause then effect, instead of two
  // symptoms firing at once with the cause invisible.

  var seenSyms = {};   // symbol -> true, so a re-render can tell new from old

  function blobCenter() {
    var c = $('blobCanvas');
    if (!c) return null;
    var r = c.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  // Fly every newly-arrived tile in from his position.
  function spawnNewTiles() {
    var origin = blobCenter();
    if (!origin) return;
    document.querySelectorAll('.tile').forEach(function(el) {
      var sym = el.getAttribute('data-sym');
      if (!sym || seenSyms[sym]) return;
      seenSyms[sym] = true;
      var r = el.getBoundingClientRect();
      // Offset from the tile's resting slot back to him — quantized to 4px so
      // the flight lands on the same grid the rest of the art lives on.
      var dx = Math.round((origin.x - (r.left + r.width / 2)) / 4) * 4;
      var dy = Math.round((origin.y - (r.top + r.height / 2)) / 4) * 4;
      el.style.setProperty('--fx', dx + 'px');
      el.style.setProperty('--fy', dy + 'px');
      el.classList.remove('spawn');
      void el.offsetWidth;
      el.classList.add('spawn');
    });
    // Forget symbols that left, so a re-entry flies in again rather than
    // silently appearing.
    var live = {};
    document.querySelectorAll('.tile').forEach(function(el) {
      live[el.getAttribute('data-sym')] = true;
    });
    Object.keys(seenSyms).forEach(function(s) { if (!live[s]) delete seenSyms[s]; });
  }

  // Glance toward a symbol's slot. -1 hard left .. +1 hard right, measured
  // against his own centre so it works whatever the grid does.
  function glanceAt(sym) {
    var el = document.querySelector('.tile[data-sym="' + sym + '"]');
    var origin = blobCenter();
    if (!el || !origin) return;
    var r = el.getBoundingClientRect();
    var dx = (r.left + r.width / 2 - origin.x) / (window.innerWidth / 2 || 1);
    blob.glance(Math.max(-1, Math.min(1, dx * 2)), 16);
  }

  // The feed and footer ticker are gone — they sat in the bottom 380, which
  // YouTube's chat occupies permanently. pollEvents() below still runs: fills
  // drive the Blob's ALERT mood even though nothing lists them any more.

  // ── Live poll ────────────────────────────────────────────────────────────
  // Same 10s cadence and same table as home_nav.js. Streamlit is never asked
  // to rerun; the stage mutates in place.
  // pollNav() is GONE — deliberately. It read nav_snapshots with
  // `order=recorded_at.asc&limit=3000`, which truncates from the WRONG END:
  // 4,325 rows existed in its 2-day window, so it fetched the OLDEST 3,000 and
  // treated the newest of those — a value hours old — as "now". That is why the
  // headline NAV sat frozen. Rather than fix the ordering, the source itself is
  // wrong: nav_snapshots is browser-written with no account column and two
  // books interleave into it. NAV now rides the engine's UPDATE stream inside
  // pollEvents, which is server-written, single-book, and already being fetched.

  function isSameEtDay(a, b) {
    var f = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York' });
    return f.format(new Date(a)) === f.format(new Date(b));
  }

  // ── Trade reactions — the whole point of the page ────────────────────────
  // pipeline_events only ever carries two types: TRADE and UPDATE. The engine
  // fires ~9 trades/min around the clock, and UPDATE ("scan complete") lands
  // every ~10s.
  //
  // The bug this replaces: it read ONLY rows[0]. An UPDATE is almost always the
  // newest row, so the type check saw 'UPDATE', never matched, and the Blob
  // reacted to essentially none of 1,056 trades in two hours. Every new row
  // must be scanned, not just the top one.
  //
  // Message shapes (parsed below):
  //   ▲ ENTER LONG BCH/USD @ $222.4728 · stop $221.8053
  //   ✗ EXIT LONG LINK/USD @ $8.3882 · pnl -0.5926 · timeout   [detail: daily_pnl=-1.67]
  //   ▸ scan complete · NAV $22,202.35 · 9 open                [detail: positions=9]

  function parseTrade(msg) {
    if (!msg) return null;
    if (msg.indexOf('ENTER') >= 0) return { dir: 'ENTER', pnl: null };
    if (msg.indexOf('EXIT') >= 0) {
      var m = msg.match(/pnl\s+(-?[\d.]+)/);
      return { dir: 'EXIT', pnl: m ? parseFloat(m[1]) : null };
    }
    return null;
  }

  function pollEvents() {
    var since = new Date(Date.now() - 10 * 60000).toISOString();
    fetch(S.supa.url + '/rest/v1/pipeline_events?select=event_type,symbol,message,detail,recorded_at' +
          '&recorded_at=gte.' + since + '&order=recorded_at.desc&limit=60',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) return;

        state.lastEventMs = Date.now();   // heartbeat regardless of type

        // ── Live NAV — from the engine's own UPDATE stream ────────────────
        // Deliberately NOT nav_snapshots. That table is browser-written with no
        // account column, so two books interleave into it (~$22.1k and ~$25.3k
        // rows seconds apart) and any chart of it sawtooths between portfolios.
        // These UPDATE rows are server-written from one book, every ~10s.
        var navPts = [];
        for (var k = rows.length - 1; k >= 0; k--) {
          if (rows[k].event_type !== 'UPDATE') continue;
          var nm = (rows[k].message || '').match(/NAV \$([\d,]+\.?\d*)/);
          if (!nm) continue;
          var ts = rows[k].recorded_at;
          if (ts && ts.slice(-1) !== 'Z' && ts.indexOf('+') < 0) ts += 'Z';
          navPts.push({ t: new Date(ts).getTime(), v: parseFloat(nm[1].replace(/,/g, '')) });
        }
        if (navPts.length) {
          // Merge into the seeded series, keeping it ascending and de-duped.
          var cutoff = navPts[0].t;
          state.pts = state.pts.filter(function(p) { return p.t < cutoff; }).concat(navPts);
          state.nav = navPts[navPts.length - 1].v;
          var openPt = state.pts.find(function(p) { return isSameEtDay(p.t, Date.now()); });
          if (openPt) {
            state.dayPnl = state.nav - openPt.v;
            state.dayPnlPct = openPt.v ? state.dayPnl / openPt.v * 100 : 0;
          }
          renderHero();
        }

        var newest = rows[0].recorded_at;
        var firstRun = !state.seenEvTs;
        if (!firstRun && newest === state.seenEvTs) return;

        // Everything newer than the last poll, oldest→newest.
        var fresh = (firstRun ? [] : rows.filter(function(r) {
          return r.recorded_at > state.seenEvTs;
        })).reverse();
        state.seenEvTs = newest;

        // Terminal strips take everything, trades and scans alike — they are
        // the room's ambient chatter, not a curated highlight reel.
        if (firstRun) pushTerm(rows.slice(0, TERM_MAX * 2).reverse());
        else if (fresh.length) pushTerm(fresh);

        // daily_pnl rides on every EXIT detail — a far fresher continuous
        // signal than the 10s nav_snapshots poll, so feed it to his shape.
        for (var i = rows.length - 1; i >= 0; i--) {
          var dm = (rows[i].detail || '').match(/daily_pnl=(-?[\d.]+)/);
          if (dm) { blob.setPnl(parseFloat(dm[1])); break; }
        }

        if (firstRun) return;   // hydration history is old — don't react to it

        // React to the most significant thing that happened, not the last.
        // Priority: a real win > an entry > an exit. Losses do NOT scare him
        // here: the book times out at ~-$0.50 constantly, and a permanently
        // terrified Blob is a broken signal. Real risk reaches him through
        // syncBlobMood's drawdown check instead.
        var best = null;
        fresh.forEach(function(r) {
          if (r.event_type !== 'TRADE') return;
          var t = parseTrade(r.message);
          if (!t) return;
          t.sym = r.symbol || '';
          var rank = (t.dir === 'EXIT' && t.pnl > 0) ? 3 : (t.dir === 'ENTER' ? 2 : 1);
          if (!best || rank >= best.rank) { t.rank = rank; best = t; }
        });
        if (!best) return;

        // ── He acts FIRST ────────────────────────────────────────────────
        // Everything below is the cause. The board is not touched yet.
        if (best.rank === 3)      blob.setMood('HAPPY', 22);   // ~2.2s at 10fps
        else if (best.rank === 2) blob.setMood('ALERT', 18);
        else                      blob.setMood('ALERT', 12);
        glanceAt(best.sym);                    // looks at the slot he's about to work
        flashTrade(best.dir, best.sym, best.pnl);
        $('blob-mood').textContent = blob.getMood();

        // Sound follows the verdict, not the event: acquisitions are neutral
        // because buying is not yet good or bad news.
        var verdict = best.dir === 'ENTER' ? 'enter' : (best.pnl > 0 ? 'win' : 'loss');
        if (verdict === 'enter')     SFX.entry();
        else if (verdict === 'win')  SFX.win();
        else                         SFX.loss();
        // The room answers too — a shockwave from behind him, same verdict.
        bg.pulse(verdict, 0.42);

        // ── ...and the board answers ─────────────────────────────────────
        // 220ms is the whole illusion. Fire this on the same frame and the eye
        // reads two simultaneous symptoms of an unseen cause; delay it and the
        // Blob becomes the cause. Long enough to register as consequence,
        // short enough to still feel connected.
        if (fresh.some(function(r) { return r.event_type === 'TRADE'; })) {
          setTimeout(function() {
            hitTile(best.sym);
            refreshCrypto();
          }, 220);
        }
      })
      .catch(function() {});
  }

  // ── Boot ─────────────────────────────────────────────────────────────────
  renderHero();
  renderPositions();
  annNext();   // settles the panel into its idle state
  // Seed the roster WITHOUT animating: on first paint the book already exists,
  // and flying 14 tiles in at once would claim he just placed them all.
  document.querySelectorAll('.tile').forEach(function(el) {
    seenSyms[el.getAttribute('data-sym')] = true;
  });

  setInterval(syncBlobMood, 1000);
  // One poll now carries both NAV and trade reactions — same rows, one request.
  // Trades land every ~7s. A 10s poll straddled them; 4s means he answers
  // almost every one while still costing ~15 tiny requests/min.
  setInterval(pollEvents, 4000);
  // CoinGecko is free/unauthenticated and rate-limits hard — 15s is the floor
  // that stays safely under it. Tiles are a P&L read, not a tape.
  setInterval(pollCryptoPrices, 15000);
  // Donations and simulated events land within ~2s of release — fast enough
  // that a dono feels acknowledged, cheap enough to run for hours.
  setInterval(pollStreamEvents, 2000);
  // Beat faster than Stream HQ's 60s staleness window so one dropped request
  // is never mistaken for a frozen page.
  setInterval(beat, 15000);
  // TEMP: filter toggle. 3s feels instant when you're flipping it in the next
  // window. Remove with yt_overlay.js.
  setInterval(pollYtOverlay, 3000);
  pollYtOverlay();
  pollEvents();
  pollCryptoPrices();
  pollStreamEvents();
  beat();
})();
