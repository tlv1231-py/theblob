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
  // The clock and session light went with the status strip. isMarketOpen is
  // kept because it is genuinely useful context, but nothing renders it now —
  // the Blob's wake state runs off isSystemLive(), not NYSE hours.

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
    // BRACE is in this list for a reason that is easy to miss: this runs every
    // 1000ms and the wind-up is only 500ms, so without it roughly half of every
    // anticipation beat would be overwritten with IDLE mid-crouch — the wind-up
    // would visibly abort before the impact it exists to set up.
    var m = blob.getMood();
    if (m === 'ALERT' || m === 'HAPPY' || m === 'SCARED' || m === 'BRACE') return;

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

  // flashTrade is GONE. It named what he reacted to back when the board was a
  // dense footnote and a mood change was otherwise unattributable. The board
  // answers that itself now — the slot pops, and a sell prints its own P&L
  // where the ticker was — so the callout was repeating the tile's line while
  // covering his face to do it.

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

  // ── The score ────────────────────────────────────────────────────────────
  // One number. The day P&L, strategy P&L and status chips are gone from the
  // stage — dayPnlPct is still tracked because the Blob's shape and his SCARED
  // threshold both read it, it just isn't printed anywhere.
  function renderHero() {
    updateNav(state.nav);
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

    // ── Mute ────────────────────────────────────────────────────────────
    // THE BROADCAST IS NEVER MUTED. ?live=1 marks the render the encoder is
    // capturing, and it ignores this entirely. Every other window — yours, a
    // spare tab — obeys Stream HQ's toggle.
    //
    // This split is the whole point. A naive global mute would be read by the
    // VM's browser too, so silencing the noise on your desk would silence the
    // actual YouTube stream, and nothing on the page would say so. The one
    // render that must stay audible is the one nobody is sitting in front of.
    var muted = false;
    var isLive = !!window._TND_LIVE;
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

    // One gate for every sound on the page: play() and note() are the only two
    // places an oscillator is ever created, so nothing can slip past this.
    function silent() { return muted && !isLive; }

    function play(notes, vol, lowpass) {
      if (!ctx || silent()) return;
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
    // A note with an explicit length — the fanfare needs sustain, which the
    // short fixed decay above cannot give.
    function note(freq, at, len, vol, type) {
      if (!ctx || silent()) return;
      try {
        var osc = ctx.createOscillator(), g = ctx.createGain();
        osc.type = type || 'square';
        osc.frequency.value = freq;
        var t = ctx.currentTime + at;
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(vol, t + 0.008);
        g.gain.setValueAtTime(vol, t + len * 0.7);
        g.gain.exponentialRampToValueAtTime(0.0001, t + len);
        osc.connect(g); g.connect(ctx.destination);
        osc.start(t); osc.stop(t + len + 0.02);
      } catch (e) {}
    }

    return {
      entry: function() { play([[330, 0], [440, 0.055]], 0.055, false); },
      win:   function() { play([[659, 0], [784, 0.07], [988, 0.14]], 0.07, false); },
      loss:  function() { play([[392, 0], [311, 0.07], [233, 0.14]], 0.055, true); },

      // ── The fanfare — a viewer did something ────────────────────────────
      // Deliberately the biggest sound on the stream. A trade win is a 3-note
      // blip; this is a four-voice, ~1.1s cadence, because a person choosing to
      // pay is a categorically louder event than the bot closing a position for
      // 6 cents. If they sounded similar the stream would be lying about what
      // matters.
      //
      // Written from scratch in the style rather than transcribed from any
      // game: an ascending G-major arpeggio (G5 B5 D6) with a triplet pickup,
      // resolving to a held G6 over a root-fifth bass, then two sparkle notes.
      // Original melody — no copyrighted jingle is reproduced here.
      fanfare: function() {
        if (!ctx) return;
        if (ctx.state === 'suspended') { ctx.resume(); return; }
        var V = 0.055;
        // pickup triplet
        note(784,  0.00, 0.06, V);          // G5
        note(988,  0.06, 0.06, V);          // B5
        note(1175, 0.12, 0.06, V);          // D6
        // the hit
        note(1568, 0.20, 0.42, V * 1.25);   // G6 — held
        note(1175, 0.20, 0.42, V * 0.5);    // D6 harmony a fifth below
        // bass
        note(196,  0.00, 0.20, V * 0.9, 'triangle');   // G3
        note(294,  0.20, 0.44, V * 0.9, 'triangle');   // D4
        // sparkle tail
        note(2093, 0.66, 0.09, V * 0.5);    // C7
        note(2637, 0.76, 0.22, V * 0.5);    // E7
      },

      // Per-character text blip — the Gameboy dialogue tell. Very quiet and
      // very short: it should read as texture under the fanfare, not as a
      // second melody competing with it.
      blip: function() {
        if (!ctx || ctx.state !== 'running') return;
        note(880 + Math.random() * 80, 0, 0.02, 0.016);
      },

      setMuted: function(m) { muted = !!m; return muted; },
      isMuted:  function() { return silent(); },
      isLive:   function() { return isLive; },
      isReady:  function() { return ready && ctx && ctx.state === 'running'; }
    };
  })();

  // ═══════════════════════════════════════════════════════════════════════
  // HOLDINGS — one board for the whole book
  // Crypto (crypto_positions, server-written) and equity (positions_data)
  // become identical cabinet slots. They differ by badge and by where their
  // live price comes from, not by living in separate widgets.
  // ═══════════════════════════════════════════════════════════════════════

  // The meter, badges and stop/target band math came out with the dense tile.
  // The data still arrives in the payload (stop_price, target_price, strategy),
  // so putting any of it back is a rendering change only — nothing upstream had
  // to be unpicked to strip the slot down to a name.

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

  // qtyStr/priceStr are gone with the dense tile — the slot shows no quantities
  // or entry prices any more. They live on the Command Center, where someone is
  // reading rather than watching.

  // The roster the board is currently showing. Rebuilding the DOM is reserved
  // for when this actually changes — see renderPositions.
  var _lastRoster = null;   // last built order — diagnostic only

  function tintOf(p) {
    var live = p.price > 0 && p.entry > 0;
    if (!live) return '#8060a0';
    var pc = (p.price - p.entry) / p.entry * 100;
    return pc > 0.001 ? '#00ff9d' : (pc < -0.001 ? '#ff3366' : '#8060a0');
  }

  function makeTile(sym, tint) {
    var el = document.createElement('div');
    el.className = 'tile';
    el.setAttribute('data-sym', sym);
    el.style.setProperty('--tc', tint || '#8060a0');
    var sp = document.createElement('span');
    sp.className = 't-sym';
    sp.textContent = sym.replace('/USD', '');
    el.appendChild(sp);
    return el;
  }

  // ── The board is EVENT-OWNED after boot ──────────────────────────────────
  // Only a trade beat may add, remove or reorder a slot. This is the fix for
  // tiles appearing ahead of their own sound: refreshCrypto() -> renderPositions
  // -> spawnNewTiles used to introduce tiles the moment a FETCH landed, so a
  // batch of four fills put all four slots on the board at once and only then
  // played their sounds 1s apart. The board was being driven by the network
  // instead of by the beat.
  //
  // Polls may now do exactly one thing: re-tint what already exists.
  var _booted = false;

  function renderPositions(force) {
    var list = $('pos-list');
    var ps = book().slice(0, 14);   // 7 cols x 2 rows — the board's exact size

    if (!ps.length) {
      if (!_booted || force) list.innerHTML = '<div class="pos-empty">NO OPEN POSITIONS</div>';
      return;
    }

    // Tint-only pass. Never re-tint a slot printing its leavebehind — boardExit
    // owns --tc until that expires.
    if (_booted && !force) {
      ps.forEach(function(p) {
        var el = list.querySelector('.tile[data-sym="' + p.sym + '"]');
        if (el && !ghostT[p.sym]) el.style.setProperty('--tc', tintOf(p));
      });
      return;
    }

    // Full build — boot, or a settle (see scheduleSettle). Never while a
    // leavebehind is on screen: rebuilding would delete the slot mid-sentence
    // and the result would silently vanish.
    if (Object.keys(ghostT).length) return;

    // FIRST — where every existing slot currently sits, before the DOM moves.
    // This is the F of a FLIP: the reorder itself is instant, and the animation
    // is played backwards from the old position afterwards.
    var first = {};
    list.querySelectorAll('.tile').forEach(function(el) {
      var r = el.getBoundingClientRect();
      first[el.getAttribute('data-sym')] = { x: r.left, y: r.top };
    });

    // REORDER BY MOVING, NOT REBUILDING. appendChild on an element already in
    // the list relocates it; it does not recreate it. The wipe-and-rebuild this
    // replaces destroyed and re-added all 14 slots just to move a few — every
    // tile blinked, and any slot still mid-animation lost it. Reuse the node,
    // reorder in place, and only build what is genuinely new.
    var have = {};
    list.querySelectorAll('.tile').forEach(function(el) {
      have[el.getAttribute('data-sym')] = el;
    });
    var ordered = [];
    ps.forEach(function(p) {
      var el = have[p.sym];
      if (el) { el.style.setProperty('--tc', tintOf(p)); delete have[p.sym]; }
      else    { el = makeTile(p.sym, tintOf(p)); }
      list.appendChild(el);          // moves if present, inserts if new
      ordered.push(el);
    });
    // Whatever is left never made it into the book — drop it.
    Object.keys(have).forEach(function(sym) { have[sym].remove(); });

    _lastRoster = ps.map(function(p) { return p.sym; }).join(',');

    // LAST + INVERT + PLAY — only for slots that actually moved.
    if (_booted) flipReorder(ordered, first);
  }

  // ── The shuffle ──────────────────────────────────────────────────────────
  // The reorder used to be instant: tiles teleported to their new slots and the
  // most interesting thing the board does — the whole book rearranging itself —
  // happened between two frames where nobody could see it.
  //
  // Now it is a FLIP: the DOM has already moved, so each tile is transformed
  // BACK to where it was and walked home. Quantized to a 4px grid over 9 discrete
  // frames — no interpolation, because a sprite cuts rather than tweens — and
  // staggered so the board resolves as a wave instead of a single lurch.
  //
  // It OWNS THE STAGE while it runs: stagePump refuses to hand the floor to ANY
  // lane until reordering is false, so nothing can land mid-shuffle. It gets to
  // finish. That is the whole reason it can afford to take this long — and it is
  // the one thing a popup cannot jump ahead of, because FLIP parks tiles on a
  // transform and killing it mid-play strands them at the wrong coordinates.
  var reordering = false;
  var FLIP_STEP = 55;        // ms per frame
  var FLIP_STAGGER = 55;     // ms between tiles starting — the wave
  var FLIP_PATH = [1.00, 0.82, 0.60, 0.38, 0.20, 0.08, 0.00, -0.04, 0.00];

  function flipReorder(ordered, first) {
    var moving = [];
    ordered.forEach(function(el) {
      var f = first[el.getAttribute('data-sym')];
      if (!f) return;                                  // brand new — flyIn owns it
      var r = el.getBoundingClientRect();
      var dx = f.x - r.left, dy = f.y - r.top;
      if (Math.abs(dx) < 2 && Math.abs(dy) < 2) return; // didn't actually move
      moving.push({ el: el, dx: dx, dy: dy });
    });
    if (!moving.length) return;

    reordering = true;
    var done = 0;
    moving.forEach(function(m, i) {
      var sp = m.el.querySelector('.t-sym');
      if (!sp) { done++; return; }
      // Park it at its OLD position immediately, before any frame paints, or
      // the tile visibly teleports first and then animates back.
      sp.style.transform = 'translate(' + Math.round(m.dx) + 'px,' + Math.round(m.dy) + 'px)';

      setTimeout(function() {
        var k = 0;
        clearInterval(sp._flip);
        sp._flip = setInterval(function() {
          if (k >= FLIP_PATH.length) {
            clearInterval(sp._flip); sp._flip = null;
            sp.style.transform = ''; sp.style.color = ''; sp.style.textShadow = '';
            if (++done >= moving.length) reordering = false;
            return;
          }
          var f = FLIP_PATH[k++];
          // Quantize to the 4px grid the rest of the art lives on. The -0.04
          // frame is a deliberate overshoot past the target before settling.
          var x = Math.round(m.dx * f / 4) * 4, y = Math.round(m.dy * f / 4) * 4;
          sp.style.transform = 'translate(' + x + 'px,' + y + 'px)';
          // Hot on the way, cooling as it lands — the trail is the flash.
          if (k <= 3) {
            sp.style.color = '#ffffff';
            sp.style.textShadow = '0 0 24px var(--tc), 0 0 10px #fff, 3px 3px 0 rgba(0,0,0,0.9)';
          } else if (k <= 6) {
            sp.style.color = '';
            sp.style.textShadow = '0 0 14px var(--tc), 3px 3px 0 #111, 5px 5px 0 rgba(0,0,0,0.8)';
          } else {
            sp.style.color = ''; sp.style.textShadow = '';
          }
        }, FLIP_STEP);
      }, i * FLIP_STAGGER);
    });

    // Belt and braces: if a tile is removed mid-shuffle its interval never
    // reaches the end and `done` never completes, which would leave the trade
    // queue blocked forever. Release the lock on a hard deadline regardless.
    var worst = moving.length * FLIP_STAGGER + FLIP_PATH.length * FLIP_STEP + 400;
    setTimeout(function() { reordering = false; }, worst);
  }

  // ── Reordering waits ─────────────────────────────────────────────────────
  // The canonical order comes from crypto_positions (newest first), so every
  // entry reshuffles the whole board. Doing that on the beat yanks the slots
  // out from under the animation that is still playing on them. Instead the new
  // tile lands wherever there is room, and the board settles into its real order
  // 3s after the LAST trade — debounced, so a burst settles once at the end
  // rather than thrashing on every fill.
  //
  // The settle is also the RECONCILE. Since only trade beats touch the board,
  // local state would drift from the DB forever on a missed event — so this is
  // the one place that re-reads crypto_positions and rebuilds from truth. It
  // fires 3s after the last trade, when nothing is mid-animation.
  var _settleT = null;
  var SETTLE_DELAY = 3000;

  function scheduleSettle() {
    clearTimeout(_settleT);
    _settleT = setTimeout(function() {
      _settleT = null;
      // Never settle over a leavebehind (it would delete the number
      // mid-sentence) and never while any lane holds the stage — the shuffle
      // would yank a slot out from under an animation still playing on it, and
      // it would step on a popup or a line of dialogue. Re-arm and wait.
      if (Object.keys(ghostT).length || stage.owner) { scheduleSettle(); return; }
      refreshCrypto();      // re-reads the DB, then rebuilds in canonical order
    }, SETTLE_DELAY);
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
  // Called ONLY from the settle, 3s after the last trade. It used to run on
  // every trade and immediately renderPositions() + spawnNewTiles(), which put
  // slots on the board the instant a fetch returned — ahead of the beat that
  // was supposed to announce them. Adds and removes now belong exclusively to
  // boardEnter/boardExit; this re-reads truth and rebuilds in canonical order
  // once the dust has settled.
  function refreshCrypto() {
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
        if (Object.keys(ghostT).length) return;   // a leavebehind is still speaking
        renderPositions(true);                    // reorder, now that it's safe
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
  // THE STAGE — one lane owns it at a time
  //
  // Every animated thing on this page belongs to exactly one of three classes,
  // and they are ranked:
  //
  //   1. POPUP   The Gameboy window. A VIEWER did something — donated, subbed,
  //              followed, raided. A person spent money or showed up, which
  //              outranks anything the machine is doing on its own.
  //   2. SPEAKS  The same window, but it is Blobby talking — his voice,
  //              scrolling by, Gameboy-style. He is the streamer, so his line
  //              outranks his own book.
  //   3. TRADE   The beat. ~9/min, all day, and the only thing here that
  //              repeats — which is exactly why it is the one that yields.
  //
  // Popups and speaks PAUSE trades. Before this arbiter existed the lanes did
  // not interact at all: annNext and tradeNext were independent state machines
  // writing to the same stage, so a donation fanfare fired on top of a loss
  // sting and the viewer heard both at once with no way to tell which was which.
  //
  // ── PAUSE MEANS THE QUEUE PAUSES, NOT THE FRAME ─────────────────────────
  // A beat already in flight has fired its sound and has a tile mid-animation.
  // Killing it would strand the tile and leave a sound with no picture. So the
  // UNIT of work is atomic and the ladder only decides who goes NEXT. Worst
  // case a donation waits out one beat (~1.6s). That is the price of never
  // showing a broken frame, and it is cheap.
  //
  // Each lane holds the floor for its whole BURST, not one item: a popup queue
  // drains before the box closes, because closing and reopening the window
  // between two donations reads as a glitch rather than as two events.
  // ═══════════════════════════════════════════════════════════════════════
  var stage = { owner: null };        // null | 'popup' | 'speaks' | 'trade'

  function stageTake(lane) { stage.owner = lane; }

  function stageDone() {
    stage.owner = null;
    stagePump();
  }

  function stagePump() {
    if (stage.owner) return;
    // The shuffle is atomic for a harder reason than the rest: FLIP parks each
    // tile at its old position with a transform and walks it home, so a reorder
    // killed mid-play leaves tiles permanently at the wrong coordinates. It
    // cannot be preempted, only waited out (~1s worst case).
    if (reordering) { setTimeout(stagePump, 120); return; }
    if (popupStart()) return;
    if (speakStart()) return;
    if (tradeStart()) return;
  }

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

  // The house format, split so the NAME can be staged on its own.
  function nameOf(type, p) {
    if (type === 'risk_breach') return 'RISK BREACH';
    return (p.from || 'SOMEONE').toUpperCase().slice(0, 14);
  }
  function actOf(type, p) {
    if (type === 'risk_breach') return 'just BROKE ' + (p.limit || '') + ' !!!';
    var amt = amountFor(type, p);
    return 'just ' + (VERB[type] || 'DID SOMETHING') + (amt ? ' ' + amt : '') + ' !!!';
  }

  var annQ = [], annTypeT = null, annHoldT = null;

  function annPush(type, payload) {
    if (!ANN[type]) return;
    annQ.push({ type: type, p: payload || {} });
    if (annQ.length > 6) annQ.splice(0, annQ.length - 6);  // drop the oldest
    annBadge();
    stagePump();          // takes the floor now, or the moment the beat ends
  }

  // Returns true if it took the floor. The ladder in stagePump calls these in
  // priority order and stops at the first one that says yes.
  function popupStart() {
    if (!annQ.length) return false;
    stageTake('popup');
    annNext();
    return true;
  }

  // Shared by both window lanes — the box leaves entirely so the score gets its
  // floor back the instant nobody is talking.
  function annClose() {
    var lcd = $('ev-lcd');
    if (!lcd) return;
    $('s-events').classList.remove('showing');
    lcd.classList.remove('open');
    lcd.classList.remove('speaking');
    // `pop` is the money hit. It is inert today (CSS animations don't run in
    // this iframe) but it is a one-shot, so leaving it stuck on means it can
    // never fire again if the clock ever does run — on a different host, or if
    // this gets ported off the iframe. Clear it with the rest of the state.
    lcd.classList.remove('pop');
    lcd.style.removeProperty('--ev-c');
    $('ev-more').className = 'ev-more';
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
      annClose();
      // Guarded because boot calls annNext() once to settle the panel into its
      // idle state, and that call holds no floor to give back.
      if (stage.owner === 'popup') stageDone();
      return;
    }
    var ev = annQ.shift();
    annBadge();

    var cfg = ANN[ev.type];
    $('s-events').classList.add('showing');   // the overlay arrives
    lcd.classList.remove('idle');
    lcd.classList.remove('speaking');
    lcd.classList.add('open');
    lcd.style.setProperty('--ev-c', cfg.c);
    $('ev-bigicon').textContent = cfg.i;
    $('ev-more').className = 'ev-more';

    // Money hits the panel itself, not just the text.
    if (cfg.c === '#00ff9d') {
      lcd.classList.remove('pop'); void lcd.offsetWidth; lcd.classList.add('pop');
    }

    // THE REACTION FIRES HERE, WITH THE BOX — not when the event was received.
    // It used to fire in applyStreamEvent on arrival, which meant an event that
    // queued behind another played its mood and sound seconds before its own
    // window appeared, and then the box fired a fanfare on top. Same rule as the
    // trade beat: one event, one frame.
    var react = EVENT_MOOD[ev.type];
    if (react) {
      if (react.mood) blob.setMood(react.mood, react.mood === 'HAPPY' ? 26 : 18);
      $('blob-mood').textContent = blob.getMood();
      // A viewer paying is the loudest thing that happens on this stream.
      bg.pulse(cfg.c === '#00ff9d' ? 'money' : (react.sfx === 'loss' ? 'loss' : 'enter'), 0.30);
    }
    SFX.fanfare();

    var name = nameOf(ev.type, ev.p);
    var act  = actOf(ev.type, ev.p);
    var msg  = (ev.p.message || '').slice(0, 42);
    var nEl = $('ev-name'), aEl = $('ev-act'), mEl = $('ev-msg');
    nEl.innerHTML = ''; aEl.textContent = ''; mEl.textContent = '';

    clearInterval(annTypeT); clearTimeout(annHoldT);

    // ── Stage 1: the NAME assembles, one glyph per frame, each with a blip.
    // Slower than the body text on purpose (52ms vs 24ms) — this is the part
    // the viewer paid for, so it gets the airtime.
    var ni = 0;
    annTypeT = setInterval(function() {
      if (ni < name.length) {
        var ch = document.createElement('i');
        ch.textContent = name[ni] === ' ' ? ' ' : name[ni];
        // Stagger the pop so the name lands like a stamp, not a wipe.
        ch.style.animationDelay = '0s';
        nEl.appendChild(ch);
        SFX.blip();
        ni++;
        return;
      }
      clearInterval(annTypeT);

      // ── Stage 2: the action line and message type underneath.
      var i = 0;
      annTypeT = setInterval(function() {
        if (i < act.length) {
          aEl.textContent += act[i++];
        } else if (i - act.length < msg.length) {
          mEl.textContent += msg[i++ - act.length];
        } else {
          clearInterval(annTypeT);
          $('ev-more').className = 'ev-more on';
          // Hold longer when nothing is waiting so a lone event can be read;
          // shorter during a burst so the queue drains. Longer overall than the
          // old strip because there is now more to actually look at.
          annHoldT = setTimeout(annNext, annQ.length ? 1800 : 4000);
        }
      }, 24);
    }, 52);
  }

  // ═══════════════════════════════════════════════════════════════════════
  // BLOBBY SPEAKS — the same window, his voice
  //
  // Deliberately the SAME box as the announcer, not a second one. A Gameboy has
  // exactly one text box; who is talking is carried by how it looks and what it
  // says, never by where it is. Two boxes would be two UIs.
  //
  // What separates it from a popup: no name stamp, no !!!, no fanfare. A popup
  // is an ANNOUNCEMENT about a viewer and lands like one. This is dialogue — it
  // opens quietly, types at a reading pace, and the blips are his voice. The
  // pink `speaking` skin is the tell, matching his body, because he is the only
  // pink thing on this stage.
  // ═══════════════════════════════════════════════════════════════════════
  var speakQ = [], speakTypeT = null, speakHoldT = null;
  var SPEAK_STEP = 30;      // ms/glyph — a hair slower than the announcer's
                            // body text; this is meant to be read, not clocked.
  var SPEAK_HOLD = 2400;    // after the last glyph, before he yields the floor

  // The only way to make him talk. Text only — he has no name line, because a
  // character's own dialogue box does not caption itself.
  function blobSpeak(text, opts) {
    if (!text) return;
    speakQ.push({
      text: String(text).slice(0, 90),
      mood: (opts && opts.mood) || null
    });
    // Shorter cap than the popup queue: stale chatter is worse than no chatter,
    // and unlike a donation nobody paid for it.
    if (speakQ.length > 3) speakQ.splice(0, speakQ.length - 3);
    stagePump();
  }

  function speakStart() {
    if (!speakQ.length) return false;
    stageTake('speaks');
    speakNext();
    return true;
  }

  function speakNext() {
    var lcd = $('ev-lcd');
    if (!lcd) return;
    if (!speakQ.length) {
      annClose();
      if (stage.owner === 'speaks') stageDone();
      return;
    }
    var s = speakQ.shift();

    $('s-events').classList.add('showing');
    lcd.classList.remove('idle');
    lcd.classList.remove('pop');            // a popup's money hit is not his
    lcd.classList.add('open');
    lcd.classList.add('speaking');          // his skin, not the announcer's
    lcd.style.setProperty('--ev-c', '#ff00cc');
    $('ev-more').className = 'ev-more';

    // No name stamp and no icon — the box is his, so it needs no attribution.
    var nEl = $('ev-name'), aEl = $('ev-act'), mEl = $('ev-msg');
    nEl.innerHTML = ''; aEl.textContent = ''; mEl.textContent = '';
    $('ev-bigicon').textContent = '';

    if (s.mood) { blob.setMood(s.mood, 30); $('blob-mood').textContent = blob.getMood(); }

    clearInterval(speakTypeT); clearTimeout(speakHoldT);

    // One glyph at a time with a blip — the Gameboy convention, and the reason
    // it reads as a voice rather than as a label that appeared.
    var i = 0;
    speakTypeT = setInterval(function() {
      if (i < s.text.length) {
        aEl.textContent += s.text[i];
        // Blip on non-spaces only, or the gaps between words click.
        if (s.text[i] !== ' ') SFX.blip();
        i++;
        return;
      }
      clearInterval(speakTypeT);
      $('ev-more').className = 'ev-more on';
      // Shorter hold during a burst so a queued line isn't left waiting.
      speakHoldT = setTimeout(speakNext, speakQ.length ? 900 : SPEAK_HOLD);
    }, SPEAK_STEP);
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

  // Routes an inbound event into its LANE. It no longer reacts here — mood,
  // sound and pulse now fire from the lane at the moment the thing is actually
  // shown. Reacting on arrival meant an event queued behind another played its
  // sound seconds before its own window opened.
  function applyStreamEvent(ev) {
    var p = ev.payload || {};

    // Blobby's own voice — the speaks lane.
    if (ev.event_type === 'blob_speak') {
      blobSpeak(p.message || p.text, { mood: p.mood || null });
      return;
    }

    if (!EVENT_MOOD[ev.event_type]) return;

    // A simulated trade speaks through the BOARD; a viewer event gets the
    // announcer. Keeping the two channels separate is what lets a viewer tell
    // "the bot did something" from "a person did something".
    if (ev.event_type === 'trade_enter' || ev.event_type === 'trade_exit') {
      // Still immediate: a simulated trade is a board poke, not a stage event,
      // and it has no window to stay in sync with.
      var win = Number(p.pnl || 0) > 0;
      var mood = ev.event_type === 'trade_exit' ? (win ? 'HAPPY' : 'ALERT') : 'ALERT';
      var sfx  = ev.event_type === 'trade_exit' ? (win ? 'win' : 'loss') : 'entry';
      blob.setMood(mood, mood === 'HAPPY' ? 26 : 18);
      if (SFX[sfx]) SFX[sfx]();
      bg.pulse(sfx === 'loss' ? 'loss' : 'enter', 0.30);
      if (p.symbol) hitTile(p.symbol);
      $('blob-mood').textContent = blob.getMood();
      return;
    }

    annPush(ev.event_type, p);
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

  // Stream HQ's mute switch. Same store and shape as the YT filter toggle:
  // strategy_params is the only thing HQ and this page can both reach, since
  // they are different browsers.
  //
  // The BROADCAST short-circuits this — ?live=1 never even polls, so no setting,
  // no outage and no bad row can ever silence the actual stream.
  function pollMute() {
    if (SFX.isLive()) return;
    fetch(S.supa.url + '/rest/v1/strategy_params?strategy=eq.stream' +
          '&param=eq.preview_muted&select=value',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) return;   // never set — stay audible
        SFX.setMuted(rows[0].value === '1');
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
          // 'muted' is distinct from 'blocked': blocked means the autoplay flag
          // is missing and the render CANNOT make sound; muted means someone
          // chose it. The watchdog alarms on the first and not the second, so
          // they must not collapse into one value.
          audio: SFX.isMuted() ? 'muted' : (SFX.isReady() ? 'on' : 'blocked'),
          live: SFX.isLive()
        },
        recorded_at: new Date().toISOString()
      })
    }).catch(function() {});
  }

  // ── Arcade hit ───────────────────────────────────────────────────────────
  // The slot reacts when its symbol trades. Driven by setInterval and NOT by a
  // CSS animation: measured earlier, the animation clock does not advance in
  // this iframe at all, so a @keyframes version renders as nothing. Everything
  // that must move on this page is a timer.
  //
  // The arcade read is QUANTIZATION. Nine frames at 45ms, each snapping to a
  // discrete scale/offset/colour — no interpolation between them. A sprite does
  // not tween; it cuts. The sequence is the classic cabinet hit: overshoot huge
  // and white, slam past the resting size, settle. Colour lands on the verdict
  // (green/red) at the peak and decays back to white, so the flash carries the
  // information and the motion carries the impact.
  var HIT_FRAMES = [
    { s: 2.20, y: -14, c: '#ffffff', b: 1 },
    { s: 1.90, y: -10, c: '#ffffff', b: 1 },
    { s: 1.55, y:  -5, c: 'tint',    b: 1 },
    { s: 1.30, y:   0, c: 'tint',    b: 0 },
    { s: 0.82, y:   3, c: 'tint',    b: 0 },
    { s: 1.14, y:  -2, c: 'tint',    b: 0 },
    { s: 0.94, y:   1, c: '#ffffff', b: 0 },
    { s: 1.06, y:   0, c: '#ffffff', b: 0 },
    { s: 1.00, y:   0, c: '#ffffff', b: 0 }
  ];

  function arcadeHit(sym) {
    var el = document.querySelector('.tile[data-sym="' + sym + '"]');
    if (!el) return;
    var sp = el.querySelector('.t-sym');
    if (!sp) return;
    var tint = el.style.getPropertyValue('--tc') || '#ffffff';

    clearInterval(sp._hit);
    var i = 0;
    sp._hit = setInterval(function() {
      if (i >= HIT_FRAMES.length) {
        clearInterval(sp._hit); sp._hit = null;
        sp.style.transform = ''; sp.style.color = ''; sp.style.textShadow = '';
        return;
      }
      var f = HIT_FRAMES[i++];
      var col = f.c === 'tint' ? tint : f.c;
      sp.style.transform = 'translateY(' + f.y + 'px) scale(' + f.s + ')';
      sp.style.color = col;
      // Bloom on the opening frames only — the hit should feel like it emits
      // light for an instant, not like it is permanently glowing.
      sp.style.textShadow = f.b
        ? '0 0 26px ' + col + ', 0 0 10px ' + col + ', 3px 3px 0 rgba(0,0,0,0.9)'
        : '0 0 14px ' + col + ', 3px 3px 0 #111, 5px 5px 0 rgba(0,0,0,0.8)';
    }, 45);
  }

  // Kept as the name the rest of the file calls.
  function hitTile(sym) { arcadeHit(sym); }

  // The terminal feed is DELETED — markup, CSS and renderer. It was texture in
  // the reserved bands; the background is the starfield now. pollEvents still
  // fetches the same rows, which the Blob's moods and the board both need.

  // ── Agency ───────────────────────────────────────────────────────────────
  // Making the Blob look like he is DOING this rather than reacting to it.
  // The whole trick is sequence: he moves first, the board answers ~220ms
  // later. Same events, same data — but cause then effect, instead of two
  // symptoms firing at once with the cause invisible.

  // seenSyms is gone with spawnNewTiles — nothing needs to infer which slots are
  // new any more, because the beat says so explicitly.

  function blobCenter() {
    var c = $('blobCanvas');
    if (!c) return null;
    var r = c.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  // Fly every newly-arrived tile in from his position. Timer-driven for the
  // same reason as arcadeHit: a CSS @keyframes version never plays here.
  // 5 frames, no interpolation — the slot jumps along the path the way a sprite
  // does, which is what sells it as a placement rather than a transition.
  function flyIn(el, dx, dy) {
    var sp = el.querySelector('.t-sym');
    if (!sp) return;
    var steps = [
      { t: 1.00, s: 0.35, o: 0.4 },
      { t: 0.62, s: 0.60, o: 0.7 },
      { t: 0.32, s: 0.85, o: 1 },
      { t: 0.10, s: 1.25, o: 1 },   // overshoot on landing
      { t: 0.00, s: 1.00, o: 1 }
    ];
    clearInterval(sp._fly);
    var i = 0;
    sp._fly = setInterval(function() {
      if (i >= steps.length) {
        clearInterval(sp._fly); sp._fly = null;
        sp.style.transform = ''; sp.style.opacity = '';
        return;
      }
      var f = steps[i++];
      // Quantize to the 4px grid the rest of the art lives on.
      var x = Math.round(dx * f.t / 4) * 4, y = Math.round(dy * f.t / 4) * 4;
      sp.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + f.s + ')';
      sp.style.opacity = f.o;
    }, 40);
  }

  // spawnNewTiles() is gone. It scanned the DOM for tiles it hadn't seen and
  // flew them in — which meant the fly-in fired whenever a tile APPEARED, and
  // tiles appeared whenever a fetch landed. That is exactly how the animation
  // got ahead of its own sound. boardEnter now calls flyIn directly on the beat,
  // so nothing has to guess when a slot is new.

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

  // The TRADE message already carries everything the board needs, so the slot
  // can react to the EVENT rather than waiting on a DB round trip:
  //   ▲ ENTER LONG BCH/USD @ $222.4728 · stop $221.8053   [detail: qty=0.999025]
  //   ✗ EXIT LONG LINK/USD @ $8.3882 · pnl -0.5926 · timeout
  function num(s) { return parseFloat(String(s).replace(/,/g, '')); }

  function parseTrade(msg, detail) {
    if (!msg) return null;
    if (msg.indexOf('ENTER') >= 0) {
      var pm = msg.match(/@\s*\$([\d,]+\.?\d*)/);
      var sm = msg.match(/stop\s+\$([\d,]+\.?\d*)/);
      var qm = (detail || '').match(/qty=([\d.]+)/);
      return {
        dir: 'ENTER', pnl: null,
        price: pm ? num(pm[1]) : 0,
        stop:  sm ? num(sm[1]) : 0,
        qty:   qm ? parseFloat(qm[1]) : 0
      };
    }
    if (msg.indexOf('EXIT') >= 0) {
      // [+-]? — a win reads "pnl +0.42". Without the plus this matched only
      // losses and silently dropped every profitable exit.
      var m = msg.match(/pnl\s+([+-]?[\d.]+)/);
      return { dir: 'EXIT', pnl: m ? parseFloat(m[1]) : null };
    }
    return null;
  }

  // ── The trade queue ──────────────────────────────────────────────────────
  // One trade at a time, 1s apart. The book fires ~9/min and arrives in bursts
  // — four fills inside one 4s poll is normal. Played simultaneously they
  // collapse into a single indistinguishable flinch; played 1s apart each one
  // is a discrete beat you can actually count.
  //
  // Every beat moves all three together — the slot, the Blob, and the score —
  // because they are three views of one event, and staggering them would read
  // as three unrelated things twitching.
  // ═══════════════════════════════════════════════════════════════════════
  // x — THE STATUS LINE
  // Reads as the back half of the sentence the nameplate starts:
  //     blob  sold BTC for -$0.39
  //
  // It DECODES between states rather than cutting: each segment scrambles
  // through junk glyphs and resolves left-to-right, staggered so the sentence
  // assembles word by word. A hard swap would be a label changing; this reads
  // as the machine working it out, which is the only thing on the stage allowed
  // to look computed — the nameplate beside it never moves at all, and the
  // contrast is the point.
  //
  // Fires from applyTrade, on the same frame as the sound and the tile.
  // ═══════════════════════════════════════════════════════════════════════

  // Junk to scramble through. Blocks and hex, so the noise reads as a machine
  // resolving rather than as letters shuffling.
  var SCRAM = '▓▒░█▄▀■◆◇01234567890ABCDEF#$%&*+=/\\|<>';
  var DECODE_FRAMES = 9, DECODE_STEP = 34, SEG_STAGGER = 90;

  // ticker_colors, seeded server-side and re-polled so an edit on the Command
  // Center reaches the stream. Stored stripped ('CRV'), so normalise.
  var tickerCols = S.ticker_colors || {};
  function tickerColor(sym) {
    var bare = sym.replace('/USD', '');
    // No assigned colour is not an error — most tickers have none. Fall back to
    // white and let the Command Center be the only place colours are decided.
    return tickerCols[bare] || '#ffffff';
  }

  function pollTickerColors() {
    fetch(S.supa.url + '/rest/v1/ticker_colors?select=ticker,color',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows)) return;
        var next = {};
        rows.forEach(function(r) { if (r.color) next[r.ticker] = r.color; });
        tickerCols = next;
      })
      .catch(function() {});
  }

  // Decode one segment to its final text. Reveals left-to-right so the eye can
  // start reading before it finishes.
  function decodeTo(el, finalText, delay) {
    clearInterval(el._dec);
    clearTimeout(el._decT);
    el.textContent = '';
    el._decT = setTimeout(function() {
      var i = 0;
      el._dec = setInterval(function() {
        if (i >= DECODE_FRAMES) {
          clearInterval(el._dec); el._dec = null;
          el.textContent = finalText;
          return;
        }
        var shown = Math.floor(finalText.length * (i / (DECODE_FRAMES - 1)));
        var out = finalText.slice(0, shown);
        for (var k = shown; k < finalText.length; k++) {
          // Spaces stay spaces or the word boundaries jitter and it reads as
          // noise instead of as a sentence resolving.
          out += finalText[k] === ' ' ? ' '
               : SCRAM[Math.floor(Math.random() * SCRAM.length)];
        }
        el.textContent = out;
        i++;
      }, DECODE_STEP);
    }, delay || 0);
  }

  function money2(v) {
    var n = Math.abs(Number(v || 0));
    return (Number(v) >= 0 ? '+$' : '−$') + n.toFixed(2);
  }
  function cost2(v) {
    var n = Number(v || 0);
    return '$' + (n >= 1000 ? Math.round(n).toLocaleString('en-US') : n.toFixed(2));
  }

  // Back to "is trading" once the tape goes quiet. Trades land every ~7s and the
  // beat is 1.6s, so 20s only ever fires when the engine has genuinely stopped —
  // it is not a timeout on the animation, it is the difference between "blob
  // sold BTC" being news and being a stale caption nobody cleared.
  var IDLE_AFTER = 20000, _idleT = null;
  function statusIdle() {
    var el = $('blob-status');
    if (!el) return;
    el.className = 'ttl-x idle';
    decodeTo(el, 'is trading', 0);
  }

  // The sentence. A BUY has no P&L yet, so "for" takes what the position COST —
  // qty x price, not the per-unit price. That distinction is the whole point:
  // "bought CRV for $0.22" reads as blob buying 22 cents of crypto, when he
  // actually spent $204. Same template shape, honest number. (qty is on every
  // ENTER's detail as qty=N; measured 20/20.)
  function setStatus(t) {
    var el = $('blob-status');
    if (!el) return;
    clearTimeout(_idleT);
    _idleT = setTimeout(statusIdle, IDLE_AFTER);
    var bare = t.sym.replace('/USD', '');
    var isExit = t.dir === 'EXIT';

    // statusIdle decodes the CONTAINER, so a decode may still be mid-flight on
    // it. Left running it would keep writing textContent over the spans below
    // and the sentence would dissolve back into junk a frame after it resolved.
    clearInterval(el._dec); clearTimeout(el._decT); el._dec = null;

    el.className = 'ttl-x';
    el.innerHTML =
      '<span class="xs-verb"></span>' +
      '<span class="xs-sym"></span>' +
      '<span class="xs-for"></span>' +
      '<span class="xs-pnl"></span>';

    var vEl = el.querySelector('.xs-verb'),
        sEl = el.querySelector('.xs-sym'),
        fEl = el.querySelector('.xs-for'),
        pEl = el.querySelector('.xs-pnl');

    sEl.style.color = tickerColor(t.sym);

    var tail, cls = '';
    if (isExit) {
      var v = Number(t.pnl || 0);
      tail = money2(v);
      cls = v >= 0 ? 'win' : 'loss';
    } else {
      // Fall back to the per-unit price only if qty is missing — a wrong-looking
      // number beats a blank one, and it has never actually been missing.
      tail = cost2(t.qty ? t.qty * t.price : t.price);
    }
    pEl.className = 'xs-pnl ' + cls;

    // Staggered so the sentence assembles word by word rather than all at once.
    decodeTo(vEl, isExit ? 'sold' : 'bought', 0);
    decodeTo(sEl, bare, SEG_STAGGER);
    decodeTo(fEl, 'for', SEG_STAGGER * 2);
    decodeTo(pEl, tail, SEG_STAGGER * 3);
  }

  // ── The beat ─────────────────────────────────────────────────────────────
  // Three phases per trade, played in order, one trade at a time:
  //
  //     PRE (brace)  ->  EVENT (impact)  ->  POST (follow-through)  ->  gap
  //
  // This is anticipation / action / follow-through. The old version was action
  // only: every reaction started at full volume out of nothing, which reads as
  // a flinch rather than a performance. The wind-up gives the impact something
  // to release, and the follow-through gives it somewhere to land.
  //
  // Slower on purpose. A trade now occupies 1.6s instead of 1.0s, so a burst of
  // four takes ~6.4s to play out. The book fires roughly every 7s, so a lone
  // trade finishes well before the next arrives, and a burst simply queues.
  var PRE_MS = 500;      // he sees it coming and crouches
  var EVENT_MS = 0;      // the impact — sound, tile and score together
  var POST_MS = 800;     // the verdict mood plays out
  var GAP_MS = 300;      // breath before the next wind-up
  // The Blob runs at 10fps, so ticks are ms/100. BLOB.md: do not raise the FPS.
  var PRE_TICKS = Math.round(PRE_MS / 100);
  var POST_TICKS = Math.round(POST_MS / 100);

  var tradeQ = [];

  function tradePush(t) {
    tradeQ.push(t);
    // A long backlog is stale by the time it plays — better to drop the oldest
    // than to narrate a minute-old fill as if it just happened. At 1.6s a beat,
    // 6 queued is ~10s of backlog, which is about as late as a "live" reaction
    // can honestly claim to be.
    if (tradeQ.length > 6) tradeQ.splice(0, tradeQ.length - 6);
    stagePump();
  }

  // The bottom of the ladder: only runs when no viewer event and no line of
  // dialogue is waiting. ONE beat per acquire, not the whole queue — that is
  // what makes "popups pause trades" true in practice, because a donation that
  // lands mid-burst only ever waits out the single beat already in flight
  // instead of the entire backlog.
  function tradeStart() {
    if (!tradeQ.length) return false;
    stageTake('trade');
    var t = tradeQ.shift();

    // ── PRE ────────────────────────────────────────────────────────────
    // He looks at the slot and braces. Nothing else moves yet: no sound, no
    // tile, no score. This half-second is the only warning the viewer gets,
    // and it is what makes the impact feel caused rather than random.
    blob.setMood('BRACE', PRE_TICKS + 2);   // +2 so it holds through the handoff
    glanceAt(t.sym);
    $('blob-mood').textContent = blob.getMood();

    setTimeout(function() {
      // ── EVENT ────────────────────────────────────────────────────────
      applyTrade(t);

      setTimeout(function() {
        // ── POST ───────────────────────────────────────────────────────
        // The verdict mood set at the impact is still decaying — this is its
        // window. Nothing to fire; the beat just isn't over yet, and the next
        // wind-up must not start on top of the follow-through.
        //
        // Then the floor goes back to the ladder rather than straight to the
        // next trade: anything that queued during this beat gets its turn here.
        setTimeout(stageDone, GAP_MS);
      }, POST_MS);
    }, PRE_MS + EVENT_MS);
    return true;
  }

  // ONE MOMENT. Sound, text and entry animation all land on the same frame.
  //
  // The board used to answer 220ms late, to sell the Blob as the cause. That
  // delay is gone: the trade is a single impact, and splitting it across two
  // frames made the sound and the slot read as two loosely-related things.
  // He still leads — his glance and mood are set before the slot moves within
  // this same synchronous block, which is enough.
  function applyTrade(t) {
    var verdict = t.dir === 'ENTER' ? 'enter' : (t.pnl > 0 ? 'win' : 'loss');

    // The verdict mood IS the follow-through, so its duration is the POST
    // window — not an arbitrary constant. A win gets a little longer because it
    // is rare and worth holding; anything shorter than POST_TICKS would have
    // him snap back to idle while the beat was still running.
    if (verdict === 'win')        blob.setMood('HAPPY', POST_TICKS + 6);
    else if (verdict === 'enter') blob.setMood('ALERT', POST_TICKS);
    else                          blob.setMood('ALERT', POST_TICKS - 2);
    glanceAt(t.sym);
    $('blob-mood').textContent = blob.getMood();

    // Sound follows the verdict: acquisitions are neutral because buying is
    // not yet good or bad news.
    if (verdict === 'enter')     SFX.entry();
    else if (verdict === 'win')  SFX.win();
    else                         SFX.loss();
    bg.pulse(verdict, 0.42);

    // THE SCORE MOVES ON THE TRADE. A realised exit changes NAV, so the number
    // reacts now rather than waiting up to 10s for the next engine UPDATE. The
    // UPDATE still lands and corrects — a prediction the authoritative feed
    // confirms, not a second source of truth.
    if (t.dir === 'EXIT' && t.pnl != null) {
      state.nav += t.pnl;
      updateNav(state.nav);
    }

    // Same frame as the sound.
    if (t.dir === 'ENTER') boardEnter(t);
    else                   boardExit(t);

    // x speaks on the same frame too. The decode runs for ~400ms after this,
    // but it STARTS here, which is what makes the sentence read as caused by the
    // sound rather than as a caption that arrived late.
    setStatus(t);

    // Any reordering waits — see scheduleSettle.
    scheduleSettle();
  }

  // ── The board reacts ─────────────────────────────────────────────────────
  function tileEl(sym) { return document.querySelector('.tile[data-sym="' + sym + '"]'); }

  var ghostT = {};   // sym -> timer holding a spent slot on screen

  function boardEnter(t) {
    // The same symbol usually re-enters seconds after it exits, so its slot is
    // often still on screen holding the leavebehind. Reclaim it.
    clearTimeout(ghostT[t.sym]);
    delete ghostT[t.sym];

    var el = tileEl(t.sym);
    if (!el) {
      // Build the slot from the EVENT — no fetch, no rebuild, no reorder. It
      // exists on this frame, alongside its sound. The poll confirms it moments
      // later with identical values, and the settle puts it in its real place.
      var exists = (S.crypto || []).some(function(c) { return c.sym === t.sym; });
      if (!exists) {
        S.crypto = (S.crypto || []).concat([{
          sym: t.sym, qty: t.qty || 0, entry_price: t.price || 0,
          stop_price: t.stop || 0, target_price: 0,
          entered_at: new Date().toISOString(), strategy: 'crypto', is_crypto: true
        }]);
      }
      el = makeTile(t.sym, '#8060a0');
      $('pos-list').appendChild(el);       // wherever there's room; settle sorts it
    } else {
      var sp = el.querySelector('.t-sym');
      sp.textContent = t.sym.replace('/USD', '');
      sp.className = 't-sym';
      el.style.removeProperty('--tc');
    }

    // Fly-in and hit fire NOW, on the same frame as the sound — whether the slot
    // is brand new or reclaimed. The position is new either way and the viewer
    // should see him place it.
    var o = blobCenter(), r = el.getBoundingClientRect();
    if (o) flyIn(el, o.x - (r.left + r.width / 2), o.y - (r.top + r.height / 2));
    hitTile(t.sym);
  }

  // ── The leavebehind ──────────────────────────────────────────────────────
  // On a sell the slot does not simply vanish — it LEAVES BEHIND what the
  // position earned, in the ticker's own face and size: green profit, red loss.
  // A tile that disappears tells you a position closed. A leavebehind tells you
  // whether it was worth having, which is the only part a viewer cares about.
  //
  // 4500ms is the requested "a little longer". Note the real ceiling is not this
  // constant: the book re-enters the same symbol within ~1-2s of exiting it, and
  // boardEnter reclaims the slot when it does — so most leavebehinds are cut
  // short by their own symbol coming back, not by this timer. This value only
  // governs the ones that DON'T immediately re-enter. Making them outlast a
  // re-entry would mean showing two tiles for one symbol, which is worse.
  var LEAVEBEHIND_MS = 4500;

  function boardExit(t) {
    var el = tileEl(t.sym);
    if (!el) return;

    var sp = el.querySelector('.t-sym');
    var v = Number(t.pnl || 0);
    sp.textContent = (v >= 0 ? '+' : '−') + '$' + Math.abs(v).toFixed(2);
    sp.className = 't-sym ' + (v >= 0 ? 'pnl-win' : 'pnl-loss');
    el.style.setProperty('--tc', v >= 0 ? '#00ff9d' : '#ff3366');
    hitTile(t.sym);              // the number lands with the same arcade punch

    // Drop the position from local state now so the settle doesn't resurrect
    // the slot — but leave the ELEMENT on screen holding its number.
    S.crypto = (S.crypto || []).filter(function(c) { return c.sym !== t.sym; });

    // Hold, then remove. boardEnter cancels this if the symbol re-enters first,
    // so a re-entry reclaims the slot instead of racing a pending removal.
    clearTimeout(ghostT[t.sym]);
    ghostT[t.sym] = setTimeout(function() {
      delete ghostT[t.sym];
      var live = tileEl(t.sym);
      if (live && live.querySelector('.t-sym.pnl-win, .t-sym.pnl-loss')) live.remove();
      // The reorder countdown RESTARTS from here, not from the trade. Otherwise
      // the board could reshuffle the instant the number cleared — which is the
      // worst possible moment, since the eye is still on that slot.
      scheduleSettle();
    }, LEAVEBEHIND_MS);
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


        // daily_pnl rides on every EXIT detail — a far fresher continuous
        // signal than the 10s nav_snapshots poll, so feed it to his shape.
        for (var i = rows.length - 1; i >= 0; i--) {
          var dm = (rows[i].detail || '').match(/daily_pnl=(-?[\d.]+)/);
          if (dm) { blob.setPnl(parseFloat(dm[1])); break; }
        }

        if (firstRun) return;   // hydration history is old — don't react to it

        // EVERY trade queues. This used to pick one "best" event per poll and
        // drop the rest, which meant a burst of four fills showed as one — the
        // stream silently under-reported its own activity. The queue plays them
        // one at a time instead, so nothing is invented and nothing is lost.
        fresh.forEach(function(r) {
          if (r.event_type !== 'TRADE') return;
          var t = parseTrade(r.message, r.detail);
          if (!t) return;
          t.sym = r.symbol || '';
          tradePush(t);
        });
      })
      .catch(function() {});
  }

  // ── Boot ─────────────────────────────────────────────────────────────────
  renderHero();
  // The one full build that isn't a settle. Nothing animates: on first paint
  // the book already exists, and flying 14 tiles in at once would claim he had
  // just placed the entire portfolio.
  renderPositions(true);
  annNext();                      // settles the panel into its idle state
  _booted = true;                 // from here, only a trade beat may change the board

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
  // Mute lands within ~3s of hitting the button — fast enough that it feels
  // like a mute button rather than a setting.
  setInterval(pollMute, 3000);
  pollMute();
  // Ticker colours change when someone edits them on the Command Center, which
  // is a human action on a page nobody is watching the clock on. 30s.
  setInterval(pollTickerColors, 30000);
  pollEvents();
  pollCryptoPrices();
  pollStreamEvents();
  beat();
})();
