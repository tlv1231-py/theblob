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
// is bucketed into the 9 mood rows (BLOB.md's stated cost of sprites). The API
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
  // are indexed by it (row = MOODS.indexOf(mood)). EXASPERATED (row 7) is the
  // loss reaction; HOPEFUL (row 8) is the fresh-pickup "gonna win" face.
  var MOODS = ['IDLE','HAPPY','SCARED','ALERT','SLEEP','SMUG','BRACE','EXASPERATED','HOPEFUL'];

  // ── Modern FX layer ─────────────────────────────────────────────────────────
  // "Hi-bit": the sprite stays crisp 8-bit, but around it we add SMOOTH light
  // and motion driven by an interval (rAF and CSS transitions are frozen in the
  // headless capture, so the fade/bounce has to be driven). None of this touches
  // the pixel art — it is transform + drop-shadow on the canvas element, plus one
  // in-canvas gloss pass. Set opts.fx = false to render the bare sprite.
  //
  // Resting neon-bloom strength per mood (the drop-shadow glow breathes at this).
  var MOOD_GLOW = { IDLE: 0.16, HAPPY: 0.46, SCARED: 0.34, ALERT: 0.52, SLEEP: 0.04,
                    SMUG: 0.24, BRACE: 0.42, EXASPERATED: 0.30, HOPEFUL: 0.44 };
  // How hard each mood "lands" — the squash bounce + glow spike + aberration hit
  // when it fires. Verdicts hit hardest; SLEEP/IDLE don't punch at all.
  var MOOD_KICK = { HAPPY: 1.0, ALERT: 0.85, SCARED: 0.7, BRACE: 0.5,
                    EXASPERATED: 0.78, HOPEFUL: 0.82, SMUG: 0.4 };

  // ── Sprite sheets ──────────────────────────────────────────────────────────
  //  blob_body.png  192x432  = 4 breath cols x 9 mood rows (48x48 cells)
  //  blob_eyes.png  144x432  = 3 lid   cols x 9 mood rows
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
    var lookX = 0, lookUntil = -1, reading = false;
    var alertAt = -1;   // when ALERT last fired, for the entry pop
    var shadesAt = -1, shadesUntil = -1;   // the dono "cool guy" sunglasses
    var crownAlpha = opts.crown === true ? 1 : 0;   // paper crown; 0 = hidden.
    // Potion-driven from stream.js (setCrown): worn while a potion is active,
    // dimmed to blink it out at the end of the potion's life.
    var fxOn = opts.fx !== false;
    // FX state: a squash SPRING (pos/vel), an aberration punch and a glow spike,
    // all eased toward rest in fxLoop. impact() kicks all three at once.
    var sqPos = 0, sqVel = 0, aber = 0, glowSpike = 0;

    function impact(strength) {
      sqVel -= strength * 0.26;                        // flatten, then spring back up
      aber = Math.max(aber, strength);
      glowSpike = Math.max(glowSpike, strength * 0.9);
    }

    function fill(c, x, y, w, h) {
      ctx.fillStyle = 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')';
      ctx.fillRect(x, y, w, h);
    }

    // Sunglasses — the dono reward. NOT a mood: an accessory that drops in from
    // overhead, holds over his eyes, then lifts off, drawn on top of whatever
    // face is underneath. Two black lenses + bridge + temple arms + a diagonal
    // shine. `oy` is the drop offset (negative = still up in the air).
    function drawShades(ox, oy) {
      function lens(x0, x1) {
        fill(P.EYE, ox + x0, oy + 15, x1 - x0 + 1, 16);          // lens — covers the eye
        fill(P.OUT, ox + x0, oy + 14, x1 - x0 + 1, 1);           // top rim
        for (var k = 0; k < 5; k++) fill(P.WHT, ox + x0 + 2 + k, oy + 18 + k, 1, 1);  // shine
      }
      lens(9, 22); lens(25, 38);
      fill(P.EYE, ox + 22, oy + 16, 4, 3);                        // bridge
      fill(P.EYE, ox + 6, oy + 16, 3, 2);                         // left temple
      fill(P.EYE, ox + 39, oy + 16, 3, 2);                        // right temple
    }

    function shadesOffset() {
      // easeOutBack drop, hold, then a quick slide back up before it clears.
      var DROP = 8, LIFT = 6, UP = 34;
      var el = self.tick - shadesAt, rem = shadesUntil - self.tick;
      if (el < DROP) {
        var q = el / DROP - 1, e = 1 + 2.70158 * q * q * q + 1.70158 * q * q;
        return Math.round(-UP * (1 - e));
      }
      if (rem < LIFT) return Math.round(-UP * (1 - rem / LIFT));
      return 0;
    }

    // The paper party crown — the Burger King kind. An accessory ON him like the
    // shades: flat gold "paper", drawn in cell coords so it scales crisp and bobs
    // on his dome with the sprite (and squashes with the FX). A wide zigzag band
    // with five points, perched over the top of his head (his eyes start ~y15, so
    // the band at y11-13 sits on the forehead). No text — just the shape. Off-ramp
    // gold is allowed here for the same reason the shades' black is: it is an
    // accessory, not his body, and the always-pink rule is about HIM.
    var CROWN_GOLD = [242, 193, 29];    // the paper
    var CROWN_HI   = [255, 228, 130];   // upper-left highlight (his key light)
    var CROWN_SH   = [176, 122, 18];    // the band's shaded underside
    function drawCrown(ox, oy) {
      // Band across the dome. Bottom row darker so it reads as a folded paper edge.
      fill(CROWN_GOLD, ox + 14, oy + 11, 21, 2);      // x14..34, y11..12
      fill(CROWN_SH,   ox + 14, oy + 13, 21, 1);      // y13 — the shaded lip
      // Five points rising from the band — centre tallest, sides shorter, so the
      // silhouette reads as a crown and not a saw. hb=2 -> ~5px bases that meet.
      var pts = [[15, 6], [20, 4], [24, 3], [28, 4], [33, 6]];   // [cx, tipY]
      for (var i = 0; i < pts.length; i++) {
        var cx = pts[i][0], tip = pts[i][1], hb = 2, h = 11 - tip;
        for (var yy = tip; yy <= 11; yy++) {
          var half = Math.round((yy - tip) / h * hb);
          fill(CROWN_GOLD, ox + cx - half, oy + yy, half * 2 + 1, 1);
          fill(CROWN_HI,   ox + cx - half, oy + yy, 1, 1);       // lit left edge
        }
      }
      // A gloss dab on the band, upper-left, and a rounded lit tip on each point.
      fill(CROWN_HI, ox + 16, oy + 11, 2, 1);
    }

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
      // Default = his identity NEON PINK. Colour comes from the MOOD (a verdict),
      // not ambient P&L: red is reserved for a loss, green for a win. Driving it
      // off `p` lit him red at rest on any down day — the opposite of confident.
      var accent = P.MID;

      if (mood === 'HAPPY')  { bob = Math.round(Math.abs(Math.sin(t * 5.5)) * -4); accent = P.GRN; }
      if (mood === 'SCARED') { accent = P.RED; jx = (self.tick % 2 ? 1 : -1); jy = (self.tick % 3 ? 0 : 1); }
      if (mood === 'ALERT')  { accent = P.CYN; var pop = Math.max(0, 1 - (self.tick - alertAt) / 12); bob -= Math.round(pop * 2); }
      if (mood === 'SLEEP')  { bob = Math.round(Math.sin(t * 0.8) * 1.2); }
      if (mood === 'BRACE')  { accent = P.CYN; bob = Math.round(Math.sin(t * 1.7) * 0.4); }
      // EXASPERATED — a loss landed. A slow, deflated sigh; red accent.
      if (mood === 'EXASPERATED') { accent = P.RED; bob = Math.round(Math.sin(t * 1.1) * 1.0) + 1; }
      // HOPEFUL — a fresh pickup. An eager little upward hop. NEUTRAL cyan, not
      // green: a buy is not a win yet, so it glows "activity" (like ALERT/BRACE),
      // and green stays reserved for an actual winning exit.
      if (mood === 'HOPEFUL') { accent = P.CYN; bob = Math.round(Math.abs(Math.sin(t * 4.2)) * -3) - 1; }

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
      // Reading a narrator/potion panel: the eyes drop toward it (it sits below
      // him) and scan the line side-to-side, so he looks like he's reading it.
      // Not for his own speech — that is him talking, not reading.
      var eyeY = 0;
      if (reading) { eyeY = 3; look += Math.round(Math.sin(self.tick * 0.55) * 2); }

      var dx = jx, dy = bob + jy;
      if (ready >= 2) {
        ctx.drawImage(bodyImg, breath * CELL, row * CELL, CELL, CELL, dx, dy, CELL, CELL);
        ctx.drawImage(eyesImg, lid * CELL, row * CELL, CELL, CELL, dx + look, dy + eyeY, CELL, CELL);
        // The crown sits on his dome, above the eyes — drawn after the sprite so
        // it rests on top of his head rather than behind it. globalAlpha lets
        // stream.js blink it out at the end of a potion's life.
        if (crownAlpha > 0) {
          ctx.save(); ctx.globalAlpha = crownAlpha;
          drawCrown(dx, dy);
          ctx.restore();
        }
      }

      // No particles — "just Blobby". Every mood is carried entirely by the
      // eyes now, so the old spark / sweat / "!" FX are gone. The ONE overlay
      // that survives is the dono sunglasses, and they are an accessory ON him,
      // not a separate character.
      if (self.tick < shadesUntil) drawShades(dx, dy + shadesOffset());

      // Gloss sweep — a slow specular sheen travelling across him, clipped to
      // his silhouette (source-atop). A glossy-mascot highlight on top of the
      // flat pixel fill. Chunky by design; it rides the 48px grid like the rest.
      if (fxOn) {
        var gp = (self.tick % 34) / 34;
        var gx = -14 + gp * (W + 28);
        ctx.save();
        ctx.globalCompositeOperation = 'source-atop';
        var grd = ctx.createLinearGradient(gx - 7, 0, gx + 7, H);
        grd.addColorStop(0, 'rgba(255,255,255,0)');
        grd.addColorStop(0.5, 'rgba(255,255,255,0.26)');
        grd.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = grd;
        ctx.fillRect(0, 0, W, H);
        ctx.restore();
      }

      self.accent = accent;   // handed to fxLoop for the bloom colour
      if (self.onAccent) self.onAccent(accent);
    }

    // A transition blink — masks an expression swap behind a dipped lid. Guarded
    // so a burst of changes doesn't restart it mid-blink and strobe.
    function transBlink() { if (self.tick >= blinkUntil) blinkUntil = self.tick + 3; }

    function loop() {
      self.tick++;
      // A transient mood decaying back to IDLE is a transition too — give the
      // return-to-calm the same soft beat + blink so it eases rather than snaps.
      if (moodUntil > 0 && self.tick > moodUntil) {
        self.mood = 'IDLE'; moodUntil = -1; impact(0.24); transBlink();
      }
      if (self.tick > nextBlink) {
        blinkUntil = self.tick + 3;    // 3 ticks = closing / shut / opening
        nextBlink = self.tick + 30 + Math.random() * 50;
      }
      draw();
    }

    // Element-level FX, on their OWN faster interval so the bounce and glow are
    // smooth even though the sprite only redraws at 10fps. Everything here is a
    // transform / drop-shadow on the canvas element — smooth over a pixel sprite
    // because both rasterise the alpha and scale/blur it, ignoring
    // image-rendering. Degrades gracefully: throttled in the capture, it simply
    // updates less often, never breaks.
    function fxLoop() {
      // Squash SPRING toward rest, plus a tiny ambient bounce on the up moods.
      sqVel += (0 - sqPos) * 0.24;
      sqVel *= 0.78;
      sqPos += sqVel;
      aber *= 0.80;
      glowSpike *= 0.86;
      var amb = (self.mood === 'HAPPY' || self.mood === 'HOPEFUL')
              ? Math.sin(Date.now() / 130) * 0.05 : 0;
      var s = Math.max(-0.30, Math.min(0.40, sqPos + amb));

      // Volume-preserving squash, bouncing off his base rather than his middle.
      var sy = (1 + s).toFixed(3), sx = (1 - s * 0.55).toFixed(3);
      canvas.style.transformOrigin = '50% 62%';
      canvas.style.transform = 'scale(' + sx + ',' + sy + ')';

      // Neon bloom — a mood-coloured glow that breathes and spikes on impact,
      // plus a chromatic-aberration hit (two offset colour shadows) on a punch.
      var c = self.accent || P.MID, rgb = c[0] + ',' + c[1] + ',' + c[2];
      var g = Math.min(1, (MOOD_GLOW[self.mood] || 0.16) + glowSpike);
      var f = 'drop-shadow(0 0 ' + (5 + g * 14).toFixed(1) + 'px rgba(' + rgb + ',' + (0.55 + g * 0.35).toFixed(2) + ')) '
            + 'drop-shadow(0 0 ' + (14 + g * 30).toFixed(1) + 'px rgba(' + rgb + ',' + (0.20 + g * 0.30).toFixed(2) + '))';
      if (aber > 0.03) {
        var ao = (aber * 5).toFixed(1);
        f += ' drop-shadow(' + ao + 'px 0 rgba(255,64,80,' + (aber * 0.8).toFixed(2) + ')) '
           + 'drop-shadow(-' + ao + 'px 0 rgba(64,220,255,' + (aber * 0.8).toFixed(2) + '))';
      }
      canvas.style.filter = f;
    }

    // ── Public API — identical surface to the procedural version ─────────────
    var api = {
      start: function() {
        if (!self.timer) self.timer = setInterval(loop, 1000 / FPS);
        if (fxOn && !self.fxTimer) self.fxTimer = setInterval(fxLoop, 42);   // 24fps —
        // matches the encode 1:1. Was 30, which burned frames the 24fps capture
        // discarded; 24 keeps that saving while staying smooth. (Briefly 20 to save
        // more, but the encode had to return to 24 for YouTube to go live, and a
        // 20fps FX under 24fps capture judders on a 1.2:1 ratio.
        return api;
      },
      stop: function() {
        clearInterval(self.timer); self.timer = null;
        clearInterval(self.fxTimer); self.fxTimer = null;
        return api;
      },

      setMood: function(m, durTicks) {
        if (MOODS.indexOf(m) < 0) return api;
        var changed = m !== self.mood;
        self.mood = m;
        moodUntil = durTicks ? self.tick + durTicks : -1;
        if (m === 'ALERT') alertAt = self.tick;
        // A mood LANDING is a punch — squash bounce + glow spike + aberration —
        // and it BLINKS. The blink is the human bit: the eyes dip shut across the
        // swap, so the new expression eases in behind a lid instead of hard-
        // cutting, which reads as a reaction rather than a state flip. Verdicts
        // hit hard (MOOD_KICK); any other change still gets a soft beat so a
        // burst feels connected. Guarded on a real change so syncBlobMood's every-
        // second re-assert doesn't buzz.
        if (changed) { impact(MOOD_KICK[m] || 0.28); transBlink(); }
        return api;
      },
      setPnl:   function(pct) { self.pnl = pct; return api; },
      setVisor: function(on)  { self.visor = !!on; return api; },   // no-op in art
      // The paper crown. Accepts a boolean (on/off) or an alpha 0..1 — stream.js
      // drives it from potion state and dims it to blink the crown out at the end
      // of a potion's life. 0 hides it entirely.
      setCrown: function(v) {
        crownAlpha = (v === true) ? 1 : (v === false ? 0 : Math.max(0, Math.min(1, +v || 0)));
        return api;
      },

      // The dono "cool guy": sunglasses drop from overhead, hold for durTicks,
      // then lift off. Independent of mood — pair it with a smirk for full effect.
      cool: function(durTicks) {
        shadesAt = self.tick;
        shadesUntil = self.tick + (durTicks || 42);
        impact(0.95);   // the dono is the biggest hit on the stream
        return api;
      },

      glance: function(dx, durTicks) {
        lookX = Math.max(-1, Math.min(1, dx));
        lookUntil = self.tick + (durTicks || 12);
        return api;
      },

      // Reading a panel below him — eyes drop and scan until turned off.
      read: function(on) { reading = !!on; return api; },

      getMood:  function()    { return self.mood; },
      getTick:  function()    { return self.tick; },
      isRunning: function()   { return !!self.timer; },
      MOODS: MOODS
    };
    return api;
  }

  global.TNDBlob = { create: create, PALETTE: P, MOODS: MOODS };

})(window);
