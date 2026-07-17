// ═══════════════════════════════════════════════════════════════════════════
// THE BLOB — sprite-driven 8-bit pilot character
//
// The body/face are now HAND-AUTHORED sprite sheets (the goofy-slime redesign),
// blitted here, rather than computed procedurally. What the sheets DO NOT bake —
// bob, jitter, the horizontal glance, blink, particles, the outer bloom — this
// engine still does, exactly as before, so the reaction language is unchanged.
//
// This reverses BLOB.md's "procedural, not sprite sheets" decision on purpose:
// the character art is now a fixed look the operator picked, and continuous PnL
// is bucketed into the 7 mood rows (BLOB.md's stated cost of sprites). The API
// below is byte-for-byte the same one stream.js and home_nav.js already drive,
// so nothing downstream changes.
//
// The two sheets are inlined as data URIs so blob.js stays a SINGLE self-
// contained text file — the one property BLOB.md cares about (hands off cleanly
// in git and review; no binary side-car to serve from inside the iframe).
// Regenerate the sheets with scripts/gen_blobby_ref.py, then re-embed them with
// scripts/embed_blob_sheets.py.
//
//   var blob = TNDBlob.create(document.getElementById('blobCanvas'), {...});
//   blob.start();
//   blob.setPnl(0.4);           // percent — buckets into a mood + rim accent
//   blob.setMood('ALERT', 12);  // transient — decays back to IDLE
//
// See dashboard/BLOB.md for the design contract.
// ═══════════════════════════════════════════════════════════════════════════

