// ═══════════════════════════════════════════════════════════════════════════
// THE BLOB — sprite-driven 8-bit pilot character
//
// The body/face are now HAND-AUTHORED sprite sheets — the EYES-ONLY redesign: a
// small pink circle, one tasteful line mouth, and cartoonishly large over-the-
// top eyes that carry every mood. No arm, no fangs, no brows, no particles.
// IDLE is the confident-dumb-guy face and is the DEFAULT. What the sheets do NOT
// bake — bob, jitter, the horizontal glance, blink, the outer bloom — this
// engine still does, so the reaction language is unchanged.
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
// Regenerate the sheets with scripts/gen_blobby_eyes.py, then re-embed them with
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

  // Palette — still the locked cyberpunk ramp. Used now only by the rim-accent
  // callback (onAccent → the outer bloom); the body/face colour lives in the
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
    var blinkUntil = -1, nextBlink = 30, moodUntil = -1;
    var lookX = 0, lookUntil = -1;
    var alertAt = -1;   // when ALERT last fired, for the entry pop

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

      // No particles — "just Blobby". Every mood is carried entirely by the
      // eyes now, so the old spark / sweat / "!" FX are gone: they were the only
      // non-Blobby marks on the canvas, and the over-the-top eyes replace them.

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
