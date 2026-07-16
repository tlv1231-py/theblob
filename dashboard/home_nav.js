// Supabase credentials — declared here so all block-1 functions can reach them
var SUPA_URL = 'https://seeevuklabvhkawawtxn.supabase.co';
var SUPA_KEY = 'sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY';

// Alpaca paper account — injected server-side from .env (never hardcoded in source)
var _ALPACA_DEFAULT  = window._TND.ALPACA_DEFAULT;
var _ALPACA_EXPOSURE = window._TND.ALPACA_EXPOSURE;
var _ALPACA_PORTVAL  = window._TND.ALPACA_PORTVAL;
(function() {
  try {
    if (!_ALPACA_DEFAULT.key || _ALPACA_DEFAULT.key === '{alpaca_api_key}') return;
    var saved = JSON.parse(localStorage.getItem('_alpacaWallets') || '[]');
    var already = saved.some(function(w) { return w.key === _ALPACA_DEFAULT.key; });
    if (!already) {
      saved.unshift(_ALPACA_DEFAULT);
      localStorage.setItem('_alpacaWallets', JSON.stringify(saved));
      localStorage.setItem('_alpacaActiveIdx', '0');
    }
  } catch(e) {}
})();

var _eqCanvasInitData = window._TND.EQ_CANVAS_TILES;
var _queuedActionsData = window._TND.QUEUED_ACTIONS;
var _allTickers = window._TND.ALL_TICKERS;
var portDates  = window._TND.PORT_DATES;
var portValues = window._TND.PORT_VALUES;
var markTs     = window._TND.MARK_TS;
var markVals   = window._TND.MARK_VALS;
// Strip initial inflated value from May 2026 double-run (> 1.5x starting capital)
(function() {
  var cap = 150000;
  var clean = []; var cleanD = [];
  for (var i = 0; i < portValues.length; i++) {
    if (portValues[i] <= cap) { clean.push(portValues[i]); cleanD.push(portDates[i]); }
  }
  // Only apply filter if at least one clean value remains; otherwise keep all data
  if (clean.length) { portValues = clean; portDates = cleanD; }
})();
window._portfolioBaseline = portValues.length ? portValues[portValues.length-1] : 100000;
var spyDates   = window._TND.SPY_DATES;
var spyNorm    = window._TND.SPY_NORM;
var qqqDates   = window._TND.QQQ_DATES;
var qqqNorm    = window._TND.QQQ_NORM;

// Nav snapshots seeded at render time — chart draws immediately, no wait for Supabase poll
window._navDbPts = window._TND.NAV_SNAP_PTS;

var latestDate = portDates.length ? portDates[portDates.length-1] : null;

// Right edge: tomorrow as date string (Plotly date axis uses date-only strings throughout)
function _datePlus(days) {
  var d = new Date(); d.setDate(d.getDate() + days);
  return d.toISOString().slice(0,10);
}
function _dateMinus(isoDateStr, days) {
  var d = new Date(isoDateStr + 'T00:00:00Z');
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0,10);
}
function _datePlus_from(isoDateStr, days) {
  var d = new Date(isoDateStr + 'T00:00:00Z');
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0,10);
}

var latestPortDate = portDates.length ? portDates[portDates.length - 1] : null;
// Fixed x range: portfolio start → tomorrow. No auto-scrolling.
var xStart = portDates.length ? portDates[0] : '2026-05-29';
var xEnd   = _datePlus(1);

// ── Benchmark trajectories ───────────────────────────────────────────────
var _benchStart = portDates.length ? new Date(portDates[0]+'T00:00:00Z') : new Date('2026-05-29T00:00:00Z');
var _benchEnd   = new Date();
var _hysaDates = [], _hysaVals = [], _tgt20Dates = [], _tgt20Vals = [];
(function() {
  var d = new Date(_benchStart);
  var msPerYear = 365.25 * 24 * 3600 * 1000;
  while (d <= _benchEnd) {
    var iso = d.toISOString().split('T')[0];
    var yr  = (d - _benchStart) / msPerYear;
    _hysaDates.push(iso);  _hysaVals.push(100000 * Math.pow(1.048, yr));
    _tgt20Dates.push(iso); _tgt20Vals.push(100000 * Math.pow(1.20,  yr));
    d.setDate(d.getDate() + 1);
  }
})();

var traces = [
  // 0-5: hidden stubs — keep index positions for any code that references them
  { x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' },
  { x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' },
  { x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' },
  { x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' },
  { x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' },
  { x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' },
  // Index 6: Portfolio — the only visible line
  {
    x:[], y:[], name:'PORTFOLIO',
    type:'scatter', mode:'lines',
    line:{ color:'rgba(255,0,204,0.9)', width:2 },
    hovertemplate:'<b style="color:#ff00cc">PORTFOLIO $%{y:,.0f}</b><extra></extra>',
    showlegend:false,
  },
  // Trade event markers — ENTER (index 7), EXIT (index 8)
  {
    x:[], y:[], text:[], name:'ENTER',
    type:'scatter', mode:'markers+text',
    marker:{ symbol:'triangle-up', size:18, color:'rgba(0,255,157,0.92)',
              line:{ color:'rgba(0,255,157,.9)', width:2.5 },
              gradient:{ type:'none' } },
    textposition:'top center',
    textfont:{ family:'Consolas', size:8.5, color:'rgba(0,255,157,1)' },
    hovertemplate:'<b style="color:#00ff9d">ENTER %{text}</b><extra></extra>',
  },
  {
    x:[], y:[], text:[], name:'EXIT',
    type:'scatter', mode:'markers+text',
    marker:{ symbol:'triangle-down', size:18, color:'rgba(255,51,102,0.92)',
              line:{ color:'rgba(255,51,102,.9)', width:2.5 } },
    textposition:'bottom center',
    textfont:{ family:'Consolas', size:8.5, color:'rgba(255,51,102,1)' },
    hovertemplate:'<b style="color:#ff3366">EXIT %{text}</b><extra></extra>',
  },
];

// Milestone y-levels
var _milestones = [97000,98000,99000,101000,102000,103000,104000,105000];
var _milestoneShapes = _milestones.map(function(v) {
  return {
    type:'line', xref:'paper', yref:'y',
    x0:0, x1:1, y0:v, y1:v,
    line:{ color:'rgba(120,0,160,0.18)', width:1, dash:'dot' },
  };
});
// Breakeven zone band ($99.5k – $100.5k)
var _bkZone = [
  { type:'rect', xref:'paper', yref:'y', x0:0, x1:1, y0:99500, y1:100500,
     fillcolor:'rgba(255,0,204,0.04)', line:{ width:0 }, layer:'below' },
  { type:'line', xref:'paper', yref:'y', x0:0, x1:1, y0:100000, y1:100000,
     line:{ color:'rgba(255,0,204,0.35)', width:1, dash:'dot' } },
];
var shapes = [].concat(_milestoneShapes, _bkZone, latestDate ? [{
  type:'line', xref:'x', yref:'paper',
  x0:latestDate, x1:latestDate, y0:0, y1:1,
  line:{ color:'rgba(255,255,255,0.15)', width:1, dash:'dot' },
}] : []);

var annotations = latestDate ? [{
  xref:'x', yref:'paper',
  x:latestDate, y:1.01,
  text:'▶ NOW',
  showarrow:false,
  font:{ family:'Consolas', size:8, color:'rgba(255,255,255,0.3)' },
  xanchor:'left',
}] : [];

var layout = {
  paper_bgcolor:'#060008',
  plot_bgcolor:'#060008',
  margin:{ t:30, b:50, l:60, r:16 },

  xaxis:{
    autorange:true,
    showgrid:true, gridcolor:'rgba(42,0,61,0.5)', gridwidth:1,
    tickfont:{ family:'Consolas', size:8, color:'#3a1a4a' },
    tickformat:'%b %d %H:%M', zeroline:false, showline:false, type:'date', fixedrange:false,
  },
  yaxis:{
    autorange:true,
    showgrid:true, gridcolor:'rgba(42,0,61,0.5)', gridwidth:1,
    tickfont:{ family:'Consolas', size:8, color:'#3a1a4a' },
    tickformat:'$,.0f',
    zeroline:false, showline:false, fixedrange:false,
    tickprefix:'', nticks:6,
  },

  shapes, annotations,
  showlegend:false,
  dragmode:'pan',
  hoverlabel:{ bgcolor:'#0d0010', bordercolor:'#2a003d', font:{ family:'Consolas', size:9, color:'#f0e0ff' } },
  hovermode:'x unified',
};

var config = { scrollZoom:true, displayModeBar:false, responsive:true };
var gd = document.getElementById('chart');

// ── Ambient canvas — night sky + drifting blobs ─────────
var ambCanvas = document.getElementById('ambient-canvas');
(function() {
  function resizeAmb() { ambCanvas.width=window.innerWidth; ambCanvas.height=window.innerHeight; }
  resizeAmb();
  window.addEventListener('resize', resizeAmb);
  var t = 0;

  // ── Star field: three depth layers moving right→left ──────────────────────
  var _starLayers = [
    { count:140, speed:0.25, r:0.55, a:0.22, cr:220, cg:220, cb:255 }, // far — blue-white
    { count:55,  speed:1.1,  r:0.9,  a:0.30, cr:0,   cg:220, cb:255 }, // mid — cyan
    { count:20,  speed:2.8,  r:1.4,  a:0.38, cr:180, cg:0,   cb:255 }, // near — purple
  ];
  var _stars = [];
  _starLayers.forEach(function(l) {
    for (var i = 0; i < l.count; i++) {
      _stars.push({
        x: Math.random(), y: Math.random(),
        speed: l.speed + Math.random() * l.speed * 0.4,
        r: l.r + Math.random() * 0.3,
        a: l.a * (0.6 + Math.random() * 0.4),
        cr: l.cr, cg: l.cg, cb: l.cb,
      });
    }
  });

  // Hyperspeed streaks
  var _streaks = [];

  var blobs = [
    { rx:.18, ry:.55, cr:148, cg:0,   cb:255, a:.11,  sx:.00017, sy:.00011 },
    { rx:.78, ry:.28, cr:0,   cg:229, cb:255, a:.08,  sx:-.00013,sy:.00009 },
    { rx:.45, ry:.80, cr:255, cg:0,   cb:204, a:.065, sx:.00009, sy:-.00015},
    { rx:.88, ry:.65, cr:0,   cg:255, cb:157, a:.05,  sx:-.00011,sy:.00007 },
  ];
  var phases = blobs.map(function(_,i){ return i * 1.57; });
  function drawAmb() {
    var ctx = ambCanvas.getContext('2d');
    var W = ambCanvas.width, H = ambCanvas.height;
    ctx.clearRect(0,0,W,H);
    t += 0.005;

    // ── Stars moving right→left ────────────────────────────────────────────
    _stars.forEach(function(s) {
      s.x -= s.speed / W;
      if (s.x < -0.01) { s.x = 1.02 + Math.random() * 0.05; s.y = Math.random(); }
      ctx.beginPath();
      ctx.arc(s.x * W, s.y * H, s.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + s.cr + ',' + s.cg + ',' + s.cb + ',' + s.a + ')';
      ctx.fill();
    });

    // ── Hyperspeed streaks (rare, fast layer) ──────────────────────────────
    if (Math.random() < 0.018) {
      var _spLen = 0.04 + Math.random() * 0.10;
      _streaks.push({
        x: 1.0 + Math.random() * 0.05, y: Math.random(),
        len: _spLen, a: 0.45 + Math.random() * 0.2,
        speed: 5 + Math.random() * 8,
        cr: Math.random() < 0.5 ? 0 : 180,
        cg: Math.random() < 0.5 ? 229 : 0,
        cb: 255,
      });
    }
    for (var si = _streaks.length - 1; si >= 0; si--) {
      var str = _streaks[si];
      str.x -= str.speed / W;
      str.a -= 0.014;
      if (str.a <= 0 || str.x < -str.len) { _streaks.splice(si, 1); continue; }
      var sg = ctx.createLinearGradient(str.x * W, str.y * H, (str.x + str.len) * W, str.y * H);
      sg.addColorStop(0, 'rgba(' + str.cr + ',' + str.cg + ',' + str.cb + ',0)');
      sg.addColorStop(1, 'rgba(' + str.cr + ',' + str.cg + ',' + str.cb + ',' + str.a + ')');
      ctx.save();
      ctx.strokeStyle = sg;
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.moveTo((str.x + str.len) * W, str.y * H);
      ctx.lineTo(str.x * W, str.y * H);
      ctx.stroke();
      ctx.restore();
    }

    blobs.forEach(function(b,i) {
      var px = (b.rx + Math.sin(t * b.sx * 1000 + phases[i]) * .15) * W;
      var py = (b.ry + Math.cos(t * b.sy * 1000 + phases[i]) * .12) * H;
      var rr = Math.min(W,H) * (.22 + .06 * Math.sin(t + i));
      var g  = ctx.createRadialGradient(px,py,0,px,py,rr);
      g.addColorStop(0, 'rgba('+b.cr+','+b.cg+','+b.cb+','+b.a+')');
      g.addColorStop(1, 'rgba('+b.cr+','+b.cg+','+b.cb+',0)');
      ctx.beginPath();
      ctx.arc(px,py,rr,0,Math.PI*2);
      ctx.fillStyle = g;
      ctx.fill();
    });
    // Heartbeat flatline — drawn on same canvas after blobs
    (function() {
      var baseY = H * 0.88;
      var now2 = Date.now();
      var idle = (now2 - (window._hbLastTrade||now2)) / 1000;
      var alpha = Math.min(1, Math.max(0, (idle - 8) / 4)) * 0.5;
      if (alpha > 0 && !window._hbSpike) {
        var t2 = now2 / 1000;
        var drift = Math.sin(t2 * 0.4) * 3;
        ctx.save();
        ctx.strokeStyle = 'rgba(0,229,255,' + (alpha * 0.55) + ')';
        ctx.lineWidth = 1;
        ctx.shadowColor = 'rgba(0,229,255,' + (alpha * 0.25) + ')';
        ctx.shadowBlur = 5;
        ctx.beginPath();
        ctx.moveTo(0, baseY + drift);
        for (var x = 0; x <= W; x += 4) {
          var noise = Math.sin(x * 0.08 + t2 * 1.2) * 0.8 + Math.sin(x * 0.31 + t2 * 0.7) * 0.4;
          ctx.lineTo(x, baseY + drift + noise * alpha * 3);
        }
        ctx.stroke();
        ctx.restore();
      }
      if (window._hbSpike) {
        var sp = window._hbSpike;
        sp.t += 0.022;
        var col2 = sp.col;
        var spA = Math.max(0, 1 - sp.t / 0.7);
        var spikeH = H * 0.28 * Math.min(1, sp.t * 8);
        var cx2 = W * 0.5;
        ctx.save();
        ctx.strokeStyle = 'rgba('+col2[0]+','+col2[1]+','+col2[2]+','+spA+')';
        ctx.lineWidth = 1.5;
        ctx.shadowColor = 'rgba('+col2[0]+','+col2[1]+','+col2[2]+','+(spA*0.7)+')';
        ctx.shadowBlur = 10;
        ctx.beginPath();
        ctx.moveTo(0, baseY); ctx.lineTo(cx2-60, baseY); ctx.lineTo(cx2-20, baseY);
        ctx.lineTo(cx2, baseY - spikeH); ctx.lineTo(cx2+8, baseY + spikeH*0.3);
        ctx.lineTo(cx2+24, baseY); ctx.lineTo(W, baseY);
        ctx.stroke();
        ctx.restore();
        if (sp.t >= 0.7) window._hbSpike = null;
      }
    })();
    requestAnimationFrame(drawAmb);
  }
  // Heartbeat state (shared with drawAmb)
  window._hbLastTrade = Date.now();
  window._hbSpike = null;
  window._triggerHeartbeat = function(isWin) {
    window._hbLastTrade = Date.now();
    window._hbSpike = { t: 0, col: isWin ? [0,255,157] : [255,51,102] };
  };
  drawAmb();
})();


// ── Pulsing canvas dots ────────────────────────────────
var canvas = document.getElementById('pulse-canvas');
function resizeCanvas() { var ma=document.getElementById('main-area'); if(!ma) return; var r=ma.getBoundingClientRect(); canvas.width=r.width||800; canvas.height=r.height||500; }
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

var pulseTargets = [];

// ── Orb state ─────────────────────────────────────────────────────────────────
var _orbFlash = { active: false, isEntry: true, isWin: false, t: 0, dur: 1400 };
var _orbBurstCount = 0;
var _liveTip = { pts: [] };

// Shockwaves: array of {age, col, cx, cy}
var _shockWaves = [];

// Smoothed orb position — lerped toward true Plotly position each frame
var _smoothPcx = null, _smoothPcy = null;
// Smoothed orbit radii per symbol
var _smoothOrbitR = {};
// Entry age per symbol (frames since first seen) — drives fade-in
var _satEntryAge = {};

// Combo streak display
var _comboCount = 0;
var _comboFlash = null; // {age, text, col}
var _comboLastAt = 0;  // timestamp of last _comboCount increment — drives auto-fade

// Satellite orbit angles: symbol → angle (radians)
var _satAngles = {};
// Satellites currently animating out: symbol → {angle, orbitR, sr, sg, sb, age}
var _satExiting = {};

// NAV particle system — small sparks that react to live price ticks
var _navParticles = [];  // {x,y,vx,vy,life,maxLife,r,g,b,size}
var _lastNavForParticles = null;

window._spawnNavParticles = function(cx, cy, isUp) {
  var col = isUp ? [0,255,157] : [255,51,102];
  var count = 6 + Math.floor(Math.random()*4);
  for (var i=0; i<count; i++) {
    var angle  = Math.random() * Math.PI * 2;
    var speed  = 0.4 + Math.random() * 1.2;
    var drift  = isUp ? -1 : 1;  // float up for gains, fall for losses
    _navParticles.push({
      x: cx + (Math.random()-0.5)*8,
      y: cy + (Math.random()-0.5)*8,
      vx: Math.cos(angle)*speed*0.6,
      vy: Math.sin(angle)*speed*0.4 + drift*(0.3+Math.random()*0.5),
      life: 1.0,
      decay: 0.018 + Math.random()*0.012,
      r: col[0], g: col[1], b: col[2],
      size: 1.2 + Math.random()*1.8,
    });
  }
  // Trim to max 120 particles
  if (_navParticles.length > 120) _navParticles = _navParticles.slice(-120);
};

window._orbTradeFlash = function(isEntry, isWin) {
  _orbFlash.active = true;
  _orbFlash.isEntry = isEntry;
  _orbFlash.isWin   = isWin;
  _orbFlash.t = Date.now();
  _orbBurstCount = isEntry ? 6 : 5;
  // Spawn 5 shockwave rings staggered — use nav-canvas center (same coord space)
  {
    try {
      var scx = (window._navOrbFracX !== undefined ? window._navOrbFracX : 0.5) * canvas.width;
      var scy = (window._navOrbFracY !== undefined ? window._navOrbFracY : 0.5) * canvas.height;
      if (isFinite(scx) && isFinite(scy)) {
        var scol = isEntry ? [255,255,255] : (isWin ? [0,255,157] : [255,51,102]);
        for (var si=0; si<5; si++) {
          (function(delay,offset) {
            setTimeout(function() {
              _shockWaves.push({ age:offset, col:scol, cx:scx, cy:scy });
            }, delay);
          })(si*75, si*0.06);
        }
      }
    } catch(e) {}
  }
};

// Called by block 2 on EXIT result (win/loss) to drive combo counter
window._orbComboResult = function(isWin) {
  if (isWin) {
    _comboCount++;
    _comboLastAt = Date.now();
    var txt = _comboCount >= 10 ? '⚡ SURGE' : _comboCount >= 5 ? 'HOT STREAK' : '+WIN';
    _comboFlash = { age:0, text:txt, col:[0,255,157] };
  } else {
    if (_comboCount > 1) {
      _comboFlash = { age:0, text:'CHAIN BROKEN', col:[255,51,102] };
    }
    _comboCount = 0;
  }
};

function buildTargets() {
  pulseTargets = [];
  // trace order: 0=baseline(skip), 1=SPY, 2=QQQ, 3=PORTFOLIO ghost, 4=PORTFOLIO
  [[1,[0,229,255]], [2,[148,0,255]], [4,[255,0,204]]].forEach(function(ic) {
    var tr = gd.data[ic[0]];
    if (tr && tr.x && tr.x.length) {
      var pt = { x: tr.x[tr.x.length-1], y: tr.y[tr.y.length-1], rgb: ic[1] };
      pulseTargets.push(pt);
    }
  });
  // If intraday trace (6) has newer data, update portfolio orb position
  var intra = gd.data[6];
  if (intra && intra.x && intra.x.length) {
    // Move portfolio dot to latest intraday position
    var pi = pulseTargets.findIndex(function(p) { return p.rgb[0]===255 && p.rgb[2]===204; });
    if (pi >= 0 && intra.y && intra.y.length) {
      pulseTargets[pi].x = intra.x[intra.x.length-1];
      pulseTargets[pi].y = intra.y[intra.y.length-1];
    }
  }
  // Portfolio trace [4] is an empty stub — synthesize portT from live nav so orb still works
  var _hasPortT = pulseTargets.some(function(t) { return t.rgb[0]===255 && t.rgb[2]===204; });
  if (!_hasPortT && window._lastKnownNav && window._lastKnownTs) {
    pulseTargets.push({ x: window._lastKnownTs, y: window._lastKnownNav, rgb: [255,0,204] });
  }
  positionPnlFloat();
}

function positionPnlFloat() {
  // Dot is always center-screen — panel is CSS-anchored, just ensure visible
  var pf = document.getElementById('pnl-float');
  if (pf) pf.classList.add('visible');
}

var phase = 0;
var rafId = null;

// ── Compute pressure from live proximity meters (0=calm, 1=at stop) ──────────
function _computePressure() {
  var maxDanger = 0;
  document.querySelectorAll('.pos-prox-wrap[data-entry]').forEach(function(wrap) {
    var fill = wrap.querySelector('.pos-prox-fill');
    if (!fill) return;
    var t = parseFloat(fill.style.width) / 100; // 0=at stop, 1=at target
    var danger = 1 - t;
    if (danger > maxDanger) maxDanger = danger;
  });
  return Math.max(0, Math.min(1, maxDanger));
}

function drawPulse() {
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  phase += 0.03;

  // Flash blend state
  var flashAlpha = 0;
  var flashRgb = [255, 0, 204];
  if (_orbFlash.active) {
    var elapsed = Date.now() - _orbFlash.t;
    flashAlpha = Math.max(0, 1 - elapsed / _orbFlash.dur);
    if (flashAlpha <= 0) { _orbFlash.active = false; _orbBurstCount = 0; }
    else flashRgb = _orbFlash.isEntry ? [255,255,255] : (_orbFlash.isWin ? [0,255,157] : [255,51,102]);
  }

  // Pressure 0=calm, 1=danger — modulates ring speed, color, tightness
  var pressure = _computePressure();

  // ── SPY / QQQ orbs (unchanged) ────────────────────────────────────────────
  pulseTargets.forEach(function(t) {
    if (t.rgb[0]===255 && t.rgb[2]===204) return; // portfolio handled separately
    try {
      var fl = gd._fullLayout;
      if (!fl || !fl.xaxis || !fl.yaxis) return;
      var cx = fl.xaxis.l2p(fl.xaxis.d2l(t.x)) + fl.margin.l;
      var cy = fl.yaxis.l2p(fl.yaxis.d2l(t.y)) + fl.margin.t;
      if (!isFinite(cx) || !isFinite(cy)) return;
      var r=t.rgb[0], g=t.rgb[1], b=t.rgb[2];
      for (var k=0; k<3; k++) {
        var p = (Math.sin(phase - k*0.9)+1)/2;
        ctx.beginPath();
        ctx.arc(cx, cy, 5+p*22, 0, Math.PI*2);
        ctx.strokeStyle='rgba('+r+','+g+','+b+','+(0.55*(1-p))+')';
        ctx.lineWidth=1.5; ctx.stroke();
      }
      ctx.shadowColor='rgba('+r+','+g+','+b+',1)'; ctx.shadowBlur=18;
      ctx.beginPath(); ctx.arc(cx,cy,5,0,Math.PI*2);
      ctx.fillStyle='rgba('+r+','+g+','+b+',1)'; ctx.fill();
      ctx.shadowBlur=0;
      ctx.beginPath(); ctx.arc(cx,cy,2,0,Math.PI*2);
      ctx.fillStyle='rgba(255,255,255,.9)'; ctx.fill();
    } catch(e) {}
  });

  // ── Portfolio orb — pressure aura + flash ─────────────────────────────────
  var portT = pulseTargets.find(function(t) { return t.rgb[0]===255 && t.rgb[2]===204; });
  if (portT) {
    try {
      // Nav-canvas always draws curNav at (W/2, H/2) of main-area.
      // Pulse-canvas shares the same coordinate space (both inset:0 in #main-area).
      // Use nav-canvas center directly — avoids Plotly yaxis mismatch (NAV $66K vs SPY $750).
      var _rawPcx, _rawPcy;
      if (window._navOrbFracX !== undefined) {
        _rawPcx = window._navOrbFracX * canvas.width;
        _rawPcy = window._navOrbFracY * canvas.height;
      } else {
        // Fallback: center of main-area via Plotly chart dimensions
        var fl0 = gd._fullLayout;
        if (!fl0) throw '';
        _rawPcx = (fl0.width  || canvas.width)  / 2;
        _rawPcy = (fl0.height || canvas.height) / 2;
      }
      if (!isFinite(_rawPcx) || !isFinite(_rawPcy)) throw '';
      // Lerp toward true position — smooths discrete Plotly axis jumps
      var _lerpK = 0.12;
      if (_smoothPcx === null) { _smoothPcx = _rawPcx; _smoothPcy = _rawPcy; }
      _smoothPcx += (_rawPcx - _smoothPcx) * _lerpK;
      _smoothPcy += (_rawPcy - _smoothPcy) * _lerpK;
      var pcx = _smoothPcx, pcy = _smoothPcy;

      // ── Comet trail — leftward gradient fade behind the dot ──────────────
      var trailLen = 220;
      var trailGrad = ctx.createLinearGradient(pcx - trailLen, pcy, pcx, pcy);
      trailGrad.addColorStop(0,   'rgba(255,0,204,0)');
      trailGrad.addColorStop(0.5, 'rgba(255,0,204,0.05)');
      trailGrad.addColorStop(1,   'rgba(255,0,204,0.28)');
      // Body of comet — tapered ellipse
      var halfH = 3.5 + pressure * 3;
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(pcx - trailLen/2, pcy, trailLen/2, halfH, 0, 0, Math.PI*2);
      ctx.fillStyle = trailGrad;
      ctx.fill();
      // Bright leading edge glow
      var edgeGrad = ctx.createRadialGradient(pcx, pcy, 0, pcx, pcy, 22);
      edgeGrad.addColorStop(0,   'rgba(255,0,204,0.18)');
      edgeGrad.addColorStop(1,   'rgba(255,0,204,0)');
      ctx.beginPath(); ctx.arc(pcx, pcy, 22, 0, Math.PI*2);
      ctx.fillStyle = edgeGrad; ctx.fill();
      ctx.restore();
      // ─────────────────────────────────────────────────────────────────────

      // Base color: interpolate pink→red with pressure
      var pr = Math.round(255);
      var pg = Math.round(204*(1-pressure)*0.0);
      var pb = Math.round(204*(1-pressure));
      // Flash overrides
      if (flashAlpha > 0) {
        pr = Math.round(pr*(1-flashAlpha) + flashRgb[0]*flashAlpha);
        pg = Math.round(pg*(1-flashAlpha) + flashRgb[1]*flashAlpha);
        pb = Math.round(pb*(1-flashAlpha) + flashRgb[2]*flashAlpha);
      }

      // ── Trade flash: radiant glow bloom instead of exploding rings ───────────
      if (flashAlpha > 0) {
        var bloomR = 14 + flashAlpha * 18;
        var bloomG = ctx.createRadialGradient(pcx, pcy, 2, pcx, pcy, bloomR);
        bloomG.addColorStop(0,   'rgba('+pr+','+pg+','+pb+','+(0.55*flashAlpha)+')');
        bloomG.addColorStop(0.4, 'rgba('+pr+','+pg+','+pb+','+(0.18*flashAlpha)+')');
        bloomG.addColorStop(1,   'rgba('+pr+','+pg+','+pb+',0)');
        ctx.beginPath(); ctx.arc(pcx, pcy, bloomR, 0, Math.PI*2);
        ctx.fillStyle = bloomG; ctx.fill();
        if (_orbBurstCount > 0) _orbBurstCount = Math.max(0, _orbBurstCount-0.04);
      }

      // Normal pressure rings (always visible, never huge)
      var ringSpeed = 2.0 + pressure * 3.5;
      var ringMax   = 28 - pressure*8;
      var ringCount = 3;

      for (var k=0; k<ringCount; k++) {
        var p2 = (Math.sin(phase*ringSpeed - k*0.9)+1)/2;
        ctx.beginPath();
        ctx.arc(pcx, pcy, 5+p2*ringMax, 0, Math.PI*2);
        ctx.strokeStyle='rgba('+pr+','+pg+','+pb+','+(0.7*(1-p2))+')';
        ctx.lineWidth=2-k*0.3; ctx.stroke();
      }

      // Pressure danger pulse — extra outer ring when near stop
      if (pressure > 0.6) {
        var dp = (Math.sin(phase*6)+1)/2;
        ctx.beginPath();
        ctx.arc(pcx, pcy, 8+dp*(ringMax+16), 0, Math.PI*2);
        ctx.strokeStyle='rgba(255,51,102,'+(0.35*(1-dp)*(pressure-0.6)/0.4)+')';
        ctx.lineWidth=1; ctx.stroke();
      }

      // Core
      var coreSize = 6;
      ctx.shadowColor='rgba('+pr+','+pg+','+pb+',1)';
      ctx.shadowBlur = 18+pressure*12;
      ctx.beginPath(); ctx.arc(pcx,pcy,coreSize,0,Math.PI*2);
      ctx.fillStyle='rgba('+pr+','+pg+','+pb+',1)'; ctx.fill();
      ctx.shadowBlur=0;
      ctx.beginPath(); ctx.arc(pcx,pcy,2.5,0,Math.PI*2);
      ctx.fillStyle='rgba(255,255,255,.95)'; ctx.fill();

      // ── Scanning pulse — slow dim ring between trades ─────────────────────
      if (!_orbFlash.active || flashAlpha < 0.05) {
        var scanPhase = (phase * 0.12) % 1;
        var scanR = 10 + scanPhase * 52;
        var scanOp = 0.20 * (1 - scanPhase) * (1 - pressure * 0.5);
        ctx.beginPath(); ctx.arc(pcx, pcy, scanR, 0, Math.PI*2);
        ctx.strokeStyle = 'rgba(255,0,204,' + scanOp.toFixed(3) + ')';
        ctx.lineWidth = 1.2; ctx.stroke();
      }

      // ── Satellite dots — one per open position (crypto + equity) ─────────
      var cryptoMap  = window._cryptoPositionsMap  || {};
      var equityMap  = window._equityPositionsMap  || {};
      var posMap = Object.assign({}, cryptoMap);
      Object.keys(equityMap).forEach(function(sym) {
        posMap[sym] = equityMap[sym];
      });
      var prices  = window._liveProxPrices    || {};
      var posSyms = Object.keys(posMap);
      posSyms.forEach(function(sym, idx) {
        var pos = posMap[sym];
        if (!pos) return;
        var isEquity = !!pos.is_equity;
        var entry  = parseFloat(pos.entry_price);
        var stop   = parseFloat(pos.stop_price);
        var tgt    = parseFloat(pos.target_price || 0) || entry*1.008;
        // Equity: use current_value as live price proxy; crypto: use live proxy prices
        var price  = isEquity ? (parseFloat(pos.current_value) || entry) : (prices[sym] || entry);
        var range  = tgt - stop;
        var t2     = range ? Math.max(0, Math.min(1, (price-stop)/range)) : 0.5;

        // Equity orbs orbit further out so they're visually distinct from crypto
        var _minR = isEquity ? 52 : 20;
        var _maxR = isEquity ? 68 : 44;
        var _targetR = _minR + t2 * (_maxR - _minR);
        if (_smoothOrbitR[sym] === undefined) _smoothOrbitR[sym] = _targetR;
        _smoothOrbitR[sym] += (_targetR - _smoothOrbitR[sym]) * 0.06;
        var orbitR = _smoothOrbitR[sym];

        // Speed: equity slower (long-term hold), crypto faster
        var satSpeed = isEquity
          ? 0.004 + pressure*0.004
          : 0.012 + (1-t2)*0.022 + pressure*0.018;

        if (_satAngles[sym] === undefined) {
          // New satellite — spawn far out and spiral in
          _satAngles[sym] = idx * (Math.PI*2/Math.max(posSyms.length,1));
          _smoothOrbitR[sym] = _targetR * 3.5;
          _satEntryAge[sym] = 0;
        }
        if (_satEntryAge[sym] !== undefined && _satEntryAge[sym] < 60) _satEntryAge[sym]++;
        _satAngles[sym] += satSpeed;

        var sx = pcx + Math.cos(_satAngles[sym]) * orbitR;
        var sy = pcy + Math.sin(_satAngles[sym]) * orbitR;

        // Equity: cyan palette. Crypto: red→orange→green by proximity to target
        var sr, sg, sb;
        if (isEquity) {
          // Cyan-white for equity — always clearly distinct
          sr = Math.round(0   + t2*40);
          sg = Math.round(200 + t2*55);
          sb = Math.round(255);
        } else {
          sr = Math.round(255*Math.max(0,1-t2*1.5));
          sg = Math.round(255*Math.min(1,t2*1.8));
          sb = Math.round(102*(1-t2));
        }

        // Entry fade-in opacity (0→1 over 40 frames)
        var entryAge = _satEntryAge[sym] !== undefined ? _satEntryAge[sym] : 60;
        var entryOp  = Math.min(1, entryAge / 40);
        var isEntering = entryAge < 40;

        // Faint orbit trail
        ctx.beginPath();
        ctx.arc(pcx, pcy, orbitR, 0, Math.PI*2);
        ctx.strokeStyle='rgba('+sr+','+sg+','+sb+','+(0.06*entryOp)+')';
        ctx.lineWidth=.5; ctx.stroke();

        // Entry streak — bright trail behind satellite as it spirals in
        if (isEntering) {
          var streakLen = (1 - entryOp) * 0.6;
          var sx2 = pcx + Math.cos(_satAngles[sym] - streakLen) * (orbitR * 1.15);
          var sy2 = pcy + Math.sin(_satAngles[sym] - streakLen) * (orbitR * 1.15);
          var sg2 = ctx.createLinearGradient(sx2, sy2, sx, sy);
          sg2.addColorStop(0, 'rgba('+sr+','+sg+','+sb+',0)');
          sg2.addColorStop(1, 'rgba('+sr+','+sg+','+sb+','+(0.7*entryOp)+')');
          ctx.beginPath(); ctx.moveTo(sx2, sy2); ctx.lineTo(sx, sy);
          ctx.strokeStyle = sg2; ctx.lineWidth = 1.5; ctx.stroke();
        }

        // Satellite dot
        var satPulse = (Math.sin(phase*4 + idx*2.1)+1)/2;
        var satSize  = (2.5 + satPulse*1.5 + (pressure>0.7&&t2<0.2 ? satPulse*2 : 0)) * entryOp;
        ctx.shadowColor='rgba('+sr+','+sg+','+sb+',1)';
        ctx.shadowBlur = (8 + t2*4) * entryOp;
        ctx.beginPath(); ctx.arc(sx,sy,Math.max(0.1,satSize),0,Math.PI*2);
        ctx.fillStyle='rgba('+sr+','+sg+','+sb+','+(0.92*entryOp)+')'; ctx.fill();
        ctx.shadowBlur=0;

        // Connector thread to orb
        ctx.beginPath(); ctx.moveTo(pcx,pcy); ctx.lineTo(sx,sy);
        ctx.strokeStyle='rgba('+sr+','+sg+','+sb+','+(0.08*entryOp)+')';
        ctx.lineWidth=.5; ctx.stroke();
      });

      // ── Exiting satellites — shoot outward and fade ───────────────────────
      Object.keys(_satExiting).forEach(function(sym) {
        var e = _satExiting[sym];
        e.age += 0.032;
        var r  = e.orbitR + e.age * 80;   // shoot outward fast
        var op = Math.max(0, 1 - e.age * 2.5);
        if (op <= 0) { delete _satExiting[sym]; return; }
        var sx = pcx + Math.cos(e.angle) * r;
        var sy = pcy + Math.sin(e.angle) * r;
        // Fading streak from orb to satellite
        var streakG = ctx.createLinearGradient(pcx, pcy, sx, sy);
        streakG.addColorStop(0,   'rgba('+e.sr+','+e.sg+','+e.sb+','+(op*0.3)+')');
        streakG.addColorStop(1,   'rgba('+e.sr+','+e.sg+','+e.sb+',0)');
        ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(sx, sy);
        ctx.strokeStyle = streakG; ctx.lineWidth = 1.5; ctx.stroke();
        // Fading dot
        ctx.shadowColor = 'rgba('+e.sr+','+e.sg+','+e.sb+',1)';
        ctx.shadowBlur  = 8 * op;
        ctx.beginPath(); ctx.arc(sx, sy, 2.5*op+0.5, 0, Math.PI*2);
        ctx.fillStyle = 'rgba('+e.sr+','+e.sg+','+e.sb+','+op+')';
        ctx.fill(); ctx.shadowBlur = 0;
      });

      // ── Combo markers — spawn LEFT of orb, drift further left as they fade ──
      // Positive (win) markers float slightly ABOVE orb Y; losses slightly BELOW.
      if (!window._comboParticles) window._comboParticles = [];
      var _cp = window._comboParticles;
      var _cpNow = Date.now();

      // Spawn combo streak label as a new particle
      if (_comboCount > 0) {
        var _comboAge2 = (_cpNow - _comboLastAt) / 1000;
        var _comboA2   = _comboAge2 < 3 ? 0.9 : Math.max(0, 0.9 - (_comboAge2 - 3) * 0.6);
        if (_comboA2 > 0 && !window._comboStreakParticle) {
          // pin the persistent streak label to a stable particle slot
          window._comboStreakParticle = {
            text: '\xd7'+_comboCount+' COMBO',
            col: _comboCount>=10 ? '0,229,255' : _comboCount>=5 ? '255,170,0' : '255,0,204',
            isWin: true, born: _cpNow, lifetime: 6000, sticky: true
          };
          _cp.push(window._comboStreakParticle);
        } else if (window._comboStreakParticle) {
          // Update streak text as count changes
          window._comboStreakParticle.text = '\xd7'+_comboCount+' COMBO';
          window._comboStreakParticle.col  = _comboCount>=10 ? '0,229,255' : _comboCount>=5 ? '255,170,0' : '255,0,204';
          window._comboStreakParticle.born = _cpNow;
        }
      } else {
        window._comboStreakParticle = null;
      }
      if (_comboFlash) {
        _cp.push({
          text: _comboFlash.text,
          col: _comboFlash.col[0]+','+_comboFlash.col[1]+','+_comboFlash.col[2],
          isWin: _comboFlash.col[1] > 100, // green = win
          born: _cpNow, lifetime: 900, sticky: false
        });
        _comboFlash = null;
      }

      // Draw and age all combo particles
      window._comboParticles = _cp.filter(function(p) { return _cpNow - p.born < p.lifetime; });
      window._comboParticles.forEach(function(p) {
        var age = (_cpNow - p.born) / p.lifetime;
        var alpha = Math.max(0, 1 - age * 1.1);
        if (alpha <= 0) return;
        // Drift left over lifetime; pos above, neg below orb Y
        var drift = age * 90;                          // drifts 90px left over lifetime
        var yOff  = p.isWin ? -14 : 10;               // win=above, loss=below orb center
        var px2   = pcx - 30 - drift;                 // start 30px left of orb center
        var py2   = pcy + yOff;
        var fsize = p.sticky ? Math.min(9 + (_comboCount||1)*0.6, 16) : 8;
        ctx.save();
        ctx.font = 'bold '+Math.round(fsize)+'px Consolas';
        ctx.fillStyle   = 'rgba('+p.col+','+alpha+')';
        ctx.shadowColor = 'rgba('+p.col+','+alpha+')';
        ctx.shadowBlur  = 10 * alpha;
        ctx.textAlign   = 'right';
        ctx.fillText(p.text, px2, py2);
        ctx.restore();
      });

    } catch(e) {}
  }

  // ── Shockwave rings — small, local, subtle ───────────────────────────────
  _shockWaves = _shockWaves.filter(function(w) { return w.age < 1; });
  _shockWaves.forEach(function(w) {
    w.age += 0.04;
    var radius = w.age * 40;
    var alpha  = Math.pow(1-w.age, 2) * 0.3;
    ctx.beginPath();
    ctx.arc(w.cx, w.cy, radius, 0, Math.PI*2);
    ctx.strokeStyle='rgba('+w.col[0]+','+w.col[1]+','+w.col[2]+','+alpha+')';
    ctx.lineWidth = 1;
    ctx.stroke();
  });

  // ── NAV particles — sparks reacting to live price ticks ─────────────────
  _navParticles = _navParticles.filter(function(p) { return p.life > 0; });
  _navParticles.forEach(function(p) {
    p.life -= p.decay;
    p.x += p.vx; p.y += p.vy;
    p.vy *= 0.97; p.vx *= 0.96;
    var alpha = p.life * p.life;
    ctx.shadowColor = 'rgba('+p.r+','+p.g+','+p.b+','+(alpha*.9)+')';
    ctx.shadowBlur  = 6 + (1-p.life)*4;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.size*(0.4+p.life*0.6), 0, Math.PI*2);
    ctx.fillStyle = 'rgba('+p.r+','+p.g+','+p.b+','+alpha+')';
    ctx.fill();
    ctx.shadowBlur = 0;
  });

  // ── Brownian live-tip ─────────────────────────────────────────────────────
  if (portT) {
    try {
      var tcx = (window._navOrbFracX !== undefined ? window._navOrbFracX : 0.5) * canvas.width;
      var tcy = (window._navOrbFracY !== undefined ? window._navOrbFracY : 0.5) * canvas.height;
      if (isFinite(tcx) && isFinite(tcy)) {
        if (!_liveTip.pts.length) _liveTip.pts.push({dx:0,dy:0});
        var last2 = _liveTip.pts[_liveTip.pts.length-1];
        var ndx = Math.min(last2.dx + (Math.random()-0.48)*1.1, 52);
        var ndy = last2.dy*0.93 + (Math.random()-0.5)*1.4;
        _liveTip.pts.push({dx:ndx,dy:ndy});
        if (_liveTip.pts.length > 80) _liveTip.pts.shift();
        var tn = _liveTip.pts.length;
        ctx.save();
        for (var ti=1; ti<tn; ti++) {
          var ta = (ti/tn)*0.55;
          var tp0=_liveTip.pts[ti-1], tp1=_liveTip.pts[ti];
          ctx.beginPath();
          ctx.moveTo(tcx+tp0.dx, tcy+tp0.dy);
          ctx.lineTo(tcx+tp1.dx, tcy+tp1.dy);
          ctx.strokeStyle='rgba(255,0,204,'+ta+')';
          ctx.lineWidth=1.1;
          ctx.shadowColor='rgba(255,0,204,'+(ta*.8)+')';
          ctx.shadowBlur=5;
          ctx.stroke();
        }
        ctx.restore();
      }
    } catch(e) {}
  }

  rafId = requestAnimationFrame(drawPulse);
}

// ── Sound system ─────────────────────────────────────────────────────────
var _audioCtx = null;
var _audioReady = false;
var _audioMuted = false;
function _unlockAudio() {
  if (_audioReady) return;
  try {
    _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    var buf = _audioCtx.createBuffer(1, 1, 22050);
    var src = _audioCtx.createBufferSource();
    src.buffer = buf; src.connect(_audioCtx.destination); src.start(0);
    _audioCtx.resume().then(function() { _audioReady = true; });
  } catch(e) {}
}
// Try to unlock immediately, then on first interaction as fallback
_unlockAudio();
['click','keydown','touchstart'].forEach(function(ev) {
  document.addEventListener(ev, function _u() {
    _unlockAudio();
    document.removeEventListener(ev, _u);
  });
});
function _toggleMute() {
  _audioMuted = !_audioMuted;
  var btn   = document.getElementById('mute-btn');
  var icon  = document.getElementById('mute-icon');
  var label = document.getElementById('mute-label');
  if (btn)   btn.classList.toggle('muted', _audioMuted);
  if (icon)  icon.textContent = _audioMuted ? '♪' : '♪';
  if (label) label.textContent = _audioMuted ? 'OFF' : 'ON';
  if (!_audioMuted) _unlockAudio();
}
function _playTones(freqs, dur, type, stagger, vol) {
  if (_audioMuted || !_audioReady || !_audioCtx) return;
  try {
    if (_audioCtx.state === 'suspended') { _audioCtx.resume(); return; }
    var _stagger = stagger !== undefined ? stagger : 0.09;
    var _vol     = vol     !== undefined ? vol     : 0.12;
    freqs.forEach(function(f, i) {
      var osc = _audioCtx.createOscillator(), g = _audioCtx.createGain();
      osc.connect(g); g.connect(_audioCtx.destination);
      osc.type = type || 'sine';
      osc.frequency.value = f;
      var t0 = _audioCtx.currentTime + i * _stagger;
      g.gain.setValueAtTime(0, t0);
      g.gain.linearRampToValueAtTime(_vol, t0 + 0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      osc.start(t0); osc.stop(t0 + dur + 0.05);
    });
  } catch(e) {}
}
// Acquisition: neutral rising 8-bit blip — two square notes, subtle
window._soundEntry = function() {
  if (_audioMuted || !_audioReady || !_audioCtx) return;
  try {
    var ctx = _audioCtx;
    if (ctx.state === 'suspended') { ctx.resume(); return; }
    [[330, 0], [440, 0.055]].forEach(function(p) {
      var osc = ctx.createOscillator(), g = ctx.createGain();
      osc.type = 'square'; osc.frequency.value = p[0];
      var t = ctx.currentTime + p[1];
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.055, t+0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, t+0.08);
      osc.connect(g); g.connect(ctx.destination);
      osc.start(t); osc.stop(t+0.10);
    });
  } catch(e) {}
};
// Win exit: ascending 8-bit arpeggio (E5→G5→B5) — bright, punchy
window._soundWin = function() {
  if (_audioMuted || !_audioReady || !_audioCtx) return;
  try {
    var ctx = _audioCtx;
    if (ctx.state === 'suspended') { ctx.resume(); return; }
    [[659, 0], [784, 0.07], [988, 0.14]].forEach(function(p) {
      var osc = ctx.createOscillator(), g = ctx.createGain();
      osc.type = 'square'; osc.frequency.value = p[0];
      var t = ctx.currentTime + p[1];
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.07, t+0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, t+0.11);
      osc.connect(g); g.connect(ctx.destination);
      osc.start(t); osc.stop(t+0.13);
    });
  } catch(e) {}
};
// Loss exit: descending 8-bit bloop (G4→Eb4→Bb3) — muted, downward
window._soundLoss = function() {
  if (_audioMuted || !_audioReady || !_audioCtx) return;
  try {
    var ctx = _audioCtx;
    if (ctx.state === 'suspended') { ctx.resume(); return; }
    [[392, 0], [311, 0.07], [233, 0.14]].forEach(function(p) {
      var osc = ctx.createOscillator(), g = ctx.createGain();
      osc.type = 'square'; osc.frequency.value = p[0];
      var lp = ctx.createBiquadFilter(); lp.type='lowpass'; lp.frequency.value=700;
      var t = ctx.currentTime + p[1];
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.055, t+0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t+0.12);
      osc.connect(lp); lp.connect(g); g.connect(ctx.destination);
      osc.start(t); osc.stop(t+0.14);
    });
  } catch(e) {}
};

// ── Fullscreen mode (borderless — keeps screen active, click-through to other monitors) ─
var _wakeLock = null;
async function _acquireWakeLock() {
  try {
    if (navigator.wakeLock) {
      _wakeLock = await navigator.wakeLock.request('screen');
    }
  } catch(e) {}
}
function _fsSetActive(on) {
  var btn  = document.getElementById('fs-btn');
  var btn2 = document.getElementById('fs-btn2');
  if (on) {
    if (btn)  { btn.textContent = '⛶ EXIT'; btn.style.color = '#ff00cc'; btn.style.borderColor = '#ff00cc'; btn.style.boxShadow = '0 0 6px rgba(255,0,204,.4)'; }
    if (btn2) { btn2.textContent = '⛶'; btn2.style.color = '#ff00cc'; btn2.style.borderColor = '#ff00cc'; btn2.style.boxShadow = '0 0 6px rgba(255,0,204,.35)'; }
  } else {
    if (btn)  { btn.textContent = '⛶ FS'; btn.style.color = '#3a1a5a'; btn.style.borderColor = '#2a003d'; btn.style.boxShadow = 'none'; }
    if (btn2) { btn2.textContent = '⛶'; btn2.style.color = 'rgba(255,255,255,.55)'; btn2.style.borderColor = 'rgba(255,255,255,.12)'; btn2.style.boxShadow = 'none'; }
  }
}
function _toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().then(function() {
      _fsSetActive(true);
      _acquireWakeLock();
    }).catch(function() {});
  } else {
    document.exitFullscreen().then(function() {
      _fsSetActive(false);
      if (_wakeLock) { _wakeLock.release(); _wakeLock = null; }
    }).catch(function() {});
  }
}
document.addEventListener('visibilitychange', function() {
  if (document.visibilityState === 'visible' && document.fullscreenElement) _acquireWakeLock();
});
document.addEventListener('fullscreenchange', function() {
  if (!document.fullscreenElement) {
    _fsSetActive(false);
    if (_wakeLock) { _wakeLock.release(); _wakeLock = null; }
  }
});

// ── Wallet canvas engine ──────────────────────────────────────────────────────
(function() {
  var wc = document.getElementById('wallet-canvas');
  if (!wc) return;
  var ctx = wc.getContext('2d');

  // ── State ─────────────────────────────────────────────────────────────────
  var rings    = [];   // { r, maxR, alpha, col, speed }
  var particles= [];   // { x,y,vx,vy,r,life,decay,col }
  var bursts   = [];   // { t, isEntry, isWin, x, y }
  var scanLines= [];   // { y, alpha, speed, col }
  var _velSmooth = 0;  // exponentially smoothed velocity
  var _lastNavVal = null;
  var _trend = 0;      // −1..+1 smoothed P&L trend

  // ── Public API ────────────────────────────────────────────────────────────
  window._walletScan = function() {
    var W = wc.width, H = wc.height;
    // Expand rings from panel center
    for (var i=0; i<3; i++) {
      rings.push({ r:0, maxR:Math.max(W,H)*0.7, alpha:0.55-i*0.12,
                    col:[0,229,255], speed:2.2+i*0.5, delay:i*60 });
    }
    // Scanning horizontal lines sweeping downward
    for (var j=0; j<2; j++) {
      scanLines.push({ y:-4+(j*8), alpha:0.7, speed:2.5+j, col:[0,229,255,0.4] });
    }
  };

  window._walletTrade = function(isEntry, isWin, sym, price) {
    var W = wc.width, H = wc.height;
    var cx = W/2, cy = H*0.42;
    var col = isEntry ? [0,255,157] : (isWin ? [255,153,0] : [255,51,102]);

    // Burst ring
    rings.push({ r:0, maxR:W*0.6, alpha:0.8, col:col, speed:4 });

    // Directional particles
    var count = 18;
    for (var i=0; i<count; i++) {
      var angle = (Math.PI*2/count)*i + (Math.random()-.5)*.4;
      var speed = 1.5 + Math.random()*2.5;
      var vy0 = isEntry ? -Math.abs(Math.sin(angle)*speed)-0.3 : Math.abs(Math.sin(angle)*speed)+0.3;
      particles.push({
        x:cx + (Math.random()-.5)*20, y:cy,
        vx:Math.cos(angle)*speed*0.6,
        vy:vy0,
        r:1.2+Math.random()*2, life:1,
        decay:0.012+Math.random()*0.016, col:col
      });
    }

    // Update event ticker
    var ticker = document.getElementById('wallet-event-ticker');
    if (ticker) {
      var arrow = isEntry ? '▲ ENTER' : '▼ EXIT';
      var tCol = isEntry ? '#00ff9d' : (isWin ? '#ff9900' : '#ff3366');
      ticker.textContent = arrow + (sym ? '  ' + sym.replace('/USD','') : '') + (price ? '  $' + price : '');
      ticker.style.color = tCol;
      ticker.style.textShadow = '0 0 10px ' + tCol;
      setTimeout(function() {
        ticker.style.color = 'rgba(255,255,255,.2)';
        ticker.style.textShadow = 'none';
      }, 4000);
    }
  };

  // Called every time NAV updates — feed into velocity smoothing
  window._walletNavUpdate = function(newNav) {
    if (_lastNavVal !== null) {
      var delta = newNav - _lastNavVal;
      var pct   = delta / 100000; // fraction of starting capital
      _velSmooth = _velSmooth * 0.75 + pct * 0.25; // EMA
    }
    _lastNavVal = newNav;
    _trend = Math.max(-1, Math.min(1, (_velSmooth * 2000)));

    // Update momentum bar
    var track = document.getElementById('wallet-vel-track');
    var fill  = document.getElementById('wallet-vel-fill');
    if (track && fill) {
      var tw = track.offsetWidth || 140;
      var half = tw / 2;
      var bar = Math.abs(_trend) * half;
      if (_trend >= 0) {
        fill.style.left = half + 'px';
        fill.style.width = bar + 'px';
        fill.style.background = 'linear-gradient(90deg,rgba(0,255,157,.6),rgba(0,255,157,1))';
        fill.style.color = '#00ff9d';
      } else {
        fill.style.left = (half - bar) + 'px';
        fill.style.width = bar + 'px';
        fill.style.background = 'linear-gradient(90deg,rgba(255,51,102,1),rgba(255,51,102,.6))';
        fill.style.color = '#ff3366';
      }
    }
  };

  // ── Resize ────────────────────────────────────────────────────────────────
  function resize() { wc.width = wc.offsetWidth; wc.height = wc.offsetHeight; }
  resize();
  window.addEventListener('resize', resize);

  // ── Helpers ───────────────────────────────────────────────────────────────
  var _t = 0;

  function _trendCols() {
    // primary color shifts from red → neutral → green based on _trend
    var r = _trend < 0 ? 255 : Math.round(255*(1-_trend));
    var g = _trend > 0 ? 255 : Math.round(255*(1+_trend));
    return [r, g, 80];
  }

  function _drawSparkline(W, H) {
    var nh = window._navHistory || [];
    if (nh.length < 2) return;
    var pts = nh.slice().reverse(); // oldest first

    var minV = Infinity, maxV = -Infinity;
    pts.forEach(function(p) { if(p.nav<minV)minV=p.nav; if(p.nav>maxV)maxV=p.nav; });
    var range = maxV - minV || 2000;
    var pad = range * 0.2;
    minV -= pad; maxV += pad;

    var sx = W * 0.08, ex = W * 0.92;
    var sy = H * 0.72, ey = H * 0.88;

    function px(i) { return sx + (i/(pts.length-1))*(ex-sx); }
    function py(v) { return ey - ((v-minV)/(maxV-minV))*(ey-sy); }

    // Glow pass
    var lastVal = pts[pts.length-1].nav;
    var isUp = lastVal >= 100000;
    var glowCol = isUp ? 'rgba(0,255,157,' : 'rgba(255,51,102,';

    ctx.save();
    ctx.lineWidth = 2;
    ctx.strokeStyle = glowCol + '0.7)';
    ctx.shadowColor  = glowCol + '0.5)';
    ctx.shadowBlur   = 12;
    ctx.beginPath();
    for (var i=0; i<pts.length; i++) {
      var x=px(i), y=py(pts[i].nav);
      if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.stroke();

    // Fill under curve
    ctx.beginPath();
    for (var i=0; i<pts.length; i++) {
      var x=px(i), y=py(pts[i].nav);
      if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.lineTo(px(pts.length-1), ey);
    ctx.lineTo(px(0), ey);
    ctx.closePath();
    ctx.fillStyle = glowCol + '0.06)';
    ctx.fill();

    // Endpoint dot
    var endX = px(pts.length-1), endY = py(lastVal);
    ctx.beginPath();
    ctx.arc(endX, endY, 3, 0, Math.PI*2);
    ctx.fillStyle = isUp ? '#00ff9d' : '#ff3366';
    ctx.shadowColor = isUp ? 'rgba(0,255,157,.9)' : 'rgba(255,51,102,.9)';
    ctx.shadowBlur = 10;
    ctx.fill();

    ctx.restore();
  }

  function _drawParticles() {
    for (var i=particles.length-1; i>=0; i--) {
      var p = particles[i];
      p.x += p.vx; p.y += p.vy;
      p.vy *= 0.97; p.vx *= 0.98;
      p.life -= p.decay;
      if (p.life <= 0) { particles.splice(i,1); continue; }
      var a = p.life * 0.7;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * p.life, 0, Math.PI*2);
      ctx.fillStyle = 'rgba('+p.col[0]+','+p.col[1]+','+p.col[2]+','+a+')';
      ctx.shadowColor= 'rgba('+p.col[0]+','+p.col[1]+','+p.col[2]+','+(a*.5)+')';
      ctx.shadowBlur = 6;
      ctx.fill();
    }
  }

  function _drawRings(W, H) {
    var cx = W/2, cy = H*0.42;
    for (var i=rings.length-1; i>=0; i--) {
      var ring = rings[i];
      if (ring.delay > 0) { ring.delay -= 16; continue; }
      ring.r += ring.speed;
      ring.alpha *= 0.975;
      if (ring.r > ring.maxR || ring.alpha < 0.005) { rings.splice(i,1); continue; }
      ctx.beginPath();
      ctx.arc(cx, cy, ring.r, 0, Math.PI*2);
      ctx.strokeStyle = 'rgba('+ring.col[0]+','+ring.col[1]+','+ring.col[2]+','+ring.alpha+')';
      ctx.lineWidth = 1.5;
      ctx.shadowColor = 'rgba('+ring.col[0]+','+ring.col[1]+','+ring.col[2]+','+(ring.alpha*.6)+')';
      ctx.shadowBlur = 8;
      ctx.stroke();
    }
  }

  function _drawScanLines(W, H) {
    for (var i=scanLines.length-1; i>=0; i--) {
      var sl = scanLines[i];
      sl.y += sl.speed; sl.alpha *= 0.97;
      if (sl.y > H || sl.alpha < 0.01) { scanLines.splice(i,1); continue; }
      var g = ctx.createLinearGradient(0,0,W,0);
      g.addColorStop(0,'transparent');
      g.addColorStop(0.2,'rgba('+sl.col[0]+','+sl.col[1]+','+sl.col[2]+','+sl.alpha*0.6+')');
      g.addColorStop(0.5,'rgba('+sl.col[0]+','+sl.col[1]+','+sl.col[2]+','+sl.alpha+')');
      g.addColorStop(0.8,'rgba('+sl.col[0]+','+sl.col[1]+','+sl.col[2]+','+sl.alpha*0.6+')');
      g.addColorStop(1,'transparent');
      ctx.fillStyle = g;
      ctx.fillRect(0, sl.y, W, 2);
    }
  }

  function _drawBackground(W, H) {
    // Ambient radial that breathes with trend
    var breath = 0.5 + 0.5*Math.sin(_t*0.4);
    var isUp = _trend >= 0;
    var bgCol = isUp ? '0,255,157' : '255,51,102';
    var grad = ctx.createRadialGradient(W/2, H*0.42, 0, W/2, H*0.42, W*0.55);
    grad.addColorStop(0,   'rgba('+bgCol+','+(0.025+breath*0.015)+')');
    grad.addColorStop(0.6, 'rgba('+bgCol+',0.005)');
    grad.addColorStop(1,   'rgba('+bgCol+',0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);
  }

  // ── Main draw loop ─────────────────────────────────────────────────────────
  function draw() {
    var W = wc.width, H = wc.height;
    ctx.clearRect(0, 0, W, H);
    _t += 0.016;
    ctx.shadowBlur = 0;

    _drawBackground(W, H);
    _drawScanLines(W, H);
    _drawSparkline(W, H);
    _drawRings(W, H);
    _drawParticles();

    requestAnimationFrame(draw);
  }
  draw();
})();

// ── C: Particle drift — upward drifting motes in the positions panel ─────────
(function() {
  var pc = document.getElementById('particle-canvas');
  if (!pc) return;
  var pCtx = pc.getContext('2d');

  // ── Canonical ticker color system ────────────────────────────────────────────
  // Single palette + override map shared by every _symCol site in this file.
  // Override map wins over hash — keeps colliding tickers visually distinct.
  // Override map is persisted to Supabase ticker_colors table so it survives
  // across sessions and machines.
  var PALETTE = ['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
  window._TICKER_OVR = { ETH:'#e040fb', CRV:'#f7b731', XTZ:'#00bfff', NUE:'#ff4dd2' };
  function _hashCol(s) { var h=0; for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))&0xffff; return PALETTE[h%PALETTE.length]; }
  function symCol(s) { var c=s.replace('/USD','').replace('USD',''); return window._TICKER_OVR[c]||_hashCol(c); }

  // Load persisted colors from Supabase on startup — overwrites defaults
  (function() {
    fetch(SUPA_URL + '/rest/v1/ticker_colors?select=ticker,color',
      { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY } })
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(rows) {
      if (!Array.isArray(rows)) return;
      rows.forEach(function(row) {
        if (row.ticker && row.color) window._TICKER_OVR[row.ticker] = row.color;
      });
      // Re-tint any already-painted canvas tiles
      (window._ET||[]).forEach(function(t) {
        var c = t.sym.replace('/USD','').replace('USD','');
        if (window._TICKER_OVR[c]) t.col = window._TICKER_OVR[c];
      });
    }).catch(function() {});
  })();

  // Persist a single color override to Supabase
  window._saveTickerColor = function(ticker, color) {
    fetch(SUPA_URL + '/rest/v1/ticker_colors',
      {
        method: 'POST',
        headers: {
          'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY,
          'Content-Type': 'application/json',
          'Prefer': 'resolution=merge-duplicates',
        },
        body: JSON.stringify({ ticker: ticker, color: color }),
      }
    ).catch(function() {});
  };

  var particles = [];
  var MAX_P = 60;

  function _resize() { pc.width = pc.offsetWidth; pc.height = pc.offsetHeight; }
  _resize();
  window.addEventListener('resize', _resize);

  function _getColors() {
    var cols = [];
    // Crypto positions
    Object.keys(window._cryptoPositionsMap || {}).forEach(function(sym) {
      cols.push(symCol(sym.replace('/USD','')));
    });
    // Equity positions
    document.querySelectorAll('#pos-equity-section .pos-card[data-sym]').forEach(function(el) {
      cols.push(symCol(el.getAttribute('data-sym')));
    });
    return cols.length ? cols : ['#1a0830']; // near-black when flat
  }

  function _spawn(cols) {
    var col = cols[Math.floor(Math.random() * cols.length)];
    particles.push({
      x: Math.random() * pc.width,
      y: pc.height + 4,
      vy: -(0.25 + Math.random() * 0.55),   // slow upward
      vx: (Math.random() - 0.5) * 0.15,
      r:  0.8 + Math.random() * 1.4,
      alpha: 0,
      fadeIn: 0.015 + Math.random() * 0.01,
      life: 1,
      decay: 0.0008 + Math.random() * 0.0012,
      col: col,
    });
  }

  var _spawnTick = 0;
  function _drawParticles() {
    var W = pc.width, H = pc.height;
    pCtx.clearRect(0, 0, W, H);

    var cols = _getColors();
    var nOpen = cols.length;
    // Spawn rate: 1 particle every N frames, scales with open positions
    _spawnTick++;
    var spawnEvery = nOpen === 1 ? 999 : Math.max(8, 60 - nOpen * 3);
    if (_spawnTick % spawnEvery === 0 && particles.length < MAX_P) _spawn(cols);

    for (var i = particles.length - 1; i >= 0; i--) {
      var p = particles[i];
      p.x  += p.vx;
      p.y  += p.vy;
      p.alpha = Math.min(p.alpha + p.fadeIn, p.life);
      p.life -= p.decay;
      if (p.life <= 0 || p.y < -8) { particles.splice(i, 1); continue; }

      // Parse hex to rgb for alpha blending
      var hex = p.col.replace('#','');
      var r = parseInt(hex.slice(0,2),16), g = parseInt(hex.slice(2,4),16), b = parseInt(hex.slice(4,6),16);
      var a = Math.min(p.alpha, p.life) * 0.55;

      pCtx.beginPath();
      pCtx.arc(p.x, p.y, p.r, 0, Math.PI*2);
      pCtx.fillStyle = 'rgba('+r+','+g+','+b+','+a+')';
      pCtx.shadowColor = 'rgba('+r+','+g+','+b+','+(a*0.6)+')';
      pCtx.shadowBlur = 4;
      pCtx.fill();
    }
    pCtx.shadowBlur = 0;
    requestAnimationFrame(_drawParticles);
  }
  _drawParticles();
})();

// ── ATH tracking ─────────────────────────────────────────────────────────────
var _athNav = Math.max.apply(null, portValues.length ? portValues : [100000]);
var _athTs  = portDates.length ? portDates[portDates.length - 1] : latestDate;
var _athShapeIdx = _milestoneShapes.length + (latestDate ? 1 : 0); // index in shapes array

function _updateAthShape(nav, ts) {
  if (nav <= _athNav) return;
  _athNav = nav;
  _athTs  = ts;
  var athShape = {
    type:'line', xref:'paper', yref:'y',
    x0:0, x1:1, y0:_athNav, y1:_athNav,
    line:{ color:'rgba(0,255,157,0.35)', width:1, dash:'dash' },
  };
  var athAnnot = {
    xref:'paper', yref:'y',
    x:0.01, y:_athNav,
    text:'▲ ATH',
    showarrow:false,
    font:{ family:'Consolas', size:7, color:'rgba(0,255,157,0.6)' },
    xanchor:'left', yanchor:'bottom',
  };
  // Upsert the ATH shape at a known index
  var newShapes = (gd.layout.shapes || []).slice();
  newShapes[_athShapeIdx] = athShape;
  var newAnnots = (gd.layout.annotations || []).slice();
  // Keep existing annotations (NOW marker), add/replace ATH annotation at index 1
  newAnnots[1] = athAnnot;
  Plotly.relayout(gd, { shapes: newShapes, annotations: newAnnots });
}

// ── Endpoint dot — SVG pulsing circle at current portfolio position ───────────
function _updateEndpointDot(nav, ts) {
  var svg = gd && gd.querySelector('svg.main-svg');
  if (!svg || !gd._fullLayout) return;
  var fl = gd._fullLayout;
  var xa = fl.xaxis, ya = fl.yaxis;
  if (!xa || !ya || !xa.range || !ya.range) return;

  var tsMs  = new Date(ts).getTime();
  var xMin  = new Date(xa.range[0]).getTime();
  var xMax  = new Date(xa.range[1]).getTime();
  var xFrac = xMax > xMin ? (tsMs - xMin) / (xMax - xMin) : 1;
  var yFrac = ya.range[1] > ya.range[0] ? (nav - ya.range[0]) / (ya.range[1] - ya.range[0]) : 0.5;
  var ml = fl.margin.l, mt = fl.margin.t;
  var cw = fl.width  - fl.margin.l - fl.margin.r;
  var ch = fl.height - fl.margin.t - fl.margin.b;
  var cx = ml + xFrac * cw;
  var cy = mt + (1 - yFrac) * ch;

  // Above/below baseline determines color
  var aboveBase = nav >= 100000;
  var dotCol  = aboveBase ? '#00ff9d' : '#ff3366';
  var ringCol = aboveBase ? 'rgba(0,255,157,' : 'rgba(255,51,102,';

  var g = svg.querySelector('#ep-g');
  if (!g) {
    g = document.createElementNS('http://www.w3.org/2000/svg','g');
    g.id = 'ep-g';
    // Outer pulse ring
    var r1 = document.createElementNS('http://www.w3.org/2000/svg','circle');
    r1.id = 'ep-ring1'; r1.setAttribute('fill','none'); r1.setAttribute('stroke-width','1');
    g.appendChild(r1);
    // Inner pulse ring
    var r2 = document.createElementNS('http://www.w3.org/2000/svg','circle');
    r2.id = 'ep-ring2'; r2.setAttribute('fill','none'); r2.setAttribute('stroke-width','1');
    g.appendChild(r2);
    // Core dot
    var dot = document.createElementNS('http://www.w3.org/2000/svg','circle');
    dot.id = 'ep-dot'; dot.setAttribute('r','4');
    g.appendChild(dot);
    // Animation styles
    var st = document.createElementNS('http://www.w3.org/2000/svg','style');
    st.id = 'ep-style';
    st.textContent =
      '@keyframes ep-p1{0%{r:5;opacity:.9}100%{r:18;opacity:0}}' +
      '@keyframes ep-p2{0%{r:5;opacity:.6}100%{r:12;opacity:0}}' +
      '#ep-ring1{animation:ep-p1 1.8s ease-out infinite}' +
      '#ep-ring2{animation:ep-p2 1.8s ease-out .6s infinite}' +
      '#ep-dot{filter:drop-shadow(0 0 4px currentColor)}';
    g.appendChild(st);
    svg.appendChild(g);
  }

  var ring1 = svg.querySelector('#ep-ring1');
  var ring2 = svg.querySelector('#ep-ring2');
  var edot  = svg.querySelector('#ep-dot');
  [ring1, ring2, edot].forEach(function(el) {
    if (!el) return;
    el.setAttribute('cx', cx); el.setAttribute('cy', cy);
  });
  if (ring1) { ring1.setAttribute('stroke', ringCol + '0.7)'); }
  if (ring2) { ring2.setAttribute('stroke', ringCol + '0.5)'); }
  if (edot)  { edot.setAttribute('fill', dotCol); edot.style.color = dotCol; }
}

function applyPortfolioGlow() {
  // Portfolio is now trace index 4 (ghost at 3, portfolio at 4)
  var scatters = gd.querySelectorAll('.scatter');
  if (scatters[4]) {
    var lp = scatters[4].querySelector('path.js-line');
    if (lp) lp.classList.add('portfolio-glow');
  }
  // Gridline shimmer
  var svg = gd.querySelector('svg.main-svg');
  if (svg && !svg.querySelector('#gl-anim')) {
    var st = document.createElementNS('http://www.w3.org/2000/svg','style');
    st.id = 'gl-anim';
    st.textContent = '@keyframes gl-sw{0%,100%{stroke:rgba(42,0,61,.5)}50%{stroke:rgba(190,160,230,.38)}}' +
      '.gridlayer .crisp line{animation:gl-sw 14s ease-in-out infinite}';
    svg.prepend(st);
  }
  var lines = gd.querySelectorAll('.gridlayer .crisp line');
  lines.forEach(function(l, i) { l.style.animationDelay = -(i * 1.1) % 14 + 's'; });
  // Update endpoint dot position after replot
  if (window._lastKnownNav && window._lastKnownTs) {
    _updateEndpointDot(window._lastKnownNav, window._lastKnownTs);
  }
}

// Start everything once Plotly has rendered
Plotly.newPlot(gd, traces, layout, config).then(function() {
  buildTargets();
  applyPortfolioGlow();
  if (rafId) cancelAnimationFrame(rafId);
  drawPulse();
  // Seed endpoint dot — extend portfolio line to "now" so orb lands in intraday window
  if (portDates.length && portValues.length) {
    var initNav = portValues[portValues.length - 1];
    var nowIso  = new Date().toISOString();
    // Extend the portfolio line (ghost trace 3, main trace 4) to current time
    var extDates  = portDates.concat([nowIso]);
    var extValues = portValues.concat([initNav]);
    Plotly.restyle(gd, { x: [extDates, extDates], y: [extValues, extValues] }, [3, 4]);
    window._lastKnownNav = initNav;
    window._lastKnownTs  = nowIso;
    setTimeout(function() { _updateEndpointDot(initNav, nowIso); }, 200);
    setTimeout(function() { _updateAthShape(initNav, nowIso); }, 250);
  }
  // Crosshair on load: show → zoom in after crosshair fades
  setTimeout(showCrosshair, 1500);
  // Mark initial layout complete so the pan tracker ignores programmatic events
  setTimeout(function() { _initLayoutDone = true; }, 500);
  // Force intraday zoom — dynamic Y scales to whatever moved in the last 20 min
  setTimeout(function() {
    _programmaticRelayout = true;
    var _xs = _intradayStart(), _xe = _intradayEnd();
    var _yr = yRange(_xs, new Date().toISOString());
    var _layout = { 'xaxis.range': [_xs, _xe] };
    if (_yr[0] !== null) { _layout['yaxis.range'] = _yr; _layout['yaxis.autorange'] = false; }
    Plotly.relayout(gd, _layout).then(function() { _programmaticRelayout = false; });
  }, 600);
});

gd.on('plotly_afterplot', function() { buildTargets(); applyPortfolioGlow(); });

// ── Portfolio canvas chart — sole chart surface, no Plotly ──────────────────
// Robinhood-style: dark bg, glowing trail line, gradient fill, Y labels,
// X time labels, current-value callout, trade markers. Star canvas sits below.
(function() {
  var _nc = document.getElementById('nav-canvas');
  if (!_nc) return;
  var _dpr = window.devicePixelRatio || 1;

  // Margins — computed dynamically each draw to avoid overlays
  var _ML = 64, _MR = 20, _MT = 28, _MB = 32;

  function _resize() {
    // offsetWidth/Height are always layout-correct; getBoundingClientRect can
    // return 0 when #chart is display:none and the parent hasn't reflowed yet.
    var cw = _nc.offsetWidth  || (window.innerWidth  - 60)  || 800;
    var ch = _nc.offsetHeight || (window.innerHeight - 140) || 500;
    var pw = Math.round(cw * _dpr), ph = Math.round(ch * _dpr);
    if (_nc.width !== pw || _nc.height !== ph) {
      _nc.width = pw; _nc.height = ph;
      var ctx = _nc.getContext('2d');
      ctx.setTransform(_dpr, 0, 0, _dpr, 0, 0);
    }
  }
  // Delay first resize until layout has settled
  setTimeout(_resize, 100);
  window.addEventListener('resize', _resize);

  // Scroll = zoom. Shift+scroll = pan. After 3s idle, gently return to default.
  var _NAV_DEFAULT_WIN = 5 * 60 * 1000;  // 5 minutes default — zoomed in tight
  window._navWindowMs       = _NAV_DEFAULT_WIN;
  window._navTargetWindowMs = _NAV_DEFAULT_WIN;
  window._navPanOffsetMs    = 0;
  window._navLastInteractMs = 0;
  var _WIN_MIN = 5  * 60 * 1000;
  var _WIN_MAX = 365 * 86400 * 1000;
  (function() {
    var ma = document.getElementById('main-area');
    if (!ma) return;
    ma.addEventListener('wheel', function(e) {
      e.preventDefault(); e.stopPropagation();
      window._navLastInteractMs = Date.now();
      if (e.shiftKey) {
        // Shift+scroll = pan through history
        var panStep = window._navWindowMs * 0.20 * (e.deltaY > 0 ? -1 : 1);
        window._navPanOffsetMs = Math.min(0, window._navPanOffsetMs + panStep);
      } else {
        // Scroll = zoom
        var factor = e.deltaY > 0 ? 1.6 : 0.625;
        window._navTargetWindowMs = Math.max(_WIN_MIN,
          Math.min(_WIN_MAX, window._navTargetWindowMs * factor));
      }
    }, { passive: false });
  })();

  // ── Hover tooltip on nav-hover-layer ────────────────────────────────────────
  (function() {
    var hl = document.getElementById('nav-hover-layer');
    var nc = document.getElementById('nav-canvas');
    if (!hl || !nc) return;
    window._navHoverX = null;
    hl.addEventListener('mousemove', function(e) {
      var r = hl.getBoundingClientRect();
      window._navHoverX = (e.clientX - r.left) / r.width;  // 0-1 fraction
    });
    hl.addEventListener('mouseleave', function() {
      window._navHoverX = null;
    });
    // Forward wheel events from hover layer to main-area so zoom/pan still works
    hl.addEventListener('wheel', function(e) {
      e.preventDefault();
      window._navLastInteractMs = Date.now();
      if (e.shiftKey) {
        var panStep = window._navWindowMs * 0.20 * (e.deltaY > 0 ? -1 : 1);
        window._navPanOffsetMs = Math.min(0, window._navPanOffsetMs + panStep);
      } else {
        var factor = e.deltaY > 0 ? 1.6 : 0.625;
        window._navTargetWindowMs = Math.max(5*60*1000,
          Math.min(365*86400*1000, window._navTargetWindowMs * factor));
      }
    }, { passive: false });
  })();

  window._navPush = function(v, isoTs) {
    // kept for API compatibility — data now comes from _navDbPts
  };

  window._drawNavCanvas = function() {
    try {
    _resize();
    var ctx = _nc.getContext('2d');
    var W = _nc.width / _dpr, H = _nc.height / _dpr;

    // ── 8-BIT CYBERPUNK VAPORWAVE CHART ──────────────────────────────────────
    // Dark background — stars (ambient-canvas z-10) bleed through the 30% gap
    ctx.fillStyle = 'rgba(4,0,14,0.70)';
    ctx.fillRect(0, 0, W, H);

    // ── Data ─────────────────────────────────────────────────────────────────
    var raw = window._navDbPts || [];
    var allPts = [];
    for (var i = 0; i < raw.length; i++) {
      var ms = new Date(raw[i].t).getTime();
      var v  = parseFloat(raw[i].v);
      if (!isNaN(ms) && !isNaN(v) && v > 100) allPts.push({ ms: ms, v: v });
    }
    allPts.sort(function(a,b){return a.ms-b.ms;});

    // Prefer the most recent nav_snapshot value as the live price; fall back to _lastKnownNav
    var pts0 = window._navDbPts || [];
    var liveNav = allPts.length ? allPts[allPts.length-1].v : parseFloat(window._lastKnownNav);
    if (!liveNav || isNaN(liveNav)) { window._navOrbFracX=0.5; window._navOrbFracY=0.5; return; }

    var now_ms = Date.now();

    // ── Auto-return pan (3s idle → drift back to center) ─────────────────
    var _idleMs = now_ms - (window._navLastInteractMs || 0);
    if (_idleMs > 3000) {
      window._navPanOffsetMs += (0 - window._navPanOffsetMs) * 0.012;
    }

    // ── Smooth zoom lerp ──────────────────────────────────────────────────
    var _tgt = window._navTargetWindowMs || window._navWindowMs || 4*3600*1000;
    window._navWindowMs += (_tgt - window._navWindowMs) * 0.10;

    // ── Time window ───────────────────────────────────────────────────────
    var winMs     = window._navWindowMs || 4 * 3600 * 1000;
    var lastPtMs  = allPts.length ? allPts[allPts.length-1].ms : now_ms;
    var dataStart = allPts.length ? allPts[0].ms : now_ms - 30*60000;
    var panOff    = window._navPanOffsetMs || 0;
    panOff = Math.max(dataStart - lastPtMs, Math.min(0, panOff));
    window._navPanOffsetMs = panOff;
    var _feedEl = document.getElementById('feed-overlay');
    var _posEl  = document.getElementById('pos-overlay');
    var _feedW  = (_feedEl ? _feedEl.offsetWidth : 0);
    var _posW   = (_posEl  ? _posEl.offsetWidth  : 0);
    var _visCtr = W > 0 ? (_feedW + (W - _feedW - _posW) / 2) / W : 0.50;
    _visCtr = Math.max(0.20, Math.min(0.80, _visCtr));
    var centerMs = now_ms + panOff;
    var t0 = centerMs - _visCtr * winMs;
    var t1 = centerMs + (1 - _visCtr) * winMs;

    // Filter to window
    allPts = allPts.filter(function(p) { return p.ms >= t0 && p.ms <= t1; });
    allPts.sort(function(a,b){return a.ms-b.ms;});

    // Thin: one point per 30s bucket — kills vertical spikes
    var _bucket = 30000;
    var _thinned = {};
    for (var ti = 0; ti < allPts.length; ti++) {
      var bk = Math.floor(allPts[ti].ms / _bucket);
      _thinned[bk] = allPts[ti];
    }
    allPts = Object.keys(_thinned).sort().map(function(k) { return _thinned[k]; });

    // ── Chart area ─────────────────────────────────────────────────────────
    var cx0 = _ML, cx1 = W - _MR, cy0 = _MT, cy1 = H - _MB;
    var cW = cx1 - cx0, cH = cy1 - cy0;

    // ── Y range ────────────────────────────────────────────────────────────
    var midV = allPts.length ? allPts[allPts.length-1].v : liveNav;
    var _lo = midV, _hi = midV;
    for (var vi = 0; vi < allPts.length; vi++) {
      if (allPts[vi].v < _lo) _lo = allPts[vi].v;
      if (allPts[vi].v > _hi) _hi = allPts[vi].v;
    }
    var spread = _hi - _lo;
    if (spread < 20) spread = 20;
    var halfRange = Math.max(Math.abs(midV - _lo), Math.abs(_hi - midV), spread / 2);
    halfRange *= 1.20;
    var lo = midV - halfRange;
    var hi = midV + halfRange;

    function tx(ms) { return cx0 + (ms - t0) / (t1 - t0) * cW; }
    function ty(v)  { return cy1 - (v - lo) / (hi - lo) * cH; }

    // ── Grid: dashed horizontal lines + Y labels ───────────────────────────
    var nTicks = 5;
    ctx.font = '10px Consolas,monospace';
    ctx.textAlign = 'left';
    for (var gi = 0; gi <= nTicks; gi++) {
      var yv = lo + (hi - lo) * gi / nTicks;
      var yy = ty(yv);
      ctx.strokeStyle = 'rgba(140,60,200,0.20)';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 5]);
      ctx.beginPath(); ctx.moveTo(cx0, yy); ctx.lineTo(cx1, yy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(190,140,255,0.50)';
      ctx.fillText('$' + Math.round(yv).toLocaleString('en-US'), cx0 + 4, yy - 3);
    }

    // ── X-axis labels ──────────────────────────────────────────────────────
    var xTickCount = Math.min(8, Math.max(3, Math.floor(cW / 120)));
    ctx.textAlign = 'center';
    ctx.font = '10px Consolas,monospace';
    for (var xi = 0; xi <= xTickCount; xi++) {
      var xms = t0 + (t1 - t0) * xi / xTickCount;
      if (xms > now_ms + 60000) continue;
      var xx = tx(xms);
      var xd = new Date(xms);
      var hh = xd.getHours() % 12 || 12;
      var mm = ('0' + xd.getMinutes()).slice(-2);
      var ap = xd.getHours() < 12 ? 'a' : 'p';
      ctx.fillStyle = 'rgba(170,120,255,0.50)';
      ctx.fillText(hh + ':' + mm + ap, xx, cy1 + 18);
    }

    // ── Map points — quantize Y to 3px grid for 8-bit feel ────────────────
    var m = allPts.map(function(p) {
      return { x: Math.round(tx(p.ms)), y: Math.round(ty(p.v) / 3) * 3 };
    });
    var n = m.length;

    if (n < 2) {
      var midY = Math.round(ty(liveNav) / 3) * 3;
      m = [{ x: cx0, y: midY }, { x: Math.round(tx(lastPtMs)), y: midY }];
      n = 2;
    }

    // ── 8-bit stepped path: horizontal then vertical (L-shaped segments) ──
    function _stepPath(pts2) {
      ctx.beginPath();
      ctx.moveTo(pts2[0].x, pts2[0].y);
      for (var si = 1; si < pts2.length; si++) {
        ctx.lineTo(pts2[si].x, pts2[si-1].y);  // horizontal
        ctx.lineTo(pts2[si].x, pts2[si].y);    // vertical
      }
    }

    // ── Vaporwave under-fill ───────────────────────────────────────────────
    var breathe = 0.5 + 0.5 * Math.sin(Date.now() / 1800);
    _stepPath(m);
    ctx.lineTo(m[n-1].x, cy1); ctx.lineTo(m[0].x, cy1); ctx.closePath();
    var fillGrad = ctx.createLinearGradient(0, cy0, 0, cy1);
    fillGrad.addColorStop(0,   'rgba(255,0,204,' + (0.18 + breathe * 0.10) + ')');
    fillGrad.addColorStop(0.4, 'rgba(100,0,255,' + (0.08 + breathe * 0.06) + ')');
    fillGrad.addColorStop(1,   'rgba(0,240,255,0)');
    ctx.fillStyle = fillGrad; ctx.fill();

    // ── 8-bit glow passes ─────────────────────────────────────────────────
    var passes = [
      { w: 20, a: 0.07, rgb: '0,240,255'  },  // cyan outer halo
      { w: 12, a: 0.12, rgb: '255,0,200'  },  // pink mid halo
      { w: 6,  a: 0.25, rgb: '180,0,255'  },  // purple bloom
      { w: 3,  a: 0.90, rgb: '255,60,220' },  // hot-pink core
      { w: 1,  a: 1.00, rgb: '0,255,255'  },  // cyan bright edge
    ];
    passes.forEach(function(pass) {
      _stepPath(m);
      ctx.strokeStyle = 'rgba(' + pass.rgb + ',' + pass.a + ')';
      ctx.lineWidth = pass.w;
      ctx.lineJoin = 'miter';
      ctx.lineCap = 'square';
      ctx.stroke();
    });

    // ── Pulsing orb at trail tip ───────────────────────────────────────────
    var tipX = m[n-1].x, tipY = m[n-1].y;
    window._navOrbFracX = Math.max(0.05, Math.min(0.95, tipX / W));
    window._navOrbFracY = Math.max(0.05, Math.min(0.95, tipY / H));

    var pulse = 0.5 + 0.5 * Math.sin(Date.now() / 400);
    ctx.beginPath(); ctx.arc(tipX, tipY, 10 + pulse * 8, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(180,0,255,' + (0.12 + pulse * 0.18) + ')'; ctx.fill();
    ctx.beginPath(); ctx.arc(tipX, tipY, 5 + pulse * 3, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(220,100,255,' + (0.5 + pulse * 0.3) + ')'; ctx.fill();
    ctx.beginPath(); ctx.arc(tipX, tipY, 3, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,0.95)'; ctx.fill();

    // ── Big portfolio value — top-center of chart ──────────────────────────
    var _rawNav = window._lastKnownNav || (allPts.length ? allPts[allPts.length-1].v : liveNav);
    if (!window._navDispVal || Math.abs(window._navDispVal - _rawNav) > 5000) {
      window._navDispVal = _rawNav;
    } else {
      window._navDispVal += (_rawNav - window._navDispVal) * 0.07;
    }
    var valStr = '$' + window._navDispVal.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
    var _sessionStart = allPts.length ? allPts[0].v : _rawNav;
    var _pnlVal = _rawNav - _sessionStart;
    var _pnlPct = _sessionStart > 0 ? (_pnlVal / _sessionStart * 100) : 0;
    var _pnlStr = (_pnlVal >= 0 ? '+$' : '-$') + Math.abs(_pnlVal).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    _pnlStr += '  (' + (_pnlPct >= 0 ? '+' : '') + _pnlPct.toFixed(2) + '%)';
    var _pnlColor = _pnlVal >= 0 ? 'rgba(0,255,140,0.9)' : 'rgba(255,60,100,0.9)';

    var vcx = W / 2;
    ctx.textAlign = 'center';
    ctx.font = 'bold 13px Consolas,monospace';
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    ctx.fillText(valStr, vcx, cy0 - 8);
    ctx.font = '9px Consolas,monospace';
    ctx.fillStyle = _pnlColor;
    ctx.fillText(_pnlStr, vcx, cy0 + 6);

    // ── Hover crosshair + tooltip ──────────────────────────────────────────
    if (window._navHoverX !== null && allPts.length > 0) {
      var hoverMs = t0 + window._navHoverX * (t1 - t0);
      var hBest = allPts[0], hDist = Math.abs(allPts[0].ms - hoverMs);
      for (var hi2 = 1; hi2 < allPts.length; hi2++) {
        var d2 = Math.abs(allPts[hi2].ms - hoverMs);
        if (d2 < hDist) { hDist = d2; hBest = allPts[hi2]; }
      }
      var hx = tx(hBest.ms), hy = ty(hBest.v);
      var _hoverTrade = null;
      var _tradeMarkersH = window._navTradeMarkers || [];
      for (var hti = 0; hti < _tradeMarkersH.length; hti++) {
        var htm = _tradeMarkersH[hti];
        var htms = new Date(_fixTs(htm.ts)).getTime();
        if (Math.abs(htms - hoverMs) < winMs * 0.015) { _hoverTrade = htm; break; }
      }
      ctx.save();
      ctx.setLineDash([3, 5]);
      ctx.strokeStyle = 'rgba(255,255,255,0.25)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(hx, cy0); ctx.lineTo(hx, cy1); ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(hx, hy, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#fff'; ctx.fill();
      var hDate = new Date(hBest.ms);
      var hLine1 = hDate.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})
                   + '  ' + hDate.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
      var hLine2 = '$' + hBest.v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
      var ttLines = [hLine1, hLine2];
      if (_hoverTrade) {
        ttLines.push((_hoverTrade.side === 'ENTER' ? '▲ BUY' : '▼ SELL') + '  ' + (_hoverTrade.sym||'') + (_hoverTrade.price ? '  $' + _hoverTrade.price : ''));
      }
      ctx.font = '11px Consolas,monospace';
      var ttW = 0;
      ttLines.forEach(function(l) { ttW = Math.max(ttW, ctx.measureText(l).width); });
      ttW += 20;
      var ttLineH = 16, ttH = ttLines.length * ttLineH + 10;
      var ttX = hx + 14; if (ttX + ttW > cx1) ttX = hx - ttW - 14;
      var ttY = hy - ttH / 2; ttY = Math.max(cy0 + 4, Math.min(cy1 - ttH - 4, ttY));
      ctx.fillStyle = 'rgba(0,0,0,0.88)';
      ctx.strokeStyle = 'rgba(255,255,255,0.22)'; ctx.lineWidth = 1;
      ctx.fillRect(ttX, ttY, ttW, ttH);
      ctx.strokeRect(ttX, ttY, ttW, ttH);
      ttLines.forEach(function(line, li) {
        ctx.font = (li === 1 ? 'bold 13px' : '11px') + ' Consolas,monospace';
        ctx.fillStyle = (li === 2 && _hoverTrade) ? (_hoverTrade.side==='ENTER' ? '#00ff9d' : '#ff3366') : '#fff';
        ctx.textAlign = 'left';
        ctx.fillText(line, ttX + 10, ttY + 14 + li * ttLineH);
      });
      ctx.restore();
    }

    // ── Trade event orbs ────────────────────────────────────────────────────
    var _tradeMarkers = window._navTradeMarkers || [];
    for (var tmi = 0; tmi < _tradeMarkers.length; tmi++) {
      var tm = _tradeMarkers[tmi];
      var tmMs = new Date(_fixTs(tm.ts)).getTime();
      if (tmMs < t0 || tmMs > t1) continue;
      var tmx = tx(tmMs);
      var tmy = tm.nav ? ty(tm.nav) : cy1 / 2;
      var isEnter = tm.side === 'ENTER';
      var _tmPhase = (now_ms / 1200 + tmi * 1.3) % (Math.PI * 2);
      var _tmPulse = 0.5 + 0.5 * Math.sin(_tmPhase);
      var _tmR    = 3.5 + _tmPulse * 2;
      var _tmRing = _tmR + 4 + _tmPulse * 5;
      var _rgbStr = isEnter ? '0,255,140' : '255,50,100';
      ctx.beginPath(); ctx.arc(tmx, tmy, _tmRing, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(' + _rgbStr + ',' + (0.12 + _tmPulse * 0.12) + ')';
      ctx.lineWidth = 1; ctx.stroke();
      ctx.beginPath(); ctx.arc(tmx, tmy, _tmR, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + _rgbStr + ',' + (0.7 + _tmPulse * 0.25) + ')'; ctx.fill();
      ctx.beginPath(); ctx.arc(tmx, tmy, 1.5, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,0.9)'; ctx.fill();
    }

    } catch(e) {
      console.error('[navChart]', e);
      var _ectx = _nc.getContext('2d');
      _ectx.font = 'bold 11px Consolas'; _ectx.fillStyle = '#ff4400'; _ectx.textAlign = 'center';
      _ectx.fillText('ERR: ' + (e.message || String(e)), (_nc.width/_dpr)/2, (_nc.height/_dpr)/2 + 28);
    }
  };

  // ~30fps — enough for a smooth breathing dot without burning GPU
  var _navLastDraw = 0;
  (function _raf(ts) {
    if (ts - _navLastDraw >= 33) { _navLastDraw = ts; window._drawNavCanvas(); }
    requestAnimationFrame(_raf);
  })(0);
})();

// ── Real-time x-axis advance — DISABLED: _recenterOnLatest() handles centering ──
var _userPanned = false;
var _initLayoutDone = false;
var _rtAdvancing = false;
gd.on('plotly_relayout', function(u) {
  if (!_initLayoutDone || _rtAdvancing) return;
  if (u['xaxis.range[0]'] !== undefined) _userPanned = true;
});

// ── Trade event markers ───────────────────────────────────────────────────────
var _tradeEventIds = new Set(); // track seen event IDs to avoid re-adding
var _tradeDropLines = []; // shapes for vertical drop lines

function _navAtTime(isoTs) {
  var tsMs = new Date(_fixTs(isoTs)).getTime();
  // Use DB points (source of truth for the chart)
  var dbPts = window._navDbPts || [];
  if (dbPts.length) {
    var closest = null, closestDiff = Infinity;
    for (var j = 0; j < dbPts.length; j++) {
      var diff = Math.abs(new Date(_fixTs(dbPts[j].t)).getTime() - tsMs);
      if (diff < closestDiff) { closestDiff = diff; closest = parseFloat(dbPts[j].v); }
    }
    if (closest !== null) return closest;
  }
  return window._lastKnownNav || null;
}

function _spawnTradeChip(isoTs, sym, isEntry, price) {
  var fl = gd._fullLayout;
  var gRect = gd.getBoundingClientRect();
  if (!fl || !fl.xaxis || !fl.yaxis) return;

  var navY = _navAtTime(isoTs) || window._lastKnownNav || 100000;
  var col  = isEntry ? [0,255,157] : [255,51,102];
  var rgb  = 'rgb(' + col.join(',') + ')';
  var rgba = function(a) { return 'rgba(' + col.join(',') + ',' + a + ')'; };

  // Pixel position on screen (chart-relative + viewport offset)
  var px = gRect.left, py = gRect.top + gRect.height * 0.5;
  try {
    px = fl.xaxis.l2p(fl.xaxis.d2l(isoTs)) + fl.margin.l + gRect.left;
    py = fl.yaxis.l2p(fl.yaxis.d2l(navY))  + fl.margin.t + gRect.top;
  } catch(e) {}

  // 1. Expanding ring pulses — 3 rings staggered 160ms apart
  for (var ri = 0; ri < 3; ri++) {
    (function(delay) {
      setTimeout(function() {
        var ring = document.createElement('div');
        ring.style.cssText =
          'position:fixed;pointer-events:none;z-index:283;border-radius:50%;' +
          'border:2px solid ' + rgb + ';' +
          'width:12px;height:12px;' +
          'left:' + (px-6) + 'px;top:' + (py-6) + 'px;' +
          'opacity:.85;transition:transform .75s cubic-bezier(.16,1,.3,1), opacity .75s ease';
        document.body.appendChild(ring);
        requestAnimationFrame(function() { requestAnimationFrame(function() {
          ring.style.transform = 'scale(' + (6 + ri*2) + ')';
          ring.style.opacity = '0';
        }); });
        setTimeout(function() { ring.remove(); }, 850);
      }, delay);
    })(ri * 160);
  }

  // 2. Flash dot at marker
  var dot = document.createElement('div');
  dot.style.cssText =
    'position:fixed;pointer-events:none;z-index:290;border-radius:50%;' +
    'width:8px;height:8px;left:' + (px-4) + 'px;top:' + (py-4) + 'px;' +
    'background:' + rgb + ';box-shadow:0 0 24px 8px ' + rgba(.65) + ';' +
    'opacity:1;transition:transform .55s ease, opacity .55s ease';
  document.body.appendChild(dot);
  requestAnimationFrame(function() { requestAnimationFrame(function() {
    dot.style.transform = 'scale(3)';
    dot.style.opacity = '0';
  }); });
  setTimeout(function() { dot.remove(); }, 650);

  // 3. Floating label chip — beat-em-up damage numbers
  // Stack chips loosely so rapid-fire events don't overlap
  if (!window._activeChips) window._activeChips = [];
  // Clean expired chips from the tracking list
  window._activeChips = window._activeChips.filter(function(c) { return c.el.isConnected; });
  // Jitter spawn position: small random offset so chips scatter loosely near the orb
  var _jx = (Math.random() - 0.5) * 40;
  var _jy = (Math.random() - 0.5) * 30;
  // Push away from existing chips to avoid direct overlap
  window._activeChips.forEach(function(c) {
    var dx = (px + 14 + _jx) - c.x, dy = (py - 12 + _jy) - c.y;
    var dist2 = Math.sqrt(dx*dx + dy*dy);
    if (dist2 < 28 && dist2 > 0) {
      _jx += (dx / dist2) * (28 - dist2) * 0.6;
      _jy += (dy / dist2) * (28 - dist2) * 0.6;
    }
  });
  var spawnX = px + 14 + _jx, spawnY = py - 12 + _jy;

  var label = (isEntry ? '▲ ENTER ' : '&#9660; EXIT ') + sym.replace('/USD','') +
              (price ? '  $' + parseFloat(price||0).toFixed(sym.indexOf('USD')!==-1?4:2) : '');
  var chip = document.createElement('div');
  chip.innerHTML = label;
  chip.style.cssText =
    'position:fixed;pointer-events:none;z-index:296;' +
    'font-family:Consolas,monospace;font-size:9.5px;font-weight:800;letter-spacing:.09em;' +
    'padding:4px 10px 4px 7px;border-radius:2px;white-space:nowrap;' +
    'color:' + rgb + ';background:' + rgba(.07) + ';' +
    'border:1px solid ' + rgba(.45) + ';' +
    'box-shadow:0 0 20px ' + rgba(.35) + ',0 0 50px ' + rgba(.1) + ';' +
    'left:' + spawnX + 'px;top:' + spawnY + 'px;' +
    'opacity:0;transform:scale(.5) translate(0,0);' +
    'transition:opacity .18s ease, transform .42s cubic-bezier(.22,1,.36,1)';
  document.body.appendChild(chip);
  window._activeChips.push({ el: chip, x: spawnX, y: spawnY });

  requestAnimationFrame(function() { requestAnimationFrame(function() {
    chip.style.opacity = '1';
    chip.style.transform = 'scale(1) translate(0,0)';
  }); });

  // Drift: gains float up-left, losses float down-left — arcade damage number feel
  var _driftX = -(55 + Math.random() * 30);  // always left
  var _driftY = isEntry ? -(45 + Math.random() * 20) : (45 + Math.random() * 20);  // up for gains, down for losses
  setTimeout(function() {
    chip.style.transition = 'opacity 1.1s ease, transform 3.5s ease';
    chip.style.opacity = '0';
    chip.style.transform = 'scale(.9) translate(' + _driftX + 'px,' + _driftY + 'px)';
    setTimeout(function() { chip.remove(); }, 1200);
  }, 2600);

  // 4. Spark burst — 8-12 particles radiate outward
  var sparkCount = 8 + Math.floor(Math.random()*5);
  for (var si = 0; si < sparkCount; si++) {
    (function() {
      var angle = Math.random() * Math.PI * 2;
      var dist  = 18 + Math.random() * 38;
      var spark = document.createElement('div');
      spark.style.cssText =
        'position:fixed;pointer-events:none;z-index:287;border-radius:50%;' +
        'width:3px;height:3px;' +
        'left:' + (px-1.5) + 'px;top:' + (py-1.5) + 'px;' +
        'background:' + rgb + ';box-shadow:0 0 5px ' + rgb + ';' +
        'opacity:.95;transition:transform .65s cubic-bezier(.22,1,.36,1), opacity .65s ease';
      document.body.appendChild(spark);
      requestAnimationFrame(function() { requestAnimationFrame(function() {
        spark.style.transform =
          'translate(' + (Math.cos(angle)*dist) + 'px,' + (Math.sin(angle)*dist) + 'px) scale(.25)';
        spark.style.opacity = '0';
      }); });
      setTimeout(function() { spark.remove(); }, 750);
    })();
  }
}

function _fetchTradeEvents() {
  var url = SUPA_URL + '/rest/v1/pipeline_events'
    + '?event_type=eq.TRADE'
    + '&order=recorded_at.asc'
    + '&limit=200';
  fetch(url, { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY } })
  .then(function(r) { return r.json(); })
  .then(function(rows) {
    if (!Array.isArray(rows) || !rows.data) {
      // rows is the array directly from PostgREST
      if (!Array.isArray(rows)) return;
    }
    var enterXs=[], enterYs=[], enterTexts=[];
    var exitXs=[],  exitYs=[],  exitTexts=[];
    var newShapes = []; // vertical drop lines

    rows.forEach(function(row) {
      var id = row.id;
      var msg = row.message || '';
      var ts  = row.recorded_at;
      if (!ts) return;

      var isEntry = msg.indexOf('ENTER') !== -1 || msg.indexOf('enter') !== -1;
      var isExit  = msg.indexOf('EXIT')  !== -1 || msg.indexOf('exit')  !== -1;
      if (!isEntry && !isExit) return;

      // Parse symbol
      var symM = msg.match(/(?:ENTER|EXIT|enter|exit)\s+([A-Z\/]+)/);
      var sym  = symM ? symM[1] : '';
      // Parse price
      var priceM = msg.match(/@\s*\$([\d,.]+)/);
      var price  = priceM ? priceM[1] : '';

      var navY = _navAtTime(ts);
      if (!navY) return;

      var isoTs = new Date(ts).toISOString();

      if (isEntry) {
        enterXs.push(isoTs); enterYs.push(navY);
        enterTexts.push(sym.replace('/USD',''));
      } else {
        exitXs.push(isoTs);  exitYs.push(navY);
        exitTexts.push(sym.replace('/USD',''));
      }

      // Vertical drop line
      newShapes.push({
        type:'line', xref:'x', yref:'paper',
        x0:isoTs, x1:isoTs, y0:0, y1:1,
        line:{ color: isEntry ? 'rgba(0,255,157,.38)' : 'rgba(255,51,102,.38)', width:1.5, dash:'dot' },
        layer:'below',
      });

      // Spawn animated chip for NEW events only
      if (id && !_tradeEventIds.has(id)) {
        _tradeEventIds.add(id);
        // Only animate events from the last 5 minutes (live)
        if (Date.now() - new Date(ts).getTime() < 300000) {
          _spawnTradeChip(isoTs, sym, isEntry, price);
        }
      }
    });

    // Feed trade markers to canvas chart
    var canvasMarkers = [];
    enterXs.forEach(function(ts, i) { canvasMarkers.push({ ts:ts, nav:enterYs[i], sym:enterTexts[i], side:'ENTER' }); });
    exitXs.forEach(function(ts, i)  { canvasMarkers.push({ ts:ts, nav:exitYs[i],  sym:exitTexts[i],  side:'EXIT'  }); });
    window._navTradeMarkers = canvasMarkers;
  })
  .catch(function() {});
}

// Fetch on load + every 10s
setTimeout(_fetchTradeEvents, 2000);
setInterval(_fetchTradeEvents, 10000);

// Also trigger on live TRADE events from feed poller
window._onLiveTrade = function() { setTimeout(_fetchTradeEvents, 1500); };

// ── Intraday "marked the book" trace — live portfolio value within today ──────
function _fetchIntradayMarks() {
  var today = new Date().toISOString().slice(0,10);
  // Only fetch "marked the book" rows for the chart — filter by message to keep row count small
  var url = SUPA_URL + '/rest/v1/pipeline_events'
    + '?select=message,recorded_at&recorded_at=gte.' + today + 'T00:00:00Z'
    + '&message=ilike.*marked%20the%20book*&order=recorded_at.asc&limit=500';
  fetch(url, { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY } })
  .then(function(r) { return r.json(); })
  .then(function(rows) {
    if (!Array.isArray(rows)) return;
    var xs = [], ys = [];
    rows.forEach(function(row) {
      var msg = row.message || '';
      var m = msg.match(/marked the book at \$?([\d,]+)/);
      if (m) {
        var v = parseFloat(m[1].replace(/,/g,''));
        if (!isNaN(v) && v > 1000 && v < 10000000) {
          xs.push(new Date(row.recorded_at).toISOString());
          ys.push(v);
        }
      }
    });
    // Update intraday trace
    if (xs.length && gd && gd.data && gd.data.length >= 7) {
      Plotly.restyle(gd, { x:[xs], y:[ys] }, [6]).then(function() {
        var lastV = ys[ys.length-1], lastT = xs[xs.length-1];
        // Only use pipeline stamp as NAV if no live price has arrived in the last 10s.
        // Prevents the frozen "marked the book" value from oscillating with the live feed.
        if (!window._lastLivePriceMs || (Date.now() - window._lastLivePriceMs) > 10000) {
          window._lastKnownNav = lastV; window._lastKnownTs = lastT;
        }
        // Always ingest marks into nav history regardless of which source wins display
        for (var _i=0; _i<xs.length; _i++) { if (window._navPush) window._navPush(ys[_i], xs[_i]); }
        _updateEndpointDot(lastV, lastT);
        buildTargets();
      });
    }
    _recenterOnLatest(xs.length > 0 ? xs[xs.length - 1] : null);
  }).catch(function() {});

  // Separate HEAD request for accurate TRADE count (bypasses row limit)
  var urlCount = SUPA_URL + '/rest/v1/pipeline_events'
    + '?select=id&event_type=eq.TRADE&recorded_at=gte.' + today + 'T00:00:00Z&limit=1';
  fetch(urlCount, { method:'HEAD', headers: {
    'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY, 'Prefer': 'count=exact'
  } })
  .then(function(r) {
    var ct = r.headers.get('content-range');
    if (!ct) return;
    var total = parseInt(ct.split('/')[1], 10);
    if (!isNaN(total)) _updateOrbMetrics(total, 0, 0);
  }).catch(function() {});
}
setTimeout(_fetchIntradayMarks, 3000);
setInterval(_fetchIntradayMarks, 15000);

// ── Live equity tile price updater ────────────────────────────────────────────
(function() {
  var _eqPrev = {};  // sym -> last displayed value

  function _flashVal(el, up) {
    el.classList.remove('pc-tick-up','pc-tick-down');
    void el.offsetWidth; // reflow
    el.classList.add(up ? 'pc-tick-up' : 'pc-tick-down');
  }

  function _pollEqPrices() {
    var liveTiles = (window._ET||[]).filter(function(t) {
      return !t.isCrypto && (t.phase === 'live' || t.phase === 'entering');
    });
    if (!liveTiles.length) return;
    var syms = liveTiles.map(function(t) { return t.sym; });

    // Fetch live quotes from Yahoo Finance (same source as yfinance, no auth needed).
    // crumb/cookie not required for the simple quote endpoint.
    var yfUrl = 'https://query1.finance.yahoo.com/v7/finance/quote?symbols='
      + syms.join(',') + '&fields=regularMarketPrice,symbol';
    fetch(yfUrl, { headers: { 'Accept': 'application/json' } })
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(data) {
      var latest = {};
      if (data && data.quoteResponse && Array.isArray(data.quoteResponse.result)) {
        data.quoteResponse.result.forEach(function(q) {
          if (q.symbol && q.regularMarketPrice) latest[q.symbol] = q.regularMarketPrice;
        });
      }
      // Fallback: if Yahoo blocked (CORS on cloud), pull yesterday's close from Supabase
      var missing = syms.filter(function(s) { return !latest[s]; });
      function _applyPrices() {
        liveTiles.forEach(function(t) {
          var price = latest[t.sym];
          if (!price) return;
          var val = t.qty * price;
          var pnl = t.entry > 0 ? (price - t.entry) * t.qty : 0;
          var pct = t.entry > 0 ? (price - t.entry) / t.entry * 100 : 0;
          var prev = _eqPrev[t.sym];
          if (prev !== undefined && Math.abs(val - prev) > 0.50) {
            t._valFlash = val > prev ? 1 : -1;
          }
          _eqPrev[t.sym] = val;
          t.curPrice = price;
          t.val = val;
          t.pnl = pnl;
          t.pnlPct = pct;
        });

        // Equity NAV slice
        var _eqLivePnl = 0, _eqCount = 0;
        liveTiles.forEach(function(t) {
          if (t.qty > 0 && t.entry > 0 && t.curPrice > 0) {
            _eqLivePnl += t.qty * (t.curPrice - t.entry);
            _eqCount++;
          }
        });
        window._livePnlBySource.equity = _eqCount > 0 ? _eqLivePnl : 0;
        if (_eqCount > 0) {
          var mood = _eqLivePnl > 0 ? 'bs-happy' : _eqLivePnl < 0 ? 'bs-sad' : '';
          var g = document.getElementById('bs-g'), hl = document.getElementById('bs-hl');
          if (g) { g.classList.remove('bs-happy','bs-sad'); if (mood) g.classList.add(mood); }
          if (hl) { hl.classList.remove('bs-hl-happy','bs-hl-sad');
            if (mood === 'bs-happy') hl.classList.add('bs-hl-happy');
            else if (mood === 'bs-sad') hl.classList.add('bs-hl-sad'); }
        }
      }

      if (missing.length) {
        // Yahoo blocked — fallback to Supabase price_bars (yesterday's close)
        var fbUrl = SUPA_URL + '/rest/v1/price_bars'
          + '?select=symbol,close&symbol=in.(' + missing.join(',') + ')'
          + '&order=date.desc&limit=' + (missing.length * 2);
        fetch(fbUrl, {headers:{'apikey':SUPA_KEY,'Authorization':'Bearer '+SUPA_KEY}})
        .then(function(r) { return r.json(); })
        .then(function(rows) {
          if (!Array.isArray(rows)) return;
          rows.forEach(function(row) { if (!latest[row.symbol]) latest[row.symbol] = row.close; });
          _applyPrices();
        }).catch(function() {});
      } else {
        _applyPrices();
      }
    }).catch(function() {
      // Yahoo fetch failed entirely — fall back to Supabase
      var fbUrl = SUPA_URL + '/rest/v1/price_bars'
        + '?select=symbol,close&symbol=in.(' + syms.join(',') + ')'
        + '&order=date.desc&limit=' + (syms.length * 2);
      fetch(fbUrl, {headers:{'apikey':SUPA_KEY,'Authorization':'Bearer '+SUPA_KEY}})
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows)) return;
        var latest2 = {};
        rows.forEach(function(row) { if (!latest2[row.symbol]) latest2[row.symbol] = row.close; });
        liveTiles.forEach(function(t) {
          var price = latest2[t.sym]; if (!price) return;
          t.curPrice = price;
          t.val = t.qty * price;
          t.pnl = t.entry > 0 ? (price - t.entry) * t.qty : 0;
          t.pnlPct = t.entry > 0 ? (price - t.entry) / t.entry * 100 : 0;
        });
      }).catch(function() {});
    });
  }

  setTimeout(_pollEqPrices, 4000);
  setInterval(_pollEqPrices, 20000);

  // ── Equity tile entry animation (wipe from transparent, bottom→up) ────────────
  (function() {
    var cards = document.querySelectorAll('.pc-eq');
    cards.forEach(function(el, i) {
      el.classList.add('pos-card-entering');
      setTimeout(function() { el.classList.remove('pos-card-entering'); }, 600);
    });
  })();
})();

// ── Shared live PnL accumulator — prevents equity+crypto pollers oscillating _lastKnownNav ──
// Each poller writes its slice; both read the combined total so NAV doesn't alternate.
window._livePnlBySource = { equity: 0, crypto: 0 };

// ── Nav chart — 100% DB-sourced, consistent across all machines ──────────────
// _navDbPts seeded from Python at render; refreshed from Supabase every 10s.
// No client-side live point is injected into the draw loop.
// _pushIntradayPoint writes to DB every 10s; the next poll picks it up.

function _fixTs(t) {
  // Supabase returns naive UTC strings; append Z so JS parses as UTC
  if (t && t[t.length-1] !== 'Z' && t.indexOf('+') === -1) return t + 'Z';
  return t;
}

function _fetchNavDb() {
  var since = new Date(Date.now() - 30*24*3600000).toISOString();  // 30 days
  fetch(SUPA_URL + '/rest/v1/nav_snapshots?select=recorded_at,nav&recorded_at=gte.' + since + '&order=recorded_at.asc&limit=5000',
    { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY } })
  .then(function(r) { return r.json(); })
  .then(function(rows) {
    if (!Array.isArray(rows)) return;
    window._navDbPts = rows.map(function(r) { return { t: _fixTs(r.recorded_at), v: r.nav }; });
    if (window._redrawNavTraces) window._redrawNavTraces();
  }).catch(function() {});
}
_fetchNavDb();
setInterval(_fetchNavDb, 10000);  // refresh every 10s

window._forceNavSnapshot = function() {
  var nav = window._lastKnownNav;
  if (!nav) return;
  var isoTs = new Date().toISOString();
  fetch(SUPA_URL + '/rest/v1/nav_snapshots', {
    method: 'POST',
    headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY,
                'Content-Type': 'application/json', 'Prefer': 'return=minimal' },
    body: JSON.stringify({ recorded_at: isoTs, nav: nav })
  }).catch(function() {});
};

var _lastNavWriteMs = 0;
window._pushIntradayPoint = function(isoTs, val) {
  var now = Date.now();
  // Always update live nav state for display
  window._lastLivePriceMs = now;
  window._lastKnownNav = val;
  window._lastKnownTs  = isoTs;
  // Write to DB at most every 10s — chart reads from DB, not local array
  if (now - _lastNavWriteMs < 10000) return;
  _lastNavWriteMs = now;
  fetch(SUPA_URL + '/rest/v1/nav_snapshots', {
    method: 'POST',
    headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY,
                'Content-Type': 'application/json', 'Prefer': 'return=minimal' },
    body: JSON.stringify({ recorded_at: isoTs, nav: val })
  }).catch(function(e) { console.warn('[nav] snapshot write failed', e); });
  if (window._navPush) window._navPush(val, isoTs);
  if (gd && gd.data && gd.data.length >= 7) {
    Plotly.restyle(gd, {
      x: [_intradayPts.map(function(p) { return p.t; })],
      y: [_intradayPts.map(function(p) { return p.v; })]
    }, [6]).then(function() {
      // Move the endpoint dot + orb to the live NAV position
      _updateEndpointDot(val, isoTs);
      buildTargets();
      // Spawn particles if NAV moved
      if (_lastNavForParticles !== null && window._spawnNavParticles) {
        var _pc = document.getElementById('pulse-canvas');
        var px = (window._navOrbFracX !== undefined ? window._navOrbFracX : 0.5) * (_pc ? _pc.width : 800);
        var py = (window._navOrbFracY !== undefined ? window._navOrbFracY : 0.5) * (_pc ? _pc.height : 500);
        if (true) {
          try {
            if (isFinite(px) && isFinite(py)) {
              window._spawnNavParticles(px, py, val >= _lastNavForParticles);
            }
          } catch(e) {}
        }
      }
      _lastNavForParticles = val;
    });
  }
  // Slide the chart window forward with each new point
  _recenterOnLatest(isoTs);
};

// ── Orb metrics panel updates ─────────────────────────────────────────────────
var _orbTodayTrades = 0, _orbWins = 0, _orbLosses = 0;
function _updateOrbMetrics(todayTrades, wins, losses) {
  if (todayTrades > 0) _orbTodayTrades = todayTrades;
  if (wins   > 0) _orbWins   = wins;
  if (losses > 0) _orbLosses = losses;
  if (typeof window._updateTradesSlot === 'function') window._updateTradesSlot(_orbTodayTrades);

  // Block 2 exposes these via window.*
  var trTs = window._tradeTs || [];
  var now  = Date.now();
  var cutoff = now - 3600000;
  var tph  = trTs.filter(function(t){ return t > cutoff; }).length;
  var el;

  el = document.getElementById('om-tph');
  if (el) el.textContent = tph > 0 ? tph.toFixed(0) : '0';

  el = document.getElementById('om-today');
  if (el) el.textContent = _orbTodayTrades > 0 ? _orbTodayTrades : '0';

  var total = _orbWins + _orbLosses;
  el = document.getElementById('om-winrate');
  if (el) el.textContent = total > 0 ? Math.round(_orbWins/total*100) + '%' : '—';

  el = document.getElementById('om-streak-orb');
  if (el) {
    var s = window._streak || null;
    if (s && s.count > 0) {
      var col = s.win ? '#00ff9d' : '#ff3366';
      el.textContent = (s.win ? '+' : '-') + s.count;
      el.style.color = col;
    } else {
      el.textContent = '—';
      el.style.color = '';
    }
  }

  // Update DAY P&L live from intraday NAV delta
  el = document.getElementById('om-dpnl');
  if (el && window._portfolioBaseline && window._lastKnownNav) {
    var liveDayPnl = window._lastKnownNav - window._portfolioBaseline;
    el.textContent = (liveDayPnl >= 0 ? '+$' : '-$') + Math.abs(liveDayPnl).toLocaleString('en-US', {maximumFractionDigits:0});
    el.style.color = liveDayPnl >= 0 ? '#00ff9d' : '#ff3366';
  }

  // Update open position count from live card state
  el = document.getElementById('om-openpos');
  if (el) {
    var cryptoCount = Object.keys(window._cryptoPositionsMap || {}).length;
    var equityCount = document.querySelectorAll('#pos-equity-section .pos-card[data-sym]').length;
    el.textContent = (cryptoCount + equityCount) || '0';
  }
}
setInterval(function() { _updateOrbMetrics(0,0,0); }, 1000);

var _scrollBusy = false;
var _smoothYMin = null, _smoothYMax = null;

// ── Wallet selector ───────────────────────────────────────────────────────────
var _walletModes = ['PAPER', 'LIVE ●'];
var _walletIdx = 0;
function _cycleWallet() {
  _walletIdx = (_walletIdx + 1) % _walletModes.length;
  var lbl = document.getElementById('wallet-mode-label');
  var sel = document.getElementById('wallet-selector');
  var ico = document.getElementById('wallet-mode-icon');
  if (!lbl || !sel) return;
  var mode = _walletModes[_walletIdx];
  lbl.textContent = mode;
  if (_walletIdx === 1) {
    sel.classList.add('live');
    ico.textContent = '◉';
  } else {
    sel.classList.remove('live');
    ico.textContent = '◈';
  }
}

var _userInteracting = false;
var _programmaticRelayout = false;
gd.on('plotly_relayout', function(ev) { buildTargets(); });

window.addEventListener('resize', function() {
  resizeCanvas();
  // Re-layout equity columns on viewport resize
  setTimeout(function() { if (window._updateOverlayWidth) window._updateOverlayWidth(); }, 50);
});
// Initial equity column layout — run after first render
setTimeout(function() {
  if (typeof _updateOverlayWidth === 'function') _updateOverlayWidth();
}, 800);

  // ── Gauge — avg trades per hour ───────────────────────────────────────────
  var _tradeTs = [];
  window._tradeTs = _tradeTs; // expose to script block 1
  var _GAUGE_MAX = 8;
  var _gaugeRate = 0;

  function _updateGauge(rate) {
    _gaugeRate = rate;
    var needle = document.getElementById('gauge-needle');
    var label  = document.getElementById('gauge-label');
    if (!needle) return;
    var pct = Math.min(1, rate / _GAUGE_MAX);
    var deg = -90 + pct * 180;
    needle.style.transform = 'rotate(' + deg + 'deg)';
    var col = pct < 0.4 ? '#00ff9d' : pct < 0.75 ? '#ffcc00' : '#ff3366';
    needle.style.stroke = col;
    if (label) {
      label.style.color = col;
      label.style.textShadow = '0 0 10px ' + col;
      label.innerHTML = rate.toFixed(1) + ' <span style="font-size:7px;opacity:.5">tr/hr</span>';
    }
  }

  window._recordTradeForGauge = function() {
    var now = Date.now();
    _tradeTs.push(now);
    var cutoff = now - 60 * 60 * 1000;
    _tradeTs = _tradeTs.filter(function(t) { return t >= cutoff; });
    _updateGauge(_tradeTs.length);
  };

  // Decay gauge every 30s when idle
  setInterval(function() {
    var now = Date.now(), cutoff = now - 60 * 60 * 1000;
    _tradeTs = _tradeTs.filter(function(t) { return t >= cutoff; });
    _updateGauge(_tradeTs.length);
  }, 30000);

  // ── Streak tracker ────────────────────────────────────────────────────────
  var _streak = { count: 0, win: null };
  window._streak = _streak; // expose to script block 1

  window._recordStreakResult = function(isWin) {
    if (_streak.win === null || _streak.win === isWin) {
      _streak.count++; _streak.win = isWin;
    } else {
      _streak.count = 1; _streak.win = isWin;
    }
    var el = document.getElementById('wallet-streak');
    if (el) {
      var col  = isWin ? '#00ff9d' : '#ff3366';
      var icon = isWin ? '&#9650;' : '&#9660;';
      var n    = _streak.count;
      el.innerHTML = '<span style="color:' + col + ';text-shadow:0 0 8px ' + col + '">' + icon + '&nbsp;' + n + (n === 1 ? ' WIN' : ' STREAK') + '</span>';
    }
    // Drive combo counter in drawPulse (block 1)
    if (window._orbComboResult) window._orbComboResult(isWin);
  };

  // ── Wallet NAV animated counter ───────────────────────────────────────────
  var _navAnimRaf = null;
  window._animateWalletNav = function(el, toStr) {
    if (!el) return;
    var fromNum = parseFloat((el.textContent || '$0').replace(/[^0-9.-]/g,'')) || 0;
    var toNum   = parseFloat(toStr.replace(/[^0-9.-]/g,'')) || 0;
    if (Math.abs(fromNum - toNum) < 1) { el.textContent = toStr; el.setAttribute('data-val', toStr); return; }
    if (_navAnimRaf) cancelAnimationFrame(_navAnimRaf);
    var start = null, dur = 750;
    function step(ts) {
      if (!start) start = ts;
      var p = Math.min(1, (ts - start) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      var cur = Math.round(fromNum + (toNum - fromNum) * e);
      var s = '$' + cur.toLocaleString('en-US');
      el.textContent = s; el.setAttribute('data-val', s);
      if (p < 1) { _navAnimRaf = requestAnimationFrame(step); }
      else { el.textContent = toStr; el.setAttribute('data-val', toStr); _navAnimRaf = null; }
    }
    _navAnimRaf = requestAnimationFrame(step);
  };

  var b = document.getElementById('term-body');
  if (b) { b.scrollTop = 0; }  // newest entries are at top

  // ── Panel resize (horizontal + vertical) ───────────────────────────────
  (function() {
    // Horizontal column drag
    function makeColDrag(handle, leftPanel, rightPanel, leftHdr, rightHdr) {
      var dragging = false, startX = 0, startLeft = 0, startRight = 0;
      function begin(clientX) {
        dragging = true; startX = clientX;
        startLeft = leftPanel.offsetWidth; startRight = rightPanel.offsetWidth;
        handle.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      }
      function move(clientX) {
        if (!dragging) return;
        var delta = clientX - startX;
        var nL = Math.max(120, startLeft + delta);
        var nR = Math.max(120, startRight - delta);
        leftPanel.style.width = nL + 'px'; leftPanel.style.flexShrink = '0';
        rightPanel.style.width = nR + 'px'; rightPanel.style.flexShrink = '0';
        if (leftHdr)  { leftHdr.style.width = nL + 'px';  leftHdr.style.flex = 'none'; }
        if (rightHdr) { rightHdr.style.width = nR + 'px'; rightHdr.style.flex = 'none'; }
      }
      function end() {
        if (!dragging) return;
        dragging = false; handle.classList.remove('dragging');
        document.body.style.cursor = ''; document.body.style.userSelect = '';
      }
      handle.addEventListener('mousedown', function(e) { begin(e.clientX); e.preventDefault(); });
      document.addEventListener('mousemove', function(e) { move(e.clientX); });
      document.addEventListener('mouseup', end);
      handle.addEventListener('touchstart', function(e) { begin(e.touches[0].clientX); }, {passive:true});
      document.addEventListener('touchmove', function(e) { move(e.touches[0].clientX); }, {passive:true});
      document.addEventListener('touchend', end);
    }

    // Panel drag disabled — panels are now absolute overlays, not flex columns

    // Vertical overlay drag (drag the top edge to resize height)
    var overlay  = document.getElementById('term-overlay');
    var vertDrag = document.getElementById('vert-drag');
    if (overlay && vertDrag) {
      var vDragging = false, vStartY = 0, vStartH = 0;
      function vBegin(clientY) {
        vDragging = true; vStartY = clientY; vStartH = overlay.offsetHeight;
        vertDrag.classList.add('dragging');
        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';
      }
      function vMove(clientY) {
        if (!vDragging) return;
        var delta = vStartY - clientY;   // drag up → taller
        var newH = Math.max(80, Math.min(window.innerHeight * 0.75, vStartH + delta));
        overlay.style.height = newH + 'px';
        overlay.style.maxHeight = 'none';
      }
      function vEnd() {
        if (!vDragging) return;
        vDragging = false; vertDrag.classList.remove('dragging');
        document.body.style.cursor = ''; document.body.style.userSelect = '';
      }
      vertDrag.addEventListener('mousedown', function(e) { vBegin(e.clientY); e.preventDefault(); });
      document.addEventListener('mousemove', function(e) { vMove(e.clientY); });
      document.addEventListener('mouseup', vEnd);
      vertDrag.addEventListener('touchstart', function(e) { vBegin(e.touches[0].clientY); }, {passive:true});
      document.addEventListener('touchmove', function(e) { vMove(e.touches[0].clientY); }, {passive:true});
      document.addEventListener('touchend', vEnd);
    }
  })();
  // ── end resize ──────────────────────────────────────────────────────────

  function fmtCountdown(diff) {
    if (diff <= 0) return 'now';
    var h = Math.floor(diff / 3600000);
    var m = Math.floor((diff % 3600000) / 60000);
    var s = Math.floor((diff % 60000) / 1000);
    if (h > 0) return h + 'h ' + String(m).padStart(2,'0') + 'm ' + String(s).padStart(2,'0') + 's';
    if (m > 0) return m + 'm ' + String(s).padStart(2,'0') + 's';
    return s + 's';
  }
  window._fmtCountdown = fmtCountdown;

  // ── Dynamic queue ────────────────────────────────────────────────────────────
  function _nextEquityPipelineMs() {
    var now = new Date();
    var etOffset = -5 * 60;
    var etNow = new Date(now.getTime() + (now.getTimezoneOffset() + etOffset) * 60000);
    var target = new Date(etNow); target.setHours(16, 5, 0, 0);
    if (etNow >= target) target.setDate(target.getDate() + 1);
    return target - etNow;
  }

  // HUD open threshold: any action within this many ms shows the HUD
  var HUD_THRESHOLD = 30000;
  var _hudOpen = false;

  function _setHud(open) {
    var hud = document.getElementById('hud-overlay');
    if (!hud) return;
    if (open === _hudOpen) return;
    _hudOpen = open;
    if (open) { hud.classList.add('hud-open'); }
    else      { hud.classList.remove('hud-open'); }
  }

  function _updateDynamicQueue() {
    var now = Date.now();
    var items = [];

    // Crypto scan
    var scanTarget = (window._lastRunAt || now) + 75000;
    var scanDiff   = Math.max(0, scanTarget - now);
    var scanPairs  = window._cryptoPairCount || 15;
    items.push({
      badge:'SCAN', label:'CRYPTO · ALL PAIRS',
      detail: scanPairs + ' pairs · EMA 3/8 signal',
      color:'#00e5ff', diff: scanDiff,
    });

    // Equity pipeline
    var eqDiff = _nextEquityPipelineMs();
    items.push({
      badge:'REBALANCE', label:'EQUITY PIPELINE',
      detail:'momentum · top-5 rebalance',
      color:'#9400ff', diff: eqDiff,
    });

    // Per-position timeouts (<90s)
    var positions = window._cryptoPositionsMap || {};
    Object.values(positions).forEach(function(p) {
      var exitAt = new Date(p.entered_at).getTime() + 4 * 60 * 1000;
      var diff   = exitAt - now;
      if (diff > 0 && diff < 90000) {
        items.push({
          badge:'TIMEOUT', label:p.symbol.replace('/USD','') + ' · MAX HOLD',
          detail:'force evaluation · stop/target check',
          color: diff < 30000 ? '#ff3366' : '#ff9900', diff: diff,
        });
      }
    });

    // Sort most urgent first
    items.sort(function(a, b) { return a.diff - b.diff; });

    // Determine if HUD should open (any item within threshold)
    var anyImminent = items.some(function(it) { return it.diff <= HUD_THRESHOLD; });
    _setHud(anyImminent);

    // Populate HUD items
    var hudItems = document.getElementById('hud-items');
    if (hudItems) {
      hudItems.innerHTML = items.map(function(it) {
        var imminent = it.diff < 15000;
        var urgent   = it.diff < 60000;
        var timerTxt = imminent ? 'EXECUTING' : fmtCountdown(it.diff);
        var timerCls = 'hud-timer' + (imminent ? ' hud-imminent' : urgent ? ' hud-urgent' : '');
        var itemCls  = 'hud-item' + (imminent ? ' hud-imminent' : '');
        return '<div class="' + itemCls + '" style="color:' + it.color + '">' +
          '<div class="hud-badge">' + it.badge + '</div>' +
          '<div class="hud-sym">' + it.label + '</div>' +
          '<div class="hud-detail">' + it.detail + '</div>' +
          '<div class="' + timerCls + '">' + timerTxt + '</div>' +
          '</div>';
      }).join('');
    }
  }

  function tick() {
    var now = Date.now();
    var n = new Date();
    var etParts = n.toLocaleDateString('en-US', {timeZone:'America/New_York', month:'numeric', day:'numeric', year:'2-digit'}).split('/');
    var etTime  = n.toLocaleTimeString('en-US', {timeZone:'America/New_York', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false});
    var el = document.getElementById('live-clock');
    if (el) el.textContent = etParts[0]+'/'+etParts[1]+'/'+etParts[2]+'  '+etTime+'  ';

    document.querySelectorAll('.q-timer').forEach(function(el) {
      var target = parseInt(el.getAttribute('data-target'), 10);
      var diff = target - now;
      var item = el.closest('.q-item');
      if (diff <= -3000) {
        /* 3s grace period then slide out and remove */
        if (item && !item.classList.contains('q-dying')) {
          item.classList.add('q-dying');
          item.style.transition = 'max-height .5s ease, opacity .5s ease, padding .5s ease';
          item.style.maxHeight = item.offsetHeight + 'px';
          requestAnimationFrame(function() {
            item.style.maxHeight = '0';
            item.style.opacity = '0';
            item.style.paddingTop = '0';
            item.style.paddingBottom = '0';
          });
          setTimeout(function() { if (item.parentNode) item.parentNode.removeChild(item); }, 520);
        }
        return;
      }
      el.textContent = fmtCountdown(diff);
      el.classList.remove('urgent','imminent');
      if (diff <= 0) { el.textContent = 'executing...'; el.classList.add('imminent'); }
      else if (diff < 300000) el.classList.add('imminent');
      else if (diff < 3600000) el.classList.add('urgent');
    });
  }
  // Sync HUD to feed overlay bounds
  function _syncHud() {
    var feed = document.getElementById('feed-overlay');
    var hud  = document.getElementById('hud-overlay');
    if (!feed || !hud) return;
    var r = feed.getBoundingClientRect();
    hud.style.left  = r.left + 'px';
    hud.style.width = r.width + 'px';
    hud.style.right = 'auto';
  }
  _syncHud();
  window.addEventListener('resize', _syncHud);

  // Position count badge removed (redundant with card count)
  function _updatePosCounts() { /* no-op */ }

  // Last feed event tracker — updated by feed poller when new entry added
  window._lastFeedEventMs = Date.now();
  function _tickFeedAgo() {
    var ago = document.getElementById('feed-last-ago');
    if (!ago) return;
    var diff = Math.floor((Date.now() - window._lastFeedEventMs) / 1000);
    if (diff < 5)        ago.textContent = 'just now';
    else if (diff < 60)  ago.textContent = diff + 's ago';
    else if (diff < 3600) ago.textContent = Math.floor(diff/60) + 'm ago';
    else                 ago.textContent = Math.floor(diff/3600) + 'h ago';
    // Color: green when fresh, dims over time
    var alpha = Math.max(0.18, 0.7 - diff * 0.008);
    ago.style.color = 'rgba(100,0,160,' + alpha + ')';
    if (diff < 10) ago.style.color = '#00ff9d';
    else if (diff < 30) ago.style.color = '#9400ff';
  }

  // ── Strategy health indicator ──────────────────────────────────────────────────
  (function() {
    var _dot   = document.getElementById('strat-health-dot');
    var _label = document.getElementById('strat-health-label');
    var _lastTradeMs = window._lastFeedEventMs || Date.now();
    // Also track only trade events (not all feed events)
    var _origPost = window._postToFeed;
    window._postToFeed = function(plain, ts, html) {
      if (_origPost) _origPost(plain, ts, html);
      var _h = html || plain;
      if (_h.indexOf('>enter<') !== -1 || _h.indexOf('>exit<') !== -1) {
        _lastTradeMs = Date.now();
      }
    };
    function _tickHealth() {
      if (!_dot || !_label) return;
      var age = (Date.now() - _lastTradeMs) / 1000;
      var cls, txt;
      if (age < 300) {        // < 5 min: healthy
        cls = 'green';  txt = 'LIVE';
      } else if (age < 900) { // 5–15 min: warning
        cls = 'yellow'; txt = 'SLOW';
      } else {                // > 15 min: stale
        cls = 'red';    txt = 'IDLE';
      }
      _dot.className = cls;
      _label.textContent = txt;
    }
    _tickHealth();
    setInterval(_tickHealth, 10000);
  })();

  // ── Position card scan animation — staggered sweeps across all visible cards ──
  function _scanPositionCards() {
    var cards = document.querySelectorAll('#pos-overlay .pos-card');
    if (!cards.length) return;
    cards.forEach(function(card, i) {
      setTimeout(function() {
        card.classList.remove('pos-card-scanning');
        void card.offsetWidth; // reflow to restart
        card.classList.add('pos-card-scanning');
        setTimeout(function() { card.classList.remove('pos-card-scanning'); }, 1200);
      }, i * 180); // stagger each card by 180ms
    });
  }
  setTimeout(_scanPositionCards, 4000);
  setInterval(_scanPositionCards, 12000); // scan every 12s

  tick();
  setInterval(function() { tick(); _tickFeedAgo(); _updateDynamicQueue(); _syncHud(); _updatePosCounts(); }, 1000);
  _updateDynamicQueue(); // immediate first render

  // ── Terminal feed ─────────────────────────────────────────────────────────────
  (function() {

    var _feedQueue = [];
    // ── Next-run progress bar ─────────────────────────────────────────────────
    var _RUN_INTERVAL = 75;  // seconds — 60s sleep + ~15s execution = loop cycle
    var _lastRunAt    = Date.now();
    window._lastRunAt = _lastRunAt; // expose for dynamic queue
    var _progTimer    = null;

    function _resetRunTimer() {
      _lastRunAt = Date.now();
      window._lastRunAt = _lastRunAt;
    }

    function _tickProgress() {
      if (_progTimer) clearInterval(_progTimer);
      _progTimer = setInterval(function() {
        var elapsed   = (Date.now() - _lastRunAt) / 1000;
        var pct       = Math.min(elapsed / _RUN_INTERVAL * 100, 100);
        var fill      = document.getElementById('run-progress-fill');
        var lbl       = document.getElementById('run-progress-label');
        var wrap      = document.getElementById('run-progress-wrap');
        if (fill) {
          fill.style.width = pct.toFixed(1) + '%';
          fill.classList.toggle('firing', pct >= 95);
        }
        if (lbl) {
          var rem = Math.max(0, Math.round(_RUN_INTERVAL - elapsed));
          if (pct >= 100) {
            lbl.textContent = '▸▸▸';
            lbl.style.color = '#00e5ff';
            lbl.style.textShadow = '0 0 12px rgba(0,229,255,1)';
          } else {
            lbl.textContent = String(rem).padStart(3,'0') + 's';
            // cyan → magenta → hot pink in last 15s
            var heat = Math.max(0, (15 - rem) / 15);
            var r = Math.round(204 + heat * 51);
            var g = Math.round(0);
            var b = Math.round(255 - heat * 145);
            lbl.style.color = 'rgb(' + r + ',' + g + ',' + b + ')';
            lbl.style.textShadow = '0 0 ' + (8 + heat * 8) + 'px rgba(' + r + ',0,' + b + ',.9)';
          }
        }
        if (wrap) wrap.classList.remove('hidden');
      }, 1000);
    }

    // Expose globally so the feed poller (separate IIFE) can reset it
    window._resetRunTimer = _resetRunTimer;

    // ── Equity position hold-timer tick ──────────────────────────────────────
    // `.pc-days` elements have data-days (integer days from Python).
    // This ticks up the displayed seconds within today so it feels live.
    (function() {
      var _dayStart = new Date(); _dayStart.setHours(0,0,0,0);
      setInterval(function() {
        var secsToday = Math.floor((Date.now() - _dayStart.getTime()) / 1000);
        document.querySelectorAll('.pc-days[data-days]').forEach(function(el) {
          var d = parseInt(el.getAttribute('data-days'), 10) || 0;
          var totalSecs = d * 86400 + secsToday;
          var dd = Math.floor(totalSecs / 86400);
          var hh = Math.floor((totalSecs % 86400) / 3600);
          var mm = Math.floor((totalSecs % 3600) / 60);
          var ss = totalSecs % 60;
          el.textContent = '⏱ ' + dd + 'd ' +
            String(hh).padStart(2,'0') + ':' +
            String(mm).padStart(2,'0') + ':' +
            String(ss).padStart(2,'0');
        });
      }, 1000);
    })();

    // Wire the crypto-cycle chip bar to _lastRunAt
    setInterval(function() {
      var fill  = document.getElementById('crypto-cycle-fill');
      var eta   = document.getElementById('crypto-cycle-eta');
      if (!fill || !eta) return;
      var elapsed = (Date.now() - _lastRunAt) / 1000;
      var pct     = Math.min(elapsed / _RUN_INTERVAL * 100, 100);
      var rem     = Math.max(Math.round(_RUN_INTERVAL - elapsed), 0);
      fill.style.width = pct + '%';
      fill.style.background = pct > 90 ? '#00ff9d' : '#00e5ff';
      eta.textContent = rem + 's';
    }, 500);

    // ── postToFeed: prepend newest to top, trim from tail ───────────────────
    function postToFeed(plain, timestamp, html) {
      var _h  = html || plain;
      var tb  = document.getElementById('term-body');
      if (!tb) return;
      var now  = timestamp ? new Date(timestamp) : new Date();
      var hhmm = now.toLocaleTimeString('en-US', {timeZone:'America/New_York', hour:'2-digit', minute:'2-digit', hour12:false});
      var row  = document.createElement('div');
      var isTrade = (_h.indexOf('>enter<') !== -1 || _h.indexOf('>exit<') !== -1) && _h.indexOf('@') !== -1;
      var isUser  = plain && plain.indexOf('[USER]') === 0;
      if (isTrade || isUser) {
        row.className = 'te te-new';
        var _isEntry  = isUser ? (plain.indexOf('BUY') !== -1) : (_h.indexOf('>enter<') !== -1);
        var _isWin    = !_isEntry && (_h.indexOf('color:#00ff9d') !== -1);
        var _flashCol = _isEntry ? '#ffffff' : (_isWin ? '#00ff9d' : '#ff4466');
        var _dimCol   = _isEntry ? 'rgba(200,200,220,.55)' : (_isWin ? 'rgba(0,210,130,.55)' : 'rgba(255,60,80,.55)');
        row.style.color = _flashCol;
        row.style.textShadow = '0 0 10px ' + _flashCol;
        setTimeout(function() {
          row.style.transition = 'color 2s ease, text-shadow 2s ease';
          row.style.color = _dimCol;
          row.style.textShadow = 'none';
        }, 1800);
      } else {
        row.className = 'te te-new';
        row.style.color = '#4a3060';
        row.style.textShadow = 'none';
      }
      row.innerHTML = '<span class="te-ts">' + hhmm + '<span style="font-size:7px;opacity:.4;letter-spacing:.08em"> ET</span>&nbsp;&nbsp;</span>' + _h;
      tb.insertBefore(row, tb.firstChild);
      // Keep viewport on newest (top) if user hasn't scrolled down intentionally
      if (tb.scrollTop < 40) tb.scrollTop = 0;
      // Trim oldest entries (now at tail)
      while (tb.children.length > 50) tb.removeChild(tb.lastChild);
      window._lastFeedEventMs = Date.now();
    }

    // Expose globally
    window._postToFeed = postToFeed;

    // On load: show server-rendered entries
    var tb = document.getElementById('term-body');
    if (tb) {
      tb.querySelectorAll('.te').forEach(function(el) { el.style.opacity = '1'; });
    }

    // Live clock at top of terminal
    (function() {
      var clk = document.getElementById('term-clock');
      var _BLOCKS = 12;
      function _tickClock() {
        if (!clk) return;
        // Derive clock from DB timestamps so it matches terminal log entries exactly.
        // When a DB anchor is known, extrapolate forward from it. Fall back to new Date().
        var now;
        if (window._lastKnownTs && window._lastLivePriceMs) {
          var _ts = window._lastKnownTs; _ts = _ts.replace(' ','T'); if (/[+-]\d{2}$/.test(_ts)) _ts += ':00'; else if (!/Z|[+-]\d{2}:\d{2}$/.test(_ts)) _ts += 'Z';
          now = new Date(new Date(_ts).getTime() + (Date.now() - window._lastLivePriceMs));
        } else {
          now = new Date();
        }
        var hhmm  = now.toLocaleTimeString('en-US', {timeZone:'America/New_York', hour:'2-digit', minute:'2-digit', hour12:false});
        var elapsed = window._lastRunAt ? (Date.now() - window._lastRunAt) / 1000 : 0;
        var pct     = Math.min(elapsed / (_RUN_INTERVAL || 75), 1);
        var filled  = Math.round(pct * _BLOCKS);
        var bar     = '▓'.repeat(filled) + '░'.repeat(_BLOCKS - filled);
        var rem     = Math.max(0, Math.round((_RUN_INTERVAL || 75) - elapsed));
        var remStr  = pct >= 1 ? '▸▸▸' : String(rem).padStart(3,'0') + 's';
        var filledCol = pct >= 0.9 ? 'rgba(255,120,0,.9)' : '#ffffff';
        var emptyCol  = 'rgba(255,255,255,.18)';
        var filledBar = '<span style="color:' + filledCol + ';font-size:9px;letter-spacing:.04em">' + '▓'.repeat(filled) + '</span>';
        var emptyBar  = '<span style="color:' + emptyCol + ';font-size:9px;letter-spacing:.04em">' + '░'.repeat(_BLOCKS - filled) + '</span>';
        clk.innerHTML = '<span style="color:#fff;font-size:9px;margin-right:3px">' + hhmm + '</span>'
          + '<span style="color:rgba(255,255,255,.28);font-size:7px;letter-spacing:.12em;margin-right:6px">ET</span>'
          + filledBar + emptyBar
          + '<span style="color:rgba(255,255,255,.35);font-size:9px;letter-spacing:.1em;margin-left:5px">' + remStr + '</span>';
      }
      _tickClock();
      setInterval(_tickClock, 1000);
    })();

    // ── Event countdown notifications ────────────────────────────────────────
    // Fires a callout card 60s before each scheduled event; card shows a live
    // countdown for the final 10s then flashes "NOW" at execution.
    (function() {
      var ET = 'America/New_York';
      // Returns ms until next occurrence of hh:mm ET on a weekday
      function _msUntilET(h, m) {
        var n = new Date();
        // Build a candidate date in ET
        var etStr = n.toLocaleString('en-US', {timeZone:ET});
        var etNow = new Date(etStr);
        var t = new Date(etNow); t.setHours(h, m, 0, 0);
        if (t <= etNow) t.setDate(t.getDate() + 1);
        while (t.getDay() === 0 || t.getDay() === 6) t.setDate(t.getDate() + 1);
        // Convert back to wall-clock delta
        return (t - etNow);
      }

      var _EVENTS = [
        { label:'MARKET OPEN',  h:9,  m:30, col:'#00e5ff' },
        { label:'MARKET CLOSE', h:16, m:0,  col:'#9400ff' },
        { label:'PIPELINE RUN', h:16, m:5,  col:'#ff00cc' },
      ];
      var _fired = {}; // key → last fire date string so we don't double-fire

      function _checkEvents() {
        var today = new Date().toLocaleDateString('en-US', {timeZone:ET});
        _EVENTS.forEach(function(ev) {
          var key = ev.label + ':' + today;
          if (_fired[key]) return;
          var ms = _msUntilET(ev.h, ev.m);
          if (ms <= 60000) {
            _fired[key] = true;
            if (window._fireEventCallout) window._fireEventCallout(ev.label, ev.col, ms / 1000);
          }
        });
      }

      setInterval(_checkEvents, 1000);
    })();

    // Kick off the progress bar — inside IIFE where _tickProgress is in scope
    _tickProgress();

  })();

  // ── Crosshair on portfolio dot ───────────────────────────────────────────────
  function showCrosshair() {
    var overlay = document.getElementById('crosshair-overlay');
    var xc      = document.getElementById('xhair-canvas');
    var gd2     = document.getElementById('chart');
    if (!overlay || !xc || !gd2 || !gd2._fullLayout) {
      // Retry up to 3s if layout not ready yet
      if (!showCrosshair._tries) showCrosshair._tries = 0;
      if (++showCrosshair._tries < 6) setTimeout(showCrosshair, 500);
      return;
    }
    showCrosshair._tries = 0;
    try {
      var fl  = gd2._fullLayout;
      // Find portfolio trace by name
      var tr = null;
      for (var i = 0; i < gd2.data.length; i++) {
        if (gd2.data[i].name && gd2.data[i].name.toLowerCase().indexOf('portfolio') >= 0) {
          tr = gd2.data[i]; break;
        }
      }
      if (!tr) tr = gd2.data[0]; // fallback to first trace
      if (!tr || !tr.x || !tr.x.length) return;
      var px = fl.xaxis.l2p(fl.xaxis.d2l(tr.x[tr.x.length-1])) + fl.margin.l;
      var py = fl.yaxis.l2p(fl.yaxis.d2l(tr.y[tr.y.length-1])) + fl.margin.t;

      xc.width  = overlay.offsetWidth;
      xc.height = overlay.offsetHeight;
      var ctx = xc.getContext('2d');
      var Y = '#FFE500';
      ctx.clearRect(0, 0, xc.width, xc.height);

      // Full cross lines
      ctx.strokeStyle = 'rgba(255,229,0,0.35)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 6]);
      ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(xc.width, py); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, xc.height); ctx.stroke();
      ctx.setLineDash([]);

      // Corner brackets (retro radar lock)
      var S = 14, G = 4;
      ctx.strokeStyle = Y; ctx.lineWidth = 2;
      [[px-G-S, py-G-S, 1, 1], [px+G+S, py-G-S, -1, 1],
       [px-G-S, py+G+S, 1, -1], [px+G+S, py+G+S, -1, -1]].forEach(function(c) {
        ctx.beginPath();
        ctx.moveTo(c[0], c[1]); ctx.lineTo(c[0] + c[2]*S, c[1]);
        ctx.moveTo(c[0], c[1]); ctx.lineTo(c[0], c[1] + c[3]*S);
        ctx.stroke();
      });

      // Center dot
      ctx.shadowColor = Y; ctx.shadowBlur = 12;
      ctx.fillStyle = Y;
      ctx.beginPath(); ctx.arc(px, py, 3.5, 0, Math.PI*2); ctx.fill();
      ctx.shadowBlur = 0;

      // Label
      ctx.fillStyle = Y; ctx.font = '700 8px Consolas,monospace';
      ctx.letterSpacing = '0.18em';
      ctx.fillText('TARGET ACQUIRED', px + G + S + 6, py + 4);

      // Fade in → hold → fade out → then zoom tightens
      overlay.style.transition = 'opacity 300ms ease';
      overlay.style.opacity = '1';
      setTimeout(function() {
        overlay.style.transition = 'opacity 400ms ease';
        overlay.style.opacity = '0';
        // Snap to 60-day window
        var yr2 = yRange(xStart, xEnd);
        Plotly.relayout(gd2, {
          'xaxis.range': [xStart, xEnd],
          'yaxis.range': yr2[0] !== null ? yr2 : undefined
        });
      }, 1100);
    } catch(e) {}
  }

  // ── Buy console ───────────────────────────────────────────────────────────────

  // Populate ticker datalist from Python-seeded universe
  (function() {
    var dl = document.getElementById('bc-tickers');
    if (!dl || !window._allTickers) return;
    // Only show equity tickers during NYSE hours; crypto is 24/7
    if (_isNYSEOpen()) {
      (_allTickers.equity || []).forEach(function(s) {
        var o = document.createElement('option'); o.value = s; dl.appendChild(o);
      });
    }
    (_allTickers.crypto || []).forEach(function(s) {
      var o = document.createElement('option'); o.value = s; dl.appendChild(o);
    });
  })();

  function bcStatus(msg, col) {
    var el = document.getElementById('bc-status');
    if (!el) return;
    el.textContent = msg;
    el.style.color = col || '#0a2a1a';
  }

  // Route buy/sell through postMessage → parent shim → Alpaca
  function _submitOrder(sym, side, dollarAmt, notional) {
    window.parent.postMessage({
      type: 'tnd_order',
      sym: sym,
      side: side,
      notional: notional,  // dollar amount → Alpaca notional order
      strategy: 'user',
    }, '*');
  }

  function _isNYSEOpen() {
    var now = new Date();
    // Convert to ET
    var etStr = now.toLocaleString('en-US', {timeZone: 'America/New_York'});
    var et = new Date(etStr);
    var day = et.getDay(); // 0=Sun, 6=Sat
    if (day === 0 || day === 6) return false;
    var h = et.getHours(), m = et.getMinutes();
    var mins = h * 60 + m;
    return mins >= 570 && mins < 960; // 9:30am–4:00pm ET
  }

  function bcSubmit() {
    var sym = (document.getElementById('bc-sym').value || '').trim().toUpperCase();
    var amt = parseFloat(document.getElementById('bc-amt').value || 0);
    if (!sym) { bcStatus('⚠ enter a ticker', '#ff9900'); return; }
    if (!amt || amt <= 0) { bcStatus('⚠ enter dollar amount', '#ff9900'); return; }

    // Block NYSE equities outside market hours
    var isCrypto = sym.indexOf('/') !== -1;
    if (!isCrypto && !_isNYSEOpen()) {
      bcStatus('⚠ NYSE closed · crypto only', '#ff9900');
      return;
    }

    var btn = document.getElementById('bc-buy');
    if (btn) btn.disabled = true;
    bcStatus('submitting…', '#00e5ff');

    _submitOrder(sym, 'buy', amt, amt);

    // Optimistic tile — only create if tile doesn't already exist (avoid value overwrite)
    var col = _symCol(sym);
    if (window._etUpsert && !(window._etBySym||{})[sym]) {
      window._etUpsert({
        sym: sym, col: col, val: amt, pnl: 0, pnlPct: 0,
        entry: 0, qty: 0, stop: 0, target: 0, curPrice: 0,
        days: 0, enteredAt: Date.now(), inSignal: true, rank: 0,
        holdText: '0s', strategy: 'user', isCrypto: isCrypto,
      });
    }

    var feedMsg = '[USER] BUY $' + amt.toLocaleString('en-US',{maximumFractionDigits:0}) + ' ' + sym + ' · market · routed to Alpaca';
    if (window._postToFeed) window._postToFeed(feedMsg);
    if (window._recordTradeForGauge) window._recordTradeForGauge();
    setTimeout(function() { if (window._pushIntradayPoint && window._lastKnownNav) window._pushIntradayPoint(new Date().toISOString(), window._lastKnownNav); }, 5000);

    bcStatus('✓ BUY ' + sym + ' $' + amt.toLocaleString('en-US',{maximumFractionDigits:0}), '#00ff9d');
    document.getElementById('bc-amt').value = '';
    document.getElementById('bc-sym').value = '';
    setTimeout(function() { bcStatus('dbl-click holding to sell', ''); if (btn) btn.disabled = false; }, 3000);
  }

  // ── Double-click tile → sell full position ────────────────────────────────────
  (function() {
    var _etC = document.getElementById('eq-tiles-canvas');
    if (!_etC) return;
    _etC.addEventListener('dblclick', function(e) {
      var rect = _etC.getBoundingClientRect();
      var mx = e.clientX - rect.left;
      var my = e.clientY - rect.top;
      // Hit-test against live tiles
      var layout = (typeof _etLayout === 'function') ? _etLayout() : null;
      if (!layout) return;
      var hit = null;
      layout.live.forEach(function(t) {
        if (t.phase === 'done') return;
        var pos = _etTilePos(t, layout);
        if (mx >= pos.x && mx < pos.x + _EQ_W && my >= pos.y && my < pos.y + _EQ_H) hit = t;
      });
      if (!hit) return;

      // Show sell flash label
      var hint = document.createElement('div');
      hint.className = 'tc-dblclick-hint';
      hint.textContent = 'SELL ' + hit.sym;
      hint.style.left = (e.clientX - 30) + 'px';
      hint.style.top  = (e.clientY - 20) + 'px';
      document.body.appendChild(hint);
      setTimeout(function() { if (hint.parentNode) hint.parentNode.removeChild(hint); }, 700);

      // Route to Alpaca
      _submitOrder(hit.sym, 'sell', hit.val, hit.val);

      // Feed label
      var feedMsg = '[USER] SELL ' + hit.sym + ' · full position · market · routed to Alpaca';
      if (window._postToFeed) window._postToFeed(feedMsg);
      if (window._recordTradeForGauge) window._recordTradeForGauge();
      setTimeout(function() { if (window._pushIntradayPoint && window._lastKnownNav) window._pushIntradayPoint(new Date().toISOString(), window._lastKnownNav); }, 5000);

      // Trigger exit animation
      if (window._etExit) window._etExit(hit.sym, null, null);
    });
  })();

  // Keyboard shortcut: B focuses buy console
  document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'b' || e.key === 'B') document.getElementById('bc-amt').focus();
  });

  // ── Live feed poller — Supabase REST, no page reload ────────────────────────
  (function() {
    var SUPA_URL  = 'https://seeevuklabvhkawawtxn.supabase.co';
    var SUPA_KEY  = 'sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY';
    // Server already rendered history; start live polling from newest server event so poller never re-inserts them
    var _lastSeen = window._TND.NEWEST_EV_TS || null;

    // Supabase returns "2026-07-12 14:57:23+00" — normalize to proper ISO UTC
    function _parseTs(s) {
      if (!s) return new Date();
      s = s.replace(' ', 'T');                          // space → T
      if (/[+-]\d{2}$/.test(s)) s += ':00';           // +00 → +00:00
      else if (!/Z|[+-]\d{2}:\d{2}$/.test(s)) s += 'Z'; // bare → UTC
      return new Date(s);
    }

    function _labelFor(eventType) {
      var m = {
        'TRADE':'TRADE','ENTRY':'BUY','EXIT':'SELL','SIGNAL':'SIGNAL',
        'SNAPSHOT':'NAV','START':'RUN','COMPLETE':'RUN','RISK_VETO':'VETO',
        'UPDATE':'UPDATE','INGEST':'DATA'
      };
      return m[eventType] || eventType;
    }

    function _poll() {
      var url = SUPA_URL + '/rest/v1/pipeline_events'
        + '?select=event_type,symbol,message,recorded_at'
        + (_lastSeen
            ? '&recorded_at=gt.' + encodeURIComponent(_lastSeen) + '&order=recorded_at.asc&limit=20'
            : '&order=recorded_at.desc&limit=8');
      fetch(url, {
        headers: {
          'apikey': SUPA_KEY,
          'Authorization': 'Bearer ' + SUPA_KEY
        }
      })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) { _lastSeen = _lastSeen || new Date().toISOString(); return; }
        var isHistory = !_lastSeen;
        if (isHistory) rows = rows.slice().reverse(); // DESC → chronological
        if (window._resetRunTimer) window._resetRunTimer();

        // Deduplicate: skip any row we've already rendered (guards WS + poll race)
        if (!window._feedSeenKeys) window._feedSeenKeys = new Set();
        rows = rows.filter(function(row) {
          var k = (row.recorded_at||'') + '|' + (row.symbol||'') + '|' + (row.message||'').slice(0,80);
          if (window._feedSeenKeys.has(k)) return false;
          window._feedSeenKeys.add(k);
          return true;
        });
        if (!rows.length) return;

        // ── Batch processing: exits before entries, then batch PnL chip ─────────
        if (!isHistory) {
          // Sort: exits first, then entries, within this batch
          rows = rows.slice().sort(function(a, b) {
            var aIsExit  = (a.message||'').indexOf('EXIT')  !== -1;
            var bIsExit  = (b.message||'').indexOf('EXIT')  !== -1;
            var aIsEntry = (a.message||'').indexOf('ENTER') !== -1;
            var bIsEntry = (b.message||'').indexOf('ENTER') !== -1;
            // exits first
            if (aIsExit  && !bIsExit)  return -1;
            if (!aIsExit &&  bIsExit)  return  1;
            // then entries
            if (aIsEntry && !bIsEntry) return -1;
            if (!aIsEntry && bIsEntry) return  1;
            return 0;
          });

          // Accumulate batch counts before any stagger fires
          var _batchPnl = 0, _exitCount = 0, _entryCount = 0, _tradeCount = 0;
          rows.forEach(function(r) {
            var _msg = r.message || '';
            if (_msg.indexOf('EXIT') !== -1) {
              var m = _msg.match(/pnl\s*([+-][\d,.]+)/);
              if (m) { _batchPnl += parseFloat(m[1].replace(/,/g,'')); _exitCount++; }
              _tradeCount++;
            }
            if (_msg.indexOf('ENTER') !== -1) { _entryCount++; _tradeCount++; }
          });
          var _batchDur = _tradeCount * 180; // total stagger duration

          // _showChip: shows chip and optionally drives decay on a companion value el
          // valId: id of the main number el; baseVal: real base number; bonusVal: the delta shown in chip
          function _showChip(id, text, col, onFade, valId, baseVal, bonusVal) {
            var c = document.getElementById(id);
            if (!c) return;
            c.style.color = col;
            c.style.textShadow = '0 0 8px ' + col;
            c.textContent = text;
            c.style.opacity = '1';
            var DECAY_MS = 7000; // slower — 7s visible window
            var startTs = Date.now() + _batchDur;
            // If companion value provided, animate it decaying from base+bonus → base
            if (valId && bonusVal) {
              var valEl = document.getElementById(valId);
              var decayRaf;
              function _decayStep() {
                var now = Date.now();
                if (now < startTs) { decayRaf = requestAnimationFrame(_decayStep); return; }
                var t = Math.min(1, (now - startTs) / DECAY_MS); // 0→1 over decay window
                var cur = baseVal + bonusVal * (1 - t); // interpolate bonus → 0
                if (valEl) {
                  var isInt = (Math.abs(bonusVal) >= 1 && Math.floor(bonusVal) === bonusVal);
                  if (isInt) {
                    valEl.textContent = Math.round(cur).toLocaleString('en-US');
                  } else {
                    var pos = cur >= 0;
                    valEl.textContent = (pos ? '+$' : '-$') + Math.abs(cur).toLocaleString('en-US', {maximumFractionDigits:0});
                    valEl.style.color = pos ? '#00c880' : '#e03355';
                  }
                }
                if (t < 1) { decayRaf = requestAnimationFrame(_decayStep); }
              }
              decayRaf = requestAnimationFrame(_decayStep);
            }
            // Chip fades after decay window
            setTimeout(function() {
              c.style.transition = 'opacity 1.2s ease';
              c.style.opacity = '0';
              if (onFade) onFade();
            }, _batchDur + DECAY_MS);
          }

          // P&L combo chip + sounds
          if (_exitCount > 0) {
            var _isPos = _batchPnl >= 0;
            var _basePnl = parseFloat((document.getElementById('total-pnl-val') || {}).getAttribute('data-raw') || '0');

            // Show batch delta chip — decays companion P&L value from base+bonus → base
            _showChip('batch-pnl-chip',
              (_isPos ? '+' : '') + _batchPnl.toFixed(2),
              _isPos ? '#00c880' : '#e03355', null,
              'total-pnl-val', _basePnl, _batchPnl);

            // Immediately update Portfolio slot with this batch's P&L delta
            if (window._walletCombo) window._walletCombo(_batchPnl);
            // Orb-side popup
            if (window._orbBatchPnl) window._orbBatchPnl(_batchPnl);

            // Sound: one per batch
            if (_isPos && window._soundWin) window._soundWin();
            else if (!_isPos && window._soundLoss) window._soundLoss();

            // After stagger + chip settle: fetch real totals from DB (single source of truth)
            setTimeout(function() {
              // Total P&L from fills table
              var pnlUrl = SUPA_URL + '/rest/v1/fills'
                + '?select=pnl&strategy=eq.crypto_momentum';
              fetch(pnlUrl, { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY } })
              .then(function(r) { return r.json(); })
              .then(function(rows) {
                if (!Array.isArray(rows)) return;
                var total = rows.reduce(function(s, r) { return s + (parseFloat(r.pnl) || 0); }, 0);
                var pv = document.getElementById('total-pnl-val');
                if (pv) {
                  pv.setAttribute('data-raw', total);
                  var pos = total >= 0;
                  pv.style.color = pos ? '#00c880' : '#e03355';
                  pv.textContent = (pos ? '+$' : '-$') + Math.abs(total).toLocaleString('en-US', {maximumFractionDigits:0});
                }
              }).catch(function() {});
            }, _batchDur + 1000);
          }

          // Trades combo chip
          if (_tradeCount > 0) {
            var _baseTrades = parseInt((document.getElementById('om-today') || {}).textContent || '0', 10);
            _showChip('trades-combo-chip', '+' + _tradeCount, '#ff9900', null,
              'om-today', _baseTrades, _tradeCount);
            if (window._tradeSlotCombo) window._tradeSlotCombo(_tradeCount);
          }

          // Open positions delta chip — flash only, _pollPositions owns the persistent count
          var _posDelta = _entryCount - _exitCount;
          if (_posDelta !== 0) {
            _showChip('pos-combo-chip',
              (_posDelta > 0 ? '+' : '') + _posDelta,
              _posDelta > 0 ? '#00e5ff' : '#ff4466', null);
          }
        }

        // Advance _lastSeen synchronously before stagger so concurrent WS polls don't re-fetch
        if (rows.length) _lastSeen = rows[rows.length - 1].recorded_at;

        // Stagger live batches so events drip in one-by-one (history: instant)
        var _staggerMs = isHistory ? 0 : 180;
        rows.forEach(function(row, _ri) { setTimeout(function() {
          var raw = row.message || '';
          var raw = row.message || '';
          var sym = row.symbol || '';
          var display;
          if (row.event_type === 'TRADE' && (raw.indexOf('ENTER') !== -1 || raw.indexOf('EXIT') !== -1)) {
            var isEntry = raw.indexOf('ENTER') !== -1;
            var verbPlain = isEntry ? 'enter' : 'exit';
            var verbCol   = isEntry ? '#00b4ff' : '#ff9900';
            var verbHtml  = '<span style="color:' + verbCol + '">' + verbPlain + '</span>';
            var symCol    = (function(s) {
              var _c=sym.replace('/USD','').replace('USD','');
              if(window._TICKER_OVR&&window._TICKER_OVR[_c]) return window._TICKER_OVR[_c];
              var _p=['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
              var h=0; for(var i=0;i<_c.length;i++)h=(h*31+_c.charCodeAt(i))&0xffff; return _p[h%_p.length];
            })(sym);
            var symHtml   = '<span style="color:' + symCol + ';font-weight:700">' + sym + '</span>';
            var priceM    = raw.match(/@\s*\$([\d,]+(?:\.\d+)?)/);
            var priceS    = priceM ? ' @ <span style="color:rgba(255,255,255,.55)">$' + priceM[1] + '</span>' : '';
            var pnlM      = raw.match(/pnl\s*([+-][\d,.]+)/);
            var pnlCol    = pnlM && pnlM[1][0] === '+' ? '#00c880' : '#e03355';
            var pnlHtml   = pnlM ? ' · <span style="color:' + pnlCol + '">' + pnlM[1] + '</span>' : '';
            var plain     = verbPlain + ' ' + sym;
            var html      = verbHtml + ' ' + symHtml + priceS + pnlHtml;
            if (window._postToFeed) window._postToFeed(plain, _parseTs(row.recorded_at), html);
            // All visual + audio effects fire in one synchronous block — no gaps
            if (!isHistory) {
              if (window._recordTradeForGauge) window._recordTradeForGauge();
              var _fillPrice = parseFloat((raw.match(/\$([\d,.]+)/) || [])[1] || '0');
              var _qty = parseFloat((raw.match(/x([\d.]+)/) || [])[1] || '1');
              if (window._recordTradeVol && _fillPrice > 0) window._recordTradeVol(_fillPrice * _qty);
              if (!isEntry && pnlM && window._recordStreakResult) {
                window._recordStreakResult(pnlM[1][0] === '+');
              }
              if (isEntry) {
                // ── ENTRY: veil flash + orb bloom + sound + card insert ──
                var _veilE = document.getElementById('trade-veil');
                if (_veilE) {
                  _veilE.classList.remove('veil-entry','veil-win','veil-loss');
                  void _veilE.offsetWidth;
                  _veilE.classList.add('veil-entry');
                }
                // No callout for entries — card appearing in positions panel is enough
                if (window._orbTradeFlash) window._orbTradeFlash(true);
                // sound fires from _etUpsert when tile animates in
                // Upsert crypto tile on canvas engine
                (function() {
                  var _symE = sym.indexOf('/') !== -1 ? sym : sym + '/USD';
                  if (!(window._etBySym||{})[_symE]) {
                    var _priceE = priceM ? parseFloat(priceM[1].replace(/,/g,'')) : 0;
                    var _ep = {
                      symbol: _symE, direction: 'long', qty: 0,
                      entry_price: _priceE, stop_price: _priceE * 0.997,
                      target_price: _priceE * 1.006, entered_at: new Date().toISOString()
                    };
                    if (!window._cryptoPositionsMap) window._cryptoPositionsMap = {};
                    window._cryptoPositionsMap[_symE] = _ep;
                    _makeCard(_ep); // → _etUpsert, no DOM element
                    // Fetch real qty from DB and backfill tile state
                    (function(_s) {
                      var _qurl = 'https://seeevuklabvhkawawtxn.supabase.co/rest/v1/crypto_positions'
                        + '?select=qty,stop_price,target_price&symbol=eq.' + encodeURIComponent(_s);
                      fetch(_qurl, { headers: { 'apikey': 'sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY',
                        'Authorization': 'Bearer sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY' } })
                      .then(function(r) { return r.json(); })
                      .then(function(rows) {
                        if (!Array.isArray(rows) || !rows.length) return;
                        var row = rows[0];
                        var realQty = parseFloat(row.qty || 0);
                        if (window._cryptoPositionsMap[_s]) {
                          window._cryptoPositionsMap[_s].qty = realQty;
                          window._cryptoPositionsMap[_s].stop_price = parseFloat(row.stop_price || 0);
                          window._cryptoPositionsMap[_s].target_price = parseFloat(row.target_price || 0);
                        }
                        var t = (window._etBySym||{})[_s];
                        if (t) {
                          t.qty   = realQty;
                          t.stop  = parseFloat(row.stop_price  || 0) || t.stop;
                          t.target= parseFloat(row.target_price|| 0) || t.target;
                          t.val   = realQty * t.curPrice;
                        }
                        _updateOverlayWidth();
                      }).catch(function() {});
                    })(_symE);
                    _updateOverlayWidth();
                  }
                })();
              } else {
                // ── EXIT: ALL effects fire simultaneously — terminal flash + orb bloom +
                //          sound + satellite shoot-out + P&L odometer — one atomic block ──
                var _isWin = pnlM && pnlM[1][0] === '+';
                // 1. Veil flash — full chart area
                var _veilX = document.getElementById('trade-veil');
                if (_veilX) {
                  _veilX.classList.remove('veil-entry','veil-win','veil-loss');
                  void _veilX.offsetWidth;
                  _veilX.classList.add(_isWin ? 'veil-win' : 'veil-loss');
                }
                // Stratagem callout drop-in
                if (window._fireCallout) {
                  var _xPrice = priceM ? parseFloat(priceM[1].replace(/,/g,'')).toFixed(2) : null;
                  var _xPnl   = pnlM ? pnlM[1] : null;
                  window._fireCallout(
                    sym.replace('/USD',''),
                    _xPrice,
                    _xPnl,
                    _isWin ? '#00ff9d' : '#ff3366'
                  );
                }
                // 2. Orb bloom
                if (window._orbTradeFlash) window._orbTradeFlash(false, _isWin);
                // 3. Sound fires from _etExit when tile animation starts
                // 4. Satellite shoot-out + immediate map removal (1:1 with tile)
                var _exitSymFull = sym.indexOf('/') !== -1 ? sym : sym + '/USD';
                var _satKey = _satAngles[_exitSymFull] !== undefined ? _exitSymFull
                            : _satAngles[sym] !== undefined ? sym : null;
                if (_satKey) {
                  _satExiting[_satKey] = {
                    angle: _satAngles[_satKey],
                    orbitR: _smoothOrbitR[_satKey] || 32,
                    age: 0,
                    sr: _isWin ? 0 : 255, sg: _isWin ? 255 : 51, sb: _isWin ? 157 : 102
                  };
                  delete _satAngles[_satKey];
                  delete _smoothOrbitR[_satKey];
                }
                // Remove from positions map immediately so count stays 1:1 with tiles
                if (window._cryptoPositionsMap) {
                  delete window._cryptoPositionsMap[_exitSymFull];
                  delete window._cryptoPositionsMap[sym];
                }
                // 5. P&L odometer — starts same RAF tick as satellite
                if (pnlM) {
                  var _pnlEl = document.getElementById('total-pnl-val');
                  var _subEl = document.getElementById('total-pnl-sub');
                  if (_pnlEl) {
                    var _raw    = parseFloat(_pnlEl.getAttribute('data-raw') || '0') || 0;
                    var _delta  = parseFloat(pnlM[1].replace(/,/g,'')) || 0;
                    var _target = _raw + _delta;
                    _pnlEl.setAttribute('data-raw', _target);
                    var _isPos  = _target >= 0;
                    var _col    = _isPos ? '#00ff9d' : '#ff3366';
                    _pnlEl.style.color = _col;
                    if (_subEl) _subEl.style.color = _col;
                    _pnlEl.classList.remove('pnl-flash-pos','pnl-flash-neg');
                    void _pnlEl.offsetWidth;
                    _pnlEl.classList.add(_isPos ? 'pnl-flash-pos' : 'pnl-flash-neg');
                    var _odoStart = _raw, _odoEnd = _target, _odoT0 = performance.now();
                    function _odoFrame(now) {
                      var p = Math.min(1, (now - _odoT0) / 600);
                      var ease = 1 - Math.pow(1-p, 3);
                      var v = _odoStart + (_odoEnd - _odoStart) * ease;
                      var sign = v >= 0 ? '+' : '−';
                      _pnlEl.textContent = sign + '$' + Math.abs(Math.round(v)).toLocaleString('en-US');
                      if (_subEl) {
                        var pct = (v / 100000) * 100;
                        _subEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '% since $100K start';
                      }
                      if (p < 1) requestAnimationFrame(_odoFrame);
                    }
                    requestAnimationFrame(_odoFrame);
                  }
                }
                // 6. Card exit animation (with sell price)
                if (window._triggerCardExit) {
                  var _reasonM = raw.match(/·\s*(target|stop|timeout|reversal|signal)\s*$/i);
                  var _exitReason = _reasonM ? _reasonM[1].toLowerCase() : (_isWin ? 'target' : 'stop');
                  var _exitPrice = priceM ? priceM[1] : null;
                  window._triggerCardExit(sym, _exitReason, pnlM ? parseFloat(pnlM[1].replace(/,/g,'')) : null, _exitPrice);
                }
              }
            }
            // Wallet canvas trade burst
            if (!isHistory && window._walletTrade) {
              var isWinW = isEntry ? true : (pnlM ? pnlM[1][0] === '+' : false);
              var priceW = priceM ? priceM[1] : '';
              window._walletTrade(isEntry, isWinW, sym, priceW);
            }
            // Trigger chart trade marker refresh
            if (!isHistory && window._onLiveTrade) window._onLiveTrade();
          } else if (row.event_type === 'UPDATE') {
            if (!isHistory) {
              // Parse open symbols
              var symMatch = raw.match(/\(([^)]+)\)/);
              var symList = symMatch
                ? symMatch[1].split(',').map(function(s) { return s.trim(); }).filter(Boolean)
                : [];
              if (window._triggerScan) window._triggerScan(symList);
              if (window._walletScan) window._walletScan();
            }
          } else {
            // Suppress scan messages — handled by VHS bar, not the feed
            if (raw.toLowerCase().indexOf('scan complete') !== -1) return;
            if (raw.toLowerCase().indexOf('scan ') === 0) return;
            var label = _labelFor(row.event_type);
            var txt   = raw || (label + (sym ? ' · ' + sym : ''));
            if (window._postToFeed) window._postToFeed(txt, _parseTs(row.recorded_at));
          }
        }, _ri * _staggerMs); }); // end stagger setTimeout + forEach
      })
      .catch(function() {}); // silent — offline or auth issue
    }

    // Poll every 3s as fallback — Realtime WebSocket triggers _poll instantly on insert
    setTimeout(function() {
      _poll();
      setInterval(_poll, 3000);
    }, 2000);

    // ── Supabase Realtime — instant push on pipeline_events INSERT ──────────────
    // Uses Phoenix channel protocol over WebSocket (no SDK required, free tier)
    (function() {
      var WS_URL = 'wss://seeevuklabvhkawawtxn.supabase.co/realtime/v1/websocket'
        + '?apikey=sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY&vsn=1.0.0';
      var _ref = 0;
      var _ws, _hbTimer, _reconnTimer;

      function _send(obj) {
        if (_ws && _ws.readyState === 1) _ws.send(JSON.stringify(obj));
      }

      function _connect() {
        try { _ws = new WebSocket(WS_URL); } catch(e) { return; }

        _ws.onopen = function() {
          // Join postgres_changes channel for pipeline_events INSERTs
          _send({
            topic: 'realtime:public:pipeline_events',
            event: 'phx_join',
            payload: {
              config: {
                broadcast: { self: false },
                postgres_changes: [{ event: 'INSERT', schema: 'public', table: 'pipeline_events' }]
              }
            },
            ref: String(++_ref)
          });
          // Heartbeat every 25s to keep connection alive
          clearInterval(_hbTimer);
          _hbTimer = setInterval(function() {
            _send({ topic: 'phoenix', event: 'heartbeat', payload: {}, ref: String(++_ref) });
          }, 25000);
        };

        _ws.onmessage = function(e) {
          try {
            var msg = JSON.parse(e.data);
            // postgres_changes INSERT fires _poll immediately for zero-lag feed update
            if (msg.event === 'postgres_changes' &&
                msg.payload && msg.payload.data &&
                msg.payload.data.type === 'INSERT') {
              _poll();
            }
          } catch(_) {}
        };

        _ws.onclose = function() {
          clearInterval(_hbTimer);
          // Reconnect after 5s
          clearTimeout(_reconnTimer);
          _reconnTimer = setTimeout(_connect, 5000);
        };
      }

      _connect();
    })();
  })();

  // ── Live NAV poller — updates chart + all NAV displays in-place ─────────────
  (function() {
    var SUPA_URL = 'https://seeevuklabvhkawawtxn.supabase.co';
    var SUPA_KEY = 'sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY';
    var START_NAV = 100000;
    var _lastNavTs = null;

    function _fmt(v) {
      return '$' + Math.round(v).toLocaleString('en-US');
    }
    function _fmtRet(v, start) {
      var pct = ((v - start) / start * 100).toFixed(2);
      return (pct >= 0 ? '+' : '') + pct + '%';
    }
    function _retColor(v, start) {
      return v >= start ? '#00ff9d' : '#ff3366';
    }

    // Rolling nav history — localStorage persists across Streamlit reloads (unlike sessionStorage)
    if (!window._navHistory) {
      try {
        var _stored = localStorage.getItem('_navHistory');
        var _cutoffMs = Date.now() - 60*1000;
        window._navHistory = _stored
          ? JSON.parse(_stored).filter(function(p) { return new Date(p.x).getTime() > _cutoffMs; })
          : [];
      } catch(e) { window._navHistory = []; }
    }
    function _trackNav(nav, ts) {
      window._navHistory.push({ x: new Date(ts).toISOString(), y: parseFloat(nav) });
      // keep last 200 points (canvas draw uses _navHistory as source of truth)
      if (window._navHistory.length > 200) window._navHistory.shift();
    }

    function _updateNavDisplays(nav, ts) {
      window._lastKnownNav = nav;
      if (window._updateWalletSlot) window._updateWalletSlot(nav);
      _trackNav(nav, ts);
      var col = _retColor(nav, START_NAV);
      var ret = _fmtRet(nav, START_NAV);
      var pnl = nav - START_NAV;
      var pnlStr = (pnl >= 0 ? '+' : '') + _fmt(Math.abs(pnl));

      // Topbar NAV stat
      document.querySelectorAll('.tb-stat-val').forEach(function(el, i) {
        // NAV is first tb-stat-val
        if (i === 0) { el.textContent = _fmt(nav); el.style.color = '#ff00cc'; }
        if (i === 1) { el.textContent = ret; el.style.color = col; }
      });

      // Wallet panel
      var wNav  = document.getElementById('wallet-nav');
      var wPnl  = document.getElementById('wallet-pnl');
      var wNoise = document.getElementById('wallet-noise');
      if (wNav) {
        var newVal = _fmt(nav);
        if (wNav.textContent !== newVal) {
          if (window._animateWalletNav) { window._animateWalletNav(wNav, newVal); }
          else { wNav.textContent = newVal; wNav.setAttribute('data-val', newVal); }
          if (wNoise) {
            wNoise.classList.remove('sweep'); void wNoise.offsetWidth;
            wNoise.classList.add('sweep');
            setTimeout(function() { wNoise.classList.remove('sweep'); }, 650);
          }
        }
      }
      if (wPnl) { wPnl.textContent = (pnl >= 0 ? '+' : '−') + '$' + Math.abs(pnl).toLocaleString('en-US',{maximumFractionDigits:0}); wPnl.style.color = pnl >= 0 ? '#00ff9d' : '#ff3366'; }
      // Feed wallet canvas engine
      if (window._walletNavUpdate) window._walletNavUpdate(nav);

      // nav-card overlay (top-left of chart)
      var nvVal = document.querySelector('.nv-val');
      var nvRet = document.querySelector('.nv-ret');
      var nvDpnl = document.querySelector('.nv-dpnl');
      if (nvVal) nvVal.textContent = _fmt(nav);
      if (nvRet) { nvRet.textContent = ret + ' vs $100K start'; nvRet.style.color = col; }

      // pnl-float — animated counter + physical nudge
      var pnlFloat = document.querySelector('.pnl-float-val');
      var pnlSub   = document.querySelector('.pnl-float-sub');
      var pnlBox   = document.getElementById('pnl-float');
      if (pnlFloat) {
        var fromVal = parseFloat(pnlFloat.getAttribute('data-raw') || '0');
        var toVal   = pnl;
        var sign    = toVal >= 0 ? '+' : '-';
        var signCol = toVal >= 0 ? '#00ff9d' : '#ff3366';
        pnlFloat.setAttribute('data-raw', toVal);
        pnlFloat.style.color = signCol;
        if (pnlBox) pnlBox.style.borderTopColor = signCol;
        // Animated digit roll
        var startTime = null;
        var dur = 800;
        function animPnl(ts) {
          if (!startTime) startTime = ts;
          var p = Math.min((ts - startTime) / dur, 1);
          var ease = 1 - Math.pow(1 - p, 3); // ease-out cubic
          var cur = fromVal + (toVal - fromVal) * ease;
          var s = cur >= 0 ? '+' : '-';
          pnlFloat.textContent = s + '$' + Math.round(Math.abs(cur)).toLocaleString('en-US');
          if (p < 1) requestAnimationFrame(animPnl);
        }
        requestAnimationFrame(animPnl);
        // Physical nudge
        if (pnlBox) {
          var going = toVal > fromVal ? 'nudge-up' : 'nudge-down';
          pnlBox.classList.remove('nudge-up','nudge-down');
          void pnlBox.offsetWidth;
          pnlBox.classList.add(going);
          setTimeout(function() { pnlBox.classList.remove('nudge-up','nudge-down'); }, 700);
        }
      }
      // ── Total P&L odometer — update on every NAV poll ────────────────────
      (function() {
        var _el  = document.getElementById('total-pnl-val');
        var _sub = document.getElementById('total-pnl-sub');
        if (!_el) return;
        var _prev = parseFloat(_el.getAttribute('data-raw') || '0');
        if (Math.abs(_prev - pnl) < 0.01) return; // no change
        _el.setAttribute('data-raw', pnl);
        var _col = pnl >= 0 ? '#00ff9d' : '#ff3366';
        _el.style.color = _col;
        if (_sub) _sub.style.color = _col;
        var _t0 = performance.now(), _dur = 500, _from = _prev;
        function _roll(now) {
          var p = Math.min(1, (now - _t0) / _dur);
          var v = _from + (pnl - _from) * (1 - Math.pow(1-p, 3));
          var s = v >= 0 ? '+' : '−';
          _el.textContent = s + '$' + Math.abs(Math.round(v)).toLocaleString('en-US');
          if (_sub) {
            var pct = (v / 100000) * 100;
            _sub.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '% since $100K start';
          }
          if (p < 1) requestAnimationFrame(_roll);
        }
        requestAnimationFrame(_roll);
      })();

      // ── Recovery meter / profit display ──────────────────────────────────
      var subRoot = document.getElementById('pnl-sub-root');
      if (subRoot) {
        if (pnl < 0) {
          var deficit = Math.abs(Math.round(pnl));
          // Track worst deficit for bar scale
          if (!window._worstDeficit || deficit > window._worstDeficit) {
            window._worstDeficit = deficit;
          }
          // Compute recovery rate from nav history
          var ratePerMin = null;
          if (window._navHistory && window._navHistory.length >= 2) {
            var nh = window._navHistory;
            var newest = nh[0], oldest = nh[nh.length - 1];
            var dMin = (newest.ts - oldest.ts) / 60000;
            if (dMin > 0.5) ratePerMin = (newest.nav - oldest.nav) / dMin;
          }
          var barPct = window._worstDeficit > 0
            ? Math.max(0, Math.round((1 - deficit / window._worstDeficit) * 100))
            : 0;
          var rateHtml = '—';
          var etaHtml  = '—';
          if (ratePerMin !== null && ratePerMin > 0) {
            var rateHr = Math.round(ratePerMin * 60);
            rateHtml = '+$' + rateHr.toLocaleString('en-US') + '/hr';
            var etaMin = Math.round(deficit / ratePerMin);
            etaHtml = etaMin < 60 ? etaMin + 'min' : Math.round(etaMin/60) + 'h';
          }
          subRoot.innerHTML =
            '<div id="rc-widget">' +
            '<div id="rc-top">' +
            '<span id="rc-label">DEFICIT</span>' +
            '<span id="rc-amount">-$' + deficit.toLocaleString('en-US') + '</span>' +
            '</div>' +
            '<div id="rc-bar-bg"><div id="rc-bar" style="width:' + barPct + '%"></div></div>' +
            '<div id="rc-stats">' +
            '<span id="rc-rate">' + rateHtml + '</span>' +
            '<span id="rc-eta">eta: ' + etaHtml + '</span>' +
            '</div></div>';
        } else {
          window._worstDeficit = 0;
          subRoot.innerHTML = '<span style="font-size:8.5px;color:#00ff9d">' + ret + ' since $100K start</span>';
        }
      }

      // Projected annual return (rolling pace from portValues)
      var proj = document.getElementById('nv-proj');
      if (proj && portValues.length >= 2) {
        var n = Math.min(portValues.length, 30);
        var vS = portValues[portValues.length - n], vE = nav;
        var dS = new Date(portDates[portDates.length - n] + 'T00:00:00Z');
        var days = Math.max(1, (Date.now() - dS) / 86400000);
        var dailyR = Math.pow(vE / vS, 1/days) - 1;
        var dec31 = new Date(new Date().getFullYear(), 11, 31);
        var dLeft = Math.max(0, (dec31 - Date.now()) / 86400000);
        var eoy = vE * Math.pow(1 + dailyR, dLeft);
        var gain = eoy - 100000;
        var gainSign = gain >= 0 ? '+' : '-';
        proj.textContent = 'pace: ' + gainSign + '$' + Math.round(Math.abs(gain)).toLocaleString('en-US') + ' by Dec 31';
        proj.style.color = gain >= 0 ? '#00ff9d' : '#ff3366';
      }

      // legend-strip PORTFOLIO
      var legVals = document.querySelectorAll('.leg-val');
      var legRets = document.querySelectorAll('.leg-ret');
      if (legVals[0]) legVals[0].textContent = _fmt(nav);
      if (legRets[0]) { legRets[0].textContent = ret; legRets[0].style.color = col; }

      // Push to _navHistory and redraw cleanly — no extendTraces, no type mixing
      var isoTs = ts || new Date().toISOString();
      window._lastKnownTs = isoTs;
      if (!window._navHistory) window._navHistory = [];
      // Deduplicate: don't push same timestamp twice
      var _last = window._navHistory[window._navHistory.length - 1];
      if (!_last || _last.x !== isoTs) {
        window._navHistory.push({ x: isoTs, y: nav });
      } else {
        _last.y = nav; // update in place if same tick
      }
      // Trim to 30 min — matches the visible window, prevents ancient points making laser beams
      var _cutoff = new Date(Date.now() - 30 * 60 * 1000).toISOString();
      while (window._navHistory.length > 0 && window._navHistory[0].x < _cutoff) {
        window._navHistory.shift();
      }
      if (window._drawNavCanvas) window._drawNavCanvas();
      _updateEndpointDot(nav, isoTs);
      _updateAthShape(nav, isoTs);
    }

    // Redraw portfolio trace (index 6) from nav_snapshots DB data + live point.
    // No axis relayout — chart stays wherever the user left it.
    var _navTraceInited = false;
    function _redrawNavTraces() {
      var _gd = document.getElementById('chart');
      // Retry until Plotly is ready — don't bail out permanently
      if (!_gd || !_gd.data) { setTimeout(_redrawNavTraces, 400); return; }
      var dbPts = window._navDbPts || [];
      var _xs = dbPts.map(function(p) { return p.t; });
      var _ys = dbPts.map(function(p) { return p.v; });
      if (window._lastKnownNav && window._lastKnownTs) {
        _xs.push(window._lastKnownTs);
        _ys.push(window._lastKnownNav);
      }
      if (!_xs.length) return;
      // Find the portfolio trace by name rather than hardcoded index
      var traceIdx = 6;
      for (var _ti = 0; _ti < _gd.data.length; _ti++) {
        if (_gd.data[_ti].name === 'PORTFOLIO') { traceIdx = _ti; break; }
      }
      // restyle returns a Promise — chain relayout so axes fit AFTER data lands
      Plotly.restyle(_gd, { x: [_xs], y: [_ys] }, [traceIdx]).then(function() {
        if (!_navTraceInited) {
          _navTraceInited = true;
          Plotly.relayout(_gd, { 'xaxis.autorange': true, 'yaxis.autorange': true });
        }
      });
    }
    window._redrawNavTraces = _redrawNavTraces;
    _redrawNavTraces();
    setInterval(_redrawNavTraces, 5000);

    function _pollNav() {
      var url = SUPA_URL + '/rest/v1/portfolio_snapshots'
        + '?select=total_value,recorded_at,strategy'
        + '&strategy=eq.crypto_momentum'
        + '&order=recorded_at.desc&limit=1';
      fetch(url, {
        headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }
      })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        var row = rows[0];
        if (row.recorded_at === _lastNavTs) return; // no change
        _lastNavTs = row.recorded_at;
        // Don't overwrite live crypto price feed with a stale DB snapshot
        if (window._lastLivePriceMs && (Date.now() - window._lastLivePriceMs) < 10000) return;
        _updateNavDisplays(row.total_value, row.recorded_at);
      })
      .catch(function() {});
    }

    // Seed _navHistory: once the first NAV is known, push a synthetic baseline point
    // at the left edge of the 20-min window so the line appears immediately.
    // crypto_momentum has no portfolio_snapshots rows, so we don't query that table.
    window._navHistory = [];
    window._navBaselineSeeded = false;
    window._seedNavBaseline = function(nav) {
      if (window._navBaselineSeeded || !nav) return;
      window._navBaselineSeeded = true;
      // Plant baseline 19.5 minutes back — maps to x ≈ 1.25% from left edge
      var baselineTs = new Date(Date.now() - 19.5*60*1000).toISOString();
      window._navHistory.push({ x: baselineTs, y: nav });
      if (window._drawNavCanvas) window._drawNavCanvas();
    };

    setTimeout(function() {
      _pollNav();
      setInterval(_pollNav, 5000);
    }, 4000);

    // Heartbeat: stamp current NAV every 5s — fires immediately after first pollNav
    function _navHeartbeat() {
      var nav = window._lastKnownNav;
      if (!nav) return;
      if (!window._navHistory) window._navHistory = [];
      var isoNow = new Date().toISOString();
      var last = window._navHistory[window._navHistory.length - 1];
      if (last && (new Date(isoNow) - new Date(last.x)) < 4000) return; // dedup <4s
      window._navHistory.push({ x: isoNow, y: nav });
      var cutoff = new Date(Date.now() - 60*1000).toISOString();
      while (window._navHistory.length > 0 && window._navHistory[0].x < cutoff) window._navHistory.shift();
      if (window._drawNavCanvas) window._drawNavCanvas();
    }
    window._navHeartbeat = _navHeartbeat;
    // Fire first heartbeat quickly so baseline seeds as soon as nav is known
    setTimeout(function() { _navHeartbeat(); setInterval(_navHeartbeat, 5000); }, 1500);

    // ── Live positions poller — DOM-diffing with enter/exit animations ───────
    var _TICKER_COLS = ['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
    function _symCol(sym) {
      var s = sym.replace('/USD','').replace('USD','');
      if (window._TICKER_OVR && window._TICKER_OVR[s]) return window._TICKER_OVR[s];
      var h = 0;
      for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffff;
      return _TICKER_COLS[h % _TICKER_COLS.length];
    }

    var _cryptoCardEls = {}; // symbol → DOM element
    window._cryptoPositionsMap = {}; // exposed for dynamic queue
    window._cryptoPairCount    = 15;

    // Scan sweep + popup — expose globally so feed poller can call it
    window._triggerScan = function(symbols) {
      // symbols: optional array e.g. ['ETH/USD','SOL/USD',...]
      // Panel-level sweep — the whole positions panel gets a scan beam
      var panel = document.getElementById('pos-panel');
      if (panel) {
        panel.classList.remove('panel-scanning');
        void panel.offsetWidth;
        panel.classList.add('panel-scanning');
        setTimeout(function() { panel.classList.remove('panel-scanning'); }, 1000);
      }
      // Canvas tiles have built-in scanline effect; legacy DOM equity cards also swept
      Object.values(_equityCardEls).forEach(function(el, i) {
        setTimeout(function() {
          el.classList.remove('pos-card-scanning');
          void el.offsetWidth;
          el.classList.add('pos-card-scanning');
          setTimeout(function() { el.classList.remove('pos-card-scanning'); }, 800);
        }, i * 90);
      });

    };

    // ── Video-game card exit ────────────────────────────────────────────────────
    // ── Arcade exit: 3-phase sequence ─────────────────────────────────────────
    // Phase 1 (0–320ms):  Target-lock overlay appears on tile
    // Phase 2 (320–580ms): Hit-flash damage blinks (3 pulses)
    // Phase 3 (580–):     Tile crushes to scanline + P&L ghost spawns left of column
    function _spawnParticles(cx, cy, col) {
      var N = 10;  // reduced for perf; 8-bit pixel burst feel
      for (var i = 0; i < N; i++) {
        var angle = (Math.PI * 2 / N) * i;
        var dist  = 24 + Math.floor(Math.random() * 4) * 12;  // quantized distances
        var size  = 2 + (Math.random() > .5 ? 2 : 0);  // 2px or 4px — 8-bit pixels
        var dur   = (.28 + Math.floor(Math.random() * 3) * .08).toFixed(2) + 's';
        var p = document.createElement('div');
        p.className = 'pnl-particle';
        p.style.cssText = [
          'width:' + size + 'px', 'height:' + size + 'px',
          'background:' + col,  // no box-shadow for perf
          'left:' + (cx - size/2) + 'px', 'top:' + (cy - size/2) + 'px',
          '--px:' + Math.round(Math.cos(angle) * dist) + 'px',
          '--py:' + Math.round(Math.sin(angle) * dist) + 'px',
          '--dur:' + dur, 'opacity:1'
        ].join(';');
        document.body.appendChild(p);
        setTimeout(function(pp) { if (pp.parentNode) pp.parentNode.removeChild(pp); }, 700, p);
      }
    }

    function _spawnPnlGhost(r, pnl, sym, exitPrice) {
      var hasPnl = (pnl !== null && pnl !== undefined);
      var isWin  = hasPnl ? pnl >= 0 : true;
      var col    = isWin ? '#00ff9d' : '#ff3366';

      // Position: to the LEFT of the tile column, vertically centered on the card
      var ghostW = 88;
      var gx = r.left - ghostW - 10;
      var gy = r.top + r.height / 2 - 30;

      var g = document.createElement('div');
      g.className = 'pnl-ghost';
      g.style.color = col;
      g.style.left  = gx + 'px';
      g.style.top   = gy + 'px';
      g.style.width = ghostW + 'px';

      var valEl = document.createElement('div');
      valEl.className = 'pg-val';
      if (hasPnl) {
        var absPnl = Math.abs(pnl);
        valEl.textContent = absPnl >= 1000
          ? (pnl >= 0 ? '+' : '-') + '$' + (absPnl / 1000).toFixed(1) + 'K'
          : (pnl >= 0 ? '+' : '-') + '$' + absPnl.toFixed(2);
      } else {
        valEl.textContent = 'CLOSED';
      }
      g.appendChild(valEl);
      if (exitPrice) {
        var priceEl = document.createElement('div');
        priceEl.className = 'pg-price';
        var ep = parseFloat(exitPrice.toString().replace(/,/g,''));
        priceEl.textContent = '@ $' + (ep > 1 ? ep.toLocaleString('en-US',{maximumFractionDigits:2}) : ep.toFixed(4));
        g.appendChild(priceEl);
      }
      document.body.appendChild(g);
      setTimeout(function() { if (g.parentNode) g.parentNode.removeChild(g); }, 2800);
    }

    // ── Equity positions map — server-rendered, for satellite orbs ──────────────
    window._equityPositionsMap = window._TND.EQ_POS;
    // ── Equity card map — built from SSR DOM on load ────────────────────────────
    var _equityCardEls = {};
    function _buildEquityMap() {
      document.querySelectorAll('#pos-equity-section .pos-card[data-sym]').forEach(function(el) {
        _equityCardEls[el.getAttribute('data-sym')] = el;
      });
    }
    setTimeout(_buildEquityMap, 500);

    // ── Batch ghost collapse — debounced, all exits finish before any reflow ──
    var _ghostsToCollapse = [];
    var _ghostCollapseTimer = null;
    function _queueGhostCollapse(ghost) {
      _ghostsToCollapse.push(ghost);
      clearTimeout(_ghostCollapseTimer);
      // 1.8s after the LAST exit trigger before any tile reflows
      // 3.2s after LAST exit: covers 2.7s P&L linger + 0.5s arcade exit animation
      _ghostCollapseTimer = setTimeout(function() {
        var batch = _ghostsToCollapse.splice(0);

        // Step 1: glitch-snap any legacy DOM equity tiles (canvas tiles self-reflow)
        var liveTiles = document.querySelectorAll('#pos-equity-section .pos-card');
        liveTiles.forEach(function(card) {
          card.classList.remove('pos-card-shuffle-land');
          void card.offsetWidth;  // force reflow so animation restarts
          card.classList.add('pos-card-shuffle-land');
          setTimeout(function() { card.classList.remove('pos-card-shuffle-land'); }, 250);
        });

        // Step 2: collapse all ghosts simultaneously in quantized steps
        batch.forEach(function(g) {
          if (!g.parentNode) return;
          var h = g.getBoundingClientRect().height;
          g.style.height = h + 'px';
          requestAnimationFrame(function() {
            g.classList.add('pos-card-ghost-collapsing');
          });
        });

        // Step 3: remove ghost DOM nodes after collapse finishes (7 steps × ~46ms = ~320ms)
        setTimeout(function() {
          batch.forEach(function(g) { if (g.parentNode) g.parentNode.removeChild(g); });
          _updateOverlayWidth();
        }, 360);
      }, 3200);
    }

    window._triggerCardExit = function(fullSym, reason, pnl, exitPrice) {
      // All tiles are now on the canvas engine
      var sym1 = fullSym;
      var sym2 = fullSym + '/USD';
      if ((window._etBySym||{})[sym1]) { window._etExit(sym1, pnl, exitPrice); return; }
      if ((window._etBySym||{})[sym2]) { window._etExit(sym2, pnl, exitPrice); return; }

      // Fallback: legacy DOM path (should not be reached)
      var el = _cryptoCardEls[fullSym] || _cryptoCardEls[fullSym + '/USD'];
      if (!el) return;
      if (_cryptoCardEls[fullSym]) delete _cryptoCardEls[fullSym];
      else if (_cryptoCardEls[fullSym + '/USD']) delete _cryptoCardEls[fullSym + '/USD'];
      var _exitSym = _cryptoCardEls[fullSym + '/USD'] ? fullSym + '/USD' : fullSym;
      if (_satAngles[_exitSym] !== undefined) {
        _satExiting[_exitSym] = {
          angle: _satAngles[_exitSym], orbitR: 32, age: 0,
          sr: pnl >= 0 ? 0 : 255, sg: pnl >= 0 ? 255 : 51, sb: pnl >= 0 ? 157 : 102
        };
        delete _satAngles[_exitSym];
        delete (window._equityPositionsMap || {})[_exitSym];
      }
      el.classList.remove('pos-card-active');
      var col = (pnl !== null && pnl !== undefined) ? (pnl >= 0 ? '#00ff9d' : '#ff3366') : '#fff';

      // ── Snapshot position, swap with ghost placeholder ─────────────────
      var r = el.getBoundingClientRect();
      var ghost = document.createElement('div');
      ghost.className = 'pos-card-ghost-space';
      ghost.style.height = r.height + 'px';
      // In-place P&L result: revealed after destroy animation fires
      var _symClean = fullSym ? fullSym.replace('/USD','').replace('USD','') : '';
      if (pnl !== null && pnl !== undefined) {
        var _absPnl = Math.abs(pnl);
        var _sign = pnl >= 0 ? '+' : '−';
        var _pnlStr = _sign + '$' + (_absPnl >= 1000 ? (_absPnl/1000).toFixed(1)+'k' : _absPnl.toFixed(2));
        ghost.innerHTML = '<span class="gc-sym">' + _symClean + '</span>'
          + '<span class="gc-pnl" style="color:' + col + '">' + _pnlStr + '</span>';
      }
      if (el.parentNode) el.parentNode.insertBefore(ghost, el);

      // Detach card and re-pin at exact viewport position — unrestricted by pos-left overflow
      if (el.parentNode) el.parentNode.removeChild(el);
      el.style.cssText += [
        ';position:fixed',
        'top:' + r.top + 'px',
        'left:' + r.left + 'px',
        'width:' + r.width + 'px',
        'height:' + r.height + 'px',
        'z-index:9990',
        'margin:0',
        'box-sizing:border-box',
        'overflow:visible',
        // Restore visual appearance lost when leaving #pos-left scope
        'background:rgba(0,0,10,.92)',
        'border:1px solid rgba(255,255,255,.07)'
      ].join(';');
      document.body.appendChild(el);

      // ── Phase 1: Canvas bitcrusher (0–500ms) ─────────────────────────────
      var bc = document.createElement('canvas');
      bc.width  = Math.round(r.width);
      bc.height = Math.round(r.height);
      bc.style.cssText = 'position:fixed;top:' + r.top + 'px;left:' + r.left + 'px;'
        + 'width:' + r.width + 'px;height:' + r.height + 'px;z-index:9991;pointer-events:none;';
      document.body.appendChild(bc);
      var bCtx = bc.getContext('2d');
      // Snapshot the card into the canvas
      var crushStart = performance.now();
      var crushDur = 500;
      (function _crushFrame(now) {
        var age = now - crushStart;
        if (age >= crushDur) {
          if (bc.parentNode) bc.parentNode.removeChild(bc);
          if (el.parentNode) el.parentNode.removeChild(el);
          ghost.classList.add('ghost-pnl-showing');
          ghost.style.opacity = '1';
          return;
        }
        var crushT = age / crushDur;
        var bSz = Math.max(2, Math.round(2 + crushT * crushT * 12));
        // On first frame, snapshot el appearance via fillRect mimic
        bCtx.clearRect(0, 0, bc.width, bc.height);
        // Draw tile background
        bCtx.fillStyle = 'rgba(0,0,8,0.92)';
        bCtx.fillRect(0, 0, bc.width, bc.height);
        // Left accent stripe
        bCtx.fillStyle = col;
        bCtx.fillRect(0, 0, 3, bc.height);
        // Eat blocks
        for (var by = 0; by < bc.height; by += bSz) {
          for (var bx = 0; bx < bc.width; bx += bSz) {
            if (Math.random() < crushT * 1.5) bCtx.clearRect(bx, by, bSz, bSz);
          }
        }
        requestAnimationFrame(_crushFrame);
      })(crushStart);
      el.style.opacity = '0'; // hide original immediately; canvas takes over

      // ── Phase 2: Ghost P&L sticks for 2.5s, then arcade-glitch out ────
      setTimeout(function() {
        ghost.classList.add('ghost-pnl-exiting');
      }, 3200);

      // Queue ghost placeholder for batch collapse after exit animation (~400ms after phase 3)
      _queueGhostCollapse(ghost);
    };

    var _CARD_W = 148; // crypto column width
    var _EQ_W   = 130; // equity column width
    var _EQ_H   = 58;  // tile height px — content ends at y+49 (VU bar), 9px margin

    // ═══════════════════════════════════════════════════════════════════════════
    // CANVAS EQUITY TILE ENGINE
    // All equity holdings rendered on a single canvas — zero DOM, zero layout cost.
    // _ET[] is the single source of truth; draw loop paints it 30fps.
    // ═══════════════════════════════════════════════════════════════════════════
    window._ET = [];          // tile state objects — on window so all scripts share reference
    window._etBySym = {};   // sym → tile for O(1) lookup
    var _ET     = window._ET;
    var _etBySym = window._etBySym;

    var _HEADING_H = 16; // px reserved at top of canvas for strategy group labels

    function _etLayout() {
      var stratBar = document.getElementById('strat-bar');
      var sbH = stratBar ? stratBar.offsetHeight : 46;
      var availH = Math.floor((window.innerHeight - sbH - 4 - _HEADING_H) * 0.67);
      // Cache key: tile count + active tile ids+phases + window height
      var _lk = _ET.length + '|' + window.innerHeight + '|' +
        _ET.map(function(t){return t.sym+t.phase;}).join(',');
      if (_etCachedLayout && _lk === _etLayoutKey) return _etCachedLayout;
      _etLayoutKey = _lk;
      var perCol = Math.max(1, Math.floor(availH / _EQ_H));
      // Stable sort: within each group, sort by enteredAt so positions don't
      // shuffle when tiles enter/exit (newest at top, oldest at bottom)
      var crypto = _ET.filter(function(t) { return t.phase !== 'done' && t.isCrypto; })
                      .sort(function(a,b) { return (b.enteredAt||0) - (a.enteredAt||0); });
      var equity = _ET.filter(function(t) { return t.phase !== 'done' && !t.isCrypto; })
                      .sort(function(a,b) { return (b.enteredAt||0) - (a.enteredAt||0); });
      var cryptoCols = Math.max(1, Math.ceil(crypto.length / perCol));
      var equityCols = equity.length > 0 ? Math.max(1, Math.ceil(equity.length / perCol)) : 0;
      var totalCols  = cryptoCols + equityCols;
      _etCachedLayout = { perCol: perCol, totalCols: totalCols, cryptoCols: cryptoCols, equityCols: equityCols,
                crypto: crypto, equity: equity, availH: availH,
                live: crypto.concat(equity) };
      return _etCachedLayout;
    }

    function _etTilePos(t, layout) {
      // Equity (NYSE): rightmost columns (col 0 = far right)
      // Crypto: columns just left of equity (separated by 2px gap)
      if (!t.isCrypto) {
        var ei  = layout.equity.indexOf(t);
        var col = Math.floor(ei / layout.perCol);
        var row = ei % layout.perCol;
        var x   = (layout.totalCols - 1 - col) * _EQ_W;
        return { x: x, y: row * _EQ_H };
      } else {
        var ci   = layout.crypto.indexOf(t);
        var col2 = Math.floor(ci / layout.perCol);
        var row2 = ci % layout.perCol;
        // Crypto columns sit to the LEFT of equity columns
        var x2   = (layout.cryptoCols - 1 - col2) * _EQ_W;
        return { x: x2, y: row2 * _EQ_H };
      }
    }

    var _etCanvas = null, _etCtx = null;
    var _etLastTileCount = -1; // tracks tile count for overlay-width dirty check
    var _etLastDraw = 0, _etDirty = true;
    var _etCachedLayout = null, _etLayoutKey = '';
    var _etScanT = 0;  // scanline phase

    function _etInitCanvas() {
      _etCanvas = document.getElementById('eq-tiles-canvas');
      if (!_etCanvas) return;
      _etCtx = _etCanvas.getContext('2d');
      _etCanvas.style.position = 'relative';
      _etCanvas.style.zIndex = '2';
    }

    var _etDpr = window.devicePixelRatio || 1;
    function _etResize() {
      if (!_etCanvas) return;
      var layout = _etLayout();
      var cw = _EQ_W * layout.totalCols;
      var ch = layout.availH;
      var pw = Math.round(cw * _etDpr);
      var ph = Math.round(ch * _etDpr);
      if (_etCanvas.width !== pw || _etCanvas.height !== ph) {
        _etCanvas.width  = pw;
        _etCanvas.height = ph;
        _etCanvas.style.width  = cw + 'px';
        _etCanvas.style.height = ch + 'px';
        _etCtx.setTransform(_etDpr, 0, 0, _etDpr, 0, 0);
        _etDirty = true;
      }
    }

    function _etDraw(ts) {
      if (!_etCtx || !_etCanvas) return;
      _etScanT = ts;

      var layout = _etLayout();
      _etResize();
      var ctx = _etCtx;
      ctx.clearRect(0, 0, _etCanvas.width, _etCanvas.height);

      var now = Date.now();
      var lerpK = 0.03; // lerp speed per frame (~30fps → ~10s to converge; slow = more cinematic)

      // Render order: ghosts first so entering/live tiles paint on top of them
      var _allTiles = layout.crypto.concat(layout.equity);
      var allLive = _allTiles.filter(function(t) { return t.phase === 'bit-crush'; })
                   .concat(_allTiles.filter(function(t) { return t.phase !== 'bit-crush'; }));
      for (var i = 0; i < allLive.length; i++) {
        var t = allLive[i];
        var pos = _etTilePos(t, layout);
        var x = pos.x, y = pos.y;
        var age = now - t.phaseStart;

        // Lerp display values toward actual values (smooths batch-update flashes)
        if (t._dVal   === undefined) t._dVal   = t.val;
        if (t._dPnl   === undefined) t._dPnl   = t.pnl;
        if (t._dPnlPct=== undefined) t._dPnlPct= t.pnlPct;
        t._dVal    += (t.val    - t._dVal)    * lerpK;
        t._dPnl    += (t.pnl   - t._dPnl)    * lerpK;
        t._dPnlPct += (t.pnlPct- t._dPnlPct) * lerpK;

        if (t.phase === 'entering') {
          // 8-bit fly-in from canvas center (120ms) + corner sparks (80ms)
          var _flyDur = 120, _sparkDur = 80;
          if (age < _flyDur) {
            // Cubic-out ease so it snaps in fast then sticks the landing
            var _flyT = age / _flyDur;
            var _flyE = 1 - Math.pow(1 - _flyT, 3);
            // Origin: canvas center minus half tile size
            var _ox = Math.round((_etCanvas.width  * 0.5 - _EQ_W * 0.5) / 8) * 8;
            var _oy = Math.round((_etCanvas.height * 0.5 - _EQ_H * 0.5) / 8) * 8;
            // Quantize current position to 4px grid for 8-bit chunky feel
            var _fx = Math.round((_ox + (x - _ox) * _flyE) / 4) * 4;
            var _fy = Math.round((_oy + (y - _oy) * _flyE) / 4) * 4;
            // Scale from 0.35 at origin to 1.0 at target
            var _fsc = 0.35 + _flyE * 0.65;
            ctx.save();
            ctx.translate(_fx + _EQ_W * 0.5, _fy + _EQ_H * 0.5);
            ctx.scale(_fsc, _fsc);
            ctx.translate(-_EQ_W * 0.5, -_EQ_H * 0.5);
            _etPaintTile(ctx, t, 0, 0, ts);
            ctx.restore();
          } else {
            // Tile landed — white corner sparks fade over 80ms
            _etPaintTile(ctx, t, x, y, ts);
            var sparkA = Math.max(0, 1 - (age - _flyDur) / _sparkDur);
            if (sparkA > 0) {
              ctx.fillStyle = 'rgba(255,255,255,' + sparkA + ')';
              var sp = Math.round(6 * sparkA);
              ctx.fillRect(x,         y,         2, sp); ctx.fillRect(x,         y,         sp, 2);
              ctx.fillRect(x+_EQ_W-2, y,         2, sp); ctx.fillRect(x+_EQ_W-sp,y,         sp, 2);
              ctx.fillRect(x,         y+_EQ_H-sp,2, sp); ctx.fillRect(x,         y+_EQ_H-2, sp, 2);
              ctx.fillRect(x+_EQ_W-2, y+_EQ_H-sp,2, sp); ctx.fillRect(x+_EQ_W-sp,y+_EQ_H-2,sp, 2);
            }
          }
          if (age > _flyDur + _sparkDur) { t.phase = 'live'; }

        } else if (t.phase === 'live') {
          _etPaintTile(ctx, t, x, y, ts);

        } else if (t.phase === 'bit-crush') {
          // Phase 1 (0–500ms): pixel decay → clearRect blocks eat tile to transparent
          // Phase 2 (500–2300ms): P&L ghost in Press Start 2P lingers in cleared space
          var crushDur = 500, ghostDur = 2800;
          if (age < crushDur) {
            var crushT = age / crushDur; // 0→1
            _etPaintTile(ctx, t, x, y, ts);
            // Quantize: block size grows from 2px → 14px
            var bSz = Math.max(2, Math.round(2 + crushT * crushT * 12));
            for (var by = 0; by < _EQ_H; by += bSz) {
              for (var bx2 = 0; bx2 < _EQ_W; bx2 += bSz) {
                if (Math.random() < crushT * 1.5) {
                  ctx.clearRect(x + bx2, y + by, bSz, bSz);
                }
              }
            }
          } else {
            // Tile space cleared — ghost: sym name + P&L in Press Start 2P
            var ghostT = Math.min(1, (age - crushDur) / ghostDur);
            // Fast in (3%), short hold (until 25%), long fade to true zero (25%→100%)
            var ghostA = ghostT < 0.03 ? ghostT / 0.03
                       : ghostT < 0.25 ? 1
                       : Math.max(0, 1 - (ghostT - 0.25) / 0.75);
            if (ghostA > 0.01) {
              var ec = t.exitPnl >= 0 ? '#00ff9d' : '#ff3366';
              var ep = Math.abs(t.exitPnl);
              var es = (t.exitPnl >= 0 ? '+$' : '-$') + (ep >= 1000 ? (ep/1000).toFixed(1)+'k' : ep.toFixed(2));
              var cx2 = x + _EQ_W/2, cy2 = y + _EQ_H/2;
              ctx.save();
              ctx.globalAlpha = ghostA;
              // Ticker name above
              ctx.shadowColor = 'rgba(255,255,255,0.4)'; ctx.shadowBlur = 6;
              ctx.fillStyle = 'rgba(255,255,255,0.7)';
              ctx.font = '7px Consolas,monospace';
              ctx.textAlign = 'center';
              ctx.fillText(t.sym, cx2, cy2 - 8);
              // P&L value
              ctx.shadowColor = ec; ctx.shadowBlur = 16;
              ctx.fillStyle = ec;
              ctx.font = '8px "Press Start 2P",monospace';
              ctx.fillText(es, cx2, cy2 + 6);
              ctx.textAlign = 'left';
              ctx.restore();
            }
            if (ghostT >= 1) { t.phase = 'done'; _etDirty = true; }
          }
        }
        // 'done' tiles excluded by live filter
      }

      // Draw equity/crypto separator if both types present
      if (layout.equityCols > 0 && layout.cryptoCols > 0) {
        var sepX = layout.equityCols * _EQ_W;
        ctx.fillStyle = 'rgba(255,255,255,0.06)';
        ctx.fillRect(sepX, 0, 2, layout.availH);
      }

      // Only update overlay width when tile count changes — not every frame
      var _nowCount = _ET.filter(function(t){return t.phase!=='done';}).length;
      if (_nowCount !== _etLastTileCount) {
        _etLastTileCount = _nowCount;
        _updateOverlayWidth();
      }
    }

    // Strategy badge map — glyph + glow color per strategy key
    var _TILE_BADGES = {
      'momentum':   { g:'▲▲', c:'#00e5ff' },
      'crypto':     { g:'◈',  c:'#e040fb' },
      'user':       { g:'◎',  c:'#00ff9d' },
      'daytrader':  { g:'⊕',  c:'#b2ff59' },
      'reversion':  { g:'⇌',  c:'#ff9900' },
      'sentiment':  { g:'◉',  c:'#ff4081' },
      'volatility': { g:'⚡', c:'#ff6b35' },
      'factor':     { g:'✦',  c:'#ffd740' },
      'macro':      { g:'≋',  c:'#00bcd4' },
      'ensemble':   { g:'❋',  c:'#ffffff' },
    };

    var _SCRAMBLE_CHARS = '0123456789';
    function _scrambleDigits(str) {
      var out = '';
      for (var si = 0; si < str.length; si++) {
        var c = str[si];
        out += (c >= '0' && c <= '9') ? _SCRAMBLE_CHARS[Math.floor(Math.random()*10)] : c;
      }
      return out;
    }

    function _etPaintTile(ctx, t, x, y, ts) {
      var W = _EQ_W, H = _EQ_H;
      var now = Date.now(); // epoch ms — use for hold timer, NOT rAF ts

      // Hard-reset shadow so exit-ghost glow doesn't leak into live tile text
      ctx.shadowBlur = 0; ctx.shadowColor = 'transparent';

      // Background — transparent
      // Left accent stripe (2px)
      ctx.fillStyle = t.col;
      ctx.fillRect(x, y, 2, H);

      // Bottom separator
      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      ctx.fillRect(x, y + H - 1, W, 1);

      // ── Strategy badge — glowing glyph left of ticker ──
      var _badge = _TILE_BADGES[t.strategy || (t.isCrypto ? 'crypto' : 'momentum')];
      var _badgeOff = 0;
      if (_badge) {
        ctx.save();
        ctx.font = '7px Consolas,monospace';
        ctx.textAlign = 'left';
        ctx.fillStyle   = _badge.c;
        ctx.globalAlpha = 0.85;
        ctx.fillText(_badge.g, x + 4, y + 14);
        ctx.restore();
        _badgeOff = 14;
      }
      var lx = x + 4 + _badgeOff;

      // Lerped display values
      var dVal    = t._dVal    !== undefined ? t._dVal    : (t.val    || 0);
      var dPnl    = t._dPnl    !== undefined ? t._dPnl    : (t.pnl    || 0);
      var dPnlPct = t._dPnlPct !== undefined ? t._dPnlPct : (t.pnlPct || 0);
      if (Math.abs(dPnl)    < 0.005) dPnl    = 0;
      if (Math.abs(dPnlPct) < 0.005) dPnlPct = 0;

      var _F1 = '700 16px VT323,monospace'; // ticker sym (bold)
      var _FV = '400 16px VT323,monospace'; // right-side value (not bold)
      var _F2 = '400 14px VT323,monospace'; // entry, pnl, timer

      // ── ROW 1 left: SYM ──
      ctx.font = _F1;
      ctx.fillStyle = t.col;
      ctx.textAlign = 'left';
      ctx.fillText(t.sym, lx, y + 15);

      // ── ROW 1 right: value ──
      if (dVal > 0.5) {
        if (dPnl > 0.01)       t._valDir = 1;
        else if (dPnl < -0.01) t._valDir = -1;
        var dir = t._valDir || 0;
        var mag = Math.min(Math.abs(dPnlPct) / 5, 1);
        var valCol;
        if (dir > 0)      valCol = 'hsl(140,' + Math.round(mag*75) + '%,' + Math.round(88 - mag*38) + '%)';
        else if (dir < 0) valCol = 'hsl(350,' + Math.round(mag*75) + '%,' + Math.round(88 - mag*44) + '%)';
        else               valCol = '#ffffff';
        var flashAge = t._flashStart ? (ts - t._flashStart) : 9999;
        var isFlashing = flashAge < 180;
        var valStr = '$' + Math.round(dVal).toLocaleString('en-US');
        ctx.font = _FV;
        ctx.fillStyle = isFlashing ? (t._flashDir > 0 ? '#00ff9d' : '#ff3366') : valCol;
        ctx.textAlign = 'right';
        ctx.fillText(isFlashing ? _scrambleDigits(valStr) : valStr, x + W - 5, y + 15);
        ctx.textAlign = 'left';
        if (t._valFlash) { t._flashStart = ts; t._flashDir = t._valFlash; t._valFlash = 0; }
      }

      // ── ROW 2 left: entry price ──
      if (t.entry > 0) {
        var entryStr = '@$' + (t.entry < 1 ? t.entry.toFixed(4) : t.entry < 100 ? t.entry.toFixed(2) : Math.round(t.entry).toLocaleString('en-US'));
        ctx.font = _F2;
        ctx.fillStyle = t.col;
        ctx.fillText(entryStr, lx, y + 28);
      }

      // ── ROW 2 right: P&L with scale-pulse ──
      if (Math.abs(dPnl) >= 0.001) t._lastPnl = dPnl;
      var showPnl = t._lastPnl !== undefined ? t._lastPnl : dPnl;
      if (Math.abs(showPnl) >= 0.001) {
        var pSign = showPnl >= 0 ? '+' : '-';
        var absPnl = Math.abs(showPnl);
        var pnlDisp = pSign + '$' + (absPnl >= 1000 ? (absPnl/1000).toFixed(1)+'k' : absPnl.toFixed(2));
        var pnlFlashAge = t._flashStart ? (ts - t._flashStart) : 9999;
        var pScale = pnlFlashAge < 260 ? (1 + 0.15 * Math.max(0, 1 - pnlFlashAge/260)) : 1;
        ctx.save();
        if (pScale > 1) {
          ctx.translate(x + W - 5, y + 28);
          ctx.scale(pScale, pScale);
          ctx.translate(-(x + W - 5), -(y + 28));
        }
        ctx.font = _F2;
        ctx.fillStyle = showPnl >= 0 ? '#00c87a' : '#e03355';
        ctx.textAlign = 'right';
        ctx.fillText(pnlDisp, x + W - 5, y + 28);
        ctx.textAlign = 'left';
        ctx.restore();
      }

      // ── ROW 3: hold timer ──
      var holdMs = t.enteredAt ? Math.max(0, now - t.enteredAt) : (t.days||0) * 86400000;
      var holdStr;
      if (holdMs < 60000)         holdStr = Math.floor(holdMs/1000) + 's';
      else if (holdMs < 3600000)  holdStr = Math.floor(holdMs/60000) + 'm';
      else if (holdMs < 86400000) { var hH=Math.floor(holdMs/3600000),hM=Math.floor((holdMs%3600000)/60000); holdStr=hH+'h'+(hM?' '+hM+'m':''); }
      else                        { var hD=Math.floor(holdMs/86400000),hHr=Math.floor((holdMs%86400000)/3600000); holdStr=hD+'d'+(hHr?' '+hHr+'h':''); }
      ctx.font = _F2;
      ctx.fillStyle = 'rgba(255,255,255,0.45)';
      ctx.fillText(holdStr, lx, y + 41);

      // ── VU meter bar + peak hat (y+46) ──
      // Equity: rank-based (rank 1=strong hold→low, rank 5=weak hold→high, EXIT=full)
      // Crypto: P&L% based (loss=low, gain toward 3%=high)
      var vuLevel;
      if (!t.isCrypto) {
        // Equity — rank drives signal
        if (!t.inSignal && t.inSignal !== undefined) {
          vuLevel = 1.0;
        } else {
          var r = t.rank ? Math.min(t.rank, 5) : 3;
          vuLevel = 0.10 + (r / 5) * 0.72; // rank1→0.24, rank5→0.82
        }
        // ±5% P&L micro-oscillation
        vuLevel = Math.max(0, Math.min(vuLevel + dPnlPct / 100, 1));
      } else {
        // Crypto — stop→target proximity is the sell signal
        var cStop   = t.stop   || 0;
        var cTarget = t.target || 0;
        var cCur    = t.curPrice || t.entry || 0;
        if (cStop > 0 && cTarget > cStop && cCur > 0) {
          vuLevel = Math.max(0, Math.min((cCur - cStop) / (cTarget - cStop), 1));
        } else {
          // Fallback: start at 0, let P&L% drift provide life (no instant baseline)
          vuLevel = Math.max(0, Math.min(dPnlPct / 6, 1));
        }
      }

      // Display lerp — bar rises from 0 on spawn, never instantly full
      if (t._dVu === undefined) t._dVu = 0;
      t._dVu += (vuLevel - t._dVu) * 0.012; // ~8s to reach target at 30fps

      // Peak hold tracks _dVu so hat also builds slowly; decays very slowly
      if (t._vuPeak === undefined) { t._vuPeak = 0; t._vuPeakTs = ts; }
      if (t._dVu >= t._vuPeak) {
        t._vuPeak   = t._dVu;
        t._vuPeakTs = ts;
      } else {
        var holdDur = 2000; // 2s hold before decay
        var decayAge = ts - t._vuPeakTs - holdDur;
        if (decayAge > 0) {
          // very slow fall — ~0.003/s, ~5 min from 1.0 to 0
          t._vuPeak = Math.max(t._dVu, t._vuPeak - decayAge * 0.0001);
          t._vuPeakTs = ts - holdDur;
        }
      }

      var xpW = W - 10, xpH = 3, xpX = x + 5, xpY = y + 46;
      ctx.fillStyle = 'rgba(255,255,255,0.09)';
      ctx.fillRect(xpX, xpY, xpW, xpH);
      ctx.fillStyle = 'rgba(255,255,255,0.70)';
      ctx.fillRect(xpX, xpY, Math.round(xpW * t._dVu), xpH);
      var hatX = xpX + Math.round(xpW * t._vuPeak) - 2;
      if (hatX > xpX && hatX + 2 <= xpX + xpW) {
        ctx.fillStyle = 'rgba(255,255,255,0.95)';
        ctx.fillRect(hatX, xpY - 1, 2, xpH + 2);
      }
    }

    var _etInitPhase = true; // suppress entry sound for init seed tiles

    // Add or replace a tile (upsert)
    function _etUpsert(data) {
      var existing = _etBySym[data.sym];
      if (existing) {
        // Update live fields only
        existing.val      = data.val      || existing.val;
        existing.pnl      = data.pnl      !== undefined ? data.pnl : existing.pnl;
        existing.pnlPct   = data.pnlPct   !== undefined ? data.pnlPct : existing.pnlPct;
        existing.curPrice = data.curPrice  || existing.curPrice;
        existing.inSignal = data.inSignal  !== undefined ? data.inSignal : existing.inSignal;
        existing.rank     = data.rank      || existing.rank;
        existing.holdText = data.holdText  || existing.holdText;
        // Only accept an enteredAt that is *older* than what we already have —
        // prevents price-poller re-calls from stomping the real DB timestamp with Date.now()
        if (data.enteredAt && (!existing.enteredAt || data.enteredAt < existing.enteredAt)) {
          existing.enteredAt = data.enteredAt;
        }
        return existing;
      }
      var tile = {
        sym:       data.sym,
        col:       data.col || '#00e5ff',
        val:       data.val || 0,
        pnl:       data.pnl || 0,
        pnlPct:    data.pnlPct || 0,
        entry:     data.entry || 0,
        qty:       data.qty || 0,
        stop:      data.stop || 0,
        target:    data.target || 0,
        curPrice:  data.curPrice || data.entry || 0,
        days:      data.days || 0,
        inSignal:  data.inSignal !== undefined ? data.inSignal : true,
        rank:      data.rank || 0,
        holdText:  data.holdText || '',
        isCrypto:  data.isCrypto || false,
        strategy:  data.strategy || (data.isCrypto ? 'crypto' : 'momentum'),
        direction: data.direction || 'long',
        enteredAt: data.enteredAt || 0,
        exitPnl:   0,
        phase:     'entering',
        phaseStart: Date.now(),
        _valFlash: 0,
      };
      _ET.push(tile);
      _etBySym[data.sym] = tile;
      _etDirty = true;
      _updateOverlayWidth();
      // Sound fires when tile first appears — skip for page-init seed tiles
      if (!_etInitPhase && window._soundEntry) window._soundEntry();
      return tile;
    }
    window._etUpsert = _etUpsert;

    // Returns { strategy: count } for all live tiles (used by HUD dropdown)
    window._etStratCounts = function() {
      var counts = {};
      _ET.forEach(function(t) {
        if (t.phase === 'done') return;
        var s = t.strategy || (t.isCrypto ? 'crypto' : 'momentum');
        counts[s] = (counts[s] || 0) + 1;
      });
      return counts;
    };

    // Exit a tile (called by notification handler or poll)
    window._etExit = function(sym, pnl, exitPrice) {
      var t = _etBySym[sym];
      if (!t || t.phase === 'bit-crush' || t.phase === 'done') return;
      t.exitPnl = (pnl !== null && pnl !== undefined) ? pnl : t.pnl;
      // Sound fires when exit animation starts (on the tile, not the notification)
      if (t.exitPnl >= 0) { if (window._soundWin)  window._soundWin();  }
      else                 { if (window._soundLoss) window._soundLoss(); }
      t.phase = 'bit-crush';
      t.phaseStart = Date.now();
      _etDirty = true;
      // Satellite ejection still uses existing system
      var _exitSym = sym + '/USD';
      if (_satAngles[_exitSym] !== undefined) {
        var col = t.pnl >= 0 ? '#00ff9d' : '#ff3366';
        _satExiting[_exitSym] = { angle:_satAngles[_exitSym], orbitR:32, age:0,
          sr: t.pnl>=0?0:255, sg: t.pnl>=0?255:51, sb: t.pnl>=0?157:102 };
        delete _satAngles[_exitSym];
      }
      // Clean up after bit-crush completes (500ms decay + 2800ms ghost + margin)
      setTimeout(function() {
        delete _etBySym[sym];
        var _rmIdx = _ET.findIndex(function(tile) { return tile.sym === sym; });
        if (_rmIdx !== -1) _ET.splice(_rmIdx, 1);
        _updateOverlayWidth();
      }, 3500);
    };

    // Strategy heading data — glyph, color, label per key
    var _HDR_BADGES = {
      momentum:  { g:'▲▲', c:'#00e5ff', n:'MOMENTUM'  },
      crypto:    { g:'◈',  c:'#e040fb', n:'CRYPTO'    },
      user:      { g:'◎',  c:'#00ff9d', n:'MANUAL'    },
      daytrader: { g:'⊕',  c:'#b2ff59', n:'DAYTRADER' },
      reversion: { g:'⇌',  c:'#ff9900', n:'MEAN REV'  },
      sentiment: { g:'◉',  c:'#ff4081', n:'SENTIMENT' },
      volatility:{ g:'⚡', c:'#ff6b35', n:'VOLATILITY'},
      factor:    { g:'✦',  c:'#ffd740', n:'FACTOR'    },
      macro:     { g:'≋',  c:'#00bcd4', n:'MACRO'     },
      ensemble:  { g:'❋',  c:'#ffffff', n:'ENSEMBLE'  },
    };

    function _updateHeadings(layout) {
      var hdrEl = document.getElementById('tile-headings');
      if (!hdrEl) return;

      // Collect strategy groups: { key, xStart, width, count }
      var groups = [];
      // Crypto group (left side)
      if (layout.cryptoCols > 0 && layout.crypto.length > 0) {
        // Identify strategy of first crypto tile (all crypto = same strategy for now)
        var cKey = (layout.crypto[0] && layout.crypto[0].strategy) || 'crypto';
        groups.push({ key: cKey, x: 0, w: layout.cryptoCols * _EQ_W, n: layout.crypto.length });
      }
      // Equity group (right side)
      if (layout.equityCols > 0 && layout.equity.length > 0) {
        var eKey = (layout.equity[0] && layout.equity[0].strategy) || 'momentum';
        var eX = layout.cryptoCols * _EQ_W + (layout.cryptoCols > 0 && layout.equityCols > 0 ? 2 : 0);
        groups.push({ key: eKey, x: eX, w: layout.equityCols * _EQ_W, n: layout.equity.length });
      }

      // Rebuild heading elements
      hdrEl.innerHTML = '';
      groups.forEach(function(g) {
        var b = _HDR_BADGES[g.key] || { g: '◆', c: '#ffffff', n: g.key.toUpperCase() };
        var div = document.createElement('div');
        div.className = 'tile-group-hdr';
        div.style.left  = g.x + 'px';
        div.style.width = g.w + 'px';
        div.style.color = b.c;
        div.style.borderBottomColor = b.c.replace(')', ',.15)').replace('rgb','rgba');
        div.style.textShadow = '0 0 8px ' + b.c;
        div.innerHTML = '<span style="font-size:9px;filter:drop-shadow(0 0 4px '+b.c+')">'
          + b.g + '</span><span>' + b.n + '</span>'
          + '<span style="margin-left:auto;opacity:.45;letter-spacing:.05em">'
          + g.n + (g.n === 1 ? ' HOLDING' : ' HOLDINGS') + '</span>';
        hdrEl.appendChild(div);
      });
    }

    function _updateOverlayWidth() {
      var overlay = document.getElementById('pos-overlay');
      if (!overlay) return;
      // All tiles (crypto + equity) are on canvas — no separate left column
      var posLeft = document.getElementById('pos-left');
      if (posLeft) posLeft.style.width = '0';
      var layout = _etLayout();
      var eqW = layout.totalCols * _EQ_W;
      overlay.style.width = eqW + 'px';
      // Resize canvas
      if (_etCanvas) {
        _etCanvas.style.width  = eqW + 'px';
        _etCanvas.style.height = layout.availH + 'px';
      }
      // Reposition strategy group headings
      _updateHeadings(layout);
    }

    window._updateOverlayWidth = _updateOverlayWidth;

    // Seed tiles from Python init data (sounds suppressed during this phase)
    (function() {
      if (!window._eqCanvasInitData) return;
      _eqCanvasInitData.forEach(function(d) { _etUpsert(d); });
      _etInitPhase = false; // future tile inserts play entry sound
    })();

    // Wait for ALL fonts (including Orbitron) before starting the draw loop
    var _etRafLast = 0;
    function _etRafLoop(ts) {
      if (ts - _etRafLast >= 33) {
        _etRafLast = ts;
        if (!_etCanvas) _etInitCanvas();
        if (_etCanvas) _etDraw(ts);
      }
      requestAnimationFrame(_etRafLoop);
    }
    // Force Orbitron to actually render before the RAF loop draws tiles.
    // document.fonts.ready resolves even if the font failed to load;
    // document.fonts.load() triggers a real load, and the warm-up fillText
    // forces the browser to finish rasterizing the glyphs before first draw.
    Promise.all([
      document.fonts.load('700 16px VT323'),
      document.fonts.load('400 14px VT323')
    ]).then(function() {
      var _tmp = document.createElement('canvas');
      var _tc = _tmp.getContext('2d');
      _tc.font = '700 16px VT323';
      _tc.fillText('BTC', 0, 10);
      _tc.font = '400 14px VT323';
      _tc.fillText('BTC', 0, 10);
      requestAnimationFrame(_etRafLoop);
    });
    // ── Ticker popup ──────────────────────────────────────────────────────────
    (function() {
      var _popup = null;
      var _popupSym = null;

      function _openPopup(sym, anchorX, anchorY) {
        var clean = sym.replace('/USD','').replace('USD','');
        if (_popup && _popupSym === clean) { _closePopup(); return; }
        _closePopup();
        _popupSym = clean;

        var p = document.createElement('div');
        p.id = 'ticker-popup';
        p.style.cssText = [
          'position:fixed;z-index:9999',
          'background:rgba(8,0,18,0.97)',
          'border:1px solid ' + (_symCol(sym)),
          'border-radius:4px',
          'padding:12px 14px',
          'min-width:260px;max-width:320px',
          'font:400 13px VT323,monospace',
          'color:#e0d0ff',
          'box-shadow:0 0 24px rgba(0,0,0,0.8)',
        ].join(';');

        // Position near click, keep on screen
        var W = window.innerWidth, H = window.innerHeight;
        var px = Math.min(anchorX + 12, W - 340);
        var py = Math.min(anchorY + 12, H - 420);
        p.style.left = px + 'px'; p.style.top = py + 'px';

        var col = (window._TICKER_OVR && window._TICKER_OVR[clean]) || _symCol(sym);

        p.innerHTML = [
          '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">',
            '<span id="tp-sym-label" style="font:700 18px VT323,monospace;color:' + col + '">' + clean + '</span>',
            '<div style="display:flex;align-items:center;gap:8px">',
              '<label style="font-size:11px;color:#6a4a8a">COLOR</label>',
              '<input type="color" id="tp-colorpick" value="' + col + '" ',
                'style="width:28px;height:20px;border:none;background:none;cursor:pointer;padding:0">',
            '</div>',
            '<span id="tp-close" style="cursor:pointer;color:#6a4a8a;font-size:16px;padding:0 4px">✕</span>',
          '</div>',
          '<div style="border-top:1px solid rgba(255,255,255,0.07);padding-top:8px;font-size:12px;color:#5a3a7a;margin-bottom:6px">',
            'RECENT TRADES',
          '</div>',
          '<div id="tp-history" style="max-height:280px;overflow-y:auto;font:400 13px VT323,monospace">',
            '<div style="color:#3a1a5a">loading…</div>',
          '</div>',
        ].join('');

        document.body.appendChild(p);
        _popup = p;

        // Color picker — updates tiles, terminal feed spans, popup header, and saves to DB
        p.querySelector('#tp-colorpick').addEventListener('input', function(e) {
          var newCol = e.target.value;
          if (!window._TICKER_OVR) window._TICKER_OVR = {};
          window._TICKER_OVR[clean] = newCol;
          if (window._saveTickerColor) window._saveTickerColor(clean, newCol);
          // Canvas tiles
          (window._ET||[]).forEach(function(t) {
            if (t.sym.replace('/USD','').replace('USD','') === clean) t.col = newCol;
          });
          // All terminal feed spans with matching data-sym
          document.querySelectorAll('[data-sym]').forEach(function(s) {
            if (s.dataset.sym.replace('/USD','').replace('USD','') === clean) s.style.color = newCol;
          });
          // Popup border + header label
          p.style.borderColor = newCol;
          p.querySelector('#tp-sym-label').style.color = newCol;
        });

        // Close button
        p.querySelector('#tp-close').addEventListener('click', _closePopup);

        // Click outside to close
        setTimeout(function() {
          document.addEventListener('click', _outsideClose);
        }, 50);

        // Fetch fill history
        var histUrl = SUPA_URL + '/rest/v1/fills'
          + '?select=symbol,side,quantity,fill_price,filled_at'
          + '&symbol=eq.' + sym
          + '&order=filled_at.desc&limit=30';
        fetch(histUrl, {headers:{'apikey':SUPA_KEY,'Authorization':'Bearer '+SUPA_KEY}})
        .then(function(r){return r.json();})
        .then(function(rows){
          var el = document.getElementById('tp-history');
          if (!el) return;
          if (!Array.isArray(rows) || !rows.length) {
            el.innerHTML = '<div style="color:#3a1a5a">no fills found</div>'; return;
          }
          el.innerHTML = rows.map(function(f) {
            var side = (f.side||'').toUpperCase() === 'BUY' ? '<span style="color:#00b4ff">enter</span>' : '<span style="color:#ff9900">exit</span>';
            var price = f.fill_price < 1 ? '$'+parseFloat(f.fill_price).toFixed(4) : '$'+parseFloat(f.fill_price).toLocaleString('en-US',{maximumFractionDigits:2});
            var qty   = parseFloat(f.qty || f.quantity || 0);
            var t     = new Date(f.filled_at);
            var ts    = (t.getMonth()+1)+'/'+(t.getDate())+' '+(t.getHours()%12||12)+':'+(('0'+t.getMinutes()).slice(-2))+(t.getHours()<12?'a':'p');
            return '<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.04)">'
              +'<span style="color:#3a1a5a;font-size:11px">'+ts+'</span>'
              +side+' '+price
              +'</div>';
          }).join('');
        }).catch(function(){
          var el = document.getElementById('tp-history');
          if (el) el.innerHTML = '<div style="color:#3a1a5a">error fetching fills</div>';
        });
      }

      function _closePopup() {
        if (_popup) { _popup.remove(); _popup = null; _popupSym = null; }
        document.removeEventListener('click', _outsideClose);
      }

      function _outsideClose(e) {
        if (_popup && !_popup.contains(e.target)) _closePopup();
      }

      // Canvas click → hit-test tiles
      document.addEventListener('click', function(e) {
        var canvas = document.getElementById('eq-tiles-canvas');
        if (!canvas || !window._ET) return;
        var rect = canvas.getBoundingClientRect();
        if (e.clientX < rect.left || e.clientX > rect.right ||
            e.clientY < rect.top  || e.clientY > rect.bottom) return;
        var mx = (e.clientX - rect.left) * (canvas.width / rect.width / _etDpr);
        var my = (e.clientY - rect.top)  * (canvas.height / rect.height / _etDpr);
        var layout = _etLayout();
        var hit = null;
        window._ET.forEach(function(t) {
          if (t.phase === 'done') return;
          var pos = _etTilePos(t, layout);
          if (mx >= pos.x && mx < pos.x + _EQ_W && my >= pos.y && my < pos.y + _EQ_H) hit = t;
        });
        if (hit) { e.stopPropagation(); _openPopup(hit.sym, e.clientX, e.clientY); }
      });

      // Terminal feed click — delegate on the feed container
      document.addEventListener('click', function(e) {
        var span = e.target;
        if (span.tagName !== 'SPAN' || !span.dataset.sym) return;
        var feedEl = document.getElementById('feed-overlay');
        if (!feedEl || !feedEl.contains(span)) return;
        e.stopPropagation();
        _openPopup(span.dataset.sym, e.clientX, e.clientY);
      });

      window._openTickerPopup = _openPopup;
    })();

    window._makeCard = function(p) { return _makeCard(p); };
    function _makeCard(p) {
      // Route all crypto tiles to the unified canvas engine — no DOM element created
      var col   = _symCol(p.symbol);
      var entry = parseFloat(p.entry_price || 0);
      var stop  = parseFloat(p.stop_price  || 0);
      var tgt   = parseFloat(p.target_price|| 0);
      if ((!tgt || tgt <= 0) && entry > 0) tgt = entry * 1.008;
      var qty   = parseFloat(p.qty || 0);
      var entTs = p.entered_at ? new Date(p.entered_at).getTime() : Date.now();
      _etUpsert({
        sym: p.symbol, col: col, entry: entry, stop: stop, target: tgt,
        qty: qty, isCrypto: true, direction: p.direction || 'long',
        enteredAt: entTs, curPrice: entry,
        val: qty * entry, pnl: 0, pnlPct: 0,
        inSignal: false, rank: 0, holdText: '',
      });
      return null; // no DOM element — callers must handle null
    }
    function _makeCardLEGACY_UNUSED(p) {
      // Original DOM card builder — kept for reference only, never called
      var col   = _symCol(p.symbol);
      var entry = parseFloat(p.entry_price);
      var stop  = parseFloat(p.stop_price);
      var qty   = parseFloat(p.qty);
      var age   = p.entered_at ? Math.round((Date.now() - new Date(p.entered_at)) / 60000) : 0;
      var stopPct = entry > 0 ? ((stop - entry) / entry * 100).toFixed(1) : '—';
      var qtyStr  = qty > 1000 ? qty.toFixed(0) : qty < 0.001 ? qty.toExponential(2) : qty.toFixed(4);
      var wr = window._winRates && window._winRates[p.symbol];
      var wrHtml = '';
      if (wr && wr.t >= 3) {
        var wrPct = Math.round(wr.w / wr.t * 100);
        var wrCol = wrPct >= 55 ? '#00ff9d' : wrPct >= 40 ? '#ff9900' : '#ff3366';
        var wrBg  = wrPct >= 55 ? 'rgba(0,255,157,.1)' : wrPct >= 40 ? 'rgba(255,153,0,.1)' : 'rgba(255,51,102,.1)';
        wrHtml = '<span class="win-badge" style="color:' + wrCol + ';background:' + wrBg + '">' + wrPct + '% W</span>';
      }
      var el = document.createElement('div');
      el.className = 'pos-card';
      el.setAttribute('data-sym', p.symbol);
      el.setAttribute('data-entered', p.entered_at || '');
      el.setAttribute('data-qty', qty || 0);
      el.setAttribute('data-entry', entry || 0);
      el.style.borderLeft = '3px solid ' + col;
      el.style.position = 'relative';
      el.style.overflow = 'hidden';
      el.style.transformOrigin = 'center top';
      var agePct  = Math.min(age / 2 * 100, 100);  // 2-min max hold
      var ageBg   = agePct < 70 ? 'rgba(0,180,140,.55)' : agePct < 90 ? 'rgba(200,140,0,.6)' : 'rgba(200,60,80,.55)';
      // Acquired flash overlay
      var flash = document.createElement('div');
      flash.className = 'pos-acq-flash';
      flash.textContent = 'ACQUIRED';
      flash.style.color = col;
      el.appendChild(flash);
      // Live proximity meter (stop → current → target)
      var tgt = parseFloat(p.target_price || 0);
      // Synthetic target from config (0.8%) if DB value is null/zero
      if ((!tgt || tgt <= 0) && entry > 0) tgt = entry * 1.008;
      var rangeHtml = '';
      if (entry > 0 && stop > 0) {
        var stopDisp = stop < 1 ? '$' + stop.toFixed(4) : '$' + stop.toFixed(2);
        var tgtDisp  = tgt  < 1 ? '$' + tgt.toFixed(4)  : '$' + tgt.toFixed(2);
        rangeHtml = '<div class="pos-prox-wrap"'
          + ' data-entry="' + entry + '" data-stop="' + stop + '" data-target="' + tgt + '">'
          + '<div class="pos-prox-labels-row">'
          + '<span class="prox-lbl-stop">● ' + stopDisp + '</span>'
          + '<span class="prox-lbl-arrow" id="prox-arrow-' + _symId + '">—</span>'
          + '<span class="prox-lbl-tgt">' + tgtDisp + ' ●</span>'
          + '</div>'
          + '<div class="pos-prox-track">'
          + '<div class="pos-prox-zone-stop" style="width:20%"></div>'
          + '<div class="pos-prox-zone-tgt"  style="width:20%"></div>'
          + '<div class="pos-prox-fill" style="width:50%"></div>'
          + '<div class="pos-prox-cursor" style="left:50%"></div>'
          + '<div class="pos-prox-live" id="prox-live-' + _symId + '" style="left:50%;color:#fff"></div>'
          + '</div>'
          + '</div>';
      }
      var entryDisp = entry > 0 ? (entry < 0.01 ? '$' + entry.toFixed(6) : entry < 1 ? '$' + entry.toFixed(4) : '$' + entry.toFixed(2)) : '—';
      var _symId = p.symbol.replace(/[^A-Za-z0-9]/g,'_');
      // Age bar: fills left→right over 4h to show how long position has been held
      var ageBarPct = Math.min(agePct / 2 * 100, 100); // agePct is 0-100 over 2min — rescale
      var inner = document.createElement('div');
      inner.innerHTML = '<div class="pos-top">'
        + '<span class="pos-sym" style="color:' + col + '">···</span>'
        + '<span class="pos-hval" id="hval-' + _symId + '">$—</span>'
        + '</div>'
        + '<div class="pos-entry-sub">'
        + '<span class="pos-epx" id="epx-' + _symId + '" style="color:' + col + '">···</span>'
        + '<span class="pos-pnl-live" id="pnl-live-' + _symId + '">——</span>'
        + '</div>'
        + rangeHtml
        + '<div class="pos-age-bar" title="time held"><div class="pos-age-fill" id="age-fill-' + _symId + '" style="width:0%;background:#00c8ff;box-shadow:0 0 7px rgba(0,200,255,.75)"></div></div>';
      el.appendChild(inner);
      // Lock the card at its natural height before entry animation so it never shrinks
      requestAnimationFrame(function() {
        var h = el.getBoundingClientRect().height;
        if (h > 0) { el.style.minHeight = h + 'px'; }
      });
      // ── Multi-phase entry animation ────────────────────────────────────────
      var CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#@$%';
      function _scramble(domEl, target, ms, onDone) {
        var steps = Math.ceil(ms / 28); var f = 0;
        var iv = setInterval(function() {
          f++;
          var out = '';
          for (var i = 0; i < target.length; i++) {
            out += (i / target.length < f / steps) ? target[i] : CHARS[Math.floor(Math.random() * CHARS.length)];
          }
          domEl.textContent = out;
          if (f >= steps) { domEl.textContent = target; clearInterval(iv); if (onDone) onDone(); }
        }, 28);
      }
      function _countUp(domEl, start, end, ms, fmt) {
        var steps = Math.ceil(ms / 20); var f = 0;
        var iv = setInterval(function() {
          f++;
          var v = start + (end - start) * (f / steps);
          domEl.textContent = fmt(v);
          if (f >= steps) { domEl.textContent = fmt(end); clearInterval(iv); }
        }, 20);
      }
      // Phase 1 (180ms): "◈ ACQUIRING" overlay flashes — blue entry theme
      setTimeout(function() {
        flash.textContent = '◈ ACQUIRING';
        flash.style.color = '#00b4ff';
        flash.style.fontSize = '8px';
        flash.style.letterSpacing = '.22em';
        flash.classList.add('show');
        el.style.boxShadow = '0 0 18px rgba(0,180,255,.45), inset 0 0 12px rgba(0,180,255,.15)';
        el.style.borderLeftColor = '#00b4ff';
      }, 180);
      // Phase 2 (360ms): sym scrambles in
      setTimeout(function() {
        var symEl = inner.querySelector('.pos-sym');
        symEl.style.opacity = '1';
        _scramble(symEl, p.symbol.replace('/USD',''), 220);
      }, 360);
      // Phase 3 (520ms): entry price scrambles into pos-epx in ticker color
      setTimeout(function() {
        var epxEl = document.getElementById('epx-' + _symId);
        if (epxEl) _scramble(epxEl, entryDisp, 220);
      }, 520);
      // Phase 4 (720ms): prox bar labels — nothing visible to show, skip
      setTimeout(function() { }, 720);
      // Phase 5 (920ms): proximity bar fills to position, overlay becomes "OPEN" — blue
      setTimeout(function() {
        flash.textContent = '● OPEN';
        flash.style.color = '#00e5ff';
        flash.style.fontSize = '9px';
        flash.style.letterSpacing = '.3em';
        el.style.boxShadow = '0 0 16px rgba(0,180,255,.3), inset 0 0 6px rgba(0,180,255,.08)';
        el.style.borderLeftColor = col;
        // Fill proximity bar
        var pFill = el.querySelector('.pos-prox-fill');
        var pCursor = el.querySelector('.pos-prox-cursor');
        if (pFill) { pFill.style.transition = 'width .4s ease-out'; pFill.style.width = '50%'; }
        if (pCursor) { pCursor.style.transition = 'left .4s ease-out'; pCursor.style.left = '50%'; }
      }, 920);
      // Phase 6 (1150ms): overlay fades, glow settles, card goes active
      setTimeout(function() {
        flash.style.transition = 'opacity .4s ease';
        flash.style.opacity = '0';
        el.classList.add('pos-card-active');
        setTimeout(function() {
          el.style.boxShadow = '';
          if (flash.parentNode) flash.style.display = 'none';
        }, 420);
      }, 1150);
      return el;
    }   // end _makeCardLEGACY_UNUSED

    function _updateCard(el, p) {
      var entry   = parseFloat(p.entry_price);
      var ageSec  = p.entered_at ? (Date.now() - new Date(p.entered_at)) / 1000 : 0;
      var ageHrs  = ageSec / 3600;
      var symId   = (p.symbol || el.getAttribute('data-sym') || '').replace(/[^A-Za-z0-9]/g,'_');

      // Entry price in ticker color (pos-epx)
      var epxEl = document.getElementById('epx-' + symId);
      if (epxEl && entry > 0) {
        epxEl.textContent = entry < 0.01 ? '$' + entry.toFixed(6) : entry < 1 ? '$' + entry.toFixed(4) : '$' + entry.toFixed(2);
      }

      // Age bar: fills left→right, full at 4 hours — purely visual sense of how long held
      var fill = document.getElementById('age-fill-' + symId) || el.querySelector('.pos-age-fill');
      if (fill) {
        var pct = Math.min(ageHrs / 4 * 100, 100); // 4h = full bar
        fill.style.width = pct + '%';
        // Color: cyan (fresh) → orange (aging) → red (very long)
        fill.style.background = pct < 33 ? '#00c8ff' : pct < 66 ? '#ffaa00' : '#ff2844';
        fill.style.boxShadow = pct < 33 ? '0 0 7px rgba(0,200,255,.75)' : pct < 66 ? '0 0 7px rgba(255,170,0,.7)' : '0 0 9px rgba(255,40,70,.85)';
      }
    }

    function _pollPositions() {
      var url = SUPA_URL + '/rest/v1/crypto_positions'
        + '?select=symbol,direction,qty,entry_price,stop_price,target_price,entered_at'
        + '&order=entered_at.asc';
      fetch(url, {
        headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }
      })
      .then(function(r) { return r.ok ? r.json() : r.json().then(function(e) { console.error('[crypto_positions] HTTP', r.status, e); return null; }); })
      .then(function(rows) {
        if (!Array.isArray(rows)) return; // error response — don't touch existing cards
        console.log('[crypto_positions] rows:', rows.length);
        var section = document.getElementById('pos-crypto-section');
        if (!section) return;
        var flat = document.getElementById('pos-crypto-flat');

        // Expose positions map; detect exits to animate satellites out
        var oldMap = window._cryptoPositionsMap || {};
        if (Array.isArray(rows) && rows.length) {
          var newMap = {};
          rows.forEach(function(p) { newMap[p.symbol] = p; });
          window._cryptoPositionsMap = newMap;
          window._cryptoPairCount    = 15;
        } else {
          window._cryptoPositionsMap = {};
        }
        // Launch exit animation for any symbol no longer in map
        Object.keys(oldMap).forEach(function(sym) {
          if (!window._cryptoPositionsMap[sym] && _satAngles[sym] !== undefined) {
            var pos = oldMap[sym]; var entry = parseFloat(pos.entry_price||0);
            var stop = parseFloat(pos.stop_price||0); var tgt = parseFloat(pos.target_price||0)||entry*1.008;
            var range = tgt - stop; var price = (window._liveProxPrices||{})[sym] || entry;
            var t2 = range ? Math.max(0,Math.min(1,(price-stop)/range)) : 0.5;
            var orbitR = 20 + t2*24;
            _satExiting[sym] = {
              angle: _satAngles[sym], orbitR: orbitR, age: 0,
              sr: Math.round(255*Math.max(0,1-t2*1.5)),
              sg: Math.round(255*Math.min(1,t2*1.8)),
              sb: Math.round(102*(1-t2))
            };
            delete _satAngles[sym];
            delete _smoothOrbitR[sym];
            delete _satEntryAge[sym];
          }
        });

        if (!Array.isArray(rows) || !rows.length) {
          // Exit all open crypto canvas tiles (poll fallback)
          _ET.filter(function(t) { return t.isCrypto; }).forEach(function(t) {
            if (t.phase === 'live' || t.phase === 'entering') {
              window._etExit(t.sym, null, null);
            }
          });
          _updateOverlayWidth();
          return;
        }

        var newSyms = {};
        rows.forEach(function(p) { newSyms[p.symbol] = p; });

        // Exit crypto canvas tiles no longer in data (poll fallback)
        _ET.filter(function(t) { return t.isCrypto; }).forEach(function(t) {
          if (!newSyms[t.sym] && (t.phase === 'live' || t.phase === 'entering')) {
            window._etExit(t.sym, null, null);
          }
        });

        // Add or update canvas tiles — _etUpsert handles both
        rows.forEach(function(p) {
          _makeCard(p);
        });
        _updateOverlayWidth();

        // Mirror into report panel rp-crypto-section
        var rpSection = document.getElementById('rp-crypto-section');
        if (rpSection) {
          var PALETTE = ['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
          function _symCol(s) { var c=s.replace('/USD','').replace('USD',''); if(window._TICKER_OVR&&window._TICKER_OVR[c])return window._TICKER_OVR[c]; var h=0; for(var i=0;i<c.length;i++)h=(h*31+c.charCodeAt(i))&0xffff; return PALETTE[h%PALETTE.length]; }
          function _rpPnlStr(p) {
            if (!p.entry_price) return '—';
            // For crypto we don't have current price in this fetch — show entry info
            return 'entered @ $' + parseFloat(p.entry_price).toFixed(4);
          }
          // Build desired set of syms
          var desiredSyms = {};
          rows.forEach(function(p) { desiredSyms[p.symbol] = p; });
          // Remove stale rp rows
          Array.from(rpSection.querySelectorAll('.rp-pos[data-sym]')).forEach(function(el) {
            if (!desiredSyms[el.getAttribute('data-sym')]) { rpSection.removeChild(el); }
          });
          // Add missing rp rows
          rows.forEach(function(p) {
            if (rpSection.querySelector('.rp-pos[data-sym="'+p.symbol+'"]')) return;
            var tcol = _symCol(p.symbol.replace('/USD',''));
            var baseSym = p.symbol.replace('/USD','');
            var holdMin = Math.floor((Date.now() - new Date(p.entered_at).getTime()) / 60000);
            var holdStr = holdMin < 1 ? '<1m' : holdMin + 'm';
            var subText = (p.qty ? parseFloat(p.qty).toFixed(4) + ' ' + baseSym : '') + (holdMin !== undefined ? '  ·  ' + holdStr : '');
            var el = document.createElement('div');
            el.className = 'rp-pos rp-pos-entering'; el.setAttribute('data-sym', p.symbol);
            el.style.cssText = 'position:relative;overflow:hidden';
            el.innerHTML = '<span class="pos-corner tl" style="border-color:'+tcol+'"></span>' +
              '<span class="pos-corner tr" style="border-color:'+tcol+'"></span>' +
              '<span class="pos-corner bl" style="border-color:'+tcol+'"></span>' +
              '<span class="pos-corner br" style="border-color:'+tcol+'"></span>' +
              '<div class="rp-pos-stripe" style="background:'+tcol+';box-shadow:0 0 8px '+tcol+'55"></div>' +
              '<div class="rp-pos-top"><span class="rp-pos-sym" style="color:'+tcol+'">'+baseSym+'</span>' +
              '<span class="rp-pos-type">CRYPTO</span></div>' +
              '<div class="rp-pos-val">—</div>' +
              '<div class="rp-pos-sub"><span class="rp-pos-qty">'+subText+'</span></div>' +
              '<div class="rp-pos-pnl" style="color:#6a4a8a">'+_rpPnlStr(p)+'</div>';
            rpSection.appendChild(el);
          });
          if (!rows.length) {
            if (!rpSection.querySelector('.rp-empty-crypto')) {
              var emp = document.createElement('div');
              emp.className = 'rp-empty-crypto';
              emp.style.cssText = 'padding:12px 14px;font-size:9px;color:#2a1a3a;letter-spacing:.04em';
              emp.textContent = 'no crypto positions';
              rpSection.appendChild(emp);
            }
          } else {
            var emp2 = rpSection.querySelector('.rp-empty-crypto');
            if (emp2) rpSection.removeChild(emp2);
          }
        }
      })
      .catch(function() {});
    }

    setTimeout(function() {
      _pollPositions();
      setInterval(_pollPositions, 2000);
    }, 2000);

    // Tick age bars every 30s (entry price + hold bar — no need for per-second update)
    setInterval(function() {
      var posMap = window._cryptoPositionsMap || {};
      Object.keys(posMap).forEach(function(sym) {
        var el = (typeof _cryptoCardEls !== 'undefined') ? _cryptoCardEls[sym] : null;
        if (el) _updateCard(el, posMap[sym]);
      });
    }, 30000);

    // ── Live crypto price poller — updates proximity meters in real time ──────
    var _CG_SYM_MAP = {
      'BTC/USD':'bitcoin','ETH/USD':'ethereum','SOL/USD':'solana',
      'AVAX/USD':'avalanche-2','LINK/USD':'chainlink','DOGE/USD':'dogecoin',
      'BCH/USD':'bitcoin-cash','XTZ/USD':'tezos','CRV/USD':'curve-dao-token',
      'UNI/USD':'uniswap','ADA/USD':'cardano','MATIC/USD':'matic-network',
      'DOT/USD':'polkadot',
    };
    var _CG_ID_TO_SYM = {};
    Object.keys(_CG_SYM_MAP).forEach(function(s) { _CG_ID_TO_SYM[_CG_SYM_MAP[s]] = s; });
    function _updateProxMeters(priceMap) {
      document.querySelectorAll('.pos-prox-wrap[data-entry]').forEach(function(wrap) {
        var card = wrap.closest('.pos-card[data-sym]');
        if (!card) return;
        var sym = card.getAttribute('data-sym');
        var price = priceMap[sym];
        if (!price) return;
        var entry  = parseFloat(wrap.getAttribute('data-entry'));
        var stop   = parseFloat(wrap.getAttribute('data-stop'));
        var tgt    = parseFloat(wrap.getAttribute('data-target'));
        if (!entry || !stop || !tgt) return;
        // t=0 at stop, t=1 at target (clamped)
        var range = tgt - stop;
        var t = range !== 0 ? Math.max(0, Math.min(1, (price - stop) / range)) : 0.5;
        var pct = (t * 100).toFixed(1);
        var fill   = wrap.querySelector('.pos-prox-fill');
        var cursor = wrap.querySelector('.pos-prox-cursor');
        var live   = wrap.querySelector('.pos-prox-live');
        if (fill)   fill.style.width  = pct + '%';
        if (cursor) cursor.style.left = pct + '%';
        // Cursor zone color
        if (cursor) {
          cursor.classList.toggle('danger', t < 0.18);
          cursor.classList.toggle('target', t > 0.82);
          if (t >= 0.18 && t <= 0.82) {
            cursor.style.background = '#ffffff';
            cursor.style.animation  = 'none';
          }
        }
        // Floating price label above cursor
        var symId2    = sym.replace(/[^A-Za-z0-9]/g,'_');
        var proxLive  = document.getElementById('prox-live-' + symId2);
        if (proxLive) {
          var priceDisp = price < 0.01 ? '$' + price.toFixed(6) : price < 1 ? '$' + price.toFixed(4) : '$' + price.toFixed(2);
          var prevPx = parseFloat(proxLive.getAttribute('data-px') || 'NaN');
          var pxDir  = !isNaN(prevPx) ? (price > prevPx ? 'up' : price < prevPx ? 'dn' : '') : '';
          proxLive.setAttribute('data-px', price);
          proxLive.style.left  = pct + '%';
          proxLive.style.color = t < 0.18 ? '#ff3366' : t > 0.82 ? '#00ff9d' : '#ffffff';
          proxLive.textContent = priceDisp;
          if (pxDir) {
            proxLive.classList.remove('prox-tick-up','prox-tick-dn');
            void proxLive.offsetWidth;
            proxLive.classList.add('prox-tick-' + pxDir);
          }
        }
        // Direction arrow between stop/target labels
        var arrowEl = document.getElementById('prox-arrow-' + symId2);
        if (arrowEl) {
          var prevT = parseFloat(arrowEl.getAttribute('data-t') || 'NaN');
          if (!isNaN(prevT) && t !== prevT) {
            arrowEl.textContent = t > prevT ? '→' : '←';
            arrowEl.style.color = t > prevT ? '#00ff9d' : '#ff3366';
          }
          arrowEl.setAttribute('data-t', t);
        }
        // Live P&L in pos-entry-sub row
        var pnlPct  = entry > 0 ? ((price - entry)/entry*100) : 0;
        var pnlSign = pnlPct >= 0 ? '+' : '';
        var pnlEl   = document.getElementById('pnl-live-' + symId2);
        if (pnlEl) {
          var prevRaw = parseFloat(pnlEl.getAttribute('data-raw') || 'NaN');
          var arrow = '';
          if (!isNaN(prevRaw) && pnlPct !== prevRaw) {
            arrow = pnlPct > prevRaw ? '▲ ' : '▼ ';
            var dir = pnlPct > prevRaw ? 'up' : 'dn';
            pnlEl.classList.remove('prox-tick-up', 'prox-tick-dn');
            void pnlEl.offsetWidth;
            pnlEl.classList.add('prox-tick-' + dir);
          }
          pnlEl.setAttribute('data-raw', pnlPct);
          pnlEl.textContent = arrow + pnlSign + pnlPct.toFixed(2) + '%';
          pnlEl.style.color = pnlPct >= 0 ? '#00ff9d' : '#ff3366';
        }

      });
    }
    function _pollCryptoPrices() {
      // Collect open crypto tile symbols from canvas engine
      var openSyms = _ET.filter(function(t) { return t.isCrypto && t.phase !== 'done'; })
                        .map(function(t) { return t.sym; });
      if (!openSyms.length) return;
      var cgIds = openSyms.map(function(s) { return _CG_SYM_MAP[s]; }).filter(Boolean);
      if (!cgIds.length) return;
      fetch('https://api.coingecko.com/api/v3/simple/price?ids=' + cgIds.join(',') + '&vs_currencies=usd')
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(data) {
          if (!data) return;
          var priceMap = {};
          Object.keys(data).forEach(function(id) {
            var sym = _CG_ID_TO_SYM[id];
            if (sym && data[id] && data[id].usd) priceMap[sym] = data[id].usd;
          });
          window._liveProxPrices = priceMap;
          if (window._onPricePoll) window._onPricePoll();
          _updateProxMeters(priceMap);
          // Update canvas tile state (replaces DOM element updates)
          var posMap = window._cryptoPositionsMap || {};
          _ET.filter(function(t) { return t.isCrypto && t.phase !== 'done'; }).forEach(function(t) {
            var price = priceMap[t.sym];
            if (!price) return;
            var posData = posMap[t.sym];
            var qty = t.qty || (posData ? parseFloat(posData.qty || 0) : 0);
            var entry = t.entry || (posData ? parseFloat(posData.entry_price || 0) : 0);
            var prevPrice = t.curPrice;
            t.curPrice = price;
            if (qty > 0) t.val = qty * price;
            if (entry > 0) {
              t.pnl    = qty * (price - entry);
              t.pnlPct = (price - entry) / entry * 100;
            }
            if (prevPrice && price !== prevPrice) {
              t._valFlash = price > prevPrice ? 1 : -1;
            }
          });
          // Compute live portfolio NAV and push intraday point
          if (window._pushIntradayPoint) {
            var baseline = window._portfolioBaseline || 100000;
            var livePnl = 0;
            Object.keys(posMap).forEach(function(sym) {
              var p = posMap[sym];
              var px = priceMap[sym];
              if (!p || !px) return;
              var entry = parseFloat(p.entry_price || 0);
              var qty   = parseFloat(p.qty || 0);
              if (entry > 0 && qty !== 0) livePnl += qty * (px - entry);
            });
            // Write crypto slice; combine with equity slice so NAV is consistent across pollers
            window._livePnlBySource.crypto = livePnl;
            var _combinedPnl = window._livePnlBySource.equity + window._livePnlBySource.crypto;
            var nav = baseline + _combinedPnl;
            if (nav > 1000 && nav < 5000000) {
              window._pushIntradayPoint(new Date().toISOString(), nav);
            }
          }
        }).catch(function() {});
    }
    setTimeout(_pollCryptoPrices, 3500);
    setInterval(_pollCryptoPrices, 4000);

    // ── Canonical NAV from DB — source of truth for displayed Portfolio number ──
    // All tabs read the latest nav_snapshots row so every screen shows the same value.
    function _pollCanonicalNav() {
      fetch(SUPA_URL + '/rest/v1/nav_snapshots?select=recorded_at,nav&order=recorded_at.desc&limit=1',
        { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        var row = rows[0];
        var age = Date.now() - new Date(row.recorded_at).getTime();
        if (age > 120000) return; // ignore rows older than 2 min — stale
        var nav = parseFloat(row.nav);
        if (!nav || nav < 1000 || nav > 10000000) return;
        // Only update display if DB value differs meaningfully from what's shown
        var shown = window._lastKnownNav || 0;
        if (Math.abs(nav - shown) < 0.01) return;
        window._lastKnownNav = nav;
        if (window._updateNavDisplays_ext) window._updateNavDisplays_ext(nav, row.recorded_at);
      }).catch(function() {});
    }
    // Expose _updateNavDisplays so canonical poller can call it
    window._updateNavDisplays_ext = function(nav, ts) { _updateNavDisplays(nav, ts); };
    setTimeout(_pollCanonicalNav, 6000); // slight delay so local compute runs first
    setInterval(_pollCanonicalNav, 5000);

    // ── Equity pipeline countdown (daily 4:05pm ET) ───────────────────────────
    (function() {
      var _PIPELINE_WINDOW = 24 * 60 * 60 * 1000; // 24h in ms
      function _nextPipelineMs() {
        var now = new Date();
        var etOffset = -5 * 60; // EST minutes offset
        var etNow = new Date(now.getTime() + (now.getTimezoneOffset() + etOffset) * 60000);
        var target = new Date(etNow);
        target.setHours(16, 5, 0, 0);
        if (etNow >= target) target.setDate(target.getDate() + 1);
        return target - etNow;
      }
      function _updatePipeline() {
        var fill = document.getElementById('eq-pip-fill');
        var eta  = document.getElementById('eq-pip-eta');
        if (!fill || !eta) return;
        var rem = _nextPipelineMs();
        fill.style.width = Math.max(0, Math.min(100, (1 - rem / _PIPELINE_WINDOW) * 100)) + '%';
        var h = Math.floor(rem / 3600000);
        var m = Math.floor((rem % 3600000) / 60000);
        eta.textContent = h + 'h ' + m + 'm';
      }
      _updatePipeline();
      setInterval(_updatePipeline, 10000);
    })();

    // ── Stats poller: streak + daily bar (every 15s) ─────────────────────────
    function _pollStats() {
      // Fetch last 60 TRADE events that have EXIT to compute streak + per-symbol win rate
      var url = SUPA_URL + '/rest/v1/pipeline_events'
        + '?select=symbol,message,recorded_at'
        + '&event_type=eq.TRADE'
        + '&message=like.*EXIT*'
        + '&order=recorded_at.desc&limit=60';
      fetch(url, { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows)) return;
        // Streak: count consecutive ✓ or ✗ from top (most recent)
        var streak = 0, streakSign = null;
        for (var i = 0; i < rows.length; i++) {
          var m = rows[i].message;
          var isWin = m.indexOf('✓') !== -1;
          var isLoss = m.indexOf('✗') !== -1;
          if (!isWin && !isLoss) continue;
          var s = isWin ? 1 : -1;
          if (streakSign === null) { streakSign = s; streak = 1; }
          else if (s === streakSign) { streak++; }
          else { break; }
        }
        var sv = document.getElementById('streak-val');
        if (sv) {
          if (streakSign === null) { sv.textContent = '—'; sv.style.color = '#3a1a5a'; }
          else {
            var ico = streakSign > 0 ? '🔥' : '☠️';
            sv.innerHTML = ico + ' ' + streak + (streakSign > 0 ? 'W' : 'L');
            sv.style.color = streakSign > 0 ? '#00ff9d' : '#ff3366';
          }
        }
        // Sync window._streak so orb tooltip STREAK field stays current
        if (streakSign !== null) {
          window._streak = { count: streak, win: streakSign > 0 };
        }
        // Win rate per symbol → store as map for _pollPositions to use
        window._winRates = {};
        var _totalW = 0, _totalT = 0;
        rows.forEach(function(row) {
          var sym = row.symbol || '';
          if (!window._winRates[sym]) window._winRates[sym] = {w:0,t:0};
          window._winRates[sym].t++;
          _totalT++;
          if (row.message.indexOf('✓') !== -1) { window._winRates[sym].w++; _totalW++; }
        });
        // Update header win rate
        var _hwrEl = document.getElementById('hdr-winrate');
        if (_hwrEl) _hwrEl.textContent = _totalT > 0 ? Math.round(_totalW/_totalT*100) + '%' : '—';
      }).catch(function() {});

      // Runner health — fetch most recent UPDATE event (heartbeat) and compute age
      var urlHb = SUPA_URL + '/rest/v1/pipeline_events'
        + '?select=recorded_at&event_type=eq.UPDATE&order=recorded_at.desc&limit=1';
      fetch(urlHb, { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        var dot = document.getElementById('runner-dot');
        var age = document.getElementById('runner-age');
        if (!dot || !age || !Array.isArray(rows) || !rows.length) return;
        var mins = (Date.now() - new Date(rows[0].recorded_at)) / 60000;
        var cls  = mins < 6 ? 'ok' : mins < 20 ? 'warn' : 'dead';
        dot.className = cls;
        age.textContent = mins < 1 ? '<1m' : Math.round(mins) + 'm ago';
        age.style.color = cls === 'ok' ? '#00ff9d' : cls === 'warn' ? '#ff9900' : '#ff3366';
      }).catch(function() {});

      // Trade count today — HEAD request with Prefer:count=exact avoids row limit
      var todayStr = new Date().toISOString().split('T')[0];
      var urlTc = SUPA_URL + '/rest/v1/pipeline_events'
        + '?select=id&event_type=eq.TRADE&recorded_at=gte.' + todayStr + 'T00:00:00Z&limit=1';
      fetch(urlTc, { method:'HEAD', headers: {
        'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY,
        'Prefer': 'count=exact'
      } })
      .then(function(r) {
        var ct = r.headers.get('content-range'); // e.g. "0-0/1842"
        if (!ct) return;
        var total = ct.split('/')[1];
        var el = document.getElementById('runner-trades');
        if (el && total) el.textContent = total + ' trades today';
      }).catch(function() {});

      // Daily bar: today's fills pnl proxy — compare earliest vs latest portfolio snapshot today
      var today = new Date().toISOString().split('T')[0];
      var urlSnap = SUPA_URL + '/rest/v1/portfolio_snapshots'
        + '?select=total_value,recorded_at&strategy=eq.crypto_momentum'
        + '&recorded_at=gte.' + today + 'T00:00:00Z&order=recorded_at.asc&limit=1';
      fetch(urlSnap, { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY } })
      .then(function(r) { return r.json(); })
      .then(function(rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        var sodNav = parseFloat(rows[0].total_value);
        var latestNav = parseFloat(document.querySelector('.tb-stat-val')?.textContent?.replace(/[$,]/g,'')) || sodNav;
        // use the nav from the last known update if possible
        if (window._lastKnownNav) latestNav = window._lastKnownNav;
        var dayPnl = latestNav - sodNav;
        var dailyLimit = 10000; // $10K = 10% of $100K
        var pct = Math.min(Math.abs(dayPnl) / dailyLimit, 1);
        var fill = document.getElementById('daily-bar-fill');
        var lbl  = document.getElementById('daily-bar-label');
        if (fill) {
          fill.style.width = (pct * 100) + '%';
          fill.style.background = dayPnl >= 0
            ? 'linear-gradient(90deg,#00ff9d,#00e5ff)'
            : 'linear-gradient(90deg,#ff3366,#ff9900)';
        }
        if (lbl) {
          var sign = dayPnl >= 0 ? '+' : '-';
          lbl.textContent = 'today ' + sign + '$' + Math.round(Math.abs(dayPnl)).toLocaleString('en-US');
          lbl.style.color = dayPnl >= 0 ? '#00ff9d' : '#ff3366';
        }
      }).catch(function() {});
    }
    var _runnerCdSecs = 15;
    var _runnerCdEl = document.getElementById('runner-countdown');
    function _resetRunnerCd() {
      _runnerCdSecs = 15;
      if (_runnerCdEl) _runnerCdEl.textContent = 'next: 15s';
    }
    setInterval(function() {
      if (_runnerCdSecs > 0) _runnerCdSecs--;
      if (_runnerCdEl) _runnerCdEl.textContent = 'next: ' + _runnerCdSecs + 's';
    }, 1000);
    var _origPollStats = _pollStats;
    _pollStats = function() { _resetRunnerCd(); _origPollStats(); };
    setTimeout(function() { _pollStats(); setInterval(_pollStats, 15000); }, 6000);

    // ══════════════════════════════════════════════════════════════
    // STRATAGEM HUD — live slot updates + drop-in callouts
    // ══════════════════════════════════════════════════════════════
    (function() {
      // ── Slot state helpers ────────────────────────────────────
      function _ssSet(id, stClass, text) {
        var el = document.getElementById(id);
        if (!el) return;
        el.parentElement.className = 'strat-slot ' + stClass;
        el.textContent = text;
      }
      function _fmtCountdown(ms) {
        if (ms <= 0) return 'NOW';
        var s = Math.round(ms / 1000);
        if (s < 60) return s + 's';
        var m = Math.floor(s / 60); s = s % 60;
        if (m < 60) return m + 'm ' + (s < 10 ? '0' : '') + s + 's';
        var h = Math.floor(m / 60); m = m % 60;
        return h + 'h ' + (m < 10 ? '0' : '') + m + 'm';
      }

      // ── ALPACA WALLET slot ────────────────────────────────────
      var _ls = (function() {
        try { localStorage.setItem('_t','1'); localStorage.removeItem('_t'); return localStorage; }
        catch(e) { return { getItem: function(){return null;}, setItem: function(){}, removeItem: function(){} }; }
      })();
      var _alpacaWallets   = JSON.parse(_ls.getItem('_alpacaWallets') || '[]');
      var _alpacaActiveIdx = parseInt(_ls.getItem('_alpacaActiveIdx') || '0', 10);
      var _alpacaSyncSecs  = 0;
      var _alpacaDropOpen  = false;

      window._toggleAlpacaDropdown = function() {
        var dd = document.getElementById('alpaca-dropdown');
        if (!dd) return;
        _alpacaDropOpen = !_alpacaDropOpen;
        if (_alpacaDropOpen) {
          var r = document.getElementById('ss-runner').getBoundingClientRect();
          dd.style.left  = r.left + 'px';
          dd.style.top   = (r.bottom + 4) + 'px';
          dd.style.display = 'block';
          _renderAlpacaList();
        } else { dd.style.display = 'none'; }
      };
      document.addEventListener('click', function(e) {
        if (_alpacaDropOpen && !e.target.closest('#alpaca-dropdown') && !e.target.closest('#ss-runner')) {
          _alpacaDropOpen = false;
          var dd = document.getElementById('alpaca-dropdown');
          if (dd) dd.style.display = 'none';
        }
      });

      function _renderAlpacaList() {
        var list = document.getElementById('alpaca-wallet-list');
        if (!list) return;
        list.innerHTML = '';
        if (!_alpacaWallets.length) {
          list.innerHTML = '<div style="padding:6px 14px;font-size:9px;color:rgba(148,0,255,.4)">no wallets saved</div>';
          return;
        }
        _alpacaWallets.forEach(function(w, i) {
          var row = document.createElement('div');
          row.style.cssText = 'padding:5px 14px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;' +
            (i === _alpacaActiveIdx ? 'background:rgba(148,0,255,.15);' : '');
          row.innerHTML = '<span style="font-size:10px;color:' + (i===_alpacaActiveIdx?'#c090ff':'#6a4a8a') + '">' +
            (i===_alpacaActiveIdx?'▶ ':'  ') + w.name + ' <span style="font-size:8px;color:rgba(148,0,255,.4)">[' + w.type + ']</span></span>' +
            '<span style="font-size:8px;color:#ff3366;cursor:pointer" onclick="window._removeAlpacaWallet(' + i + ');event.stopPropagation()">✕</span>';
          row.onclick = function() { _alpacaActiveIdx = i; _ls.setItem('_alpacaActiveIdx', i); _renderAlpacaList(); _fetchAlpacaBalance(); };
          list.appendChild(row);
        });
      }

      window._saveAlpacaWallet = function() {
        var name   = (document.getElementById('alp-name')   || {}).value || '';
        var key    = (document.getElementById('alp-key')    || {}).value || '';
        var secret = (document.getElementById('alp-secret') || {}).value || '';
        var type   = (document.getElementById('alp-type')   || {}).value || 'paper';
        if (!name || !key || !secret) return;
        _alpacaWallets.push({ name:name, key:key, secret:secret, type:type });
        _ls.setItem('_alpacaWallets', JSON.stringify(_alpacaWallets));
        _alpacaActiveIdx = _alpacaWallets.length - 1;
        _ls.setItem('_alpacaActiveIdx', _alpacaActiveIdx);
        ['alp-name','alp-key','alp-secret'].forEach(function(id) { var el=document.getElementById(id); if(el) el.value=''; });
        _renderAlpacaList();
        _fetchAlpacaBalance();
      };

      window._removeAlpacaWallet = function(i) {
        _alpacaWallets.splice(i, 1);
        _ls.setItem('_alpacaWallets', JSON.stringify(_alpacaWallets));
        if (_alpacaActiveIdx >= _alpacaWallets.length) _alpacaActiveIdx = Math.max(0, _alpacaWallets.length - 1);
        _ls.setItem('_alpacaActiveIdx', _alpacaActiveIdx);
        _renderAlpacaList();
        _fetchAlpacaBalance();
      };

      var _alpacaAnimRaf = null, _alpacaDispVal = null;
      function _animateAlpacaVal(toVal) {
        var el = document.getElementById('ss-runner-st');
        if (!el) return;
        var from = _alpacaDispVal !== null ? _alpacaDispVal : toVal;
        if (_alpacaAnimRaf) cancelAnimationFrame(_alpacaAnimRaf);
        var start = null;
        function step(ts) {
          if (!start) start = ts;
          var p = Math.min(1, (ts - start) / 800);
          var e = 1 - Math.pow(1 - p, 3);
          _alpacaDispVal = from + (toVal - from) * e;
          el.textContent = '$' + _alpacaDispVal.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
          if (p < 1) _alpacaAnimRaf = requestAnimationFrame(step);
          else { _alpacaDispVal = toVal; _alpacaAnimRaf = null; }
        }
        _alpacaAnimRaf = requestAnimationFrame(step);
      }

      function _fetchAlpacaBalance() {
        var w = _alpacaWallets[_alpacaActiveIdx];
        if (!w) return;  // no wallet configured — keep server-seeded value
        var base = w.type === 'live' ? 'https://api.alpaca.markets' : 'https://paper-api.alpaca.markets';
        fetch(base + '/v2/account', { headers: { 'APCA-API-KEY-ID': w.key, 'APCA-API-SECRET-KEY': w.secret } })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            var val = parseFloat(data.portfolio_value || data.equity || 0);
            if (!val) return;
            _animateAlpacaVal(val);
            var lmv = parseFloat(data.long_market_value || 0);
            if (lmv >= 0) _animateLongExp(lmv);
            // Sync success flash
            var chip = document.getElementById('ss-alpaca-chip');
            if (chip) { chip.textContent = '✓ SYNCED'; chip.style.color = '#00ff9d'; chip.style.opacity = '1';
              setTimeout(function() { chip.style.opacity = '0'; }, 2500); }
            _alpacaSyncSecs = 30;  // reset countdown
          }).catch(function() {
            var el = document.getElementById('ss-runner-st');
            if (el) el.textContent = 'ERR';
          });
      }

      // 30-second sync countdown
      setInterval(function() {
        var cd = document.getElementById('ss-alpaca-sync-cd');
        if (_alpacaSyncSecs > 0) {
          _alpacaSyncSecs--;
          if (cd) cd.textContent = _alpacaSyncSecs + 's';
          if (_alpacaSyncSecs === 0) _fetchAlpacaBalance();
        } else {
          if (cd) cd.textContent = '';
        }
      }, 1000);
      // Seed wallet slot immediately from server-injected value (no CORS needed)
      if (typeof _ALPACA_PORTVAL === 'number' && _ALPACA_PORTVAL > 0) {
        _animateAlpacaVal(_ALPACA_PORTVAL);
      }
      // Initial fetch after short delay — overwrites seed if client-side succeeds
      setTimeout(function() { _fetchAlpacaBalance(); _alpacaSyncSecs = 30; }, 1500);

      // ── LONG EXPOSURE slot — market value of open positions, server-injected ────────
      var _longExpDisp = null, _longExpRaf = null;
      function _animateLongExp(toVal) {
        var el = document.getElementById('ss-pipeline-st');
        if (!el) return;
        var from = _longExpDisp !== null ? _longExpDisp : toVal;
        if (_longExpRaf) cancelAnimationFrame(_longExpRaf);
        var start = null;
        function step(ts) {
          if (!start) start = ts;
          var p = Math.min(1, (ts - start) / 2000);
          var e = 1 - Math.pow(1 - p, 3);
          _longExpDisp = from + (toVal - from) * e;
          el.textContent = '$' + Math.round(_longExpDisp).toLocaleString('en-US');
          if (p < 1) _longExpRaf = requestAnimationFrame(step);
          else { _longExpDisp = toVal; _longExpRaf = null; }
        }
        _longExpRaf = requestAnimationFrame(step);
      }
      // Seed from server-injected Alpaca long_market_value
      if (typeof _ALPACA_EXPOSURE === 'number' && _ALPACA_EXPOSURE > 0) {
        setTimeout(function() { _animateLongExp(_ALPACA_EXPOSURE); }, 800);
      }

      // ── TRADES slot — accurate fill count from Supabase ───────
      function _fetchFillCount() {
        fetch(SUPA_URL + '/rest/v1/fills?select=id',
          { headers: { 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY,
             'Prefer': 'count=exact', 'Range': '0-0' } })
          .then(function(r) {
            var ct = r.headers.get('content-range');  // "0-0/1376"
            if (ct) {
              var total = parseInt(ct.split('/')[1], 10);
              if (!isNaN(total)) {
                var el = document.getElementById('ss-nav-st');
                if (el) { el.textContent = total.toLocaleString('en-US'); el.style.color = total > 0 ? '#ff9900' : 'rgba(148,0,255,.4)'; }
              }
            }
          }).catch(function() {});
      }
      setTimeout(_fetchFillCount, 3000);
      setInterval(_fetchFillCount, 30000);

      // ── WALLET slot — Alpaca NAV with gain/loss color flash (window-exposed) ─
      var _lastWalletVal = null;
      // rAF-animated counter — rolls from current displayed value to target
      var _walletRaf = null;
      var _walletRendered = null;
      function _animateWallet(toVal) {
        var el = document.getElementById('ss-wallet-val');
        if (!el) return;
        var from = _walletRendered !== null ? _walletRendered : toVal;
        if (_walletRaf) { cancelAnimationFrame(_walletRaf); _walletRaf = null; }
        var startTs = null;
        var DURATION = 700;
        function step(ts) {
          if (!startTs) startTs = ts;
          var t = Math.min((ts - startTs) / DURATION, 1);
          t = 1 - Math.pow(1 - t, 3); // ease-out cubic
          var cur = from + (toVal - from) * t;
          _walletRendered = cur;
          window._navLiveVal = cur; // feed live interpolated value to canvas each frame
          el.textContent = '$' + cur.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
          if (t < 1) _walletRaf = requestAnimationFrame(step);
          else { _walletRendered = toVal; _walletRaf = null; }
        }
        _walletRaf = requestAnimationFrame(step);
      }
      // Quiet sync from NAV polls — color intensity scales with move size vs. recent history
      var _prevWalletNav = null;
      var _recentMagWindow = [];
      var _flashTimeout = null;
      window._updateWalletSlot = function(nav) {
        if (!nav) return;
        var el = document.getElementById('ss-wallet-val');
        if (el && _prevWalletNav !== null && nav !== _prevWalletNav) {
          var delta = nav - _prevWalletNav;
          var mag = Math.abs(delta);
          if (mag > 0.01) {
            _recentMagWindow.push(mag);
            if (_recentMagWindow.length > 30) _recentMagWindow.shift();
          }
          // Intensity: floor 0.15 so even tiny ticks show faint hue; scales to 1 at median+ moves
          var intensity = 0.15;
          if (_recentMagWindow.length >= 3) {
            var sorted = _recentMagWindow.slice().sort(function(a,b) { return a-b; });
            var median = sorted[Math.floor(sorted.length / 2)];
            if (median > 0) intensity = Math.min(1, 0.15 + (mag / median) * 0.85);
          }
          if (mag > 0.01) {
            var isGain = delta > 0;
            var rgb = isGain ? '0,255,157' : '255,51,102';
            var col = 'rgba(' + rgb + ',' + intensity + ')';
            var glow = 'rgba(' + rgb + ',' + (intensity * 0.7) + ')';
            el.style.color = col;
            el.style.textShadow = '0 0 16px ' + glow + ', 0 0 4px ' + glow;
            if (_flashTimeout) clearTimeout(_flashTimeout);
            _flashTimeout = setTimeout(function() {
              if (el) { el.style.color = ''; el.style.textShadow = ''; }
            }, 750); // matches rAF animation duration; combos use class-based color separately
          }
        }
        _prevWalletNav = nav;
        _lastWalletVal = nav;
        _animateWallet(nav);
        // Throttle: push at most 1 point per 3s so points are spread across the canvas,
        // not clustered at center (rAF handles visual smoothness; data density doesn't need to match)
        if (!window._navHistory) window._navHistory = [];
        var _nowMs2 = Date.now();
        var _lastH = window._navHistory[window._navHistory.length - 1];
        // Push on every distinct value — no time throttle; rAF smooths visually
        if (!_lastH || _lastH.y !== nav) {
          window._navHistory.push({ x: new Date(_nowMs2).toISOString(), y: nav });
          var _cutoff = new Date(_nowMs2 - 60*1000).toISOString();
          while (window._navHistory.length > 0 && window._navHistory[0].x < _cutoff) window._navHistory.shift();
          try { localStorage.setItem('_navHistory', JSON.stringify(window._navHistory)); } catch(e) {}
        }
      };
      // Trade event: flash color + chip + animate to new value
      window._walletCombo = function(delta) {
        var el = document.getElementById('ss-wallet-val');
        var chip = document.getElementById('ss-wallet-chip');
        if (!el) return;
        var newVal = (_lastWalletVal || 0) + delta;
        _lastWalletVal = newVal;
        var isGain = delta >= 0;
        el.classList.remove('gain', 'loss');
        void el.offsetWidth;
        el.classList.add(isGain ? 'gain' : 'loss');
        _animateWallet(newVal);
        if (chip) {
          chip.textContent = (isGain ? '+$' : '-$') + Math.abs(delta).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
          chip.style.color = isGain ? '#00ff9d' : '#ff3366';
          chip.classList.remove('dmg-active');
          void chip.offsetWidth; // force reflow so re-triggering works
          chip.classList.add('dmg-active');
          setTimeout(function() {
            chip.classList.remove('dmg-active');
            el.classList.remove('gain','loss');
          }, 5000);
        }
      };

      // ── QUEUED EVENTS slot + dropdown ────────────────────────
      var _lastPriceTs = 0;
      window._onPricePoll = function() { _lastPriceTs = Date.now(); };
      var _queueOpen = false;
      function _fmtMs(ms) {
        if (ms <= 0) return 'NOW';
        var s = Math.round(ms / 1000);
        if (s < 60) return s + 's';
        var m = Math.floor(s / 60), ss = s % 60;
        if (m < 60) return m + 'm ' + (ss ? ss + 's' : '');
        var h = Math.floor(m / 60), mm = m % 60;
        return h + 'h ' + (mm ? mm + 'm' : '');
      }
      window._toggleQueueDropdown = function() {
        _queueOpen = !_queueOpen;
        var dd = document.getElementById('queue-dropdown');
        if (!dd) return;
        if (_queueOpen) {
          var slot = document.getElementById('ss-queue');
          var r = slot ? slot.getBoundingClientRect() : {left:0,bottom:0};
          dd.style.left = r.left + 'px';
          dd.style.top  = (r.bottom + 4) + 'px';
          dd.style.display = 'block';
          _renderQueueItems();
        } else {
          dd.style.display = 'none';
        }
        // Close on outside click
        setTimeout(function() {
          function _closeOnOut(e) {
            var dd2 = document.getElementById('queue-dropdown');
            var sl2 = document.getElementById('ss-queue');
            if (dd2 && !dd2.contains(e.target) && sl2 && !sl2.contains(e.target)) {
              dd2.style.display = 'none'; _queueOpen = false;
              document.removeEventListener('click', _closeOnOut);
            }
          }
          document.addEventListener('click', _closeOnOut);
        }, 10);
      };
      function _renderQueueItems() {
        var el = document.getElementById('queue-dropdown-items');
        if (!el) return;
        var now = Date.now();
        var html = '';
        (_queuedActionsData || []).forEach(function(q) {
          var rem  = (q.target_ms || 0) - now;
          var eta  = _fmtMs(rem);
          var past = rem <= 0;
          var col  = past ? 'rgba(255,255,255,.22)' : q.color;
          html += '<div style="display:flex;align-items:baseline;gap:10px;padding:6px 14px;border-bottom:1px solid rgba(255,255,255,.04)">'
            + '<span style="font-size:8px;font-weight:700;color:'+col+';letter-spacing:.12em;min-width:44px">'+ q.badge +'</span>'
            + '<span style="font-size:10px;color:rgba(220,200,255,.8);flex:1">'+ (q.label||'') +'</span>'
            + '<span style="font-size:8px;color:'+(past?'rgba(255,255,255,.2)':col)+';letter-spacing:.06em;white-space:nowrap">'
            + (past ? 'done' : 'in '+eta) +'</span>'
            + '</div>';
        });
        if (!html) html = '<div style="padding:8px 14px;font-size:9px;color:rgba(255,255,255,.25)">no events scheduled</div>';
        el.innerHTML = html;
      }
      function _updateQueueSlot() {
        var now = Date.now();
        var next = null;
        (_queuedActionsData || []).forEach(function(q) {
          var rem = (q.target_ms || 0) - now;
          if (rem > 0 && (next === null || rem < next.rem)) next = {rem:rem, q:q};
        });
        if (next) {
          _ssSet('ss-queue-st', 'ss-active', next.q.badge + ' in ' + _fmtMs(next.rem));
        } else {
          _ssSet('ss-queue-st', '', 'all done');
        }
        if (_queueOpen) _renderQueueItems();  // live-update countdowns while open
      }

      // ── TRADES slot (was CURRENT POS) — fill count from Supabase (updated by _fetchFillCount) ─
      function _updateNavSlot() {
        var nav = window._lastKnownNav;
        if (window._updateWalletSlot && nav) window._updateWalletSlot(nav);
        // fill count is updated by _fetchFillCount on its own interval — nothing extra here
      }

      // ── Callout system — stackable drop-in notifications ────────
      var _calloutRail = document.getElementById('callout-rail');

      function _symColor(sym) {
        var s=sym.replace('/USD','').replace('USD','');
        if(window._TICKER_OVR&&window._TICKER_OVR[s])return window._TICKER_OVR[s];
        var _p=['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
        var h=0; for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))&0xffff; return _p[h%_p.length];
      }

      function _spawnCallout(cfg) {
        var rail = document.getElementById('callout-rail');
        if (!rail) return;

        var symClean = (cfg.sym || '').replace('/USD','').replace('USD','');
        var symCol   = _symColor(symClean);
        var pnlVal   = cfg.pnl ? parseFloat(cfg.pnl.replace(/[^0-9.\-]/g,'')) : null;
        var isPos    = pnlVal !== null ? pnlVal >= 0 : null;
        var pnlCol   = isPos === null ? 'rgba(255,255,255,.6)' : (isPos ? '#00ff9d' : '#ff3366');
        var pnlStr   = pnlVal !== null
          ? (isPos ? '+$' : '-$') + Math.abs(pnlVal).toFixed(2)
          : (cfg.pnl || '');

        var isEvent  = cfg.isEvent || false; // true for MARKET OPEN etc.

        var card = document.createElement('div');
        card.className = 'callout-card';
        if (isEvent) {
          card.innerHTML =
            '<span class="cc-verb" style="color:' + (cfg.col||'#fff') + ';letter-spacing:.2em">' + symClean + '</span>' +
            (cfg.countdown ? '<span class="cc-pnl" style="color:' + (cfg.col||'#fff') + '" id="cc-cd-' + Date.now() + '">' + Math.round(cfg.countdown) + 's</span>' : '');
        } else {
          card.innerHTML =
            '<span class="cc-verb" style="color:rgba(180,140,220,.65)">◆</span>' +
            '<span class="cc-sym" style="color:' + symCol + '">' + symClean + '</span>' +
            (pnlStr ? '<span class="cc-pnl" style="color:' + pnlCol + '">' + pnlStr + '</span>' : '');
        }

        rail.appendChild(card);
        requestAnimationFrame(function() {
          requestAnimationFrame(function() { card.classList.add('cc-show'); });
        });

        // Handle countdown for event callouts
        if (isEvent && cfg.countdown > 0) {
          var cdEl = card.querySelector('[id^="cc-cd-"]');
          var _end = Date.now() + cfg.countdown * 1000;
          (function _tick() {
            if (!cdEl) return;
            var rem = Math.max(0, Math.round((_end - Date.now()) / 1000));
            cdEl.textContent = rem > 0 ? rem + 's' : 'NOW';
            if (rem > 0) requestAnimationFrame(_tick);
          })();
        }

        // Linger then CRT-off exit
        var linger = isEvent ? Math.max(3000, (cfg.countdown||0)*1000 + 1500) : 4500;
        setTimeout(function() {
          card.classList.remove('cc-show');
          card.classList.add('cc-exit');
          setTimeout(function() { if (card.parentNode) card.parentNode.removeChild(card); }, 600);
        }, linger);
      }

      window._fireCallout = function(sym, price, pnl, col, countdown) {
        _spawnCallout({ sym:sym, price:price, pnl:pnl, col:col||'#ff3366', countdown:countdown||0 });
      };
      window._fireEventCallout = function(label, col, countdown) {
        _spawnCallout({ sym:label, col:col, countdown:countdown||0, isEvent:true });
      };

      // ── STRATEGIES slot ───────────────────────────────────────
      // Badge definitions — glyph + glow color per strategy archetype
      var _STRAT_BADGES = {
        'momentum':   { glyph:'▲▲', color:'#00e5ff', label:'Momentum',  desc:'JT 12-1 price momentum · NYSE equities' },
        'crypto':     { glyph:'◈',  color:'#e040fb', label:'Crypto',    desc:'Crypto positions pipeline' },
        'daytrader':  { glyph:'⊕',  color:'#b2ff59', label:'Daytrader', desc:'Intraday ORB · VWAP · RVOL' },
        'reversion':  { glyph:'⇌',  color:'#ff9900', label:'Mean Rev',  desc:'Statistical mean reversion' },
        'sentiment':  { glyph:'◉',  color:'#ff4081', label:'Sentiment', desc:'Alt data · earnings · insider flow' },
        'volatility': { glyph:'⚡', color:'#ff6b35', label:'Volatility',desc:'VIX-based dynamic sizing' },
        'factor':     { glyph:'✦',  color:'#ffd740', label:'Factor',    desc:'Fama-French multi-factor' },
        'macro':      { glyph:'≋',  color:'#00bcd4', label:'Macro',     desc:'Regime · sector rotation' },
        'ensemble':   { glyph:'❋',  color:'#ffffff', label:'Ensemble',  desc:'Meta-allocator across strategies' },
      };

      var _stratDropOpen = false;
      window._toggleStratDropdown = function() {
        _stratDropOpen = !_stratDropOpen;
        var dd = document.getElementById('strat-dropdown');
        if (!dd) return;
        if (_stratDropOpen) {
          _renderStratDropdown();
          var slot = document.getElementById('ss-exposure');
          if (slot) {
            var r = slot.getBoundingClientRect();
            dd.style.top  = (r.bottom + 4) + 'px';
            dd.style.right = (window.innerWidth - r.right) + 'px';
            dd.style.left = 'auto';
          }
          dd.style.display = 'block';
          setTimeout(function() {
            document.addEventListener('click', function _csd(e) {
              if (!dd.contains(e.target) && e.target.id !== 'ss-exposure') {
                _stratDropOpen = false; dd.style.display = 'none';
                document.removeEventListener('click', _csd);
              }
            });
          }, 10);
        } else {
          dd.style.display = 'none';
        }
      };

      function _renderStratDropdown() {
        var items = document.getElementById('strat-dropdown-items');
        if (!items) return;
        var counts = window._etStratCounts ? window._etStratCounts() : {};
        var html = '';
        // Active strategies first, then future ones dimmed
        var allKeys = ['momentum','crypto','daytrader','reversion','sentiment','volatility','factor','macro','ensemble'];
        allKeys.forEach(function(key) {
          var b = _STRAT_BADGES[key]; if (!b) return;
          var n = counts[key] || 0;
          var active = n > 0;
          var dimAlpha = active ? '1' : '0.28';
          var glowStyle = active ? 'filter:drop-shadow(0 0 6px '+b.color+');' : '';
          html += '<div style="display:flex;align-items:center;gap:10px;padding:7px 14px;border-bottom:1px solid rgba(148,0,255,.08);opacity:'+dimAlpha+'">'
            + '<span style="font-size:14px;'+glowStyle+'color:'+b.color+';flex-shrink:0;width:20px;text-align:center">'+b.glyph+'</span>'
            + '<div style="min-width:0;flex:1">'
            + '<div style="font-size:8px;letter-spacing:.12em;color:'+(active?b.color:'rgba(255,255,255,.5)')+';'+(active?'text-shadow:0 0 8px '+b.color+';':'')+';font-weight:700">'+b.label+'</div>'
            + '<div style="font-size:7px;color:rgba(255,255,255,.35);margin-top:1px">'+b.desc+'</div>'
            + '</div>'
            + '<span style="margin-left:auto;font-size:11px;font-weight:700;color:'+(active?b.color:'rgba(255,255,255,.2)')+';'+(active?'text-shadow:0 0 8px '+b.color:'')+'">'+( active ? n : '—' )+'</span>'
            + '</div>';
        });
        items.innerHTML = html;
      }

      function _updateExposureSlot() {
        var counts = window._etStratCounts ? window._etStratCounts() : {};
        var activeStrats = Object.keys(counts).filter(function(k) { return counts[k] > 0; }).length;
        if (activeStrats === 0) { _ssSet('ss-exposure-st', '', '—'); return; }
        _ssSet('ss-exposure-st', 'ss-active', activeStrats + '');
      }

      // ── $/HR slot — dollar volume traded per hour ─────────────
      var _tradeVolTs = [];   // {ts, val} for last-hour fills
      window._recordTradeVol = function(fillAmt) {
        var now = Date.now();
        _tradeVolTs.push({ts: now, val: Math.abs(fillAmt)});
        _tradeVolTs = _tradeVolTs.filter(function(x) { return x.ts > now - 3600000; });
      };
      function _updateTphSlot() {
        var now = Date.now();
        _tradeVolTs = _tradeVolTs.filter(function(x) { return x.ts > now - 3600000; });
        var total = _tradeVolTs.reduce(function(s, x) { return s + x.val; }, 0);
        if (total < 1) { _ssSet('ss-tph-st', '', '—'); return; }
        var fmt = total >= 1000 ? '$' + (total/1000).toFixed(1) + 'k' : '$' + Math.round(total);
        _ssSet('ss-tph-st', 'ss-active', fmt + '/hr');
      }

      // ── Orb-side batch P&L popup ──────────────────────────────
      var _orbPopupTimer = null;
      window._orbBatchPnl = function(pnl) {
        var popup = document.getElementById('orb-batch-popup');
        var canvas = document.getElementById('pulse-canvas');
        if (!popup || !canvas) return;
        var rect = canvas.getBoundingClientRect();
        var ma = document.getElementById('main-area');
        var maRect = ma ? ma.getBoundingClientRect() : rect;
        var orbX = (window._navOrbFracX || 0.5) * rect.width;
        var orbY = (window._navOrbFracY || 0.5) * rect.height;
        // Place popup left of orb; drift animation carries it further left
        var popX = orbX - 70;
        var popY = orbY;
        popup.style.left      = (rect.left - maRect.left + popX) + 'px';
        popup.style.top       = (rect.top  - maRect.top  + popY) + 'px';
        popup.style.animation = 'none';
        void popup.offsetWidth; // force reflow to restart animation
        popup.style.animation = 'orb-popup-drift 5s ease-in forwards';
        var isPos = pnl >= 0;
        popup.style.color = isPos ? '#00ff9d' : '#ff3366';
        popup.textContent = (isPos ? '+$' : '-$') + Math.abs(pnl).toLocaleString('en-US', {minimumFractionDigits:2,maximumFractionDigits:2});
        popup.style.opacity = '1';
        if (_orbPopupTimer) clearTimeout(_orbPopupTimer);
        _orbPopupTimer = setTimeout(function() {
          popup.style.opacity = '0';
        }, 4000);
      };

      // ── System health tracking ────────────────────────────────
      var _apiReqTs = [];
      var _lastFetchLatency = null;
      var _dbOk = true;
      var _origFetch = window.fetch;
      window.fetch = function() {
        var t0 = Date.now();
        _apiReqTs.push(t0);
        _apiReqTs = _apiReqTs.filter(function(t){ return t > t0 - 60000; });
        var p = _origFetch.apply(this, arguments);
        p.then(function() {
          _lastFetchLatency = Date.now() - t0;
          _dbOk = true;
        }).catch(function() { _dbOk = false; });
        return p;
      };

      function _updateSysHealth() {
        // Market data connected
        var mktAge = window._lastLivePriceMs ? (Date.now() - window._lastLivePriceMs) : Infinity;
        var mdDot = document.getElementById('sysh-mktdata');
        var mdVal = document.getElementById('sysh-mktdata-val');
        if (mdDot) mdDot.className = 'sysh-dot ' + (mktAge < 45000 ? 'ok' : mktAge < 120000 ? 'warn' : 'dead');
        if (mdVal) mdVal.textContent = mktAge < 45000 ? 'LIVE' : mktAge < 120000 ? Math.round(mktAge/1000)+'s ago' : 'LOST';

        // DB connected
        var dbDot = document.getElementById('sysh-db');
        var dbVal = document.getElementById('sysh-db-val');
        if (dbDot) dbDot.className = 'sysh-dot ' + (_dbOk ? 'ok' : 'dead');
        if (dbVal) dbVal.textContent = _dbOk ? 'OK' : 'ERR';

        // Heartbeat (runner age) — reuse runner-age text with conditional color
        var hbEl = document.getElementById('runner-age');
        var syshHb = document.getElementById('sysh-hb');
        if (syshHb && hbEl) {
          var _hbTxt = hbEl.textContent || '—';
          syshHb.textContent = _hbTxt;
          var _hbMins = _hbTxt === '<1m' ? 0 : parseFloat(_hbTxt);
          syshHb.style.color = isNaN(_hbMins) ? '' : _hbMins < 5 ? '#00ff9d' : _hbMins < 30 ? '#ffaa00' : '#ff3366';
        }

        // Latency
        var latEl = document.getElementById('sysh-lat');
        if (latEl) {
          var _lat = _lastFetchLatency;
          latEl.textContent = _lat !== null ? _lat + 'ms' : '—';
          latEl.style.color = _lat === null ? '' : _lat < 200 ? '#00ff9d' : _lat < 600 ? '#ffaa00' : '#ff3366';
        }

        // API req/min
        var rpmEl = document.getElementById('sysh-rpm');
        if (rpmEl) {
          var _rpm = _apiReqTs.length;
          rpmEl.textContent = _rpm + '/min';
          rpmEl.style.color = _rpm < 5 ? '#ff3366' : _rpm < 20 ? '#ffaa00' : '#00ff9d';
        }

        // Clock drift: compare extrapolated DB time to system clock
        var driftEl = document.getElementById('sysh-drift');
        if (driftEl && window._lastKnownTs && window._lastLivePriceMs) {
          var tsRaw = window._lastKnownTs; tsRaw = tsRaw.replace(' ','T'); if (/[+-]\d{2}$/.test(tsRaw)) tsRaw += ':00'; else if (!/Z|[+-]\d{2}:\d{2}$/.test(tsRaw)) tsRaw += 'Z';
          var dbNow = new Date(new Date(tsRaw).getTime() + (Date.now() - window._lastLivePriceMs));
          var driftMs = Math.abs(Date.now() - dbNow.getTime() - (Date.now() - window._lastLivePriceMs));
          // drift = difference between DB-derived time and real wall clock, ignoring network lag
          var sysMs = Date.now();
          var dbMs  = new Date(tsRaw).getTime();
          var elapsed = sysMs - window._lastLivePriceMs;
          var derived = dbMs + elapsed;
          var drift = Math.abs(sysMs - derived);
          driftEl.textContent = drift < 1000 ? '<1s' : Math.round(drift/1000) + 's';
          driftEl.style.color = drift < 5000 ? 'rgba(255,255,255,.55)' : '#ffaa00';
        } else {
          if (driftEl) driftEl.textContent = '—';
        }
      }

      // ── Master tick ───────────────────────────────────────────
      function _stratTick() {
        // TRADES slot updated via window._updateTradesSlot from _updateOrbMetrics
        // WALLET slot updated via window._updateWalletSlot from _updateNavDisplays
        _updateQueueSlot();
        _updateNavSlot();
        _updateExposureSlot();
        _updateTphSlot();
        _updateSysHealth();
      }
      _stratTick();
      setInterval(_stratTick, 1000);
    })();

    // (age bars now updated by _updateCard via _pollPositions every 2s)

  })();



// ═══════════════════════════════════════════════════════════════════════════════
// STRATEGIES MODAL
// ═══════════════════════════════════════════════════════════════════════════════

(function() {

var _P = '#ff00cc';
var _D = '#3a3a52';
var _PS2P = '"Press Start 2P",monospace';

// ── SVG icon symbol defs ──────────────────────────────────────────────────────
var _ICON_DEFS = '<svg width="0" height="0" style="position:absolute;overflow:hidden"><defs>'
  + '<symbol id="sm-rebal" viewBox="0 0 48 48"><rect x="4" y="6" width="40" height="36" stroke="'+_D+'" stroke-width="1.5" fill="none"/><line x1="4" y1="16" x2="44" y2="16" stroke="'+_D+'" stroke-width="1.5"/><line x1="15" y1="4" x2="15" y2="10" stroke="'+_D+'" stroke-width="1.5"/><line x1="33" y1="4" x2="33" y2="10" stroke="'+_D+'" stroke-width="1.5"/><rect x="9" y="22" width="4" height="4" fill="'+_P+'"/><rect x="20" y="22" width="4" height="4" fill="'+_P+'"/><rect x="31" y="22" width="4" height="4" fill="'+_P+'"/><rect x="9" y="32" width="4" height="4" fill="'+_P+'"/><rect x="20" y="32" width="4" height="4" fill="'+_P+'"/><rect x="31" y="32" width="4" height="4" fill="'+_D+'"/><rect x="38" y="22" width="4" height="4" fill="'+_D+'"/><rect x="38" y="32" width="4" height="4" fill="'+_D+'"/></symbol>'
  + '<symbol id="sm-universe" viewBox="0 0 48 48"><line x1="8" y1="46" x2="8" y2="28" stroke="'+_D+'" stroke-width="5"/><line x1="20" y1="46" x2="20" y2="18" stroke="'+_D+'" stroke-width="5"/><line x1="32" y1="46" x2="32" y2="34" stroke="'+_D+'" stroke-width="5"/><line x1="44" y1="46" x2="44" y2="8" stroke="'+_P+'" stroke-width="5"/><line x1="4" y1="47" x2="48" y2="47" stroke="'+_D+'" stroke-width="1.5"/><polyline points="40,5 44,1 48,5" fill="none" stroke="'+_P+'" stroke-width="1.5"/></symbol>'
  + '<symbol id="sm-momentum" viewBox="0 0 48 48"><line x1="8" y1="46" x2="8" y2="36" stroke="'+_D+'" stroke-width="4"/><line x1="18" y1="46" x2="18" y2="28" stroke="'+_D+'" stroke-width="4"/><line x1="28" y1="46" x2="28" y2="18" stroke="'+_D+'" stroke-width="4"/><line x1="38" y1="46" x2="38" y2="6" stroke="'+_P+'" stroke-width="4"/><line x1="4" y1="47" x2="48" y2="47" stroke="'+_D+'" stroke-width="1.5"/></symbol>'
  + '<symbol id="sm-filter" viewBox="0 0 48 48"><path d="M4 6 H44 L28 26 V42 L20 38 V26 Z" stroke="'+_D+'" stroke-width="1.5" fill="none" stroke-linejoin="miter"/><line x1="4" y1="3" x2="8" y2="3" stroke="'+_P+'" stroke-width="2"/><line x1="12" y1="3" x2="16" y2="3" stroke="'+_P+'" stroke-width="2"/><line x1="20" y1="3" x2="24" y2="3" stroke="'+_P+'" stroke-width="2"/><line x1="28" y1="3" x2="32" y2="3" stroke="'+_P+'" stroke-width="2"/><line x1="36" y1="3" x2="40" y2="3" stroke="'+_P+'" stroke-width="2"/></symbol>'
  + '<symbol id="sm-size" viewBox="0 0 48 48"><line x1="4" y1="22" x2="44" y2="22" stroke="'+_D+'" stroke-width="1.5"/><line x1="24" y1="22" x2="24" y2="44" stroke="'+_D+'" stroke-width="1.5"/><line x1="16" y1="44" x2="32" y2="44" stroke="'+_D+'" stroke-width="1.5"/><line x1="4" y1="22" x2="4" y2="32" stroke="'+_D+'" stroke-width="1.5"/><line x1="0" y1="32" x2="10" y2="32" stroke="'+_P+'" stroke-width="2"/><line x1="44" y1="22" x2="44" y2="32" stroke="'+_D+'" stroke-width="1.5"/><line x1="38" y1="32" x2="48" y2="32" stroke="'+_P+'" stroke-width="2"/><rect x="22" y="18" width="4" height="4" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-risk" viewBox="0 0 48 48"><path d="M24 2 L42 9 V24 C42 34 34 42 24 46 C14 42 6 34 6 24 V9 Z" stroke="'+_D+'" stroke-width="1.5" fill="none" stroke-linejoin="miter"/><line x1="15" y1="19" x2="33" y2="19" stroke="'+_P+'" stroke-width="1.5" opacity=".35"/><line x1="15" y1="26" x2="33" y2="26" stroke="'+_P+'" stroke-width="1.5" opacity=".65"/><line x1="15" y1="33" x2="33" y2="33" stroke="'+_P+'" stroke-width="1.5"/></symbol>'
  + '<symbol id="sm-execute" viewBox="0 0 48 48"><polygon points="28,2 14,26 24,26 20,48 36,22 26,22" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-wave" viewBox="0 0 48 48"><line x1="2" y1="28" x2="46" y2="28" stroke="'+_D+'" stroke-width="1" stroke-dasharray="3 3"/><polyline points="2,28 10,28 16,46 24,28 30,28" stroke="'+_D+'" stroke-width="1.5" fill="none" stroke-linejoin="miter" stroke-linecap="square"/><line x1="30" y1="28" x2="46" y2="28" stroke="'+_P+'" stroke-width="1.5"/><line x1="16" y1="46" x2="16" y2="32" stroke="'+_P+'" stroke-width="1.5"/><polyline points="12,36 16,30 20,36" stroke="'+_P+'" stroke-width="1.5" fill="none" stroke-linejoin="miter"/></symbol>'
  + '<symbol id="sm-trend" viewBox="0 0 48 48"><line x1="4" y1="44" x2="44" y2="12" stroke="'+_D+'" stroke-width="1.5" stroke-dasharray="3 3"/><polyline points="4,40 12,34 20,28 28,20 38,10 44,6" stroke="'+_P+'" stroke-width="2" fill="none" stroke-linejoin="miter" stroke-linecap="square"/><rect x="41" y="3" width="6" height="6" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-coins" viewBox="0 0 48 48"><ellipse cx="24" cy="38" rx="14" ry="5" stroke="'+_D+'" stroke-width="1.5" fill="none"/><ellipse cx="24" cy="30" rx="14" ry="5" stroke="'+_D+'" stroke-width="1.5" fill="#13131c"/><ellipse cx="24" cy="22" rx="14" ry="5" stroke="'+_P+'" stroke-width="1.5" fill="#13131c"/><rect x="18" y="17" width="3" height="3" fill="'+_P+'"/><rect x="27" y="21" width="3" height="3" fill="'+_P+'"/><line x1="20" y1="25" x2="27" y2="18" stroke="'+_P+'" stroke-width="1.5"/></symbol>'
  + '<symbol id="sm-spread" viewBox="0 0 48 48"><line x1="6" y1="14" x2="42" y2="14" stroke="'+_P+'" stroke-width="2"/><line x1="6" y1="34" x2="42" y2="34" stroke="'+_D+'" stroke-width="2"/><line x1="24" y1="34" x2="24" y2="16" stroke="'+_P+'" stroke-width="1.5" stroke-dasharray="2 2"/><polyline points="20,18 24,13 28,18" stroke="'+_P+'" stroke-width="1.5" fill="none" stroke-linejoin="miter"/></symbol>'
  + '<symbol id="sm-pulse" viewBox="0 0 48 48"><polyline points="2,24 10,24 15,10 21,38 27,16 33,30 37,24 46,24" stroke="'+_P+'" stroke-width="1.5" fill="none" stroke-linejoin="miter" stroke-linecap="square"/></symbol>'
  + '<symbol id="sm-beta" viewBox="0 0 48 48"><line x1="6" y1="44" x2="44" y2="6" stroke="'+_D+'" stroke-width="1.5"/><line x1="6" y1="38" x2="44" y2="18" stroke="'+_P+'" stroke-width="2"/><text x="3" y="14" font-size="11" fill="'+_P+'" font-family="Consolas,monospace" font-weight="700">b&lt;1</text></symbol>'
  + '<symbol id="sm-clock-o" viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" stroke="'+_D+'" stroke-width="1.5" fill="none"/><line x1="24" y1="24" x2="13" y2="20" stroke="'+_P+'" stroke-width="2" stroke-linecap="square"/><line x1="24" y1="24" x2="24" y2="9" stroke="'+_P+'" stroke-width="1.5" stroke-linecap="square"/><rect x="22" y="22" width="4" height="4" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-orb" viewBox="0 0 48 48"><rect x="16" y="18" width="16" height="22" stroke="'+_D+'" stroke-width="1.5" fill="none" stroke-dasharray="3 2"/><rect x="18" y="5" width="12" height="14" fill="'+_P+'"/><line x1="24" y1="2" x2="24" y2="5" stroke="'+_P+'" stroke-width="1.5"/><line x1="24" y1="19" x2="24" y2="40" stroke="'+_D+'" stroke-width="1.5"/></symbol>'
  + '<symbol id="sm-rvol" viewBox="0 0 48 48"><rect x="4" y="34" width="7" height="14" fill="'+_D+'"/><rect x="14" y="28" width="7" height="20" fill="'+_D+'"/><rect x="24" y="22" width="7" height="26" fill="'+_D+'"/><rect x="34" y="8" width="7" height="40" fill="'+_P+'"/><line x1="2" y1="49" x2="46" y2="49" stroke="'+_D+'" stroke-width="1.5"/><line x1="2" y1="22" x2="46" y2="22" stroke="'+_P+'" stroke-width="1" stroke-dasharray="2 3" opacity=".4"/></symbol>'
  + '<symbol id="sm-vwap" viewBox="0 0 48 48"><polyline points="4,42 14,34 24,28 34,20 44,14" stroke="'+_D+'" stroke-width="1.5" fill="none" stroke-linecap="square"/><polyline points="4,40 14,32 24,26 34,22 44,16" stroke="'+_P+'" stroke-width="1.5" fill="none" stroke-dasharray="4 2" stroke-linecap="square"/><rect x="31" y="19" width="6" height="6" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-bracket" viewBox="0 0 48 48"><line x1="6" y1="12" x2="42" y2="12" stroke="'+_P+'" stroke-width="1.5"/><line x1="6" y1="38" x2="42" y2="38" stroke="'+_P+'" stroke-width="1.5" opacity=".35"/><line x1="6" y1="24" x2="42" y2="24" stroke="'+_D+'" stroke-width="1"/><rect x="21" y="21" width="6" height="6" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-clock-c" viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" stroke="'+_D+'" stroke-width="1.5" fill="none"/><line x1="24" y1="24" x2="38" y2="28" stroke="'+_P+'" stroke-width="2" stroke-linecap="square"/><line x1="24" y1="24" x2="24" y2="9" stroke="'+_P+'" stroke-width="1.5" stroke-linecap="square"/><rect x="22" y="22" width="4" height="4" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-longs" viewBox="0 0 48 48"><rect x="4" y="28" width="8" height="20" fill="'+_P+'" opacity=".45"/><rect x="15" y="20" width="8" height="28" fill="'+_P+'" opacity=".6"/><rect x="26" y="24" width="8" height="24" fill="'+_P+'" opacity=".75"/><rect x="37" y="10" width="8" height="38" fill="'+_P+'"/><line x1="2" y1="49" x2="48" y2="49" stroke="'+_D+'" stroke-width="1.5"/></symbol>'
  + '<symbol id="sm-bell" viewBox="0 0 48 48"><path d="M2 44 Q8 44 14 30 Q18 16 24 12 Q30 16 34 30 Q40 44 46 44" stroke="'+_D+'" stroke-width="1.5" fill="none"/><path d="M34 30 Q40 44 46 44" stroke="'+_P+'" stroke-width="2" fill="none"/><line x1="2" y1="44" x2="46" y2="44" stroke="'+_D+'" stroke-width="1.5"/></symbol>'
  + '<symbol id="sm-strike" viewBox="0 0 48 48"><line x1="6" y1="10" x2="42" y2="10" stroke="'+_D+'" stroke-width="1.5"/><line x1="6" y1="18" x2="42" y2="18" stroke="'+_D+'" stroke-width="1.5"/><rect x="4" y="23" width="40" height="8" fill="'+_P+'" opacity=".12"/><line x1="6" y1="27" x2="42" y2="27" stroke="'+_P+'" stroke-width="2"/><line x1="6" y1="36" x2="42" y2="36" stroke="'+_D+'" stroke-width="1.5"/><line x1="6" y1="44" x2="42" y2="44" stroke="'+_D+'" stroke-width="1.5"/><rect x="40" y="24" width="6" height="6" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-sell" viewBox="0 0 48 48"><line x1="24" y1="6" x2="24" y2="34" stroke="'+_P+'" stroke-width="2" stroke-linecap="square"/><polyline points="14,26 24,38 34,26" fill="none" stroke="'+_P+'" stroke-width="2" stroke-linejoin="miter"/><line x1="8" y1="44" x2="40" y2="44" stroke="'+_P+'" stroke-width="2" opacity=".35"/></symbol>'
  + '<symbol id="sm-collect" viewBox="0 0 48 48"><ellipse cx="24" cy="40" rx="14" ry="5" stroke="'+_D+'" stroke-width="1.5" fill="none"/><ellipse cx="24" cy="32" rx="14" ry="5" stroke="'+_P+'" stroke-width="1.5" fill="#13131c"/><polyline points="18,26 24,16 30,26" fill="none" stroke="'+_P+'" stroke-width="2" stroke-linejoin="miter"/><line x1="24" y1="16" x2="24" y2="32" stroke="'+_P+'" stroke-width="1.5"/></symbol>'
  + '<symbol id="sm-cal" viewBox="0 0 48 48"><rect x="4" y="8" width="40" height="36" stroke="'+_D+'" stroke-width="1.5" fill="none"/><line x1="4" y1="18" x2="44" y2="18" stroke="'+_D+'" stroke-width="1.5"/><line x1="15" y1="4" x2="15" y2="12" stroke="'+_D+'" stroke-width="1.5"/><line x1="33" y1="4" x2="33" y2="12" stroke="'+_D+'" stroke-width="1.5"/><rect x="16" y="24" width="16" height="12" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-eps" viewBox="0 0 48 48"><rect x="6" y="28" width="12" height="20" fill="'+_D+'"/><rect x="30" y="10" width="12" height="38" fill="'+_P+'"/><line x1="2" y1="49" x2="46" y2="49" stroke="'+_D+'" stroke-width="1.5"/><polyline points="27,24 31,28 27,32" fill="none" stroke="'+_P+'" stroke-width="1.5" stroke-linejoin="miter"/></symbol>'
  + '<symbol id="sm-entry" viewBox="0 0 48 48"><polyline points="2,44 14,38 26,32 38,22 46,16" stroke="'+_D+'" stroke-width="1.5" fill="none" stroke-linecap="square"/><rect x="22" y="28" width="8" height="8" fill="'+_P+'"/><line x1="26" y1="28" x2="26" y2="14" stroke="'+_P+'" stroke-width="1.5" stroke-dasharray="2 2"/><polyline points="22,17 26,11 30,17" fill="none" stroke="'+_P+'" stroke-width="1.5" stroke-linejoin="miter"/></symbol>'
  + '<symbol id="sm-hold" viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" stroke="'+_D+'" stroke-width="1.5" fill="none"/><path d="M24 6 A18 18 0 0 1 42 24" stroke="'+_P+'" stroke-width="2" fill="none" stroke-linecap="square"/><line x1="24" y1="24" x2="24" y2="9" stroke="'+_P+'" stroke-width="1.5" stroke-linecap="square"/><line x1="24" y1="24" x2="38" y2="24" stroke="'+_P+'" stroke-width="1.5" stroke-linecap="square"/><rect x="22" y="22" width="4" height="4" fill="'+_P+'"/></symbol>'
  + '<symbol id="sm-rotate" viewBox="0 0 48 48"><path d="M10 24 A14 14 0 1 1 24 38" stroke="'+_P+'" stroke-width="1.5" fill="none"/><polyline points="20,36 24,40 20,44" fill="none" stroke="'+_P+'" stroke-width="1.5" stroke-linejoin="miter"/></symbol>'
  + '</defs></svg>';

// ── Strategy definitions ───────────────────────────────────────────────────────
var _STRAT_DEFS = [
  { key:'momentum', label:'MOMENTUM', status:'paper',
    generic:'Rank assets by recent price performance, buy top performers, rebalance on a fixed schedule.',
    template:'Every {rebalance_days} days, rank {universe_size} stocks by their {lookback_months}-month return — skipping the most recent {skip_months} month — buy the top {top_n} at equal weight. Halt if a position exceeds {max_position}, daily loss hits {daily_dd_halt}, or total drawdown reaches {total_dd_halt}.',
    chain:[
      {id:'sm-rebal',    pkey:'rebalance_days',  lbl:'rebalance'},
      {id:'sm-universe', pkey:'universe_size',   lbl:'universe'},
      {id:'sm-momentum', pkey:'lookback_months', lbl:'momentum'},
      {id:'sm-filter',   pkey:'top_n',           lbl:'rank & filter'},
      {id:'sm-size',     pkey:'max_position',    lbl:'equal weight'},
      {id:'sm-risk',     pkey:'total_dd_halt',   lbl:'risk gate'},
      {id:'sm-execute',  pkey:'slippage_bps',    lbl:'execute'},
    ]
  },
  { key:'mean_reversion', label:'MEAN REVERSION', status:'research',
    generic:'Buy assets that have fallen significantly below their historical average, expecting them to snap back.',
    template:'Screen {universe_size} stocks for those trading more than {zscore_threshold} below their {lookback_days}-day rolling mean. Stop-loss at {stop_loss} per position.',
    chain:[
      {id:'sm-universe', pkey:'universe_size',    lbl:'universe'},
      {id:'sm-wave',     pkey:'zscore_threshold', lbl:'deviation'},
      {id:'sm-filter',   pkey:'lookback_days',    lbl:'threshold'},
      {id:'sm-size',     pkey:'max_position',     lbl:'size'},
      {id:'sm-risk',     pkey:'stop_loss',        lbl:'risk gate'},
      {id:'sm-execute',  pkey:'slippage_bps',     lbl:'execute'},
    ]
  },
  { key:'trend_following', label:'TREND FOLLOWING', status:'research',
    generic:'Hold assets trending upward, rotate out when the trend breaks.',
    template:'Hold ETFs trading above their {ma_period}-day moving average, rank by trend strength, rotate every {rebalance_freq} days. Exit if drawdown hits {total_dd_halt}.',
    chain:[
      {id:'sm-longs',    pkey:'universe_size',  lbl:'asset classes'},
      {id:'sm-trend',    pkey:'ma_period',      lbl:'trend filter'},
      {id:'sm-universe', pkey:'universe_size',  lbl:'rank'},
      {id:'sm-rotate',   pkey:'rebalance_freq', lbl:'rotate'},
      {id:'sm-risk',     pkey:'total_dd_halt',  lbl:'risk gate'},
      {id:'sm-execute',  pkey:'slippage_bps',   lbl:'execute'},
    ]
  },
  { key:'carry', label:'CARRY', status:'research',
    generic:'Hold assets offering the highest yield and rotate when yield relationships shift.',
    template:'Compare yield across {universe_size} assets, rank by yield spread, hold top {top_n}, rotate every {rebalance_freq} days. Exit if drawdown hits {total_dd_halt}.',
    chain:[
      {id:'sm-longs',    pkey:'universe_size',  lbl:'asset classes'},
      {id:'sm-coins',    pkey:'universe_size',  lbl:'measure yield'},
      {id:'sm-spread',   pkey:'top_n',          lbl:'differential'},
      {id:'sm-rotate',   pkey:'rebalance_freq', lbl:'rotate'},
      {id:'sm-risk',     pkey:'total_dd_halt',  lbl:'risk gate'},
      {id:'sm-execute',  pkey:'slippage_bps',   lbl:'execute'},
    ]
  },
  { key:'quality_low_vol', label:'QUALITY / LOW VOL', status:'research',
    generic:'Hold high-quality, low-volatility stocks that hold up better when markets get rough.',
    template:'Screen {universe_size} stocks by quality score, filter to beta under {max_beta}, hold the top {top_n}, rebalance every {rebalance_freq} days. Exit if drawdown hits {total_dd_halt}.',
    chain:[
      {id:'sm-universe', pkey:'universe_size',  lbl:'universe'},
      {id:'sm-pulse',    pkey:'universe_size',  lbl:'quality score'},
      {id:'sm-beta',     pkey:'max_beta',       lbl:'low beta'},
      {id:'sm-filter',   pkey:'top_n',          lbl:'filter'},
      {id:'sm-risk',     pkey:'total_dd_halt',  lbl:'risk gate'},
      {id:'sm-execute',  pkey:'slippage_bps',   lbl:'execute'},
    ]
  },
  { key:'daytrader', label:'INTRADAY', status:'research',
    generic:'Trade short-term price breakouts within a single session, flat before the close.',
    template:'At {market_open}, wait for an opening range breakout confirmed by RVOL over {rvol_threshold} and VWAP alignment. Enter with a {rr_ratio}:1 R:R bracket — stop {stop_pct}, target {target_pct}. Flat by {market_close}.',
    chain:[
      {id:'sm-clock-o',  pkey:'market_open',    lbl:'open'},
      {id:'sm-orb',      pkey:'rvol_threshold', lbl:'breakout'},
      {id:'sm-rvol',     pkey:'rvol_threshold', lbl:'confirm RVOL'},
      {id:'sm-vwap',     pkey:'rr_ratio',       lbl:'VWAP align'},
      {id:'sm-bracket',  pkey:'rr_ratio',       lbl:'bracket'},
      {id:'sm-clock-c',  pkey:'market_close',   lbl:'flat by close'},
    ]
  },
  { key:'volatility_selling', label:'VOL SELLING', status:'research',
    generic:'Collect option premium by writing options against existing positions when implied volatility is elevated.',
    template:'When IV rank exceeds {iv_rank_min}, sell an OTM option at {delta_target} delta with {dte_entry} DTE against existing longs. Close at {profit_target} of max profit or when {dte_close} DTE remains.',
    chain:[
      {id:'sm-longs',    pkey:'iv_rank_min',   lbl:'positions'},
      {id:'sm-bell',     pkey:'iv_rank_min',   lbl:'IV rank'},
      {id:'sm-strike',   pkey:'delta_target',  lbl:'select strike'},
      {id:'sm-sell',     pkey:'dte_entry',     lbl:'write option'},
      {id:'sm-collect',  pkey:'profit_target', lbl:'collect / roll'},
    ]
  },
  { key:'earnings_drift', label:'EARNINGS DRIFT', status:'research',
    generic:'Buy stocks that beat earnings expectations and hold through the post-announcement drift period.',
    template:'Enter {entry_delay} day after a positive EPS surprise above {surprise_min}. Hold for {hold_min}–{hold_max} days to capture the drift. Exit if drawdown hits {total_dd_halt}.',
    chain:[
      {id:'sm-cal',      pkey:'entry_delay',   lbl:'event date'},
      {id:'sm-eps',      pkey:'surprise_min',  lbl:'eps surprise'},
      {id:'sm-entry',    pkey:'entry_delay',   lbl:'entry'},
      {id:'sm-hold',     pkey:'hold_max',      lbl:'hold'},
      {id:'sm-risk',     pkey:'total_dd_halt', lbl:'risk gate'},
      {id:'sm-execute',  pkey:'slippage_bps',  lbl:'execute'},
    ]
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function _pval(stratKey, paramKey) {
  var sp = (window._TND && window._TND.STRATEGY_PARAMS) || {};
  var p = (sp[stratKey] || {})[paramKey];
  if (!p || p.value === null || p.value === undefined) return '—';
  return p.value + (p.unit ? ' ' + p.unit : '');
}

function _fillTemplate(tmpl, stratKey) {
  return tmpl.replace(/\{([^}]+)\}/g, function(_, key) {
    var sp = (window._TND && window._TND.STRATEGY_PARAMS) || {};
    var p = (sp[stratKey] || {})[key];
    if (!p || p.value === null || p.value === undefined)
      return '<span style="color:'+_D+'">—</span>';
    var v = p.value + (p.unit ? ' ' + p.unit : '');
    return '<span style="color:'+_P+';font-weight:700">' + v + '</span>';
  });
}

function _statusBadge(status) {
  var col = status === 'paper' ? _P : status === 'live' ? '#00ff9d' : _D;
  return '<span style="font-family:'+_PS2P+';font-size:6px;letter-spacing:.08em;color:'+col+';border:1px solid '+col+';padding:2px 5px;margin-left:8px;vertical-align:middle;opacity:.85">'+status+'</span>';
}

function _buildRow(def) {
  var sp = (window._TND && window._TND.STRATEGY_PARAMS) || {};
  var sparams = sp[def.key] || {};

  var chainHtml = def.chain.map(function(n, i) {
    var p = sparams[n.pkey];
    var val = (p && p.value !== null && p.value !== undefined) ? p.value + (p.unit ? ' ' + p.unit : '') : '—';
    var arrow = i < def.chain.length - 1
      ? '<div style="padding:0 2px;margin-bottom:22px;flex-shrink:0"><svg width="22" height="14" viewBox="0 0 22 14"><line x1="0" y1="7" x2="14" y2="7" stroke="'+_D+'" stroke-width="1.5"/><polyline points="10,2 18,7 10,12" fill="none" stroke="'+_D+'" stroke-width="1.5" stroke-linejoin="round"/></svg></div>'
      : '';
    return '<div style="display:flex;flex-direction:column;align-items:center;gap:5px;padding:0 3px">'
      + '<svg width="42" height="42"><use href="#'+n.id+'"/></svg>'
      + '<span style="font-family:'+_PS2P+';font-size:6px;color:'+_P+';white-space:nowrap;letter-spacing:.04em">'+val+'</span>'
      + '<span style="font-family:'+_PS2P+';font-size:5.5px;color:#7070a0;text-transform:uppercase;letter-spacing:.1em;white-space:nowrap;text-align:center">'+n.lbl+'</span>'
      + '</div>' + arrow;
  }).join('');

  return '<div style="display:flex;align-items:center;gap:0;padding:12px 0;border-bottom:1px solid #18182a">'
    + '<div class="_strat-name-btn" data-key="'+def.key+'" style="font-family:'+_PS2P+';font-size:6.5px;letter-spacing:.16em;text-transform:uppercase;color:#9090b8;min-width:110px;max-width:110px;flex-shrink:0;cursor:pointer;line-height:1.6;padding-right:12px" onmouseover="this.style.color=\'#ff00cc\'" onmouseout="this.style.color=\'#9090b8\'">'
    + def.label + _statusBadge(def.status)
    + '</div>'
    + '<div style="display:flex;align-items:center;overflow-x:auto;padding:4px 0">'+chainHtml+'</div>'
    + '</div>';
}

// ── Open / close ──────────────────────────────────────────────────────────────
window._openStrategiesModal = function() {
  var bg   = document.getElementById('strat-modal-bg');
  var body = document.getElementById('strat-modal-body');
  if (!bg || !body) return;

  if (!bg._built) {
    document.body.insertAdjacentHTML('afterbegin', _ICON_DEFS);
    body.innerHTML = _STRAT_DEFS.map(_buildRow).join('');
    body.querySelectorAll('._strat-name-btn').forEach(function(el) {
      el.addEventListener('click', function() {
        window._openStratDetail(el.getAttribute('data-key'));
      });
    });
    bg._built = true;
  }

  bg.style.display = 'flex';
  document.addEventListener('keydown', _smEsc);
};

window._closeStrategiesModal = function() {
  var bg = document.getElementById('strat-modal-bg');
  if (bg) bg.style.display = 'none';
  document.removeEventListener('keydown', _smEsc);
};

function _smEsc(e) { if (e.key === 'Escape') window._closeStrategiesModal(); }

(function() {
  var bg = document.getElementById('strat-modal-bg');
  if (bg) bg.addEventListener('click', function(e) {
    if (e.target === this) window._closeStrategiesModal();
  });
})();

// ── Detail popup ──────────────────────────────────────────────────────────────
window._openStratDetail = function(key) {
  var def = null;
  for (var i = 0; i < _STRAT_DEFS.length; i++) {
    if (_STRAT_DEFS[i].key === key) { def = _STRAT_DEFS[i]; break; }
  }
  if (!def) return;
  document.getElementById('sd-name').textContent    = def.label;
  document.getElementById('sd-generic').textContent = def.generic;
  document.getElementById('sd-case').innerHTML      = _fillTemplate(def.template, key);
  var bg = document.getElementById('strat-detail-bg');
  bg.style.display = 'flex';
  document.addEventListener('keydown', _sdEsc);
};

window._closeStratDetail = function() {
  var bg = document.getElementById('strat-detail-bg');
  if (bg) bg.style.display = 'none';
  document.removeEventListener('keydown', _sdEsc);
};

function _sdEsc(e) { if (e.key === 'Escape') window._closeStratDetail(); }

(function() {
  var bg = document.getElementById('strat-detail-bg');
  if (bg) bg.addEventListener('click', function(e) {
    if (e.target === this) window._closeStratDetail();
  });
})();

})();

