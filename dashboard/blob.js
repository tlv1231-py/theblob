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
  var SHEET_EYES_SRC = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAJAAAAGwCAYAAABGnew6AAAKlUlEQVR4nO3dTW7cxhYGUCp4I2niLMBAxjbydpCMvB4HWYnhtyRnBzascYAsIJnIUz3QMB26TDarLosUi30OoImat/uKLP40RdTXdQAAAAAAAABAXTfRwhfdL49Tv7/v/rjZoq621vs/itAfPazEj92bb37/svv94sqM1tXWev9HUvQHz63AVLpCo3W1td7/Ef1QWrC0EueWidbV1nr/R5O9p/R7YekKGvbISF3tvbj1/k9zBILiAXRp773rXn39mRKp62vmvu3sdfQZ9xKpeVGx/yP7T+6CcwPk4fHvf5e5+fGb137qfg7VDbWcaACNN/h4w/c/w2vpMi9vfp2sS99jrpYruQaaOoLkGgbOmve4Frfds8fI8tG6TQZQ7Q09fj+DKG/jLm3gqWWiddVOYWM1NrTBUu5T989NyVGlX35NXf37QI/vvtv4D6/fd3f/++/ktc5wHTPUXRpA/ft0b59/rdviPtCf3YeimuFCPlJ3v/F9oEsD4dIAiNZVPQL1g2UYAHODp+Q9PvsyeLY0981vrv9hB5h7/W7mPfb4AhDZ2Gvqqu3Fucb3QaJ1+j++4ovonL1raploXW2t93+uxzmSa5thBS4+DlFYV1vr/R+JB8oSHigDAAAAAAAAAAAAAAAAAAAA4CuzcyTMzrHxAJqbI2dprpxoXW1LyTtziTvRurMrmqFsaRCMX0unuIvU1ZYT2zS8Ntl/Yd01CM3SmuvSLK1LddJ6Tha2sn0r231m6/2f4hQ2dxQZ8jJq1pUesXLsndZzLVZnZYyzLkpmn4/W0dg1UM61zzixZ3wdE6mrfS0UmaF+mG0+Urf3jPVNHoHGR4306HHpaBKtW6sfpOOf8e/TZca/j9Q9TCx/ZqtOYdGNfpRTVuv9NzuAJveu3/5aPCVF62prtf/bA+aFhcJWpvShK3vW1dZK/7dfNm5pIk+0brMBlCYN5u6B0braWuz/0wHzwrKUpO2kyTtRtW8kttz/pXTBqZ8t6jY/hbGvo+SFZV9ER6OMInVbxCa13v9RZQ2gp7gZVvMzW+//yIr+yJzHMqae7YnW1dZ6/83fBxpWzKVD9NRKjNbV1nr/R+SR1oRHWgEAAAAAAAAAAAAAAAAAAOBcTK6QMLlCGXlhCXlhG8Y9lQShpHPplNZtEfdUEoQyDKRBad39lcwTVBT3VJKiM142UrdF3FNJis542UjdC3FPdSKYInXink50BIokFeam9VzS19bYiz/3H8jv6k9Fa3K/PnZvruIotDovjOt2c8SjT/pe0QvSp8wKu5bMsFUz1a/Ni9gjb+LSe899fj9oc3q6y+j/7JOOO4XxdEegtUeOp071a63/2+7ZY0nWxbB8tC5nWWErjbk9S14Y+2syL+wpsrZqZm613v8ceWGcIi/sKhL/Wu//yATOLRA4VzFwrmRljpeN1G0RONdq/0d2vQ+UNdr/0XikNeGRVgAAAAAAAAAAAAAAAAAAADgXkyskTK6w1/QujeZttd7/0RT9scNKXIoB6Kf3H6/MaF1tubFP6WCI1l2DosC50vyLYdKlSN0WgXOl6TvDgIjU3V/JICoKnNvTFoFze3phks1vCZzL93FFzlhrhK3wtImFfeTREHtUkhk2VzeQWNiG1VkZfWLNMBhK0muidRF33avimv4bYaRu6lvlmYVPYVNHj0tHlLV1a/QDNP0Z/35q2WjdQ7Ls2VVJLNyrrrbW+r89YF5Y+Aj03R74+n3WXhetq63V/m+7Z49LkU1Ty0TrNk8s/Lo3vn2+eV1trfX/qcW8sDOk3bTe/xR5YZwiL0zc0wJxTxXjnva0RdzTnu6v5J+pocc5lv4vlkYfRetqa73/I/qhdnDb1EqM1tXWev9H5JHWhEdaAQAAAAAAAAAAAAAAAAAAAAAAAAAA2EhpFFBJQsyaz9nqffW/QV5Y7kaYyquq+f5R+r9sl7yw4UOmkl8uNRCtq03//1Rb/8Uz1Zd80HigROtq03/d9V98Cst983S5aF1t+q+7/m9q7805DUTratP/065/AAAAAAAAAAAAAAAAAAAAAAAA4GzC05q96H6ZnDTzvvvjZou62lrv/yiK/+hhBX7s3ky+/rL7fXKFRutqa73/oymapXVpJY5fG++p0braWu//iLL3lpyVOLVHDkrrau/Jrfd/iiNQ7kpMl43W1dZ6/80OoH7vja6YSF1fU/NU0Hr/R1Y8Uz2MGUCskp3Wc9e9Kn7zn7qfQ3VDLd9HM5REEgzLR+uqDqCHx79nX7u7+XFy+Zc3v4bqen0tZVFV6TI16jbJC1vy8Pr9rnXX4tOXo0nuxh4GS7Su+n2gj4/vso4m6VEkUrfFfaDSb1TDPZ1I3f3G94EuDYToUSaS2FN+I/HCYBhLT0GldW4ktqFoxOUOonQQROtqG/r4s/uQdQGf9l9adw3i/0ydGQxzgyBaV1vr/R+NxzkSHucAAAAAAAAAAAAAAAAAAAAAAADgqpmhLGGGsh0m2cwJXpuapLK0rrbW+z8ieWEz5IVVjnvaO2+rdtxTtI9o3QtxT/MrdI+8rdpa77/ZU1i/Jy1NsD036XakLn2PtdcT0bC5/hS2diC83CHy4Kllha1MJe70GRfD7+fyLiJ1YxJ7Th441w+Aqcimrequ3W1hHFNJQk/0c8IDKD1i9FFNl7LB1tbx78Zd2sBTy0TrlmSdn5/iOqjG9c9Z+h8r2cDj+KZoXbXAuX6FRHKzonW1td5/unFLc7+idUvcSJzhRmIe/8pI+FdGGf9MTfhnKgAAAAAAAAAAAAAAAAAAAAAA0DoTTCVMMLXDAJrLnhimh5vbCNG62lrvv/k5EpdmLU1XaLSuttb7P6LiicZzprydWiZaV1vr/R9N0TS/0fmSI3W19+LW+z9lVgZkB87tnbdVO3Cu5f6PLDvq4K57VfzmfUxApG6o5UQDaJyos5TzNZjLDBubey9ZYScbQGM145lEPeXrg1JKAlGG5aN1mw0gns7tl7SdSxt4KpEnWrfEAGrIpy9Hk9yNPQyWaF21b2H9PY3oNUmkrq+peR/lc//BDK9I3csN7wP1G3dpA08tE61bclVHoNJvhMM3wWjdliLhcGvqqujvbeQa3weJ1un/hHeic05JU8tE62prvf9zPc7x+G5yBS4+DlFYV1vr/R+JB8oSHigDAAAAAAAAAAAAAAAAAAAA4CuzcyTMzrHxAJqbI2dprpxoXW1LyTtziTvRurMrmqFsaRCMX0unuIvU1ZYT2zS8Ntl/Yd01KEvruTAALh1VInXSek4WtnIpqmAcV5Brqa522Eqt9zryZx76FDZ3FFmKKojUlR6xcuyd1nMtwnlhuYErtepo9Bpo7tonPf30g6H/3TAo+uuYSF3ta6G+/z+7D8V1/WThkbr0Pc7+rSx8BPpug//2V9YRJVq3Rv/+Uz/fLPP6/XevReoeZpY7q1WRl9+spLfPN6+rrfX+j2B1VkZ0TzvKHtpS/7fywlhLXhinygvLUpK2kybvRNW+kdhy/1P6gTD3s0XdnKvKCzuTTwfJC8v+FrZ3YmFtrfd/VNmRl9u3st1ntt7/kRX9kTmPZUw92xOtq631/pu/kTismEuH6KmVGK2rrfX+j8gjrQmPtAIAAAAAAAAA0LXr/w76xs8RPDXGAAAAAElFTkSuQmCC';

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
    var shadesAt = -1, shadesUntil = -1;   // the dono "cool guy" sunglasses
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

      var dx = jx, dy = bob + jy;
      if (ready >= 2) {
        ctx.drawImage(bodyImg, breath * CELL, row * CELL, CELL, CELL, dx, dy, CELL, CELL);
        ctx.drawImage(eyesImg, lid * CELL, row * CELL, CELL, CELL, dx + look, dy, CELL, CELL);
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
        if (fxOn && !self.fxTimer) self.fxTimer = setInterval(fxLoop, 33);   // ~30fps
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

      getMood:  function()    { return self.mood; },
      getTick:  function()    { return self.tick; },
      isRunning: function()   { return !!self.timer; },
      MOODS: MOODS
    };
    return api;
  }

  global.TNDBlob = { create: create, PALETTE: P, MOODS: MOODS };

})(window);
