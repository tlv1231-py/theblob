// ═══════════════════════════════════════════════════════════════════════════
// RETRONEWS — fake 90s cable channel renderer.
//
// THE ERA RULE (CLAUDE.md) is binding here and it agrees with the hardware:
//   * tiles change by HARD CUT (display none/block). Never a fade or slide —
//     both because the WeatherSTAR swapped pages on a timer, and because a
//     24fps software compositor cannot tween anything smoothly anyway.
//   * ambient motion is palette-based (blink/colour), never positional.
//   * setInterval for everything. rAF and CSS animations are INERT in this
//     component iframe and fail SILENTLY.
// ═══════════════════════════════════════════════════════════════════════════
(function () {
  var S = window._TND_RETRONEWS || {};
  var $ = function (id) { return document.getElementById(id); };

  // ── Letterbox ────────────────────────────────────────────────────────────
  function fit() {
    var w = window.innerWidth || 1080, h = window.innerHeight || 1920;
    document.documentElement.style.setProperty(
      '--s', Math.min(w / 1080, h / 1920).toFixed(4));
  }
  fit();
  window.addEventListener('resize', fit);
  setInterval(fit, 1000);

  // ── Broadcast preview: double-tap the top-left corner ────────────────────
  // Fullscreen frames the stage at a true 9:16 — the aspect a YouTube vertical
  // live stream gives you — and switches the reserved-band guides on, so you
  // can see exactly what YouTube's own chrome will cover. That is the whole
  // point of the gesture: not "make it big", but "show me the real frame".
  //
  // NOTE ON FIDELITY, so the preview is not trusted for the wrong thing: your
  // phone renders this at the phone's own resolution, while the broadcast is
  // 810x1440. LAYOUT and framing are exact here; sharpness is optimistic.
  var DTAP_MS = 400;
  var lastTap = 0;

  function fsToggle() {
    try {
      var d = document;
      if (d.fullscreenElement || d.webkitFullscreenElement) {
        (d.exitFullscreen || d.webkitExitFullscreen || function () {}).call(d);
      } else {
        var el = d.documentElement;
        var req = el.requestFullscreen || el.webkitRequestFullscreen;
        if (req) {
          // navigationUI:'hide' asks mobile to drop its bars — advisory, and
          // harmless as an unknown key where unsupported.
          var p = req.call(el, { navigationUI: 'hide' });
          // requestFullscreen REJECTS rather than throws; without this the
          // failure is an unhandled rejection in a console nobody is watching.
          if (p && p.catch) p.catch(function (e) {
            console.warn('[retronews] fullscreen refused:', e);
          });
        }
      }
    } catch (e) {
      console.warn('[retronews] fullscreen refused:', e);
    }
  }

  var hit = $('fs-hit');
  if (hit) {
    // pointerdown, not click: one handler covers touch and mouse, and it fires
    // early enough to still carry the transient activation requestFullscreen
    // demands. Deliberately NOT preventDefault-ed — touch-action in the CSS
    // already kills double-tap zoom, and cancelling here risks the activation.
    hit.addEventListener('pointerdown', function () {
      var now = Date.now();
      if (now - lastTap > 0 && now - lastTap < DTAP_MS) {
        lastTap = 0;                 // consume, so a third tap starts a fresh pair
        fsToggle();
      } else {
        lastTap = now;
      }
    });
  }

  // Entering fullscreen resizes the wrap, but the box is not final on the event
  // itself — re-fit over the next few frames. setTimeout, never rAF.
  function fsChange() {
    var on = !!(document.fullscreenElement || document.webkitFullscreenElement);
    var stage = $('stage');
    // Guides ride fullscreen: preview mode shows what YouTube covers. ?guides=1
    // still forces them on outside fullscreen.
    if (stage && !S.guidesPinned) stage.classList.toggle('guides-on', on);
    fit(); setTimeout(fit, 60); setTimeout(fit, 250);
  }
  document.addEventListener('fullscreenchange', fsChange);
  document.addEventListener('webkitfullscreenchange', fsChange);

  // If the page was loaded with ?guides=1 the class is already on; remember that
  // so leaving fullscreen does not strip a guide the operator explicitly asked for.
  S.guidesPinned = !!(document.getElementById('stage') &&
                      document.getElementById('stage').classList.contains('guides-on'));

  // The iframe's own resize event does NOT reliably fire when the frame is
  // resized from outside, and rAF/ResizeObserver ride the inert rendering loop.
  // A timer is the only thing that can be trusted to notice. Cheap: one rect
  // read, and it only refits when the box actually changed.
  var lastBox = '';
  setInterval(function () {
    var wrap = $('stage-wrap');
    if (!wrap) return;
    var r = wrap.getBoundingClientRect();
    var k = Math.round(r.width) + 'x' + Math.round(r.height);
    if (k === lastBox) return;
    lastBox = k;
    fit();
  }, 500);

  // ── Broadcast clock ──────────────────────────────────────────────────────
  // A channel always knows what time it is. Also doubles as proof-of-life: a
  // frozen clock on air is the tell that the render died while ffmpeg happily
  // kept encoding the dead frame at a perfect 24fps.
  function clock() {
    var d = new Date();
    var h = d.getHours(), m = d.getMinutes();
    var ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12; if (h === 0) h = 12;
    var el = $('rn-clock');
    if (el) el.textContent = h + ':' + String(m).padStart(2, '0') + ' ' + ap;
  }
  clock();
  setInterval(clock, 1000);

  // ── National weather ─────────────────────────────────────────────────────
  // Open-Meteo: free, NO API KEY, CORS-enabled, and it takes comma-separated
  // coordinates so ten cities cost ONE request. That matters twice over — the
  // free-tier rule, and not hammering a public endpoint from a 24/7 stream.
  // FIFTEEN, because that is what the tall panel reveals. Still ONE request —
  // Open-Meteo takes comma-separated coordinates, so the city count costs
  // nothing extra against the free tier or the endpoint.
  // Paging falls out of it: 10 fit with the host on (2 pages), all 15 fit with
  // him off (1 page, no counter).
  var CITIES = [
    ['SEATTLE',       47.61, -122.33], ['CHICAGO',      41.88,  -87.63],
    ['SAN FRANCISCO', 37.77, -122.42], ['ATLANTA',      33.75,  -84.39],
    ['LOS ANGELES',   34.05, -118.24], ['MIAMI',        25.76,  -80.19],
    ['DENVER',        39.74, -104.99], ['NEW YORK',     40.71,  -74.01],
    ['PHOENIX',       33.45, -112.07], ['BOSTON',       42.36,  -71.06],
    ['DALLAS',        32.78,  -96.80], ['HOUSTON',      29.76,  -95.37],
    ['PHILADELPHIA',  39.95,  -75.17], ['DETROIT',      42.33,  -83.05],
    ['MINNEAPOLIS',   44.98,  -93.27]
  ];

  // WMO weather codes -> the short, all-caps labels a 90s CG would have shown.
  function condOf(c) {
    if (c === 0) return 'CLEAR';
    if (c === 1) return 'FAIR';
    if (c === 2) return 'P CLOUDY';
    if (c === 3) return 'CLOUDY';
    if (c === 45 || c === 48) return 'FOG';
    if (c >= 51 && c <= 57) return 'DRIZZLE';
    if (c >= 61 && c <= 67) return 'RAIN';
    if (c >= 71 && c <= 77) return 'SNOW';
    if (c >= 80 && c <= 82) return 'SHOWERS';
    if (c === 85 || c === 86) return 'SNOW SHWRS';
    if (c >= 95) return 'T-STORM';
    return '--';
  }

  // ROW HEIGHT IS FIXED; how many rows FIT is what changes. The panel is 171
  // logical with the host on and 267 with him off, and a row is 17 either way —
  // so 10 rows become 15. Nothing scales, the board just reveals more of itself,
  // which is what those boards actually did.
  //
  // Measured rather than hardcoded: the two page sizes are a consequence of the
  // layout, and writing 10 and 15 down here is how they end up disagreeing with
  // it the next time a panel height moves.
  var WX_ROW_LOGICAL = 17;
  var wxAll = [], wxPage = 0;

  // Measured off the SLOT, which is always visible — NOT off the weather grid.
  // The grid lives inside a tile that is display:none whenever another tile is
  // showing, so it measures ZERO height, floor(0/68) clamps to 1, and the board
  // repaints with a SINGLE row. That bites exactly when the host intro repaints
  // during a transition to a different tile, i.e. most of the time.
  var WX_HEAD_LOGICAL = 24;               // .rn-tile-head, above the grid
  function wxRowsThatFit() {
    var slot = document.querySelector('.rn-slot');
    if (!slot) return 10;
    var cs = getComputedStyle(document.documentElement);
    var s = parseFloat(cs.getPropertyValue('--s')) || 1;
    var px = parseFloat(cs.getPropertyValue('--px')) || 4;
    var body = slot.getBoundingClientRect().height / s - WX_HEAD_LOGICAL * px;
    return Math.max(1, Math.floor(body / (WX_ROW_LOGICAL * px)));
  }

  // Writes EVERY .rn-wx-grid, not the first. There is one panel set per slot,
  // and today there is one slot — but a document-wide single lookup is exactly
  // the bug that would come back the moment a second is added: it paints
  // whichever copy sorts first and leaves the other permanently blank.
  function renderWx(rows) {
    var grids = document.querySelectorAll('.rn-wx-grid');
    if (!grids.length) return;
    for (var gi = 0; gi < grids.length; gi++) {
      var g = grids[gi];
      g.innerHTML = '';
      rows.forEach(function (r) {
        var cell = document.createElement('div');
        cell.className = 'wx-cell';
        var city = document.createElement('div');
        city.className = 'wx-city'; city.textContent = r.city;
        var temp = document.createElement('div');
        temp.className = 'wx-temp';
        temp.textContent = (r.t == null ? '--' : Math.round(r.t)) + '°';
        var cond = document.createElement('div');
        cond.className = 'wx-cond'; cond.textContent = r.cond;
        cell.appendChild(city); cell.appendChild(temp); cell.appendChild(cond);
        g.appendChild(cell);
      });
    }
    var subs = document.querySelectorAll('.rn-wx-sub');
    var stamp = 'UPDATED ' + new Date().toLocaleTimeString('en-US',
      { hour: 'numeric', minute: '2-digit' });
    var pages = Math.max(1, Math.ceil(wxAll.length / wxRowsThatFit()));
    for (var si = 0; si < subs.length; si++) {
      subs[si].textContent = pages > 1
        ? stamp + '  ' + (wxPage + 1) + '/' + pages
        : stamp;
    }
  }

  function paintWxPage() {
    if (!wxAll.length) return;
    var per = wxRowsThatFit();
    var pages = Math.max(1, Math.ceil(wxAll.length / per));
    if (wxPage >= pages) wxPage = 0;       // panel grew; old page may not exist
    var from = wxPage * per;
    renderWx(wxAll.slice(from, from + per));
  }

  // Page on the same beat the tiles cut on, so the board never has two
  // different clocks running against each other.
  setInterval(function () {
    if (!wxAll.length) return;
    var pages = Math.ceil(wxAll.length / wxRowsThatFit());
    if (pages < 2) return;
    wxPage = (wxPage + 1) % pages;
    paintWxPage();
  }, 15000);

  function pollWeather() {
    var lat = CITIES.map(function (c) { return c[1]; }).join(',');
    var lon = CITIES.map(function (c) { return c[2]; }).join(',');
    fetch('https://api.open-meteo.com/v1/forecast?latitude=' + lat +
          '&longitude=' + lon +
          '&current=temperature_2m,weather_code&temperature_unit=fahrenheit')
      .then(function (r) { return r.json(); })
      .then(function (j) {
        // One coord returns an object, many return an array. Normalise.
        var arr = Array.isArray(j) ? j : [j];
        wxAll = CITIES.map(function (c, i) {
          var cur = (arr[i] && arr[i].current) || {};
          return { city: c[0], t: cur.temperature_2m, cond: condOf(cur.weather_code) };
        });
        paintWxPage();
      })
      .catch(function () { /* a blip is not a reason to blank the board */ });
  }
  pollWeather();
  setInterval(pollWeather, 10 * 60 * 1000);   // 10min — weather does not sprint

  // -- Tile rotation - TWO SLOTS ---------------------------------------------
  // The schedule IS the aesthetic ("Local on the 8s"). Cuts only.
  //
  // Two slots each run their own cycle over the same panel list and are held
  // apart by pickNext(), so the same panel is never on screen twice. They also
  // never dissolve simultaneously: two ~935ms dissolves firing together reads as
  // the whole screen glitching rather than one page turning, so slot B starts
  // half a dwell out of phase and rotate() lets only one cut run at a time.
  var order = ['wx', 'donors', 'market', 'nowplaying'];
  var dwell = 15000;

  // -- THE DISSOLVE ----------------------------------------------------------
  // Tiles never fade - they dissolve in chunky blocks, cover, swap behind a
  // one-frame gold flash, uncover. That is the GBA's own transition vocabulary
  // (hardware MOSAIC + window wipes), and it is quantised BY CONSTRUCTION:
  // every step is a discrete cut, so there is nothing for a 24fps software
  // compositor to fail to interpolate.
  //
  // -- FRAME BUDGET - every timed visual on this page obeys it ---------------
  // ffmpeg captures at 24fps, so ONE BROADCAST FRAME IS ~42ms and nothing
  // shorter can appear on the stream at all. Worse, a duration that is not a
  // whole MULTIPLE of the frame period beats against the capture clock: the
  // first version of this dissolve used 55ms = 1.32 frames, so steps drifted in
  // and out of phase and some were merged into a single captured frame and
  // simply never appeared.
  //
  // TWO frames per step, not one. The render paints ~22-23.6 unique fps against
  // a 24fps capture (measured on the host), so a 1-frame step can be dropped
  // entirely. Two frames is the smallest unit that is guaranteed to survive.
  var FRAME_MS = 42;
  // Must COVER the panel or the dissolve leaves a live strip along an edge.
  // Blocks are 12x12 logical and the panel is 208 wide, so 18 columns = 216.
  //
  // ROWS ARE SIZED FOR THE TALLER STATE. With the host hidden the panel grows
  // from 195 to 291 logical, and 17 rows (204) would have covered the small
  // panel and left the bottom THIRD of the big one live during every dissolve —
  // visible only in the mode we just added, which is exactly the kind of bug
  // that ships. 25 rows = 300, over both, and the overflow is clipped anyway.
  var WIPE_COLS = 18, WIPE_ROWS = 25, WIPE_STEPS = 6, WIPE_MS = FRAME_MS * 2;

  function Slot(el, startIdx, startCut) {
    this.el = el;
    this.wipe = el.querySelector('.rn-wipe');
    this.blocks = [];
    this.shuffle = [];
    this.wiping = false;
    this.idx = startIdx;
    this.lastCut = startCut;
    this.build();
    this.show(order[this.idx]);
  }

  Slot.prototype.build = function () {
    if (!this.wipe) return;
    var frag = document.createDocumentFragment();
    var n = WIPE_COLS * WIPE_ROWS;
    for (var i = 0; i < n; i++) {
      var b = document.createElement('div');
      b.className = 'wipe-b';
      frag.appendChild(b);
      this.blocks.push(b);
      this.shuffle.push(i);
    }
    this.wipe.appendChild(frag);
    // Scatter the reveal order. A raster fill reads as a wipe; a scatter reads
    // as a DISSOLVE, which is the mosaic feel we want. Each slot shuffles
    // separately so the two never dissolve in an identical pattern.
    for (var j = this.shuffle.length - 1; j > 0; j--) {
      var k = Math.floor(Math.random() * (j + 1));
      var t = this.shuffle[j]; this.shuffle[j] = this.shuffle[k]; this.shuffle[k] = t;
    }
  };

  // Scoped to THIS slot's subtree. The panel set exists twice in the DOM, so a
  // document-wide query would toggle both slots to the same tile.
  Slot.prototype.show = function (id) {
    var tiles = this.el.querySelectorAll('.rn-tile');
    for (var i = 0; i < tiles.length; i++) {
      tiles[i].classList.toggle('on', tiles[i].getAttribute('data-tile') === id);
    }
    this.current = id;
  };

  // onSwap fires at FULL COVER, the one moment the panel is completely hidden.
  // Anything that changes the panel's geometry belongs there: the host appearing
  // shrinks it by 96 logical, and doing that in the open would be a visible jump
  // rather than a cut.
  Slot.prototype.cutTo = function (id, onSwap) {
    var self = this;
    // No overlapping dissolves: a second one mid-flight would strand blocks
    // visible forever. Same reasoning as the Blob stream's lane arbiter.
    if (!this.wipe || !this.blocks.length || this.wiping) {
      this.show(id);
      if (onSwap) onSwap(id);
      return;
    }
    this.wiping = true;
    this.wipe.classList.add('on');
    var n = this.blocks.length, step = 0;

    var cover = setInterval(function () {
      step++;
      var upto = Math.round(n * step / WIPE_STEPS);
      for (var i = 0; i < upto; i++) self.blocks[self.shuffle[i]].classList.add('on');
      if (step < WIPE_STEPS) return;
      clearInterval(cover);

      // Full cover: swap the tile behind it, flash gold for one frame.
      self.wipe.classList.add('flash');
      self.show(id);
      if (onSwap) onSwap(id);
      setTimeout(function () {
        self.wipe.classList.remove('flash');
        var back = WIPE_STEPS;
        var uncover = setInterval(function () {
          back--;
          var from = Math.round(n * back / WIPE_STEPS);
          for (var i = from; i < n; i++) self.blocks[self.shuffle[i]].classList.remove('on');
          if (back > 0) return;
          clearInterval(uncover);
          self.wipe.classList.remove('on');
          self.wiping = false;
        }, WIPE_MS);
      }, WIPE_MS);            /* flash held 2 frames - see FRAME_MS */
    }, WIPE_MS);
  };

  var slots = [];
  (function initSlots() {
    var els = document.querySelectorAll('.rn-slot');
    var now = Date.now();
    for (var i = 0; i < els.length; i++) {
      // Slot B starts on a different panel AND half a dwell out of phase, so
      // the two never show the same thing and never cut together.
      slots.push(new Slot(els[i], i % Math.max(1, order.length),
                          now - (i * dwell / 2)));
    }
  })();

  // The next panel this slot may show: forward from its current index, skipping
  // whatever another slot is already showing. Without the skip, two slots over
  // an even-length list drift into lockstep and display identical pages.
  function pickNext(slot) {
    for (var step = 1; step <= order.length; step++) {
      var i = (slot.idx + step) % order.length;
      var taken = false;
      for (var k = 0; k < slots.length; k++) {
        if (slots[k] !== slot && slots[k].current === order[i]) { taken = true; break; }
      }
      if (!taken) return i;
    }
    return slot.idx;                       // fewer panels than slots - hold
  }


  // ── TILE COUNTDOWN ───────────────────────────────────────────────────────
  // Six pips draining over the dwell. TIME-BASED off the slot's own lastCut, not
  // a counter of its own: a second timer would drift against the one that
  // actually decides when the tile changes, and the bar would empty at a
  // different moment than the cut it is predicting.
  //
  // Clamped at zero because the dwell is a FLOOR, not a promise — rotate() also
  // waits for any dissolve to finish and takes one slot per tick, so the real
  // interval can run past `dwell` and a naive count would go negative.
  var PIPS = 6;
  function updatePips() {
    var sl = slots[0];
    if (!sl) return;
    var frac = Math.max(0, Math.min(1, (Date.now() - sl.lastCut) / dwell));
    // FILLS, not drains. ceil() rather than floor() so the final pip lights for
    // the whole last 1/6 of the dwell — with floor() it would arrive only at
    // frac === 1, a single frame, and the green would never be seen.
    var filled = Math.ceil(frac * PIPS);
    // The last pip blinks GREEN — bar full, cut imminent. Class toggle only, so
    // it is palette motion and costs the compositor nothing. 504ms matches the
    // alert bar rather than inventing a third blink rate.
    var blinkOn = Math.floor(Date.now() / (FRAME_MS * 12)) % 2 === 0;
    var bars = document.querySelectorAll('.rn-pips');
    for (var b = 0; b < bars.length; b++) {
      var kids = bars[b].children;
      for (var i = 0; i < kids.length; i++) {
        var on = i < filled;
        var last = (i === PIPS - 1);
        kids[i].classList.toggle('hot', last && on);
        kids[i].classList.toggle('on', last && on ? blinkOn : on);
      }
    }
  }

  function rotate() {
    updatePips();                        // same tick that decides the cut
    if (!order.length) return;
    var now = Date.now();
    // One cut at a time across the whole board: simultaneous dissolves read as
    // the screen glitching, not as pages turning.
    for (var k = 0; k < slots.length; k++) if (slots[k].wiping) return;
    for (var i = 0; i < slots.length; i++) {
      var sl = slots[i];
      if (now - sl.lastCut < dwell) continue;
      sl.lastCut = now;
      sl.idx = pickNext(sl);
      sl.cutTo(order[sl.idx], hostIntro);
      return;                              // only one per tick
    }
  }
  setInterval(rotate, 250);




  // ── VOICE ────────────────────────────────────────────────────────────────
  // Pokemon's text sound is a short square blip per character. It is the single
  // most recognisable thing about that dialogue, more than the box itself.
  //
  // The bootstrap is ported from the Blob stream's SFX rather than rewritten,
  // because it encodes two things that took debugging to find:
  //   * The unlock listens on the PARENT document as well as this one. This page
  //     is an iframe inside Streamlit, and a tap only reaches the window it lands
  //     in — on a phone nearly every tap lands on the parent chrome, so the
  //     iframe's context stayed suspended no matter how much you prodded it.
  //   * NOT {once:true}. A gesture that fails to unlock — context not built yet,
  //     resume() rejected — used to consume the listener with no second chance.
  //     resume() on a running context is free, so retrying costs nothing.
  // The broadcast never needs any of it: chromium.sh runs with
  // --autoplay-policy=no-user-gesture-required.
  var VOICE = (function () {
    var ctx = null;
    function init() {
      if (ctx) return;
      try {
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        ctx.resume().catch(function () {});
      } catch (e) {}
    }
    function unlock() {
      init();
      if (ctx && ctx.state === 'suspended') ctx.resume();
    }
    ['pointerdown', 'keydown', 'touchstart', 'touchend', 'click'].forEach(function (ev) {
      window.addEventListener(ev, unlock, { passive: true });
      try {
        if (window.parent && window.parent !== window && window.parent.document) {
          window.parent.document.addEventListener(ev, unlock, { passive: true });
        }
      } catch (e) {}          // cross-origin one day: never take the page down
    });
    init();
    return {
      // Square wave, fixed pitch, ~26ms. Fixed because Gen 1's was — a blip that
      // wanders in pitch reads as an effect rather than as a voice. The short
      // ramps are not decoration: a square wave started and stopped at full gain
      // clicks, and 24 clicks a second is unlistenable.
      blip: function () {
        if (!ctx || ctx.state !== 'running') return false;
        try {
          var t = ctx.currentTime;
          var osc = ctx.createOscillator(), g = ctx.createGain();
          osc.type = 'square';
          osc.frequency.setValueAtTime(1380, t);
          g.gain.setValueAtTime(0.0001, t);
          g.gain.exponentialRampToValueAtTime(0.035, t + 0.004);
          g.gain.exponentialRampToValueAtTime(0.0001, t + 0.026);
          osc.connect(g); g.connect(ctx.destination);
          osc.start(t); osc.stop(t + 0.03);
          return true;
        } catch (e) { return false; }
      },
      state: function () { return ctx ? ctx.state : 'none'; }
    };
  })();

  // ── TALKING BOB ──────────────────────────────────────────────────────────
  // He has no mouth-open frame — the sheet is 3 lid columns x 6 mood rows and
  // every mouth is baked into its row, so there is nothing to animate. A 1
  // logical px bob in time with the blips is what the hardware would have done
  // anyway, and it is discrete BY DESIGN: this is sprite animation, not a glide,
  // so the coarse step is the point rather than the flaw.
  //
  // Bobs DOWN, never up. The portrait clips at 72x90 with his shoulders already
  // cut by the frame, so moving down hides 4px of shoulder (invisible) and opens
  // 4px above his hair (already background). Moving up would clip his hair and
  // expose a dark strip under him.
  var bobOn = false;
  function hostBob(on) {
    var sp = $('rn-host-sprite');
    if (!sp || on === bobOn) return;
    bobOn = on;
    sp.style.transform = on ? 'translateY(4px)' : '';
  }

  // ── GEN-1 DIALOGUE BOX ───────────────────────────────────────────────────
  // Pokemon Red's box cuts in; the remembered "animation" is the typewriter and
  // the blinking arrow. Both are quantized by construction, which is the only
  // kind of motion this hardware renders cleanly.
  //
  // TIME-BASED, not tick-based — the same rule the crawl obeys. Characters are
  // derived from elapsed wall-clock, so a delayed timer on the loaded broadcast
  // VM jumps to the right character instead of typing slower than in preview.
  var SAY_STEPS   = 5;                 // stepped open/close
  var SAY_STEP_MS = FRAME_MS * 2;      // 84ms per step = 420ms, ~10 frames
  var SAY_H       = 72 * 4;            // 72 logical x --px, the box's full height
  var CHAR_MS     = FRAME_MS;          // ~24 chars/sec, close to Gen-1 medium
  // KEEP DIALOGUE ASCII. Press Start 2P is a narrow bitmap face; a character it
  // lacks silently falls back to Courier New MID-SENTENCE, which is exactly the
  // inconsistency that looks like a font bug. An em dash was doing this.
  function sayAscii(t) {
    return String(t).replace(/[—–]/g, '-')
                    .replace(/[‘’]/g, "'")
                    .replace(/[“”]/g, '"');
  }

  var sayBox, sayTxt, sayArrow;
  var sayFull = '', sayT0 = 0, sayPhase = 'shut', sayStep = 0, sayTimer = null;

  function sayEls() {
    if (!sayBox) {
      sayBox = $('rn-say'); sayTxt = $('rn-say-txt'); sayArrow = $('rn-say-arrow');
    }
    return !!(sayBox && sayTxt);
  }

  // WHICH EDGE MOVES IS THE WHOLE EFFECT, and height alone does not control it.
  // The box is pinned by its TOP in normal flow, so shrinking height lifts the
  // bottom edge and it collapses UPWARD. Compensating margin-top by exactly the
  // height lost holds the BOTTOM still and walks the top down instead — the box
  // wipes DOWN and out, like a shade being let go.
  //
  // Total occupied space stays marginTop + height = SAY_MARGIN + SAY_H, so the
  // host strip's fixed 92 logical is never overrun and nothing below shifts.
  //
  // OPEN keeps the top pinned (it unrolls downward); only CLOSE compensates.
  function sayApplyStep() {
    var px = parseFloat(getComputedStyle(document.documentElement)
                          .getPropertyValue('--px')) || 4;
    var base = 4 * px;                                   // #rn-say margin-top
    var h = Math.round(SAY_H * sayStep / SAY_STEPS);
    sayBox.style.height = h + 'px';
    sayBox.style.marginTop = (base + (sayPhase === 'close' ? SAY_H - h : 0)) + 'px';
    // VERTICAL PADDING SCALES WITH THE STEP, or the box never actually leaves.
    // box-sizing is border-box, so height:0 still renders the 16px top and
    // bottom padding — the close bottomed out at a 32px sliver AND pushed 32px
    // past the host strip, since margin was compensating for a height the box
    // refused to reach. Horizontal padding is untouched: scaling it would reflow
    // the text mid-animation.
    var padV = Math.round(base * sayStep / SAY_STEPS);
    sayBox.style.paddingTop = padV + 'px';
    sayBox.style.paddingBottom = padV + 'px';
  }

  // The ONE entry point. Everything that speaks goes through here so the box can
  // never be half-typed by one writer and overwritten by another.
  function saySpeak(text) {
    if (!sayEls()) return;
    clearInterval(sayTimer);
    sayFull = sayAscii(text == null ? '' : text);
    sayTxt.textContent = '';
    if (sayArrow) sayArrow.classList.remove('on');

    if (!sayFull) {                       // nothing to say: close and stay shut
      sayPhase = 'shut'; sayStep = 0; sayApplyStep(); return;
    }
    sayPhase = 'open'; sayStep = 0; sayApplyStep();
    sayT0 = Date.now();
    sayTimer = setInterval(sayTick, FRAME_MS);
  }

  function sayTick() {
    if (!sayEls()) return;
    var el = Date.now() - sayT0;
    if (sayPhase === 'open') {
      var st = Math.min(SAY_STEPS, Math.floor(el / SAY_STEP_MS) + 1);
      if (st !== sayStep) { sayStep = st; sayApplyStep(); }
      if (st >= SAY_STEPS) { sayPhase = 'type'; sayT0 = Date.now(); }
      return;
    }
    if (sayPhase === 'type') {
      var n = Math.floor(el / CHAR_MS);
      if (n >= sayFull.length) {
        sayTxt.textContent = sayFull;
        sayPhase = 'done'; sayT0 = Date.now();
        hostBob(false);              // land him flat on the last character
        return;
      }
      // Only touch the DOM when the count actually changes — and that is also
      // the one moment a NEW character appeared, so the blip and the bob hang
      // off it rather than off a second timer that would drift against it.
      if (sayTxt.textContent.length !== n) {
        sayTxt.textContent = sayFull.slice(0, n);
        // Every OTHER character. One blip per character at 24 chars/sec is a
        // buzz rather than a voice, and this plays every 15 seconds forever.
        // Spaces stay silent: Gen 1 bipped through them and it sounds mechanical
        // in a sentence this short.
        var ch = sayFull.charAt(n - 1);
        if (n % 2 === 0 && ch !== ' ') VOICE.blip();
        hostBob(n % 2 === 0);
      }
      return;
    }
    if (sayPhase === 'done' && sayArrow) {
      // Blink by class toggle — palette motion, zero compositor cost.
      sayArrow.classList.toggle('on', Math.floor(el / ARROW_MS) % 2 === 0);
    }
  }

  // Stepped close, so the box leaves the way it arrived.
  function sayClose() {
    if (!sayEls()) return;
    clearInterval(sayTimer);
    if (sayArrow) sayArrow.classList.remove('on');
    sayPhase = 'close'; sayT0 = Date.now();
    hostBob(false);
    sayTimer = setInterval(function () {
      var st = SAY_STEPS - Math.floor((Date.now() - sayT0) / SAY_STEP_MS);
      sayStep = Math.max(0, st); sayApplyStep();
      if (sayStep <= 0) {
        clearInterval(sayTimer);
        sayTxt.textContent = '';
        sayPhase = 'shut';
      }
    }, FRAME_MS);
  }

  // ── HOST INTRO — the default tile transition ─────────────────────────────
  // He appears WITH the new tile (both arrive behind the dissolve), introduces
  // it, then steps aside and the board takes his space — 10 weather rows become
  // 15. That is the REVEAL behaviour already built for the host toggle, now
  // driven by the schedule instead of by hand.
  //
  // Both edges are CUTS. A panel that grows by 96 logical cannot be animated
  // here anyway (CSS transitions are inert in this iframe), and a cut is the era.
  var INTRO_MS = FRAME_MS * 120;          // 5040ms = 120 frames exactly
  // SENTENCE CASE. These were written in all caps back when dialogue used the
  // SIGNAGE face, whose lowercase reads as caps anyway — so caps cost nothing
  // and matched the headers. The speech face has true lowercase now, and a
  // presenter talking should not read like a station ident. Budget is 63 chars.
  var INTRO = {
    wx:         'And now, your national forecast.',
    donors:     "Let's thank tonight's contributors.",
    market:     'Next up: how the markets closed.',
    nowplaying: "And here's what we've been playing."
  };
  var introT = null;
  var hostMaster = true;                  // HQ can switch him off entirely

  function hostShow(on) {
    var stg = $('stage');
    if (!stg) return;
    if (stg.classList.contains('no-host') === !on) return;   // already there
    stg.classList.toggle('no-host', !on);
    // The panel just changed height, so a different number of rows fits. Without
    // this the board keeps the old page size until the next 15s page tick.
    wxPage = 0;
    paintWxPage();
  }

  function hostIntro(tileId) {
    clearTimeout(introT);
    if (!hostMaster) { hostShow(false); return; }
    hostShow(true);

    // Do NOT talk over a viewer. pollEvents locks the say box for 12s when
    // someone tips, and a thank-you outranks a programming link every time.
    var say = $('rn-say');
    var line = INTRO[tileId];
    if (say && !say._locked && line) {
      saySpeak(line);
      say._introOwned = true;             // so pollConfig does not clobber it
    }
    setHostMood('NEUTRAL', INTRO_MS);

    introT = setTimeout(function () {
      // Box leaves BEFORE he does, so the beat reads as him finishing a line and
      // then stepping aside rather than both vanishing at once.
      sayClose();
      setTimeout(function () {
        hostShow(false);
        if (say && say._introOwned) { say._introOwned = false; }
      }, SAY_STEPS * SAY_STEP_MS);
    }, INTRO_MS);
  }



  // ── Config (namespaced to THIS app) ──────────────────────────────────────
  // strategy_params' PK is (strategy, param), so 'stream:retronews' is a free
  // namespace and cannot collide with the Blob's settings.
  function pollConfig() {
    if (!S.supa || !S.supa.url) return;
    fetch(S.supa.url + '/rest/v1/strategy_params?strategy=eq.' +
          encodeURIComponent(S.ns) + '&select=param,value',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        if (!Array.isArray(rows)) return;
        var c = {};
        rows.forEach(function (r) { c[r.param] = r.value; });
        window._TND_RN_CFG = c;

        if (c.dwell_s) dwell = Math.max(4, parseInt(c.dwell_s, 10) || 15) * 1000;
        if (c.rotation) {
          try {
            var o = JSON.parse(c.rotation);
            if (Array.isArray(o) && o.length) {
              var changed = o.join(',') !== order.join(',');
              order = o;
              if (changed) {
                // Re-seat EVERY slot. A single global index cannot describe two
                // independent cycles, and leaving them where they were can put
                // both on the same panel or off the end of a shorter list.
                var t = Date.now();
                for (var si = 0; si < slots.length; si++) {
                  slots[si].idx = si % order.length;
                  slots[si].show(order[slots[si].idx]);
                  slots[si].lastCut = t - (si * dwell / 2);
                }
              }
            }
          } catch (e) {}
        }
        // HOST — now a MASTER switch over the intro cycle, not a direct
        // show/hide. '0' means he never appears at all; anything else means he
        // introduces each tile and then steps aside. Only an explicit '0'
        // suppresses him, so a missing row or a failed fetch leaves the stage as
        // designed rather than silently dropping the channel's anchor.
        var master = c.host_visible !== '0';
        if (master !== hostMaster) {
          hostMaster = master;
          if (!master) { clearTimeout(introT); hostShow(false); }
        }

        // Measuring overlay, driven live from HQ. No reload: the toggle has to
        // be usable while you are looking at the stream in the next window.
        //
        // NO ROW = NO OPINION, the same rule switch.py uses for broadcast_enabled.
        // Without the guard the poll fires ~2s after load with undefined !== '1'
        // and switches off whatever ?yt=1 just asked for, so the URL param looks
        // broken. HQ wins the moment it has ever been pressed, and not before.
        if (window._rnYtToggle && c.yt_overlay !== undefined) {
          window._rnYtToggle(c.yt_overlay === '1');
        }

        var np = $('rn-nameplate');
        if (np) np.textContent = c.host_name || 'YOUR HOST';
        var say = $('rn-say');
        // Only speak when he is actually ON SCREEN. Once the intro ends he is
        // hidden, and without this the config poll keeps re-typing its line into
        // an invisible box every few seconds — a 42ms interval doing nothing a
        // viewer can ever see, on a host whose compositor is already pegged.
        var stgV = $('stage');
        var hostOnScreen = stgV && !stgV.classList.contains('no-host');
        if (say && hostOnScreen && !say._locked && !say._introOwned
            && (c.host_say || '') !== sayFull) saySpeak(c.host_say || '');

        // Alert bar. Empty string = off. Blink is a class toggle, no transition.
        var al = $('rn-alert');
        if (al) {
          var txt = (c.alert || '').trim();
          al.classList.toggle('on', !!txt);
          if (txt) al.firstChild ? (al.textContent = txt) : (al.textContent = txt);
        }
      })
      .catch(function () {});
  }
  pollConfig();
  setInterval(pollConfig, 3000);

  // Alert blink — palette-based ambient motion, ~2 cuts/sec.
  setInterval(function () {
    var al = $('rn-alert');
    if (al && al.classList.contains('on')) al.classList.toggle('blink');
  }, FRAME_MS * 12);      /* 504ms = 12 frames exactly, not 500 */

  // ── THE HOST ─────────────────────────────────────────────────────────────
  // One sprite sheet, indexed exactly like blob.js: column = eyelid, row = mood.
  // Everything is frame-aligned (see FRAME_MS) so no state lasts less than one
  // captured frame — a blink that falls between frames simply never happened as
  // far as the broadcast is concerned.
  var MOOD_ROW = { NEUTRAL: 0, HAPPY: 1, SURPRISED: 2, SMUG: 3, WORRIED: 4, SLEEPY: 5 };
  var CELL_W = 72, CELL_H = 90, ART = 4;          // 4x -> 288x360 stage
  var hostMood = 'NEUTRAL', hostLid = 0;
  var moodUntil = 0, nextBlink = 0, blinkSeq = null, blinkI = 0;

  function drawHost() {
    var el = $('rn-host-sprite');
    if (!el) return;
    var row = MOOD_ROW[hostMood] || 0;
    el.style.backgroundPosition =
      (-hostLid * CELL_W * ART) + 'px ' + (-row * CELL_H * ART) + 'px';
  }

  function setHostMood(m, holdMs) {
    if (!(m in MOOD_ROW)) return;
    hostMood = m;
    moodUntil = Date.now() + (holdMs || 6000);
    drawHost();
  }

  // The travelling blink: half / shut / half, never a hard cut from open to
  // closed. At this rate a two-state blink reads as the eye VANISHING for a
  // frame rather than as a blink — the same lesson BLOB.md records.
  var BLINK = [1, 2, 1];

  function hostTick() {
    var now = Date.now();
    if (blinkSeq) {
      hostLid = blinkSeq[blinkI++];
      if (blinkI >= blinkSeq.length) { blinkSeq = null; hostLid = 0; }
      drawHost();
      return;
    }
    if (moodUntil && now > moodUntil && hostMood !== 'NEUTRAL') {
      hostMood = 'NEUTRAL'; moodUntil = 0; drawHost();
    }
    if (now > nextBlink) {
      // SLEEPY holds his eyes shut; blinking through it would fight the pose.
      if (hostMood !== 'SLEEPY') { blinkSeq = BLINK; blinkI = 0; }
      nextBlink = now + 2600 + Math.random() * 4200;
    }
  }
  drawHost();
  nextBlink = Date.now() + 1500;
  setInterval(hostTick, FRAME_MS * 2);            // 84ms = 2 frames per lid state

  window._TND_HOST = {
    mood: function () { return hostMood; },
    lid: function () { return hostLid; },
    set: setHostMood
  };


  // ── THE CRAWL ────────────────────────────────────────────────────────────
  // Lives in the VARIABLE band, and is the only surface allowed to: when chat
  // covers it, chat is showing the same events, so the occlusion cancels out.
  //
  // Motion is a GLIDE in stage px, not a step per character cell. CLAUDE.md is
  // explicit that a coarse position grid reads as choppy at any framerate — the
  // ART steps, the POSITION glides. 5 stage px/frame is ~119px/s (~3.7 chars/s
  // at the 8-logical face) — a readable chyron pace. transform on the element,
  // capture-safe, driven by setInterval because CSS animation is inert here.
  //
  // SPEED AND CONTENT LENGTH ARE ONE DECISION, not two. New content is applied
  // at the WRAP (rebuilding mid-scroll visibly jumps the line), so the loop time
  // IS the worst-case latency for a tip reaching the crawl. The first version
  // ran 4px/frame over all four idents: a 7515px track, a 79-SECOND loop, and
  // therefore up to 79s before a donation appeared. Fixed by carrying ONE ident
  // per build and capping events, not by dropping the wrap-sync.
  // TIME-BASED, NOT TICK-BASED — the one thing on this page whose appearance
  // would otherwise differ between a dev preview and the broadcast. Position was
  // accumulated per tick (crawlX -= 5), which makes SPEED a function of timer
  // reliability: on a laptop at 60fps with an idle GPU the timer fires on
  // schedule and it runs at exactly 119px/s, but the broadcast VM holds its
  // software compositor at ~98% of one core, delays timer callbacks, and the
  // crawl would simply run SLOWER on air than in preview. Deriving position from
  // wall-clock elapsed makes the speed correct no matter when ticks actually
  // land — a late tick jumps to where it should be instead of falling behind.
  //
  // This is also why a dropped frame is harmless here where it would not be for
  // a stepped effect: continuous motion has no discrete state to lose.
  var CRAWL_PX = 5;                         // design px per 42ms frame
  var CRAWL_PPS = CRAWL_PX * 1000 / FRAME_MS;   // = 119 px/sec, the real unit
  var CRAWL_EVENTS = 4;
  var crawlTrack = $('rn-crawl-track');
  var crawlHalf = 0, crawlPending = null, crawlKey = '', crawlT0 = Date.now();

  // Station idents, so the crawl is never empty on a quiet stream. Same job as
  // the Blob stream's AFK lines: silence should read as programming, not death.
  var IDENTS = [
    'RETRONEWS &#9670; CHANNEL 4 &#9670; BROADCASTING 24 HOURS A DAY',
    'NATIONAL CONDITIONS UPDATED CONTINUOUSLY FROM OUR WEATHER CENTER',
    'YOU ARE WATCHING RETRONEWS &#9670; THANK YOU FOR STAYING WITH US',
    'STAY TUNED FOR MARKET WATCH, TOP CONTRIBUTORS AND MORE'
  ];

  function esc(t) {
    return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function evText(row) {
    var p = row.payload || {};
    var who = '<span class="cr-who">' + esc((p.from || 'SOMEONE').toUpperCase()) + '</span>';
    var t = (row.event_type || '').toLowerCase();
    if (p.amount != null) {
      return who + ' TIPPED <span class="cr-amt">$'
             + Number(p.amount).toFixed(2) + '</span>';
    }
    if (t.indexOf('sub') === 0) return who + ' SUBSCRIBED';
    if (t.indexOf('follow') === 0) return who + ' FOLLOWED';
    if (t.indexOf('raid') === 0) {
      return who + ' RAIDED WITH ' + esc(p.viewers || '?') + ' VIEWERS';
    }
    if (p.text) return who + ': ' + esc(String(p.text).toUpperCase());
    return who + ' &#9670; ' + esc(t.toUpperCase());
  }

  function buildCrawl(items) {
    if (!crawlTrack) return;
    var SEP = '<span class="cr-sep">&#9670;</span>';
    var one = items.join(SEP);
    // Doubled so the wrap is seamless: when the first copy has fully scrolled
    // past, resetting by exactly its width lands on the identical frame.
    crawlTrack.innerHTML = '<span>' + one + SEP + '</span><span>' + one + SEP + '</span>';
    // Measured in STAGE px: getBoundingClientRect is post-transform, so dividing
    // by --s undoes the stage scale. That keeps the loop identical at 1080x1920
    // and at the broadcast's 810x1440, where --s is 0.75.
    crawlHalf = crawlTrack.firstChild.getBoundingClientRect().width /
                (parseFloat(getComputedStyle(document.documentElement)
                  .getPropertyValue('--s')) || 1);
    crawlT0 = Date.now();
    crawlTrack.style.transform = 'translateX(0px)';
  }

  function crawlTick() {
    if (!crawlTrack || !crawlHalf) return;
    var travelled = (Date.now() - crawlT0) * CRAWL_PPS / 1000;

    if (travelled >= crawlHalf) {
      // Advance the ORIGIN by whole loops rather than resetting it, so no
      // distance is lost and no drift accumulates. Handles being late by more
      // than one full loop, which a stalled VM can genuinely do.
      var loops = Math.floor(travelled / crawlHalf);
      crawlT0 += loops * crawlHalf * 1000 / CRAWL_PPS;
      travelled -= loops * crawlHalf;

      // Content changes are applied HERE, at the wrap, not the moment they
      // arrive. Rebuilding mid-scroll resets the transform and the whole line
      // visibly jumps; at the wrap the seam is already invisible.
      if (crawlPending) { buildCrawl(crawlPending); crawlPending = null; return; }
      if (!crawlKey) { idleCrawl(); return; }   // still idle — next ident
    }
    crawlTrack.style.transform = 'translateX(' + (-travelled).toFixed(1) + 'px)';
  }
  // Idle: ONE ident per loop, rotating. Keeps the quiet-stream loop near 17s
  // instead of 79, so the channel identifies itself often rather than rarely.
  var identI = 0;
  function idleCrawl() {
    buildCrawl(['<span class="cr-idle">' + IDENTS[identI % IDENTS.length] + '</span>']);
    identI++;
  }
  idleCrawl();
  setInterval(crawlTick, FRAME_MS);

  // Blinking dot — palette motion, one class toggle, zero compositor cost.
  var crawlDot = $('rn-crawl-dot'), dotOn = true;
  setInterval(function () {
    dotOn = !dotOn;
    if (crawlDot) crawlDot.classList.toggle('off', !dotOn);
  }, FRAME_MS * 16);     /* 672ms = 16 frames exactly, not 700 */

  function setCrawlEvents(rows) {
    var items = [];
    for (var i = 0; i < rows.length && items.length < CRAWL_EVENTS; i++) {
      items.push(evText(rows[i]));
    }
    // Exactly ONE ident, so a busy stream still says what channel it is without
    // tripling the loop time. Four idents was the whole 79-second problem.
    items.push('<span class="cr-idle">' + IDENTS[Math.floor(Math.random() * IDENTS.length)]
               + '</span>');
    var key = items.join('|');
    if (key === crawlKey) return;      // nothing changed; do not disturb the scroll
    crawlKey = key;
    if (!crawlHalf) buildCrawl(items); else crawlPending = items;
  }

  // ── Viewer events (the SHARED bus) ───────────────────────────────────────
  // streamlabs.py / chat.py have no idea this page exists; they just write
  // stream_events and whatever is rendering reacts. A tip therefore works here
  // with zero infrastructure change.
  var seenTs = null;
  function pollEvents() {
    if (!S.supa || !S.supa.url) return;
    var since = new Date(Date.now() - 5 * 60000).toISOString();
    fetch(S.supa.url + '/rest/v1/stream_events?select=event_type,payload,created_at' +
          '&created_at=gte.' + since + '&order=created_at.desc&limit=10',
          { headers: { apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key } })
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        setCrawlEvents(rows);          // the crawl shows the whole recent list
        var top = rows[0];
        if (seenTs === top.created_at) return;
        var first = seenTs === null;
        seenTs = top.created_at;
        if (first) return;                       // never replay history on load
        var p = top.payload || {};
        // Viewer names keep the case THEY chose. Upper-casing someone's handle
        // to match the old all-caps copy was rewriting their name to suit our
        // layout. The crawl still upper-cases, and should: that is a chyron in
        // the signage face, not speech.
        var who = p.from || 'Someone';
        var amt = (p.amount != null) ? ' $' + Number(p.amount).toFixed(2) : '';
        // "We interrupt this broadcast" — the interruption IS the format.
        var say = $('rn-say');
        if (say) {
          saySpeak(who + amt + ' - thank you!');
          say._locked = true;
          setTimeout(function () { say._locked = false; }, 12000);
        }
        // He reacts. Money gets the big face; everything else is a smaller beat.
        setHostMood(p.amount != null ? 'HAPPY' : 'SURPRISED', 12000);
      })
      .catch(function () {});
  }
  pollEvents();
  setInterval(pollEvents, 2000);

  // ── Heartbeat ────────────────────────────────────────────────────────────
  // NOT optional, and not merely "nice for the health strip". watchdog.py
  // restarts Chromium when the newest live stream_page beat is older than 75s.
  // A stream app that does not beat is therefore restarted forever: the reload
  // takes ~90s to come back, still says nothing, and trips the watchdog again.
  // RetroNews could never have stayed on air without this — it would have looked
  // like a mysterious 90-second reboot loop with every unit reporting healthy.
  //
  // Same component name as the Blob stream ON PURPOSE. The watchdog is asking
  // "is the page the encoder captures still alive", which is a question about
  // the render, not about which app is in it — and only one is ever on air.
  var _beats = 0;
  function beat() {
    if (!S.supa || !S.supa.url) return;
    _beats++;
    fetch(S.supa.url + '/rest/v1/stream_health', {
      method: 'POST',
      headers: {
        apikey: S.supa.key, Authorization: 'Bearer ' + S.supa.key,
        'Content-Type': 'application/json', Prefer: 'return=minimal'
      },
      body: JSON.stringify({
        component: 'stream_page',
        status: 'ok',
        detail: {
          app: 'RetroNews',      // which app was rendering — the beat is shared
          beats: _beats,
          tiles: slots.map(function (q) { return q.current; }).join(','),
          mood: hostMood,
          // chromium.sh's own comment says to verify audio via this field. A
          // suspended context is SILENT and looks identical to a working one
          // from outside — without this, a mute broadcast is only discoverable
          // by listening to it.
          audio: VOICE.state(),
          wiping: slots.some(function (q) { return q.wiping; }),
          live: !!S.live
        },
        recorded_at: new Date().toISOString()
      })
    }).catch(function () {});
  }
  beat();
  setInterval(beat, 15000);      // matches stream.js and the 75s stale window

  window._TND_RN = {
    cfg: function () { return window._TND_RN_CFG || {}; },
    beats: function () { return _beats; },
    tile: function () { return slots.map(function (q) { return q.current; }); },
    order: function () { return order.slice(); },
    // Exposed so the host-toggle repaint can be exercised without writing to
    // the live config table just to test a layout change.
    wxRows: function () { return wxRowsThatFit(); },
    pips: function () {
      var b = document.querySelector('.rn-tile.on .rn-pips');
      return b ? [].map.call(b.children, function (k) {
        return k.classList.contains('on') ? 1 : 0; }) : null;
    },
    // Speak an arbitrary line, so copy length can be checked against the
    // auto-fit without editing the config table to try a sentence.
    say: function (t) { saySpeak(t); return sayFull; },
    // The EXIT is an animation in its own right and needs to be checkable
    // without waiting out a 5s intro to see it once.
    sayClose: function () { sayClose(); },
    voice: function () { return VOICE.state(); },
    blip: function () { return VOICE.blip(); },
    repaintWx: function () { wxPage = 0; paintWxPage(); },
    cut: function (id, n) { var q = slots[n || 0]; if (q) { q.cutTo(id, hostIntro); q.lastCut = Date.now(); } },
    wiping: function () { return slots.map(function (q) { return q.wiping; }); },
    blocks: function () { return slots.map(function (q) { return q.blocks.length; }); }
  };

  // ── First tile gets an introduction too ──────────────────────────────────
  // Otherwise the channel opens with the anchor already gone, which reads as him
  // having walked off before the show started.
  //
  // THIS CALL LIVES AT THE VERY END OF THE FILE, AND THAT IS NOT STYLE.
  // It walks the whole machine — hostShow -> paintWxPage -> wxRowsThatFit, and
  // setHostMood -> MOOD_ROW — and those live in blocks further down the file.
  // Function declarations hoist; the `var`s they close over do NOT. Placed up
  // beside setInterval(rotate) it read hostMaster as undefined and silently took
  // the master-off branch; moved just below hostMaster it then hit
  // `m in MOOD_ROW` with MOOD_ROW undefined, threw a TypeError, and killed
  // everything after it — the config poll, the crawl, the heartbeat and the
  // debug API all stopped existing. Anything that touches several blocks at
  // startup belongs here, after all of them.
  hostIntro(slots.length ? slots[0].current : order[0]);
})();