(function(global) {

  // Palette — still the locked cyberpunk ramp. Used now only by the FX
  // particles and the rim-accent callback; the body/face colour lives in the
  // sheets. MID is his identity colour.
  var P = {
    OUT : [ 42,  0, 61],
    LO  : [138,  0,108],
    MID : [255,  0,204],   // #ff00cc
    HI  : [255,110,226],
    SPEC: [255,200,248],
    EYE : [ 10,  0, 16],
    GRN : [  0,255,157],   // up
    RED : [255, 51,102],   // down
    CYN : [  0,229,255],   // activity
    WHT : [255,255,255]
  };

  // Row order is the sprite-sheet row order and is NON-NEGOTIABLE — the sheets
  // are indexed by it. Matches the old MOODS array so every setMood() call in
  // stream.js still lands on the right face.
  var MOODS = ['IDLE','HAPPY','SCARED','ALERT','SLEEP','SMUG','BRACE'];

  // ── Sprite sheets ──────────────────────────────────────────────────────────
  //  blob_body.png  192x336  = 4 breath cols x 7 mood rows (48x48 cells)
  //  blob_eyes.png  144x336  = 3 lid   cols x 7 mood rows
  // Body col: 0 neutral / 1 expanded / 2 neutral / 3 contracted (a breath loop).
  // Eyes col: 0 open / 1 half / 2 shut. SLEEP row is shut in all three.
  var CELL = 48;
  var SHEET_BODY_SRC = 'data:image/png;base64,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';
  var SHEET_EYES_SRC = 'data:image/png;base64,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';

  var bodyImg = new Image(), eyesImg = new Image(), ready = 0;
  bodyImg.onload = function() { ready++; };
  eyesImg.onload = function() { ready++; };
  bodyImg.src = SHEET_BODY_SRC;
  eyesImg.src = SHEET_EYES_SRC;

  // Ticks each breath frame is held: 4 x 7 / 10fps = 2.8s per cycle. Subtle —
  // this is breathing, not bouncing.
  var BREATH_HOLD = 7;

  function create(canvas, opts) {
    opts = opts || {};
    var W = opts.grid || 48;
    var H = W;
    var FPS = opts.fps || 10;   // Do not raise. See BLOB.md "Framerate".

    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    var self = {
      mood: 'IDLE',
      pnl: 0,
      visor: !!opts.visor,   // stored for API-compat; the sheets have no visor
      tick: 0,
      timer: null,
      onAccent: opts.onAccent || null
    };
    var blinkUntil = -1, nextBlink = 30, moodUntil = -1, fx = [];
    var lookX = 0, lookUntil = -1;
    var alertAt = -1;   // when ALERT last fired, for the entry pop

    function rgb(c) { return 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'; }
    function fill(c, x, y, w, h) { ctx.fillStyle = rgb(c); ctx.fillRect(x, y, w, h); }

    function draw() {
      ctx.clearRect(0, 0, W, H);

      var t = self.tick / FPS;
      var p = Math.max(-1, Math.min(1, self.pnl / 4));      // ±4% saturates
      var mood = self.mood;
      var row = MOODS.indexOf(mood); if (row < 0) row = 0;

      // ── Engine motion the sheet deliberately does NOT bake ─────────────────
      // Whole-pixel translation only; the mood deformation itself is in the art.
      var bob = Math.round(Math.sin(t * 1.7) * 1.6);
      var jx = 0, jy = 0;
      var accent = p > 0.05 ? P.GRN : (p < -0.05 ? P.RED : P.MID);

      if (mood === 'HAPPY')  { bob = Math.round(Math.abs(Math.sin(t * 5.5)) * -4); accent = P.GRN; }
      if (mood === 'SCARED') { accent = P.RED; jx = (self.tick % 2 ? 1 : -1); jy = (self.tick % 3 ? 0 : 1); }
      if (mood === 'ALERT')  { accent = P.CYN; var pop = Math.max(0, 1 - (self.tick - alertAt) / 12); bob -= Math.round(pop * 2); }
      if (mood === 'SLEEP')  { bob = Math.round(Math.sin(t * 0.8) * 1.2); }
      if (mood === 'BRACE')  { accent = P.CYN; bob = Math.round(Math.sin(t * 1.7) * 0.4); }

      // ── Breath frame (baked columns) ───────────────────────────────────────
      var breath = Math.floor(self.tick / BREATH_HOLD) % 4;

      // ── Blink / lid ────────────────────────────────────────────────────────
      // The travelling blink: half on the way down, shut, half on the way up.
      // SMUG rides the half-lid as its resting state; SLEEP is always shut.
      var baseLid = mood === 'SLEEP' ? 2 : (mood === 'SMUG' ? 1 : 0);
      var bl = blinkUntil - self.tick;
      var lid = baseLid;
      if (bl > 0) lid = (bl === 2) ? 2 : Math.max(baseLid, 1);
      if (mood === 'SLEEP') lid = 2;

      // ── Glance — the engine slides the EYES layer only ─────────────────────
      // Brows sit on the BODY sheet, so a glance moves the eyes under a held
      // brow, which is what makes it read as a glance. Whole pixels.
      var look = Math.round(p * 1.6);
      if (self.tick < lookUntil) look = Math.round(lookX * 2.4);

      var dx = jx, dy = bob + jy;
      if (ready >= 2) {
        ctx.drawImage(bodyImg, breath * CELL, row * CELL, CELL, CELL, dx, dy, CELL, CELL);
        ctx.drawImage(eyesImg, lid * CELL, row * CELL, CELL, CELL, dx + look, dy, CELL, CELL);
      }

      // ── FX particles — unchanged, drawn with the 2D context now ────────────
      fx = fx.filter(function(f) { return f.life-- > 0; });
      fx.forEach(function(f) {
        f.y += f.vy;
        var X = Math.round(f.x), Y = Math.round(f.y);
        if (f.t === 'spark') {
          var c = f.life > 4 ? P.GRN : P.WHT;
          fill(c, X, Y, 1, 1); fill(c, X - 1, Y, 1, 1); fill(c, X + 1, Y, 1, 1);
          fill(c, X, Y - 1, 1, 1); fill(c, X, Y + 1, 1, 1);
        } else if (f.t === 'sweat') { fill(P.CYN, X, Y, 2, 3); fill(P.CYN, X, Y - 1, 1, 1); }
        else if (f.t === 'bang')    { fill(P.CYN, X, Y, 2, 5); fill(P.CYN, X, Y + 6, 2, 2); }
      });
      if (mood === 'SLEEP' && self.tick % 22 === 0) {
        fx.push({ t:'spark', x:W*0.75, y:H*0.33, life:16, vy:-0.3 });
      }

      if (self.onAccent) self.onAccent(accent);
    }

    function loop() {
      self.tick++;
      if (moodUntil > 0 && self.tick > moodUntil) { self.mood = 'IDLE'; moodUntil = -1; }
      if (self.tick > nextBlink) {
        blinkUntil = self.tick + 3;    // 3 ticks = closing / shut / opening
        nextBlink = self.tick + 30 + Math.random() * 50;
      }
      draw();
    }

    // ── Public API — identical surface to the procedural version ─────────────
    var api = {
      start: function() {
        if (!self.timer) self.timer = setInterval(loop, 1000 / FPS);
        return api;
      },
      stop: function() { clearInterval(self.timer); self.timer = null; return api; },

      setMood: function(m, durTicks) {
        if (MOODS.indexOf(m) < 0) return api;
        self.mood = m;
        moodUntil = durTicks ? self.tick + durTicks : -1;
        if (m === 'ALERT') alertAt = self.tick;
        if (m === 'HAPPY') {
          for (var i = 0; i < 7; i++) {
            fx.push({ t:'spark', x:W/2 + (Math.random()*30-15), y:H*0.42 + (Math.random()*16-8),
                      life:8 + Math.random()*7, vy:-0.35 });
          }
        }
        if (m === 'SCARED') fx.push({ t:'sweat', x:W*0.69, y:H*0.35, life:14, vy:0.5 });
        if (m === 'ALERT')  fx.push({ t:'bang',  x:W/2,     y:H*0.17, life:12, vy:-0.1 });
        return api;
      },
      setPnl:   function(pct) { self.pnl = pct; return api; },
      setVisor: function(on)  { self.visor = !!on; return api; },   // no-op in art

      glance: function(dx, durTicks) {
        lookX = Math.max(-1, Math.min(1, dx));
        lookUntil = self.tick + (durTicks || 12);
        return api;
      },

      getMood:  function()    { return self.mood; },
      getTick:  function()    { return self.tick; },
      isRunning: function()   { return !!self.timer; },
      MOODS: MOODS
    };
    return api;
  }

  global.TNDBlob = { create: create, PALETTE: P, MOODS: MOODS };

})(window);
