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
// is bucketed into the 8 mood rows (BLOB.md's stated cost of sprites). The API
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
  // are indexed by it (row = MOODS.indexOf(mood)). EXASPERATED is the loss
  // reaction, added as row 7.
  var MOODS = ['IDLE','HAPPY','SCARED','ALERT','SLEEP','SMUG','BRACE','EXASPERATED'];

  // ── Sprite sheets ──────────────────────────────────────────────────────────
  //  blob_body.png  192x384  = 4 breath cols x 8 mood rows (48x48 cells)
  //  blob_eyes.png  144x384  = 3 lid   cols x 8 mood rows
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
      // EXASPERATED — a loss landed. A slow, deflated sigh; red accent.
      if (mood === 'EXASPERATED') { accent = P.RED; bob = Math.round(Math.sin(t * 1.1) * 1.0) + 1; }

      // ── Breath frame (baked columns) ───────────────────────────────────────
      var breath = Math.floor(self.tick / BREATH_HOLD) % 4;

      // ── Blink / lid ────────────────────────────────────────────────────────
      // The travelling blink: half on the way down, shut, half on the way up.
      // Each mood's resting lid is BAKED into its col-0 eye (SMUG and
      // EXASPERATED are already heavy-lidded there), so col 0 is the resting
      // state for every open-eyed mood; only SLEEP forces shut. (SMUG used to
      // force col 1 here, which double-lidded it nearly shut at runtime.)
      var baseLid = mood === 'SLEEP' ? 2 : 0;
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
