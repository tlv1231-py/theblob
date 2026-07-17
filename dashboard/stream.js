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

  // The mood readout is gone from the stage — it captioned a performance the
  // character was already giving, in the one gap between him and his score.
  // The call sites stay and route through here rather than being deleted: mood
  // is still the most useful single fact about him on a headless box, so it
  // goes to _TND_DBG instead of to the viewer. Put the element back and it
  // lights up again.
  var _mood = 'IDLE';
  function showMood() {
    _mood = blob.getMood();
    var el = $('blob-mood');
    if (el) el.textContent = _mood;
  }

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
    showMood();
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

    // ── Sound is ALWAYS ON ──────────────────────────────────────────────
    // The mute is gone. There used to be a preview_muted policy that silenced
    // every render except ?live=1, so the operator could kill the noise on their
    // desk without touching the broadcast. It worked exactly as designed and
    // that was the problem: it sat at 1 for hours, and a silent phone reads as a
    // broken phone, not as a setting on another page doing its job. It cost more
    // debugging than it ever saved.
    //
    // Removed rather than defaulted to 0, and the HQ button removed with it. A
    // toggle that no longer toggles anything is a placebo, and this page already
    // has one hard rule about those.
    //
    // If the noise ever needs killing again: mute the TAB (every browser has
    // that), or close it. Neither can reach the broadcast, which is the property
    // the old split existed to protect.
    var isLive = !!window._TND_LIVE;
    function init() {
      if (ctx) return;
      try {
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        ctx.resume().then(function() { ready = true; }).catch(function() {});
      } catch (e) {}
    }
    // Any gesture unlocks. Harmless if it never comes (the encoder's headless
    // Chromium runs with no-user-gesture-required and never needs it).
    //
    // Listened for on the PARENT document as well as this one. This page is an
    // iframe inside Streamlit, and a tap only reaches the window it lands in —
    // on a phone almost every tap lands on the parent chrome, not on the stage,
    // so the iframe's context stayed suspended no matter how much you prodded
    // it. Same-origin, so reaching up is allowed; wrapped anyway because if it
    // ever isn't, a thrown SecurityError here would take the whole page down
    // over a sound effect.
    function unlock() {
      init();
      if (ctx && ctx.state === 'suspended') ctx.resume();
      ready = true;
    }
    // NOT `once`. A gesture that fails to unlock — the context not yet built, a
    // resume() rejected, iOS in one of its moods — used to consume the listener
    // and there was no second chance however many times you tapped. Every
    // gesture now retries; resume() on a running context is free.
    var GESTURES = ['pointerdown', 'keydown', 'touchstart', 'touchend', 'click'];
    GESTURES.forEach(function(ev) {
      window.addEventListener(ev, unlock, { passive: true });
      try {
        if (window.parent && window.parent !== window && window.parent.document) {
          window.parent.document.addEventListener(ev, unlock, { passive: true });
        }
      } catch (e) {}
    });
    init();

    // One gate for every sound on the page: play() and note() are the only two
    // places an oscillator is ever created, so nothing can slip past this.
    // Kept as a named no-op so the two call sites below still read as gates —
    // they are the ONLY places an oscillator is ever created, and that
    // chokepoint is worth preserving even now that nothing closes it.
    function silent() { return false; }

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
      // ── JACKPOT — money, and only money ─────────────────────────────────
      // The fanfare is a fanfare: a triplet and a held note, the sound of an
      // event. This is the sound of a PAYOUT, and it has to be a different
      // animal or a $50 lands with the same weight as a follow.
      //
      // Three parts, straight off a cabinet:
      //   1. A rising run. Not a chord — a RUN, because a jackpot climbs. It is
      //      the major pentatonic, which is the scale that cannot sound wrong,
      //      which is why every arcade in history is built on it.
      //   2. The hit: a fat octave-stacked chord over a triangle bass.
      //   3. The COIN CASCADE — a scatter of short high blips at irregular
      //      spacing. Regular spacing reads as a melody; irregular reads as
      //      coins hitting a tray, and that is the whole illusion.
      //
      // ~1.6s total, which is longer than anything else on the page makes. It
      // is allowed: somebody paid.
      jackpot: function() {
        if (!ctx) return;
        if (ctx.state === 'suspended') { ctx.resume(); return; }
        var V = 0.05;
        // 1. the climb — C major pentatonic, two octaves
        var run = [523, 587, 659, 784, 880, 1047, 1175, 1319, 1568, 1760];
        for (var i = 0; i < run.length; i++) {
          note(run[i], i * 0.045, 0.05, V * 0.8);
        }
        // 2. the hit — root, fifth, octave, plus the octave above
        var t = run.length * 0.045;
        note(1047, t, 0.55, V * 1.3);          // C6
        note(1568, t, 0.55, V * 0.8);          // G6
        note(2093, t, 0.55, V * 0.6);          // C7
        note(131,  t, 0.30, V * 1.1, 'triangle');   // C3 — the thump
        note(262,  t, 0.55, V * 0.9, 'triangle');   // C4
        // 3. the coin cascade — irregular on purpose
        var coins = [0.10, 0.17, 0.21, 0.30, 0.34, 0.45, 0.52, 0.56, 0.68, 0.79, 0.86, 0.98];
        for (var c = 0; c < coins.length; c++) {
          var pitch = 2093 + Math.round(Math.random() * 3) * 220;
          note(pitch, t + 0.18 + coins[c], 0.035, V * 0.42);
        }
      },

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

  // ── Per-glyph tickers ────────────────────────────────────────────────────
  // Every ticker is one <i> per character rather than a string, so a wave can
  // travel THROUGH the word. Nothing else may set .t-sym's textContent directly
  // — that would drop the glyphs and silently kill the wave on that tile only,
  // which reads as one tile being mysteriously dead.
  function setSym(sp, text) {
    if (!sp) return;
    sp.innerHTML = '';
    for (var i = 0; i < text.length; i++) {
      var c = document.createElement('i');
      c.textContent = text[i];
      sp.appendChild(c);
    }
  }

  function makeTile(sym, tint) {
    var el = document.createElement('div');
    el.className = 'tile';
    el.setAttribute('data-sym', sym);
    el.style.setProperty('--tc', tint || '#8060a0');
    var sp = document.createElement('span');
    sp.className = 't-sym';
    setSym(sp, sym.replace('/USD', ''));
    el.appendChild(sp);
    return el;
  }

  // ── The wave ─────────────────────────────────────────────────────────────
  // Each character rises ONE pixel in series, so a ripple runs left→right
  // through every ticker on the board. One pixel is the whole trick: at 38px
  // glyphs it is barely a shimmer standing still, but across 14 tiles it is the
  // difference between a board and a screenshot of a board. Any more and it
  // competes with the trade beat, which is the only thing here allowed to shout.
  //
  // ONE interval for the entire board, not one per tile. 14 tiles x ~4 glyphs is
  // ~56 elements; 56 timers would each wake independently and the phases would
  // drift apart into noise instead of a wave.
  //
  // 10fps and whole pixels — the Blob's clock and grid (BLOB.md). setInterval,
  // because a CSS animation here is inert.
  var WAVE_AMP = 1;          // "up a pixel"
  var WAVE_SPREAD = 0.9;     // radians of phase per glyph — the wavelength
  var WAVE_SPEED = 0.55;     // radians per tick
  var _waveT = 0;

  function waveTick() {
    _waveT += WAVE_SPEED;
    var syms = document.querySelectorAll('#pos-list .t-sym');
    for (var s = 0; s < syms.length; s++) {
      var gl = syms[s].children;
      // Offset each tile by its index so the board ripples as one field rather
      // than 14 words all bobbing in lockstep.
      var base = _waveT - s * 0.35;
      for (var g = 0; g < gl.length; g++) {
        var y = -Math.round((Math.sin(base - g * WAVE_SPREAD) * 0.5 + 0.5) * WAVE_AMP);
        gl[g].style.transform = y ? 'translateY(' + y + 'px)' : '';
      }
    }
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
  // The trade poll's cadence. Named because ROLL_WAIT is derived from it — the
  // two are one decision, and 4s written twice is a bug waiting for whoever
  // changes only the obvious one.
  var POLL_MS = 4000;

  var stage = { owner: null, since: 0 };   // null | 'popup' | 'speaks' | 'trade'

  function stageTake(lane) { stage.owner = lane; stage.since = Date.now(); }

  function stageDone() {
    stage.owner = null;
    stage.since = 0;
    stagePump();
  }

  // ── The watchdog ─────────────────────────────────────────────────────────
  // A lane holds the floor until it calls stageDone. If it never does — a timer
  // chain broken by a thrown callback, a detached node, anything — the stage is
  // held FOREVER and the broadcast freezes: no trades, no popups, no dialogue,
  // just a still frame. Observed exactly that: the speaks lane wedged mid-word
  // and 4s of watching showed zero mutations with 2 popups, 3 speaks and 8
  // trades stacked behind it.
  //
  // This page runs unattended for days with nobody to reload it, so "a lane can
  // deadlock the stream" is not an acceptable failure mode no matter how rare
  // the trigger. The floor is therefore taken on a LEASE, not a lock.
  //
  // The bound is generous — a popup burst legitimately runs ~36s (6 events at
  // ~6s each) — because this must never fire during normal operation. It is a
  // last resort, not pacing, and it says so loudly when it trips.
  var STAGE_MAX_MS = 45000;

  function stageWatchdog() {
    if (!stage.owner || !stage.since) return;
    // A HIDDEN tab is throttled, not wedged. Chrome slows timers hard in a
    // background tab, so a beat that normally takes 3s can straddle a minute and
    // look exactly like a deadlock — it fooled this watchdog into reporting a
    // 53s "wedge" that was nothing but a backgrounded window. The real capture
    // renders to a virtual display and is never hidden, so skipping here costs
    // the broadcast nothing and removes the only known false positive.
    if (document.hidden) return;
    var held = Date.now() - stage.since;
    if (held < STAGE_MAX_MS) return;
    console.warn('[stream] lane "' + stage.owner + '" held the stage ' +
                 Math.round(held / 1000) + 's — forcing release. Queues: ' +
                 JSON.stringify({ ann: annQ.length, speak: speakQ.length, trade: tradeQ.length }));
    // Tear down whatever the wedged lane was mid-way through, or its corpse
    // stays on screen over whatever plays next.
    clearInterval(speakTypeT); clearTimeout(speakHoldT);
    clearInterval(annTypeT);   clearTimeout(annHoldT);
    annClose();
    stageDone();
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
  // ALL CYBERPUNK. The money events used to be #00ff9d — trading-terminal green,
  // borrowed from the P&L language on the board. It was the one colour in the box
  // that came from a spreadsheet rather than from an arcade, and it made a
  // donation look like a winning trade. The palette is the house set now:
  // pink is identity, cyan is money, purple is scale. Only risk_breach keeps its
  // red, because that one IS an alarm.
  var ANN = {
    donation:        { c: '#00e5ff', i: '♥', verb: 'DONATED' },
    superchat:       { c: '#00e5ff', i: '♥', verb: 'SUPERCHATTED' },
    supersticker:    { c: '#9400ff', i: '♥', verb: 'SENT A STICKER' },
    bits:            { c: '#00e5ff', i: '◆', verb: 'CHEERED' },
    membership_gift: { c: '#ff00cc', i: '♦', verb: 'GIFTED' },
    subscription:    { c: '#ff00cc', i: '★', verb: 'SUBSCRIBED' },
    follow:          { c: '#9400ff', i: '◈', verb: 'FOLLOWED' },
    raid:            { c: '#ff00cc', i: '⚡', verb: 'RAIDED' },
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
  // The verb only. The AMOUNT has its own element now — it is the single most
  // important fact in the box and it was set in 15px verb text, the same size as
  // the grammar wrapped around it and half the size of the handle.
  function actOf(type, p) {
    if (type === 'risk_breach') return 'just BROKE ' + (p.limit || '') + ' !!!';
    return 'just ' + (VERB[type] || 'DID SOMETHING') + ' !!!';
  }

  var annQ = [], annTypeT = null, annHoldT = null;

  function annPush(type, payload, id) {
    if (!ANN[type]) return;
    annQ.push({ type: type, p: payload || {}, id: id });
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
  // ═══════════════════════════════════════════════════════════════════════
  // THE BOX — how it arrives and how it dies
  //
  // ONE treatment for BOTH lanes. A viewer's donation and a line of Blobby's
  // dialogue are different messages in the same window; if they opened
  // differently the window would stop being a window and start being two.
  //
  // IN — it SNAPS. A hot line at the floor thrown open in seven quantized
  // frames with an overshoot: a menu opening, not a panel fading. No easing
  // anywhere. An ease is the single loudest modern-web tell there is, and this
  // is a DMG. It grows UP from the bottom edge because that is where a Gameboy
  // text box comes from — see transform-origin in the CSS.
  //
  // OUT — it DECAYS. The text rots back into the junk x decoded out of, the LCD
  // lattice eats the panel from the inside until the box is nothing but its own
  // pixel grid, and the whole thing tears sideways a pixel at a time before
  // collapsing. ~880ms against the entrance's ~240ms, deliberately: arriving is
  // an EVENT and leaving is an afterthought, and a box that vanished as fast as
  // it appeared would read as a dropped frame rather than a decision.
  //
  // Both are setInterval. Standing rule, and this page's animation clock cannot
  // be trusted to run a CSS keyframe at all.
  // ═══════════════════════════════════════════════════════════════════════
  // A hot slit that throws itself open, RIPS THROUGH THE PALETTE, glitches, and
  // settles. `c` overrides the bezel per frame — cyan, magenta, purple, in the
  // house set — then null hands it back to the event's own colour. `k` is a
  // skewX glitch in degrees: hard, alternating, and only during the throw, so
  // it reads as a signal punching in rather than as a wobble.
  //
  // The colour cycle is the cyberpunk part. A box that opens in one colour is a
  // panel; a box that strobes through three on the way in is a machine coming
  // online.
  var BOX_IN_STEP = 34;
  var BOX_IN = [
    // scaleY, brightness, bezel override, skewX
    { y: 0.03, b: 3.4, c: '#00e5ff', k:  0 },
    { y: 0.17, b: 2.6, c: '#ff00cc', k: -7 },
    { y: 0.49, b: 2.0, c: '#9400ff', k:  5 },
    { y: 0.83, b: 1.5, c: '#00e5ff', k: -3 },
    { y: 1.09, b: 1.3, c: '#ff00cc', k:  2 },   // past the frame
    { y: 0.96, b: 1.1, c: null,      k: -1 },   // and back
    { y: 1.00, b: 1.0, c: null,      k:  0 }
  ];

  var BOX_OUT_STEP = 55, BOX_OUT_FRAMES = 16;
  // Opacity in DISCRETE steps. A linear ramp is a dissolve, and a dissolve is
  // not chaos — it is a fade with extra words. Quantizing makes the panel drop
  // out in visible chunks, which is what decay looks like on a 4-bit display.
  var BOX_OUT_A = [1, 1, 0.94, 0.94, 0.8, 0.8, 0.62, 0.62,
                   0.46, 0.32, 0.32, 0.19, 0.11, 0.06, 0.02, 0];
  var _boxT = null;

  function boxOpen(settleColor) {
    var lcd = $('ev-lcd');
    if (!lcd) return;
    clearInterval(_boxT);
    lcd.style.removeProperty('--lcd-a');
    lcd.style.opacity = '';
    var i = 0;
    _boxT = setInterval(function() {
      if (i >= BOX_IN.length) {
        clearInterval(_boxT); _boxT = null;
        lcd.style.transform = ''; lcd.style.filter = '';
        // Hand the bezel back to whatever the event actually is. Passed in
        // rather than read back, because the strobe overwrote it and the frames
        // above have no idea what they interrupted.
        if (settleColor) lcd.style.setProperty('--ev-c', settleColor);
        return;
      }
      var f = BOX_IN[i++];
      lcd.style.transform = 'scaleY(' + f.y + ') skewX(' + f.k + 'deg)';
      lcd.style.filter = 'brightness(' + f.b + ')';
      if (f.c) lcd.style.setProperty('--ev-c', f.c);
      else if (settleColor) lcd.style.setProperty('--ev-c', settleColor);
    }, BOX_IN_STEP);
  }

  // Kills whatever the box was doing and takes it apart. `done` runs when there
  // is nothing left — the lane must not release the stage until then, or the
  // next thing plays over a corpse.
  function boxDecay(done) {
    var lcd = $('ev-lcd');
    if (!lcd || !$('s-events').classList.contains('showing')) { done(); return; }

    clearInterval(_boxT);
    // Whatever was typing must stop, or it types into the rot.
    clearInterval(annTypeT); clearTimeout(annHoldT);
    clearInterval(speakTypeT); clearTimeout(speakHoldT);

    var texts = [$('ev-name'), $('ev-act'), $('ev-msg')].map(function(el) {
      return { el: el, s: el ? el.textContent : '' };
    });

    var i = 0;
    _boxT = setInterval(function() {
      var p = i / (BOX_OUT_FRAMES - 1);      // 0 .. 1

      // Each glyph rots on its OWN roll, so the word visibly comes apart rather
      // than being swapped for a different word. This is the decode played
      // backwards — the same alphabet it resolved out of, returning to it.
      texts.forEach(function(t) {
        if (!t.s || !t.el) return;
        var out = '';
        for (var k = 0; k < t.s.length; k++) {
          out += (t.s[k] !== ' ' && Math.random() < p * 1.2)
            ? SCRAM[Math.floor(Math.random() * SCRAM.length)]
            : t.s[k];
        }
        t.el.textContent = out;
      });

      // The panel eats itself with its own pixel lattice — by the last frame the
      // box IS the grid and nothing else. Cheapest possible disintegration: the
      // lattice is already there, it just gets louder.
      lcd.style.setProperty('--lcd-a', (0.30 + p * 0.7).toFixed(2));

      // Tear. Whole even pixels, and NOT every frame — a constant jitter is
      // noise, an intermittent one is a signal breaking up.
      var tear = (i % 3 === 0) ? 0 : Math.round((Math.random() - 0.5) * p * 7) * 2;
      lcd.style.transform = 'translateX(' + tear + 'px) scaleY(' + (1 - p * 0.07).toFixed(3) + ')';
      lcd.style.opacity = BOX_OUT_A[Math.min(i, BOX_OUT_A.length - 1)];
      lcd.style.filter = 'brightness(' + (1 + p * 0.7).toFixed(2) + ')';

      i++;
      if (i < BOX_OUT_FRAMES) return;
      clearInterval(_boxT); _boxT = null;
      lcd.style.transform = ''; lcd.style.opacity = '';
      lcd.style.filter = ''; lcd.style.removeProperty('--lcd-a');
      done();
    }, BOX_OUT_STEP);
  }

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
    startAmtRgb(false);        // the sweep must not outlive the box it lit
    annBadge();
  }

  function annBadge() {
    var b = $('ev-badge');
    if (!b) return;
    var n = annQ.length;
    b.textContent = n > 0 ? '+' + n + ' MORE' : '';
    b.className = 'ev-badge' + (n > 0 ? ' on' : '');
  }

  // ── The amount's rainbow ─────────────────────────────────────────────────
  // Same trick as a power-up's amount: three hues 120deg apart — an actual RGB
  // triad — sweeping together, so several colours show at once. That
  // simultaneity is what reads as a cheap LED sign rather than as a tasteful
  // colour animation.
  //
  // Its own ticker rather than puTick's: the box comes and goes on the popup
  // lane's clock, and borrowing a loop that only runs while power-ups exist
  // would leave the number grey whenever the ring was empty.
  var _amtT = null, _amtF = 0;

  function startAmtRgb(on) {
    clearInterval(_amtT); _amtT = null;
    var el = $('ev-amt');
    if (!el) return;
    if (!on) {
      el.style.removeProperty('--ev-a1');
      el.style.removeProperty('--ev-a2');
      el.style.removeProperty('--ev-a3');
      return;
    }
    _amtF = 0;
    _amtT = setInterval(function() {
      _amtF++;
      var h = (_amtF * 7) % 360;
      el.style.setProperty('--ev-a1', 'hsl(' + h + ',100%,62%)');
      el.style.setProperty('--ev-a2', 'hsl(' + ((h + 120) % 360) + ',100%,58%)');
      el.style.setProperty('--ev-a3', 'hsl(' + ((h + 240) % 360) + ',100%,58%)');
    }, 45);
  }

  function annNext() {
    var lcd = $('ev-lcd');
    if (!lcd) return;
    if (!annQ.length) {
      // The box holds the stage while it dies. Releasing first would let the
      // next thing play over a corpse mid-decay.
      boxDecay(function() {
        annClose();
        // Guarded because boot calls annNext() once to settle the panel into
        // its idle state, and that call holds no floor to give back.
        if (stage.owner === 'popup') {
          stageDone();
          // Hand x back to the AFK cycle on the same 2s rule a trade uses —
          // otherwise "is happy!" waves forever after the last dono of the night.
          clearTimeout(_idleT); clearTimeout(_afkT);
          _idleT = _afkT = setTimeout(afkNext, AFK_AFTER);
        }
      });
      return;
    }
    var ev = annQ.shift();
    annBadge();

    var cfg = ANN[ev.type];
    // Only when it is actually ARRIVING. Mid-burst the box is already open and
    // the next donation just replaces its contents — re-snapping it open for
    // every event in a dono train would read as the window flickering rather
    // than as three people being thanked.
    var arriving = !$('s-events').classList.contains('showing');
    $('s-events').classList.add('showing');   // the overlay arrives
    lcd.classList.remove('idle');
    lcd.classList.remove('speaking');
    lcd.classList.add('open');
    lcd.style.setProperty('--ev-c', cfg.c);
    $('ev-bigicon').textContent = cfg.i;
    $('ev-more').className = 'ev-more';
    // AFTER --ev-c, and told what to settle on: the entry strobes the bezel
    // through the palette and has to know what colour to hand back. Called
    // before, its frames would fire after this line and the two would fight over
    // the same property.
    if (arriving) boxOpen(cfg.c);

    // Money hits the panel itself, not just the text.
    //
    // Asks what the event IS, not what colour it happens to be. This used to be
    // `cfg.c === '#00ff9d'` — repainting the palette to cyberpunk silently broke
    // it, because no colour is that green any more and every money event quietly
    // stopped registering as money. A colour is a rendering decision; PU_TYPES is
    // the fact.
    var isMoney = !!PU_TYPES[ev.type];
    if (isMoney) {
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
      showMood();
      // A viewer paying is the loudest thing that happens on this stream.
      bg.pulse(isMoney ? 'money' : (react.sfx === 'loss' ? 'loss' : 'enter'), 0.30);
    }
    // Money gets the jackpot; everything else gets the fanfare. A follow and a
    // $50 must not sound the same.
    if (isMoney) SFX.jackpot(); else SFX.fanfare();
    // x celebrates on the same frame as the box and the sound, and holds for
    // as long as the popup lane owns the stage — see the empty branch above,
    // which hands the sentence back to the AFK cycle when the burst drains.
    if (VIEWER_EVENTS[ev.type]) {
      setStatusHappy();
      // Money buys an orbit AND a thank-you. Both fire here, with the box.
      if (PU_TYPES[ev.type] && Number(ev.p.amount) > 0) {
        puAdd(ev.id, ev.p.from || 'SOMEONE', Number(ev.p.amount));
        thankThem(ev.p.from || 'SOMEONE', Number(ev.p.amount));
      }
    } else {
      // A non-viewer popup must actively CLEAR the celebration, not merely
      // decline to set one. Measured: a donation and a risk_breach in the same
      // burst left "blob is happy!" waving through the drawdown alarm for the
      // full 10.3s the lane held the floor. Gating the set was not enough —
      // the state persists until something overwrites it.
      statusLine(react && react.mood === 'SCARED' ? 'is scared' : 'is busy');
    }

    var name = nameOf(ev.type, ev.p);
    var act  = actOf(ev.type, ev.p);
    var amt  = amountFor(ev.type, ev.p);
    var msg  = (ev.p.message || '').slice(0, 42);
    var nEl = $('ev-name'), aEl = $('ev-act'), mEl = $('ev-msg'), amEl = $('ev-amt');
    nEl.innerHTML = ''; aEl.textContent = ''; mEl.textContent = '';

    // THE AMOUNT — big, and rainbow if it is money.
    //
    // Text goes on AFTER the fit. fitNoWrap ends by clearing the element, which
    // is right for the name and the comment (a typewriter fills those in a
    // moment) and wrong for this one, which is never typed — it just appears.
    // Measured: the amount rendered at a perfect 62px and completely blank.
    if (amEl) {
      amEl.className = 'ev-amt' + (amt ? ' on' : '') + (isMoney ? ' rgb' : '');
      amEl.style.fontSize = '';
      amEl.textContent = '';
      if (amt) {
        fitNoWrap(amEl, amt, 20, 62);
        amEl.textContent = amt;
      }
    }
    startAmtRgb(isMoney && !!amt);

    // BOTH lines are sized to fit before a glyph is typed.
    //
    // The action line MUST be reset here even if it were never fitted: ev-act is
    // shared with the speaks lane, and fitSpeak leaves an inline font-size on it.
    // Without this, a blob_speak at 105px leaked straight into the next donation
    // — "DEGENMIKE / just SUPER" rendered enormous and clipped mid-word, which is
    // exactly what it looked like on air.
    //
    // Maxima, not fixed sizes: the handle is what someone paid for, so it takes
    // what the box will give (up to 56) and only shrinks when it must. The action
    // line is grammar around it and stays subordinate.
    fitNoWrap(nEl, name, 14, 56, true);   // stamped — the name renders as glyphs
    fitNoWrap(aEl, act, 11, 30);          // plain text
    // THE COMMENT gets its own line and FILLS it. It was 21px of dim purple with
    // text-overflow:ellipsis — the smallest thing in the box and the only part a
    // viewer actually WROTE, quietly truncated. It is nowrap, so fitting to width
    // is what "at least its own line" means: as big as the line will carry.
    //
    // Ceiling 52, not 40: at 40 a short comment stopped less than two-thirds
    // across the box and still read as a footnote. The band budget takes it —
    // nameline ~62 + verb ~45 + this ~57 + margins is ~190 against 220 usable.
    if (msg) fitNoWrap(mEl, msg, 14, 52);

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

  // ── Autoscale — the line FILLS the window ────────────────────────────────
  // A Gameboy text box is a fixed frame: the text inside grows to use it rather
  // than the frame shrinking to the text. So three words land like a shout and
  // a long line still fits, without anyone choosing a size per message.
  //
  // Binary search, not a shrink loop: the range is 16..120px, so a linear walk
  // costs up to 100 forced reflows per line against 7 here. Measured on the
  // FULL text before a single glyph is typed — sizing as it types would make
  // the box visibly breathe, and the size would depend on how far the typewriter
  // had got rather than on the sentence.
  // MAX is set so a SHORT line is bound by the box, not by this number: the
  // window is ~192px of usable height at line-height 1.2, so one line tops out
  // near 160. A lower ceiling (120 was tried) left "hi" floating in 48px of dead
  // space — capped rather than filled, which is not what autoscale means. MIN is
  // the floor at which VT323 stops being readable on a phone-sized Shorts view.
  var SPEAK_MIN = 16, SPEAK_MAX = 160;

  // Fit a single NOWRAP line to its own width. The popup's handle and action
  // line are both nowrap + overflow:hidden, so an overlong one neither shrinks
  // nor wraps — it silently CLIPS, and "DEGENMIKE just SUPERCHATTED $10 !!!"
  // lost its back half to the box edge with no sign anything was missing.
  //
  // clientWidth is the laid-out content box (it already respects the 54px
  // indent); scrollWidth is what the text actually needs. The gap between them
  // IS the clipping.
  // One <i> per glyph — the shape the announcer's name actually renders in.
  function stampGlyphs(el, text) {
    el.innerHTML = '';
    for (var i = 0; i < text.length; i++) {
      var c = document.createElement('i');
      c.textContent = text[i] === ' ' ? ' ' : text[i];
      el.appendChild(c);
    }
  }

  // `stamped` measures with per-glyph <i> boxes instead of a plain string.
  // MEASURE THE WAY YOU RENDER: each inline-block glyph rounds its advance up to
  // its own box, so the stamped name is ~2.8% wider than the same string as text
  // (measured: 528px vs 514px at 56px). Fitting against the plain string picked
  // a size the real render then overflowed — a clip of exactly the last glyph or
  // two, which looks like a rendering artefact rather than a sizing bug.
  function fitNoWrap(el, text, minPx, maxPx, stamped) {
    if (!el) return;
    var put = stamped ? function() { stampGlyphs(el, text); }
                      : function() { el.textContent = text; };
    put();
    var lo = minPx, hi = maxPx, best = minPx;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      el.style.fontSize = mid + 'px';
      if (el.scrollWidth <= el.clientWidth) { best = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    el.style.fontSize = best + 'px';
    el.innerHTML = '';
    return best;
  }

  function fitSpeak(aEl, text) {
    var lcd = $('ev-lcd'), body = $('ev-body');
    if (!lcd || !body) return;
    var lcs = getComputedStyle(lcd), bcs = getComputedStyle(body);
    // clientWidth/Height exclude the border and include padding, so subtract
    // padding only — the box is border-box (see the global reset). The ▼ reserve
    // is the body's own padding-bottom, read from CSS rather than duplicated as
    // a constant here: two copies of that number would drift the first time
    // anyone nudged the arrow.
    var availW = lcd.clientWidth
               - parseFloat(lcs.paddingLeft) - parseFloat(lcs.paddingRight)
               - parseFloat(bcs.paddingLeft) - parseFloat(bcs.paddingRight);
    var availH = lcd.clientHeight
               - parseFloat(lcs.paddingTop) - parseFloat(lcs.paddingBottom)
               - parseFloat(bcs.paddingTop) - parseFloat(bcs.paddingBottom);

    // The "blob" header sits above the line and takes real height. Measured
    // rather than assumed — it is the same element a viewer's handle uses, and
    // its size is set by CSS that may change without this code hearing about it.
    var nl = document.querySelector('.ev-nameline');
    if (nl && getComputedStyle(nl).display !== 'none') {
      availH -= nl.offsetHeight + (parseFloat(getComputedStyle(nl).marginBottom) || 0);
    }

    aEl.textContent = text;
    var lo = SPEAK_MIN, hi = SPEAK_MAX, best = SPEAK_MIN;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      aEl.style.fontSize = mid + 'px';
      // scrollHeight catches too many wrapped lines; scrollWidth catches a
      // single unbreakable word wider than the box, which wrapping cannot save.
      if (aEl.scrollHeight <= availH && aEl.scrollWidth <= availW) { best = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    aEl.style.fontSize = best + 'px';
    aEl.textContent = '';        // typing begins from empty, at the settled size
    return best;
  }

  function speakNext() {
    var lcd = $('ev-lcd');
    if (!lcd) return;
    if (!speakQ.length) {
      // Same death as a popup — it is the same window. See boxDecay.
      boxDecay(function() {
        annClose();
        if (stage.owner === 'speaks') {
          stageDone();
          // Hand x back to the AFK cycle on the same 2s rule the popup lane and
          // a trade use, or "says:" would sit there forever after his last word.
          clearTimeout(_idleT); clearTimeout(_afkT);
          _idleT = _afkT = setTimeout(afkNext, AFK_AFTER);
        }
      });
      return;
    }
    var s = speakQ.shift();

    // Same arrival as a popup, and only when it is actually arriving — a second
    // line mid-burst replaces the contents of a box that is already open.
    var arriving = !$('s-events').classList.contains('showing');
    $('s-events').classList.add('showing');
    lcd.classList.remove('idle');
    lcd.classList.remove('pop');            // a popup's money hit is not his
    lcd.classList.add('open');
    lcd.classList.add('speaking');          // his skin, not the announcer's
    lcd.style.setProperty('--ev-c', '#ff00cc');
    startAmtRgb(false);                     // no amount in his box
    if (arriving) boxOpen('#ff00cc');       // settles back to his pink
    $('ev-more').className = 'ev-more';

    // The header. Same slot and shape a viewer's handle uses, so the box reads
    // the same way whoever is talking — but it is HIM, so it is his pink and it
    // says only "blob". Plain textContent, not the announcer's per-glyph <i>
    // stamp: the handle assembles because a name is the news, and his own
    // nameplate is not news, it is just who is speaking.
    var nEl = $('ev-name'), aEl = $('ev-act'), mEl = $('ev-msg');
    nEl.innerHTML = ''; aEl.textContent = ''; mEl.textContent = '';
    nEl.style.fontSize = '';        // drop any size fitNoWrap left on a handle
    nEl.textContent = 'blob';
    $('ev-bigicon').textContent = '';

    statusLine('says:');

    // Size to the box now — after the classes are on (a display:none element
    // measures as 0) and before the first glyph.
    fitSpeak(aEl, s.text);

    if (s.mood) { blob.setMood(s.mood, 30); showMood(); }

    clearInterval(speakTypeT); clearTimeout(speakHoldT);

    // One glyph at a time with a blip — the Gameboy convention, and the reason
    // it reads as a voice rather than as a label that appeared.
    // `h` is a LOCAL handle. speakTypeT is shared, so a re-entrant speakNext
    // reassigns it and this callback's clearInterval(speakTypeT) would then kill
    // the NEW typewriter instead of itself — leaving two chains, one of them
    // orphaned and running forever.
    var i = 0, h;
    h = setInterval(function() {
      // The whole body is guarded. `i` only advances if the glyph lands, so ANY
      // throw in here (audio, a detached node) freezes i and the line stops mid
      // word with the lane still holding the floor — the exact deadlock observed.
      // A voice is not worth wedging the broadcast: on failure, finish the line.
      try {
        if (i < s.text.length) {
          aEl.textContent += s.text[i];
          if (s.text[i] !== ' ') SFX.blip();   // blip on non-spaces, or word gaps click
          i++;
          return;
        }
      } catch (err) {
        console.warn('[stream] speak typewriter failed at glyph ' + i + ':', err);
        try { aEl.textContent = s.text; } catch (e2) {}
      }
      clearInterval(h);
      if (speakTypeT === h) speakTypeT = null;
      var more = $('ev-more');
      if (more) more.className = 'ev-more on';
      // Shorter hold during a burst so a queued line isn't left waiting.
      speakHoldT = setTimeout(speakNext, speakQ.length ? 900 : SPEAK_HOLD);
    }, SPEAK_STEP);
    speakTypeT = h;
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
      // Be generous about the key. HQ hands this page raw JSON, and the natural
      // mistake is to overwrite the KEY with the line you want said rather than
      // the value — which produced {"I see what you're doing here.": "..."} and
      // a silently dropped event. If there is exactly one string that isn't a
      // known field, that IS the line, whatever it got called.
      var line = p.message || p.text || p.line;
      if (!line) {
        for (var k in p) {
          if (k === 'mood' || typeof p[k] !== 'string') continue;
          line = p[k];               // the value...
          if (!line) line = k;       // ...or the key, if they swapped them
          break;
        }
      }
      if (!line) {
        // Never fail silently: the event aired, so SAY that it arrived broken.
        // A stream that swallows a malformed event looks identical to one that
        // never received it, which is the hardest possible thing to debug.
        console.warn('[stream] blob_speak with no readable line:', p);
        blobSpeak('...?');
        return;
      }
      blobSpeak(line, { mood: p.mood || null });
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
      showMood();
      return;
    }

    annPush(ev.event_type, p, ev.id);
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
          audio: SFX.isReady() ? 'on' : 'blocked',
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

  // ── The arcade entry ─────────────────────────────────────────────────────
  // The ticker ASSEMBLES: each glyph drops in on its own beat, left to right,
  // overshooting and settling. It is the ambient wave at full volume — same
  // mechanic, ~20x the amplitude — so the entry reads as the board waking up
  // rather than as an unrelated effect bolted on.
  //
  // Per-glyph and staggered is the whole point of "individually": a tile that
  // pops as one block is a tile appearing, and a tile whose letters land one
  // after another is a tile being PLACED.
  var ENTER_FRAMES = [
    { y: -22, s: 1.9 }, { y: -12, s: 1.5 }, { y: -5, s: 1.2 },
    { y:   2, s: 0.9 }, { y:   1, s: 1.05 }, { y:  0, s: 1.0 }
  ];
  var ENTER_STEP = 45;       // ms per frame
  var ENTER_STAGGER = 1;     // frames of delay per glyph — the left-to-right run

  function enterSym(sp) {
    if (!sp) return;
    var gl = sp.children;
    if (!gl.length) return;
    clearInterval(sp._ent);
    var f = 0;
    var total = ENTER_FRAMES.length + gl.length * ENTER_STAGGER;
    sp._ent = setInterval(function() {
      if (f >= total) {
        clearInterval(sp._ent); sp._ent = null;
        // Hand every glyph back to the ambient wave, which owns transform from
        // here. Clearing is required: a leftover inline transform would pin the
        // glyph and the wave would look dead on exactly the tiles that traded.
        for (var g = 0; g < gl.length; g++) gl[g].style.transform = '';
        return;
      }
      for (var g2 = 0; g2 < gl.length; g2++) {
        var k = f - g2 * ENTER_STAGGER;
        if (k < 0) { gl[g2].style.opacity = '0'; continue; }
        gl[g2].style.opacity = '1';
        var fr = ENTER_FRAMES[Math.min(k, ENTER_FRAMES.length - 1)];
        gl[g2].style.transform = 'translateY(' + fr.y + 'px) scale(' + fr.s + ')';
      }
      f++;
    }, ENTER_STEP);
  }

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

  // ── Ticker colour ────────────────────────────────────────────────────────
  // Ported from home_nav.js `symCol()`, deliberately verbatim. The Command
  // Center is where colours are decided, so this page agreeing with it is the
  // whole requirement — any divergence here is a bug by definition. If you
  // change the palette or the hash, change it in BOTH or the same ticker will
  // be two different colours on two screens.
  //
  // THREE tiers, and missing the first one is what made 8 of 9 tickers white:
  //   1. hash → PALETTE        EVERY ticker gets a colour, always
  //   2. TICKER_OVR            built-in defaults for a handful
  //   3. ticker_colors table   what you actually edit on the Command Center
  //
  // The table is an OVERRIDE map, never the source. It holds 3 rows (AMD, CAT,
  // CRV) against 9 symbols on the board, so a table-only lookup coloured CRV
  // and fell through to white for BTC/ETH/SOL/AVAX/DOGE/LINK/XTZ/BCH. That was
  // not a naming bug — 'BTC/USD' normalises to 'BTC' correctly; there simply
  // has never been a row for it, and there does not need to be.
  var PALETTE = ['#00e5ff', '#cc00ff', '#ff9900', '#e040fb', '#40c4ff',
                 '#ff6b35', '#00ffcc', '#f7b731', '#7c4dff', '#18ffff'];
  var TICKER_OVR = { ETH: '#e040fb', CRV: '#f7b731', XTZ: '#00bfff', NUE: '#ff4dd2' };

  function _hashCol(s) {
    var h = 0;
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffff;
    return PALETTE[h % PALETTE.length];
  }
  // Both forms exist in the wild — 'BTC/USD' from positions, 'BTCUSD' from some
  // feeds — and home_nav strips both. Match it.
  function bareSym(s) { return String(s || '').replace('/USD', '').replace('USD', ''); }

  var tickerCols = S.ticker_colors || {};   // tier 3, re-polled below
  function tickerColor(sym) {
    var c = bareSym(sym);
    return tickerCols[c] || TICKER_OVR[c] || _hashCol(c);
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

  // ═══════════════════════════════════════════════════════════════════════
  // DONATION POWER-UPS — a viewer's name in orbit
  //
  // Someone paid, so their handle circles the Blob like a power-up they stuck
  // on him. Two rules carry it:
  //
  //   DURATION = $1 : 1 MINUTE. A $5 dono orbits for 5 minutes; a $60 one for
  //   an hour. Not a design flourish — it is the promise that what you paid for
  //   stays on screen, and it is why the list has to be authoritative rather
  //   than a fire-and-forget animation. It survives a page reload because the
  //   expiry is a TIMESTAMP in the DB, not a countdown in a browser tab.
  //
  //   SIZE AND INTENSITY SCALE WITH THE AMOUNT, on a curve rather than a line.
  //   Linear would make a $100 dono fifty times the size of a $2 one and cover
  //   the character; a cube root keeps $2 legible and $100 enormous while both
  //   stay on screen. sqrt was too flat at the top, log too flat at the bottom.
  //
  // DOM, not canvas: a name is type. Rendering type on a canvas at this size
  // means hand-kerning a bitmap font to gain nothing.
  //
  // setInterval at 20fps — smoother than the Blob's 10, because this layer is
  // deliberately NOT of his world: it is a HUD over him, the one place allowed
  // to look modern-videogame rather than 8-bit.
  // ═══════════════════════════════════════════════════════════════════════
  var PU_FPS = 20;
  var PU_BASE_FONT = 20;      // px at the smallest dono
  var PU_FONT_GAIN = 13;      // px added per unit of scale
  // ── The wave ─────────────────────────────────────────────────────────────
  // The name's only motion: each glyph rises in series, same mechanic as the
  // board's tickers — but LOUD. The board runs 1px because 14 of them shimmering
  // would compete with the trade beat; a donor's name is meant to compete, so it
  // runs ~10-20x that.
  //
  // This replaced a 3D tumble with four ghost trails per name. That was 20 extra
  // nodes rewritten every frame for five power-ups, and it read as noise rather
  // than as celebration — the name was moving so much you could not read it,
  // which is the one thing a donor's name has to do.
  var PU_WAVE_BASE = 5;       // px of rise at the smallest dono
  var PU_WAVE_GAIN = 5;       // px added per unit of scale — intensity by amount
  var PU_WAVE_SPREAD = 0.8;   // radians of phase per glyph — the wavelength
  var PU_WAVE_SPEED = 0.34;   // radians per frame

  // ── The arrival ──────────────────────────────────────────────────────────
  // A new name does not fade in, it SLAMS in — on the dono event, alongside the
  // jackpot and the box. It is the only moment this element gets to be
  // flamboyant; after ~1.2s it settles into the ambient wave and behaves.
  //
  // Per-glyph and staggered: the whole name arriving as one block is a label
  // appearing, whereas letters landing in series is a name being PLACED. Same
  // reasoning as the board's tiles.
  //
  // Frames, not eases. Every one is a hard cut on the 20fps clock.
  var PU_IN_FRAMES = [
    // scale, y offset, rotation, brightness
    { s: 0.00, y: -70, r: -25, b: 4.0 },
    { s: 2.60, y: -34, r:  16, b: 3.4 },   // overshoot enormously
    { s: 0.55, y:  18, r: -11, b: 2.6 },   // undershoot past the mark
    { s: 1.75, y:  -9, r:   7, b: 2.0 },
    { s: 0.82, y:   5, r:  -4, b: 1.6 },
    { s: 1.28, y:  -3, r:   2, b: 1.3 },
    { s: 0.94, y:   1, r:  -1, b: 1.15 },
    { s: 1.08, y:   0, r:   0, b: 1.05 },
    { s: 1.00, y:   0, r:   0, b: 1.00 }
  ];
  var PU_IN_STEP = 42;        // ms per frame
  var PU_IN_STAGGER = 2;      // frames of delay per glyph
  // Mirrors .pu's opacity in stream.css. The lapse fade writes opacity inline,
  // which beats the stylesheet, so it has to scale by this or an expiring name
  // ends up brighter than a live one. CHANGE BOTH — they are one decision.
  var PU_REST_OPACITY = 0.78;
  var PU_MIN_S = 1;           // $1 and under all look the same — the floor
  var PU_REF = 5;             // the dono the curve is normalised around
  // Bounds the stack in the LIST rather than by clipping the container. The box
  // used to be overflow:hidden, which sheared the top name's hover and glow off
  // against a line level with the bottom of the tiles. Newest 5 orbit; the rest
  // are still live in the DB and still visible in HQ, they just wait their turn.
  var PU_MAX = 5;

  // ── The thank-you ────────────────────────────────────────────────────────
  // He says their NAME. That is the whole feature: an alert box with your
  // handle in it is a notification, but the character turning round and thanking
  // you by name is the reason you paid.
  //
  // It queues on the SPEAKS lane, so it lands AFTER the popup rather than over
  // it — the box announces what happened, then he responds to it. That ordering
  // is free: the ladder already makes speaks wait for popups, so the sequence
  // falls out of the lanes without anyone scheduling it.
  //
  // Tiered by amount, because "ty" for $100 is an insult and a scream for $2 is
  // noise. Several per tier so a dono train does not repeat itself word for word.
  var THANKS_SMALL = [
    'thanks {n}!', 'ty {n} <3', '{n} you legend', 'appreciate you {n}',
    '{n} thank you!!', 'love you {n}'
  ];
  var THANKS_BIG = [
    '{n} YOU ABSOLUTE LEGEND', '{n} WHAT!! thank you!!', 'OH MY GOD. thank you {n}',
    '{n} you are insane. thank you', 'I LOVE YOU {n}', '{n} just made my whole week'
  ];
  var THANKS_BIG_AT = 20;     // dollars — above this he loses it

  function thankThem(name, amount) {
    var pool = Number(amount) >= THANKS_BIG_AT ? THANKS_BIG : THANKS_SMALL;
    var line = pool[Math.floor(Math.random() * pool.length)]
      .replace('{n}', String(name || 'you').toLowerCase().slice(0, 16));
    // HAPPY, not ALERT: someone gave him money, and the face should agree with
    // the words. The box autoscales the line, so length is not a constraint.
    blobSpeak(line, { mood: 'HAPPY' });
  }

  // Cube root of the dollar amount, normalised so $5 == 1.0. Clamped at both
  // ends: below $1 nothing shrinks further, and past ~$250 nothing grows —
  // beyond that it would leave the stage rather than impress anyone.
  function puScale(amount) {
    var a = Math.max(PU_MIN_S, Number(amount) || 0);
    return Math.min(3.4, Math.cbrt(a) / Math.cbrt(PU_REF));
  }

  // Only events that carry actual money buy an orbit. A follow is lovely and
  // gets the box and the cheer; it does not get a power-up, or the ring fills
  // with people who paid nothing and the whole signal is gone.
  var PU_TYPES = { donation: 1, superchat: 1, supersticker: 1, bits: 1, membership_gift: 1 };

  var puList = [];            // [{ id, name, amount, until, el, phase, r, speed }]

  // A donor's name gets a colour the same way a ticker does: hashed into the
  // house palette. Same function, same 10 colours — so a name and a ticker are
  // visibly from the same world, and a regular keeps their colour every time
  // they show up without anyone assigning one.
  //
  // This replaced an RGB sweep on the name. Rainbow is what the AMOUNT is for;
  // a name that will not hold still on a colour is a name you cannot recognise,
  // which defeats the point of putting it on screen.
  function puColor(name) {
    return _hashCol(String(name || '').toUpperCase());
  }

  // When a power-up ARRIVED, derived rather than stored: puUntil() sets
  // until = arrival + amount minutes, so this inverts it exactly. No new field,
  // no migration, and it is correct for every row already in the store.
  function puSince(d) {
    return new Date(d.until).getTime() - Math.max(1, Number(d.amount) || 0) * 60000;
  }

  function puRender(full) {
    var host = $('s-orbit');
    if (!host) return;
    // NEWEST FIRST — by arrival, not by expiry.
    //
    // Sorting on `until` looked like "newest first" and is not: until is
    // arrival + amount, so it conflates recency with SIZE. A fresh $10 buys 10
    // minutes and loses to an hour-old $50 that still has 39 left — so with five
    // big ones alive, a new small donation could never reach the top and simply
    // never appeared. Someone paid and got nothing, which is the worst bug this
    // page can have.
    //
    // Arrival is the honest key: the newest dono is always on top, whatever it
    // was worth, and the ones that drop off the bottom are the OLDEST rather
    // than the cheapest.
    var list = full.slice().sort(function(a, b) {
      return puSince(b) - puSince(a);
    }).slice(0, PU_MAX);

    var seen = {};
    list.forEach(function(d) { seen[d.name + '|' + d.until] = 1; });

    // Drop anything no longer in the list (expired, or deleted from HQ).
    for (var i = puList.length - 1; i >= 0; i--) {
      if (seen[puList[i].name + '|' + puList[i].until]) continue;
      if (puList[i].el && puList[i].el.parentNode) puList[i].el.remove();
      puList.splice(i, 1);
    }

    list.forEach(function(d) {
      var key = d.name + '|' + d.until;
      for (var j = 0; j < puList.length; j++) {
        if (puList[j].name + '|' + puList[j].until === key) return;   // already up
      }
      var s = puScale(d.amount);
      var el = document.createElement('div');
      el.className = 'pu';
      el.style.fontSize = Math.round(PU_BASE_FONT + s * PU_FONT_GAIN) + 'px';
      el.style.setProperty('--pu-n', puColor(d.name));
      var nm = String(d.name || '').toUpperCase().slice(0, 16);
      el.innerHTML = '<span class="pu-name"></span><span class="pu-amt"></span>';

      // One <i> per glyph so the wave can travel THROUGH the name — the same
      // construction the board's tickers use (setSym), so the two move like they
      // belong to the same machine.
      var nameEl = el.querySelector('.pu-name');
      for (var ci = 0; ci < nm.length; ci++) {
        var gi = document.createElement('i');
        gi.textContent = nm[ci] === ' ' ? ' ' : nm[ci];
        nameEl.appendChild(gi);
      }
      el.querySelector('.pu-amt').textContent = '$' + (Number(d.amount) % 1 === 0
        ? Number(d.amount).toFixed(0) : Number(d.amount).toFixed(2));
      host.appendChild(el);
      puList.push({
        name: d.name, until: d.until, amount: d.amount, el: el, scale: s,
        amtEl: el.querySelector('.pu-amt'),
        glyphs: [].slice.call(nameEl.children),
        // Each name waves on its OWN phase. In lockstep the stack pulses as one
        // rigid block; offset, they read as separate things hanging there.
        phase: (puList.length * 2.399) % 6.283,
        // THE INTENSITY, still by amount — it just lives in the wave's height
        // now instead of a hover's travel.
        waveAmp: PU_WAVE_BASE + s * PU_WAVE_GAIN,
        // Hue offset so two amounts are never the same colour at once.
        hue: Math.random() * 360,
        // THE STROBE, on the AMOUNT only. Bigger donations flash harder and more
        // often — a $2 blinks rarely, a $75 is a lightning storm.
        strobeEvery: Math.max(4, Math.round(26 - s * 6)),
        f: 0,
        // Frames of arrival left to play. While this is running the glyphs
        // belong to puEnter, not to the wave — two things writing one transform
        // would fight and the loser would win at random.
        entering: PU_IN_FRAMES.length + nm.length * PU_IN_STAGGER
      });
      puEnter(puList[puList.length - 1]);
    });

    // Put the DOM in the sorted order — biggest/newest on top, because a fresh
    // whale should not have to be hunted for at the bottom of the stack.
    //
    // Done as a REORDER pass rather than by inserting each new node at the top:
    // that reversed the sort (last inserted wins the top slot), so the stack
    // came out smallest-first — measured, the $6 was above the $75. appendChild
    // on an element already in the DOM MOVES it, so walking the sorted list is
    // all it takes, and it is correct no matter what order they arrived in
    // across polls.
    list.forEach(function(d) {
      var key = d.name + '|' + d.until;
      for (var j = 0; j < puList.length; j++) {
        if (puList[j].name + '|' + puList[j].until === key) {
          host.appendChild(puList[j].el);
          break;
        }
      }
    });
  }

  // The slam. Runs on its own interval so it lands on the DONO EVENT rather than
  // on puTick's next turn — the arrival has to share a frame with the jackpot and
  // the box, and waiting up to 50ms for the shared loop would break that.
  function puEnter(p) {
    if (!p || !p.glyphs.length) return;
    var f = 0, total = PU_IN_FRAMES.length + p.glyphs.length * PU_IN_STAGGER;
    clearInterval(p._inT);
    p._inT = setInterval(function() {
      if (f >= total) {
        clearInterval(p._inT); p._inT = null;
        p.entering = 0;
        for (var q = 0; q < p.glyphs.length; q++) {
          p.glyphs[q].style.opacity = '';
          p.glyphs[q].style.filter = '';
        }
        p.el.style.filter = '';
        return;
      }
      for (var g = 0; g < p.glyphs.length; g++) {
        var k = f - g * PU_IN_STAGGER;
        var el = p.glyphs[g];
        if (k < 0) { el.style.opacity = '0'; continue; }
        el.style.opacity = '1';
        var fr = PU_IN_FRAMES[Math.min(k, PU_IN_FRAMES.length - 1)];
        el.style.transform = 'translateY(' + fr.y + 'px) scale(' + fr.s + ') rotate(' + fr.r + 'deg)';
        el.style.filter = fr.b > 1.02 ? 'brightness(' + fr.b + ')' : '';
      }
      p.entering = total - f;
      f++;
    }, PU_IN_STEP);
  }

  function puTick() {
    if (!puList.length) return;
    var now = Date.now();
    for (var i = puList.length - 1; i >= 0; i--) {
      var p = puList[i];
      if (new Date(p.until).getTime() <= now) {   // lapsed mid-orbit
        if (p.el && p.el.parentNode) p.el.remove();
        clearInterval(p._inT);
        puList.splice(i, 1);
        continue;
      }
      p.f++;

      // ── The wave — the name's ONLY motion ────────────────────────────────
      // Each glyph rises in series, so a ripple runs through the word. Same
      // mechanic as the board's tickers, ~10-20x the amplitude: the board runs
      // 1px because 14 shimmering tickers would compete with the trade beat, and
      // a donor's name is MEANT to compete.
      //
      // Whole pixels — subpixel drift is what breaks pixel art (BLOB.md), and
      // this hangs in the same room as a 48x48 sprite. The name holds still
      // otherwise: it has to be READ, and a word that will not sit still is a
      // word nobody reads.
      // The arrival owns the glyphs while it plays. Both write the same
      // transform, so without this they trade frames and the slam comes out as a
      // stutter — whichever interval fired last wins, at random.
      if (!p.entering) {
        for (var g = 0; g < p.glyphs.length; g++) {
          var gy = -Math.round(
            (Math.sin(p.phase + p.f * PU_WAVE_SPEED - g * PU_WAVE_SPREAD) * 0.5 + 0.5) * p.waveAmp);
          p.glyphs[g].style.transform = gy ? 'translateY(' + gy + 'px)' : '';
        }
      }

      // ── The amount: absurd RGB, and ONLY the amount ───────────────────────
      // The rainbow lives here now. It is the money — it can be as obnoxious as
      // it likes, because nobody needs to recognise it, only notice it. The name
      // above it keeps one palette colour so it stays a NAME.
      //
      // Three hues 120deg apart — an actual RGB triad — sweeping together, so
      // several colours show at once. That simultaneity is the difference: one
      // hue sliding through the spectrum reads as a designer's colour animation;
      // three at once reads as a cheap LED strip on a pier, which is the brief.
      var spin = 3.4 + p.scale * 4.2;                      // hue degrees per frame
      var hue  = (p.hue + p.f * spin) % 360;
      p.el.style.setProperty('--pu-c',  'hsl(' + hue.toFixed(0) + ',100%,60%)');
      p.el.style.setProperty('--pu-c2', 'hsl(' + ((hue + 120) % 360).toFixed(0) + ',100%,58%)');
      p.el.style.setProperty('--pu-c3', 'hsl(' + ((hue + 240) % 360).toFixed(0) + ',100%,58%)');

      // The glow BREATHES on its own faster clock, so the light pulses against
      // the hue sweep instead of with it. Two rhythms beating is what makes it
      // read as alive rather than as a looping asset.
      var pulse = 1 + Math.sin(p.f * 0.22) * 0.45;
      p.el.style.setProperty('--pu-glow',
        Math.round((10 + p.scale * 9) * pulse) + 'px');

      // Strobe: a hard white frame on a beat, on the AMOUNT only. Two frames on,
      // the rest off — any longer and it stops being a flash and becomes a
      // colour.
      var strobe = (p.f % p.strobeEvery) < 2;
      if (strobe !== p.wasStrobe) {
        p.wasStrobe = strobe;
        if (p.amtEl) {
          p.amtEl.style.color = strobe ? '#ffffff' : '';
          p.amtEl.style.filter = strobe
            ? 'brightness(' + (1.6 + p.scale * 0.8).toFixed(2) + ')'
            : '';
        }
      }

      // The last 20s fades out, so a lapse is a decision rather than a name that
      // was simply there and then was not.
      //
      // Scaled by PU_REST_OPACITY, not written raw: an inline opacity overrides
      // the stylesheet's 0.78, so a raw ramp would make an EXPIRING power-up
      // brighter than a live one on its way out. Blank hands it back to the CSS.
      var left = new Date(p.until).getTime() - now;
      p.el.style.opacity = left < 20000
        ? (PU_REST_OPACITY * (0.15 + 0.85 * (left / 20000))).toFixed(3)
        : '';
    }
  }

  // $1 : 1 minute. The whole promise of the feature, so it is derived here once
  // and nowhere else: HQ shows this same arithmetic back to you before you save.
  function puUntil(amount, fromMs) {
    return new Date((fromMs || Date.now()) + Math.max(1, Number(amount) || 0) * 60000).toISOString();
  }

  // Autofill. EVERY renderer airs every event (it is a broadcast, not a work
  // queue), so every renderer reaches this — the stream event's own id is what
  // makes the write idempotent. Without it, the operator's preview window and
  // the encoder would each append the same donation and the name would orbit
  // twice.
  //
  // SERIALISED, because read-modify-write on a JSON blob is not atomic and two
  // donations in one burst race each other. This is not hypothetical: the first
  // test fired $3 and $50 1.8s apart, both read the blob before either wrote,
  // and the $50 vanished — a paying viewer silently got nothing. The announcer
  // chains popups 1.8s apart, so a dono train hits this every time.
  //
  // A chain fixes the same-renderer case, which is all of them in practice: two
  // renderers writing in the same instant is still possible and still costs one
  // lost ring. The real fix is a table with a unique key and an upsert, which is
  // a migration.
  var _puChain = Promise.resolve();

  function puAdd(id, name, amount) {
    _puChain = _puChain.then(function() { return puAddOne(id, name, amount); })
                       .catch(function() {});   // one failure must not break the chain
  }

  function puAddOne(id, name, amount) {
    var key = 'ev' + (id != null ? id : Date.now());
    return fetch(S.supa.url + '/rest/v1/strategy_params?strategy=eq.stream' +
          '&param=eq.dono_powerups&select=value',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        var list = [];
        if (Array.isArray(rows) && rows.length) {
          try { list = JSON.parse(rows[0].value) || []; } catch (e) { list = []; }
        }
        if (!Array.isArray(list)) list = [];
        if (list.some(function(d) { return d && d.id === key; })) return;   // beaten to it
        // Returned so the chain waits for the write, not just the read — the
        // whole point of serialising.

        var now = Date.now();
        // Drop the lapsed while we are here — otherwise the blob grows forever
        // and nothing else ever prunes it.
        list = list.filter(function(d) {
          return d && d.until && new Date(d.until).getTime() > now;
        });
        list.push({ id: key, name: String(name).slice(0, 16), amount: Number(amount),
                    until: puUntil(amount, now) });

        // unit and label are NOT NULL on strategy_params — omitting them fails
        // the insert with a 23502 and, because the catch below was silent, the
        // autofill looked like it simply never ran. Mirrors _set_policy()'s
        // INSERT in stream_hq.py; the two must agree on the columns.
        var body = JSON.stringify({
          strategy: 'stream', param: 'dono_powerups',
          value: JSON.stringify(list), unit: '',
          label: 'Active donation power-ups',
          updated_at: new Date().toISOString()
        });
        // on_conflict MUST name (strategy,param). PostgREST infers the conflict
        // target from the PRIMARY KEY otherwise — here that is `id`, so
        // merge-duplicates targeted the wrong column entirely: the first write
        // inserted and every one after it 409'd against uq_strategy_param.
        // Which is precisely one power-up surviving per burst.
        return fetch(S.supa.url + '/rest/v1/strategy_params?on_conflict=strategy,param', {
          method: 'POST',
          headers: {
            apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key,
            'Content-Type': 'application/json',
            Prefer: 'resolution=merge-duplicates,return=minimal'
          },
          body: body
        }).then(function(r) {
          // Not silent. A rejected write here means a viewer paid and got no
          // orbit — the one failure on this page with a customer on the other
          // end of it. A silent catch hid exactly this for its first outing.
          if (!r.ok) {
            return r.text().then(function(tx) {
              console.error('[stream] power-up write rejected (' + r.status + '):', tx);
            });
          }
          pollPowerups();
        }).catch(function(e) { console.error('[stream] power-up write failed:', e); });
      })
      .catch(function(e) { console.error('[stream] power-up read failed:', e); });
  }

  function pollPowerups() {
    fetch(S.supa.url + '/rest/v1/strategy_params?strategy=eq.stream' +
          '&param=eq.dono_powerups&select=value',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) { puRender([]); return; }
        var list;
        try { list = JSON.parse(rows[0].value); } catch (e) { return; }
        if (!Array.isArray(list)) return;
        var now = Date.now();
        puRender(list.filter(function(d) {
          return d && d.name && new Date(d.until).getTime() > now;
        }));
      })
      .catch(function() {});
  }

  // ── AFK ──────────────────────────────────────────────────────────────────
  // He is on 24/7 and the book is quiet ~20s between rolls. A single frozen
  // line across that gap reads as a dead page — the stream's own liveness is
  // the thing being broadcast, so the sentence keeps talking when the book
  // does not. Each one completes the nameplate: "blob" + "is cooking".
  //
  // HARD LIMIT 25 CHARACTERS. Measured, not guessed: 640px of runway after the
  // nameplate at 25.5px/glyph, and #s-title is overflow:hidden — a 26th
  // character does not wrap or shrink, it silently disappears. There is an
  // assertion below that drops anything too long rather than letting it clip.
  // Editable live from Stream HQ (strategy_params.afk_phrases, polled below).
  // This array is the FALLBACK, not the source: it is what he says before the
  // first poll lands and if the row is ever empty or unparseable, because a
  // silent nameplate is worse than a stale joke.
  var AFK_FALLBACK = [
    'is trading',              'is watching the tape',
    'is doing numbers',        'is up to something',
    'is holding the line',     'is thinking about it',
    'is reading the charts',   'is vibing',
    'is waiting for a sign',   'is down bad',
    'is cooking',              'is locked in',
    'is calculating',          'is fully committed',
    'is trusting the plan',    'needs a minute',
    'is running the numbers',  'is feeling lucky',
    'has a good feeling',      'is staying humble',
    'is doing his best',       'is monitoring',
    'is unbothered',           'is so back',
    'is never selling',        'is in the trenches',
    'is chilling',             'is zoomed in',
    'is touching grass',       'is diamond handing',
    'is not selling',          'is being patient'
  ];

  // The live list. Sanitised on every load rather than trusted: HQ writes free
  // text, and the 25-char ceiling is a hard geometric fact (640px of runway at
  // 25.5px/glyph, and #s-title is overflow:hidden — a 26th character does not
  // wrap or shrink, it silently vanishes). Enforcing it HERE rather than only in
  // HQ means a row written by anything else still cannot break the nameplate.
  var AFK_MAX_CHARS = 25;

  function sanitizeAfk(list) {
    if (!Array.isArray(list)) return null;
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var s = String(list[i] || '').trim();
      if (s && s.length <= AFK_MAX_CHARS) out.push(s);
    }
    return out.length ? out : null;
  }

  var AFK = sanitizeAfk(S.afk_phrases) || sanitizeAfk(AFK_FALLBACK);

  function pollAfkPhrases() {
    fetch(S.supa.url + '/rest/v1/strategy_params?strategy=eq.stream' +
          '&param=eq.afk_phrases&select=value',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        var next;
        try { next = sanitizeAfk(JSON.parse(rows[0].value)); } catch (e) { return; }
        // Never swap in an empty list — that would leave x with nothing to say.
        if (next) AFK = next;
      })
      .catch(function() {});
  }

  var AFK_AFTER = 2000;     // quiet for this long and he starts talking
  var AFK_HOLD  = 4200;     // per message — long enough to read, short enough
                            // that a 20s gap gets four of them, not two
  var _idleT = null, _afkT = null, _afkIdx = -1;

  // ── "is happy!" — the viewer-event face ──────────────────────────────────
  // A viewer event OUTRANKS the AFK cycle the same way its popup outranks a
  // trade. While someone is being thanked, the sentence must not be idly
  // musing about touching grass underneath the box.
  //
  // NOT every popup — only viewer ones. risk_breach opens the same box but is
  // the machine hurting itself, and its mood is SCARED: "blob is happy!" over a
  // drawdown alarm would be the single worst sentence this page could produce.
  var VIEWER_EVENTS = {
    donation: 1, superchat: 1, supersticker: 1, bits: 1,
    membership_gift: 1, subscription: 1, follow: 1, raid: 1, chat: 1
  };

  var HAPPY_TEXT = 'is happy!';
  var _happyT = null;

  function clearHappy() {
    clearInterval(_happyT);
    _happyT = null;
  }

  function setStatusHappy() {
    var el = $('blob-status');
    if (!el) return;
    // Silence the AFK cycle and any decode mid-flight on the container.
    clearTimeout(_idleT); clearTimeout(_afkT);
    clearInterval(el._dec); clearTimeout(el._decT); el._dec = null;
    clearHappy();

    // Per-character, because the win is a WAVE across the word — one element
    // can only bob as a block, which reads as a wobble rather than a cheer.
    el.className = 'ttl-x idle happy';
    el.innerHTML = '';
    var chars = [];
    for (var i = 0; i < HAPPY_TEXT.length; i++) {
      var c = document.createElement('i');
      c.textContent = HAPPY_TEXT[i] === ' ' ? ' ' : HAPPY_TEXT[i];
      el.appendChild(c);
      chars.push(c);
    }

    // THE ARCADE WIN. A bounce wave travelling left→right, on a 10fps clock and
    // quantized to whole pixels — the Blob's own framerate and grid, so his
    // celebration and the sentence are visibly the same machine. A 60fps sine
    // would read as a modern web toy sitting next to a 10fps sprite, which is
    // exactly the failure BLOB.md warns about. No decode here on purpose: the
    // decode is him computing, and this is him NOT computing.
    var f = 0;
    _happyT = setInterval(function() {
      f++;
      for (var i = 0; i < chars.length; i++) {
        var y = Math.round(Math.sin((f - i * 1.2) * 0.7) * 4);
        chars[i].style.transform = 'translateY(' + y + 'px)';
      }
    }, 100);
  }

  // A one-off system line in the same white voice as AFK, held until something
  // else claims x rather than cycling on.
  function statusLine(text) {
    var el = $('blob-status');
    if (!el) return;
    clearTimeout(_idleT); clearTimeout(_afkT);
    clearHappy();
    clearInterval(el._dec); clearTimeout(el._decT); el._dec = null;
    el.className = 'ttl-x idle';
    el.innerHTML = '';
    decodeTo(el, text, 0);
  }

  function afkNext() {
    var el = $('blob-status');
    if (!el) return;
    clearHappy();       // the wave stops or it runs forever on detached nodes
    // "No event for 2s" must mean nothing is PENDING either, not just that the
    // last one finished. Beat-to-beat is 1.6s against this 2s timer — only
    // 400ms of margin — so a beat delayed by a reorder would flash an AFK line
    // mid-roll and have it stomped a frame later. If trades are waiting, he is
    // not AFK; re-arm and stay quiet.
    if (tradeQ.length || stage.owner === 'trade') {
      _afkT = setTimeout(afkNext, AFK_AFTER);
      return;
    }
    var i;
    do { i = Math.floor(Math.random() * AFK.length); } while (AFK.length > 1 && i === _afkIdx);
    _afkIdx = i;                 // random, never twice running: a fixed rotation
                                 // becomes recognisable over an 8-hour stream
    el.className = 'ttl-x idle';
    clearInterval(el._dec); clearTimeout(el._decT); el._dec = null;
    el.innerHTML = '';
    decodeTo(el, AFK[i], 0);     // same decode as a trade — one voice, not two
    _afkT = setTimeout(afkNext, AFK_HOLD);
  }

  // The sentence. A BUY has no P&L yet, so "for" takes what the position COST —
  // qty x price, not the per-unit price. That distinction is the whole point:
  // "bought CRV for $0.22" reads as blob buying 22 cents of crypto, when he
  // actually spent $204. Same template shape, honest number. (qty is on every
  // ENTER's detail as qty=N; measured 20/20.)
  function setStatus(t) {
    var el = $('blob-status');
    if (!el) return;
    // An event silences the AFK cycle and restarts the countdown to it.
    clearTimeout(_idleT); clearTimeout(_afkT);
    clearHappy();
    _idleT = _afkT = setTimeout(afkNext, AFK_AFTER);
    var bare = t.sym.replace('/USD', '');
    // A roll realised a P&L exactly like a sale did, so it reads like one — the
    // only difference is the verb, because he still holds it.
    var hasPnl = t.dir === 'EXIT';

    // afkNext decodes the CONTAINER, so an AFK decode may still be mid-flight
    // on it. Left running it would keep writing textContent over the spans below
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
    if (hasPnl) {
      var v = Number(t.pnl || 0);
      tail = money2(v);
      cls = v >= 0 ? 'win' : 'loss';
    } else {
      // Fall back to the per-unit price only if qty is missing — a wrong-looking
      // number beats a blank one, and it has never actually been missing.
      tail = cost2(t.qty ? t.qty * t.price : t.price);
    }
    pEl.className = 'xs-pnl ' + cls;

    var verb = t.dir === 'EXIT' ? 'sold' : 'bought';
    _beat('x: "' + verb + ' ' + bare + ' for ' + tail + '"');

    // Staggered so the sentence assembles word by word rather than all at once.
    decodeTo(vEl, verb, 0);
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

  // ═══════════════════════════════════════════════════════════════════════
  // BATCHING — the book does not trade, it ROLLS
  //
  // Measured over 6h / 3,210 fills: 798 of 799 batches are PURE ROLLS. The
  // engine exits a set of symbols on `timeout` and re-enters the identical set
  // within ~1.5s. The board is unchanged before and after. Batch sizes are
  // always even (2,4,6...16) for exactly that reason — every fill is one half
  // of a round trip.
  //
  // Narrating the legs separately was not just badly paced, it was FALSE. A
  // 16-batch is 8 positions rolled. The queue capped at 6 and kept the NEWEST
  // six, which are the last six ENTERs — so the stream played "bought SOL,
  // bought AVAX, bought LINK..." and threw away all 8 exits along with their
  // P&L. A roll rendered as a buying spree that never happened, with 62% of the
  // batch dropped on the floor.
  //
  // So a round trip is ONE event: `rolled BTC for −$0.38`. The tile stays where
  // it is (the position never left), the realised P&L is the news, and 16 legs
  // become 8 beats that are each true. 8 beats is 12.8s against a ~2min cadence
  // for the big batches, so the whole roll now plays instead of being culled.
  //
  // PAIRING. Both legs land inside one poll ~63% of the time and pair for free.
  // The batch spans ~1.5s against a 4s poll, so the boundary splits it the other
  // ~37%: those exits wait one poll cycle for their re-entry rather than being
  // announced as a sale that didn't happen.
  // ═══════════════════════════════════════════════════════════════════════
  var pendExit = {};        // sym -> { t, timer } — an exit awaiting its re-entry
  // How long an unpaired exit waits for its re-entry before airing as a plain
  // sell. DERIVED from the poll, because that is the only thing it depends on:
  // a straddled batch puts the exits in one poll and the enters in the NEXT, so
  // anything under one poll interval cannot pair by construction.
  //
  // Two intervals plus a second, not one plus a second. The old 5000 left ~1s of
  // margin against a 4s poll — fine when polls are punctual, and they are not
  // always: a slow fetch, a GC pause or a throttled tab pushes one late and the
  // pairing silently degrades into two beats with the tile churning out and back.
  // The cost of waiting longer is paid only by a GENUINE standalone sell, which
  // this book has never once produced (798/799 batches are pure rolls).
  var ROLL_WAIT = POLL_MS * 2 + 1000;
  var _dbgIngest = [], _dbgPush = 0;   // see window._TND_DBG.q()

  // ── Beat trace ───────────────────────────────────────────────────────────
  // A ring buffer of what the stage actually did, readable from a console via
  // _TND_DBG.q().beat. Kept, not scaffolding: this page runs unattended on a
  // headless box, the beat is four chained setTimeouts, and a gap in this trace
  // is the only thing that names WHICH link broke. It is what proved the beat
  // healthy after hours of instrumentation that lied — every other probe said
  // "frozen" and only the trace showed a clean 3011ms beat against a designed
  // 2976ms.
  //
  // Phase boundaries and the spoken line only — enough to reconstruct a beat,
  // cheap enough to leave on: ~4 short strings per 3s.
  var _beatLog = [];
  function _beat(what) {
    _beatLog.push(Math.round(performance.now()) + ' ' + what);
    if (_beatLog.length > 40) _beatLog.shift();
  }

  // ── Program order ────────────────────────────────────────────────────────
  // A batch is not a bag of trades, it is a SENTENCE with a shape:
  //
  //     every exit, one at a time   ->   the numbers fade together   ->
  //     every entry, one at a time  ->   settle and reshuffle
  //
  // The exits are a paragraph, the fade is the full stop, and the entries are
  // the next paragraph. Interleaving them (which is what pairing each roll into
  // a single sell-then-buy beat did) means the board is being written and
  // erased in the same breath and there is nothing a viewer can actually follow.
  // Separating them costs ~27s for a 16-leg batch against a ~2min cadence, and
  // buys a sequence you can watch.
  //
  // Each step stays its OWN beat rather than the batch holding the floor for the
  // whole 27s: the ladder must still be able to slot a donation in between two
  // exits. The order survives the interruption because it is baked into the
  // queue, not into who holds the stage.
  var _rollSeq = 0;
  function mkRoll(ex, en) {
    // Kept as a pair so the exit and its entry can be matched by eye in the
    // trace, and so a future change can collapse them again without re-deriving
    // which entry belonged to which exit.
    var id = ++_rollSeq;
    return {
      exit:  { dir: 'EXIT',  sym: ex.sym, pnl: ex.pnl, roll: id },
      entry: { dir: 'ENTER', sym: en.sym, price: en.price, stop: en.stop, qty: en.qty, roll: id }
    };
  }

  // Hold an unpaired exit briefly. If its re-entry never comes it really was a
  // sale, and it plays as one — just one poll late.
  function stageExit(t) {
    var prev = pendExit[t.sym];
    if (prev) { clearTimeout(prev.timer); tradePush(prev.t); }
    pendExit[t.sym] = { t: t, timer: setTimeout(function() {
      delete pendExit[t.sym];
      tradePush(t);
    }, ROLL_WAIT) };
  }

  // Walks one poll's fresh trades IN ARRIVAL ORDER, pairing exit→re-entry.
  // Order matters: within a batch every exit precedes every entry, so pairing
  // forward is what distinguishes a roll from a genuine sell-then-rebuy.
  function tradeIngest(list) {
    _dbgIngest.push(list.map(function(t) { return t.dir + ':' + t.sym; }).join(','));
    if (_dbgIngest.length > 6) _dbgIngest.shift();
    var open = {}, exits = [], entries = [];

    list.forEach(function(t) {
      if (t.dir === 'EXIT') { open[t.sym] = t; return; }
      // ENTER — does it close a roll opened in this poll, or a staged one from
      // the previous poll (the straddle case)?
      var pair = null;
      if (open[t.sym]) { pair = mkRoll(open[t.sym], t); delete open[t.sym]; }
      else {
        var staged = pendExit[t.sym];
        if (staged) { clearTimeout(staged.timer); delete pendExit[t.sym]; pair = mkRoll(staged.t, t); }
      }
      if (pair) { exits.push(pair.exit); entries.push(pair.entry); return; }
      entries.push(t);      // a genuinely new position — nothing to sell first
    });

    // Exits with no re-entry in this poll — the batch may have straddled.
    Object.keys(open).forEach(function(sym) { stageExit(open[sym]); });

    // THE PROGRAM. Exits, then the full stop, then entries.
    var program = exits.slice();
    // The fade only earns its beat if there is actually something to fade AND
    // something coming after it. A batch of pure entries has no numbers on the
    // board and no reason to pause.
    if (exits.length) program.push({ dir: 'FADE' });
    program = program.concat(entries);
    program.forEach(tradePush);
  }

  var tradeQ = [];

  // The cap must hold a WHOLE batch now, not a handful of beats: the largest
  // observed batch is 16 legs = 8 exits + a fade + 8 entries = 17 items. A cap
  // below that decapitates the program — it drops the oldest, which are the
  // exits, and the board would show 8 unexplained purchases. That is the same
  // buying-spree fiction the pairing was written to kill, arriving by a
  // different door.
  //
  // 20 at ~1.6s is ~32s of backlog against a ~2min batch cadence, so the queue
  // drains long before the next one lands and the cap should never actually
  // fire. It is a bound, not a policy.
  var TRADE_CAP = 20;

  function tradePush(t) {
    _dbgPush++;
    tradeQ.push(t);
    if (tradeQ.length > TRADE_CAP) tradeQ.splice(0, tradeQ.length - TRADE_CAP);
    stagePump();
  }

  // The bottom of the ladder: only runs when no viewer event and no line of
  // dialogue is waiting. ONE beat per acquire, not the whole queue — that is
  // what makes "popups pause trades" true in practice, because a donation that
  // lands mid-burst only ever waits out the single beat already in flight
  // instead of the entire backlog.
  // ── The fade ─────────────────────────────────────────────────────────────
  // Every leavebehind on the board goes transparent TOGETHER, and only when the
  // last one is gone may an entry start. This beat is the full stop between the
  // two paragraphs. Without it the first entry lands while seven numbers are
  // still on screen, and the eye has nowhere to rest — which is the difference
  // between watching a sequence and watching a board flicker.
  //
  // setInterval, not a CSS transition: standing rule for this page.
  var FADE_MS = 1000, FADE_STEP = 50, FADE_SETTLE = 260;

  function fadeLeavebehinds(done) {
    var els = [].slice.call(
      document.querySelectorAll('#pos-list .t-sym.pnl-win, #pos-list .t-sym.pnl-loss'));
    if (!els.length) { done(); return; }
    var steps = Math.max(1, Math.round(FADE_MS / FADE_STEP)), i = 0;
    var iv = setInterval(function() {
      i++;
      var o = Math.max(0, 1 - i / steps);
      for (var k = 0; k < els.length; k++) els[k].style.opacity = o;
      if (i < steps) return;
      clearInterval(iv);
      // The slots keep their (now invisible) numbers. An entry reclaims one and
      // pulls it back to opacity 1; a slot with no entry was a real sale and the
      // settle removes it, because by then it is gone from S.crypto.
      for (var j = 0; j < els.length; j++) els[j].style.opacity = 0;
      // The numbers are spent — release the tiles the tint pass and the settle
      // were both told to leave alone.
      Object.keys(ghostT).forEach(function(sym) { delete ghostT[sym]; });
      done();
    }, FADE_STEP);
  }

  function tradeStart() {
    if (!tradeQ.length) return false;
    stageTake('trade');
    var t = tradeQ.shift();
    _beat('take ' + t.dir + (t.sym ? ' ' + t.sym : ''));

    // ── FADE ───────────────────────────────────────────────────────────
    // Its own beat, so it cannot overlap either paragraph. No blob reaction and
    // no sound: nothing HAPPENED here, which is exactly what it is for.
    if (t.dir === 'FADE') {
      fadeLeavebehinds(function() {
        _beat('faded');
        setTimeout(function() { _beat('release'); stageDone(); }, FADE_SETTLE);
      });
      return true;
    }

    // ── PRE ────────────────────────────────────────────────────────────
    // He looks at the slot and braces. Nothing else moves yet: no sound, no
    // tile, no score. This half-second is the only warning the viewer gets,
    // and it is what makes the impact feel caused rather than random.
    blob.setMood('BRACE', PRE_TICKS + 2);   // +2 so it holds through the handoff
    glanceAt(t.sym);
    // The cursor names the target while he winds up. His glance already aims at
    // the slot, but a 768px blob looking 8px left is not something a viewer can
    // actually read — the pointer is what makes the aim legible.
    if (t.dir === 'EXIT') pointAt(t.sym);
    showMood();

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
        setTimeout(function() { _beat('release'); stageDone(); }, GAP_MS);
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
    showMood();

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

    // The pointer's job is done the instant the impact lands — from here the
    // hit animation is saying "this one" far louder than a cursor could.
    clearPointer();

    // Same frame as the sound.
    if (t.dir === 'ENTER') boardEnter(t);
    else                   boardExit(t);

    // x speaks on the same frame too. The decode runs for ~400ms after this,
    // but it STARTS here, which is what makes the sentence read as caused by the
    // sound rather than as a caption that arrived late.
    //
    setStatus(t);

    // Any reordering waits — see scheduleSettle.
    scheduleSettle();
  }

  // ── The board reacts ─────────────────────────────────────────────────────
  function tileEl(sym) { return document.querySelector('.tile[data-sym="' + sym + '"]'); }

  // sym -> true. A MARKER, not a timer: "this slot is showing a P&L, leave it
  // alone" for the tint pass and the settle. The fade clears it.
  //
  // It USED to hold a setTimeout id, and three call sites still clearTimeout'd
  // it after it became a boolean. `clearTimeout(true)` coerces to
  // `clearTimeout(1)` — a silent, valid call that cancels whatever owns timer
  // ID 1. On this page that is the Blob's 10fps loop, because he is started
  // before almost anything else. He ran for ~30s and then died on the first
  // exit batch, with no error, while every other interval kept going.
  //
  // NEVER clearTimeout this. If it goes back to holding a timer, guard the type.
  var ghostT = {};

  function boardEnter(t) {
    // The same symbol usually re-enters seconds after it exits, so its slot is
    // often still on screen holding the leavebehind. Reclaim it.
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
      // Reclaiming a slot the fade left at opacity 0 — pull it back or the
      // ticker types itself onto an invisible element and the tile reads as
      // permanently empty.
      var sp0 = el.querySelector('.t-sym');
      setSym(sp0, t.sym.replace('/USD', ''));
      sp0.className = 't-sym';
      sp0.style.opacity = '';
      el.style.removeProperty('--tc');
    }

    // Fly-in and hit fire NOW, on the same frame as the sound — whether the slot
    // is brand new or reclaimed. The position is new either way and the viewer
    // should see him place it.
    var o = blobCenter(), r = el.getBoundingClientRect();
    if (o) flyIn(el, o.x - (r.left + r.width / 2), o.y - (r.top + r.height / 2));
    hitTile(t.sym);
    enterSym(el.querySelector('.t-sym'));
  }

  // ── The pointer ──────────────────────────────────────────────────────────
  // The Gen-1 menu cursor. During the wind-up it parks against the slot he is
  // about to sell: BRACE says "something is coming", the pointer says "to THAT
  // one". Without it the 500ms of anticipation has no target and the impact
  // still arrives from nowhere.
  //
  // Sells only — and that is a constraint, not a preference. Only a sale has a
  // tile to point AT; an entry's slot does not exist until the impact creates
  // it, so there is nothing on the board to aim at during its wind-up.
  //
  // It nudges on a 2-frame cycle, setInterval — a CSS animation here would be
  // inert like every other one on this page.
  var POINT_NUDGE = [0, 3];
  var _pointEl = null, _pointT = null;

  function pointAt(sym) {
    clearPointer();
    var el = tileEl(sym);
    if (!el) return;
    var p = document.createElement('span');
    p.className = 't-point';
    p.textContent = '▶';
    el.appendChild(p);
    _pointEl = p;
    var i = 0;
    _pointT = setInterval(function() {
      i = (i + 1) % POINT_NUDGE.length;
      p.style.transform = 'translate(' + (-POINT_NUDGE[i]) + 'px, -50%)';
    }, 150);
  }

  function clearPointer() {
    clearInterval(_pointT); _pointT = null;
    if (_pointEl && _pointEl.parentNode) _pointEl.parentNode.removeChild(_pointEl);
    _pointEl = null;
  }

  // ── The leavebehind ──────────────────────────────────────────────────────
  // On a sell the slot does not simply vanish — it LEAVES BEHIND what the
  // position earned, in the ticker's own face and size: green profit, red loss.
  // A tile that disappears tells you a position closed. A leavebehind tells you
  // whether it was worth having, which is the only part a viewer cares about.
  //
  // NO TIMER. The number STAYS until the fade beat takes it, which is what lets
  // every exit in a batch sit on the board together and be read as a set before
  // anything replaces them. It used to expire on its own 4.5s clock, which meant
  // the first exits of a 16-leg batch had faded before the last ones landed —
  // the board was being written and erased in the same breath.
  //
  // The fade owns the ending now; boardExit only owns the impact. ghostT still
  // marks "this slot is showing a number, leave it alone" for the tint pass and
  // the settle, and fadeLeavebehinds clears it.
  function boardExit(t) {
    var el = tileEl(t.sym);
    if (!el) return;

    var sp = el.querySelector('.t-sym');
    var v = Number(t.pnl || 0);
    setSym(sp, (v >= 0 ? '+' : '−') + '$' + Math.abs(v).toFixed(2));
    sp.className = 't-sym ' + (v >= 0 ? 'pnl-win' : 'pnl-loss');
    sp.style.opacity = '';       // a reclaimed slot may still carry the last fade
    el.style.setProperty('--tc', v >= 0 ? '#00ff9d' : '#ff3366');
    hitTile(t.sym);              // the number lands with the same arcade punch

    // Drop the position from local state now so the settle doesn't resurrect
    // the slot — but leave the ELEMENT on screen holding its number.
    S.crypto = (S.crypto || []).filter(function(c) { return c.sym !== t.sym; });

    // A marker, not a countdown: nothing fires when this is set, it only tells
    // the tint pass and the settle that this slot is spoken for.
    ghostT[t.sym] = true;
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
        // Collected first, then ingested as a SET — the batch has to be visible
        // as a batch for its legs to pair. Pushing each row as it is read is
        // what made a roll look like eight sales and eight purchases.
        var trades = [];
        fresh.forEach(function(r) {
          if (r.event_type !== 'TRADE') return;
          var t = parseTrade(r.message, r.detail);
          if (!t) return;
          t.sym = r.symbol || '';
          trades.push(t);
        });
        if (trades.length) tradeIngest(trades);
      })
      // NOT a silent catch. This .then() runs the entire ingest → pump → beat
      // chain synchronously, so ANY throw inside a lane lands here — and an
      // empty catch turned a hard crash into "the stream is quiet", which is
      // indistinguishable from a quiet market and cost this session an hour.
      // A fetch failure is expected and boring; a TypeError from the renderer
      // is not, and must say so.
      .catch(function(err) {
        if (err && err.name === 'TypeError' && /fetch/i.test(err.message || '')) return;
        console.error('[stream] pollEvents chain threw:', err && err.stack ? err.stack : err);
      });
  }

  // ── Boot ─────────────────────────────────────────────────────────────────
  renderHero();
  // The one full build that isn't a settle. Nothing animates: on first paint
  // the book already exists, and flying 14 tiles in at once would claim he had
  // just placed the entire portfolio.
  renderPositions(true);
  annNext();                      // settles the panel into its idle state
  _booted = true;                 // from here, only a trade beat may change the board
  afkNext();                      // he starts talking immediately — a page that
                                  // boots into silence during a quiet spell
                                  // looks broken for the first 20s

  // Lane state, exposed for diagnosis. This page runs unattended on a headless
  // box where the only way to ask "why is nothing happening" is from a console.
  window._TND_DBG = {
    stage: stage,
    q: function() { return { ann: annQ.length, speak: speakQ.length, trade: tradeQ.length,
                             owner: stage.owner, reordering: reordering,
                             pendExit: Object.keys(pendExit),
                             seenEvTs: state.seenEvTs,
                             ingested: _dbgIngest, pushed: _dbgPush,
                             beat: _beatLog }; },
    speak: blobSpeak,
    fit: fitSpeak,     // pure (element, text) -> px; testable without the lane
    blob: blob,        // .getTick() / .isRunning() — is the star actually alive?
    mood: function() { return _mood; },  // no longer on the stage; still knowable
    bg: bg,            // .getCam() — the horizon IS the P&L, so it is worth reading
    // "what would he say for a $50?" — answerable without waiting for a
    // donation to work its way through two lanes at a typewriter's pace.
    thanksFor: function(name, amount) {
      var pool = Number(amount) >= THANKS_BIG_AT ? THANKS_BIG : THANKS_SMALL;
      return pool.map(function(l) {
        return l.replace('{n}', String(name || 'you').toLowerCase().slice(0, 16));
      });
    }
  };

  setInterval(syncBlobMood, 1000);
  // The ambient ticker wave. 10fps — the Blob's clock, so the board and the
  // character share one heartbeat instead of beating against each other.
  setInterval(waveTick, 100);
  // Last resort against a wedged lane freezing the whole broadcast. 2s is the
  // detection granularity, not the bound — see STAGE_MAX_MS.
  setInterval(stageWatchdog, 2000);
  // One poll now carries both NAV and trade reactions — same rows, one request.
  // Trades land every ~7s. A 10s poll straddled them; 4s means he answers
  // almost every one while still costing ~15 tiny requests/min.
  setInterval(pollEvents, POLL_MS);
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
  // AFK copy is edited by a human in HQ, so it changes at human speed. 15s is
  // fast enough to see your own edit land while you are still looking at it.
  setInterval(pollAfkPhrases, 15000);
  pollAfkPhrases();
  // Power-ups: the ring animates locally at 20fps, but the LIST is polled — HQ
  // may add, edit or revoke one at any time, and a dono may land on a different
  // renderer than the one that aired it.
  puRender(S.dono_powerups || []);
  setInterval(puTick, 1000 / PU_FPS);
  setInterval(pollPowerups, 10000);
  // Ticker colours change when someone edits them on the Command Center, which
  // is a human action on a page nobody is watching the clock on. 30s.
  setInterval(pollTickerColors, 30000);
  pollEvents();
  pollCryptoPrices();
  pollStreamEvents();
  beat();
})();
