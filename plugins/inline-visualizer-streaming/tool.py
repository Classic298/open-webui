"""
title: Inline Visualizer (Streaming)
author: Classic298
version: 2.0.0
description: Renders interactive HTML/SVG visualizations inline in chat. Supports a STREAMING mode — the tool emits an empty wrapper, then parasitically tails the model's streaming text for a ```visualization code fence and renders it live token-by-token. Requires "iframe Sandbox Allow Same Origin" to be enabled in Open WebUI Settings → Interface. For design instructions, the model should call view_skill("visualize").
"""

import re
from typing import Literal

from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Injected CSS — Theme variables (light default, dark via data-theme)
# ---------------------------------------------------------------------------

THEME_CSS = """
:root {
  --color-text-primary: #1F2937;
  --color-text-secondary: #6B7280;
  --color-text-tertiary: #9CA3AF;
  --color-text-info: #2563EB;
  --color-text-success: #059669;
  --color-text-warning: #D97706;
  --color-text-danger: #DC2626;
  --color-bg-primary: #FFFFFF;
  --color-bg-secondary: #F9FAFB;
  --color-bg-tertiary: #F3F4F6;
  --color-border-tertiary: rgba(0,0,0,0.15);
  --color-border-secondary: rgba(0,0,0,0.3);
  --color-border-primary: rgba(0,0,0,0.4);
  --font-sans: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'SF Mono', Menlo, Consolas, monospace;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  /* --- Color ramp variables (light) --- */
  --ramp-purple-fill:#EEEDFE; --ramp-purple-stroke:#534AB7; --ramp-purple-th:#3C3489; --ramp-purple-ts:#534AB7;
  --ramp-teal-fill:#E1F5EE;   --ramp-teal-stroke:#0F6E56;   --ramp-teal-th:#085041;   --ramp-teal-ts:#0F6E56;
  --ramp-coral-fill:#FAECE7;  --ramp-coral-stroke:#993C1D;  --ramp-coral-th:#712B13;  --ramp-coral-ts:#993C1D;
  --ramp-pink-fill:#FBEAF0;   --ramp-pink-stroke:#993556;   --ramp-pink-th:#72243E;   --ramp-pink-ts:#993556;
  --ramp-gray-fill:#F1EFE8;   --ramp-gray-stroke:#5F5E5A;   --ramp-gray-th:#444441;   --ramp-gray-ts:#5F5E5A;
  --ramp-blue-fill:#E6F1FB;   --ramp-blue-stroke:#185FA5;   --ramp-blue-th:#0C447C;   --ramp-blue-ts:#185FA5;
  --ramp-green-fill:#EAF3DE;  --ramp-green-stroke:#3B6D11;  --ramp-green-th:#27500A;  --ramp-green-ts:#3B6D11;
  --ramp-amber-fill:#FAEEDA;  --ramp-amber-stroke:#854F0B;  --ramp-amber-th:#633806;  --ramp-amber-ts:#854F0B;
  --ramp-red-fill:#FCEBEB;    --ramp-red-stroke:#A32D2D;    --ramp-red-th:#791F1F;    --ramp-red-ts:#A32D2D;
  /* --- Common aliases (catch hallucinated variable names) --- */
  /* Text */
  --fg: var(--color-text-primary);
  --text: var(--color-text-primary);
  --foreground: var(--color-text-primary);
  --text-primary: var(--color-text-primary);
  --text-color: var(--color-text-primary);
  --color-text: var(--color-text-primary);
  --color-foreground: var(--color-text-primary);
  --body-color: var(--color-text-primary);
  --muted: var(--color-text-secondary);
  --muted-foreground: var(--color-text-secondary);
  --text-muted: var(--color-text-secondary);
  --text-secondary: var(--color-text-secondary);
  --secondary: var(--color-text-secondary);
  --subtle: var(--color-text-tertiary);
  --text-tertiary: var(--color-text-tertiary);
  /* Backgrounds */
  --bg: var(--color-bg-primary);
  --background: var(--color-bg-primary);
  --bg-primary: var(--color-bg-primary);
  --body-bg: var(--color-bg-primary);
  --color-bg: var(--color-bg-primary);
  --surface: var(--color-bg-secondary);
  --surface-1: var(--color-bg-secondary);
  --surface-2: var(--color-bg-tertiary);
  --card: var(--color-bg-secondary);
  --card-bg: var(--color-bg-secondary);
  --card-foreground: var(--color-text-primary);
  --card-background: var(--color-bg-secondary);
  --popover: var(--color-bg-secondary);
  --popover-foreground: var(--color-text-primary);
  --hover: rgba(0,0,0,0.04);
  /* Borders */
  --border: var(--color-border-tertiary);
  --border-color: var(--color-border-tertiary);
  --divider: var(--color-border-tertiary);
  --separator: var(--color-border-tertiary);
  --input: var(--color-border-tertiary);
  --ring: var(--color-border-secondary);
  /* Accent / Primary (AI uses --accent as brand color, not surface) */
  --primary: #6c2eb9;
  --primary-foreground: #ffffff;
  --accent: #6c2eb9;
  --accent-foreground: #ffffff;
}
:root[data-theme="dark"] {
  --color-text-primary: #E5E7EB;
  --color-text-secondary: #9CA3AF;
  --color-text-tertiary: #6B7280;
  --color-text-info: #60A5FA;
  --color-text-success: #34D399;
  --color-text-warning: #FBBF24;
  --color-text-danger: #F87171;
  --color-bg-primary: #1A1A1A;
  --color-bg-secondary: #262626;
  --color-bg-tertiary: #111111;
  --color-border-tertiary: rgba(255,255,255,0.15);
  --color-border-secondary: rgba(255,255,255,0.3);
  --color-border-primary: rgba(255,255,255,0.4);
  --ramp-purple-fill:#3C3489; --ramp-purple-stroke:#AFA9EC; --ramp-purple-th:#CECBF6; --ramp-purple-ts:#AFA9EC;
  --ramp-teal-fill:#085041;   --ramp-teal-stroke:#5DCAA5;   --ramp-teal-th:#9FE1CB;   --ramp-teal-ts:#5DCAA5;
  --ramp-coral-fill:#712B13;  --ramp-coral-stroke:#F0997B;  --ramp-coral-th:#F5C4B3;  --ramp-coral-ts:#F0997B;
  --ramp-pink-fill:#72243E;   --ramp-pink-stroke:#ED93B1;   --ramp-pink-th:#F4C0D1;   --ramp-pink-ts:#ED93B1;
  --ramp-gray-fill:#444441;   --ramp-gray-stroke:#B4B2A9;   --ramp-gray-th:#D3D1C7;   --ramp-gray-ts:#B4B2A9;
  --ramp-blue-fill:#0C447C;   --ramp-blue-stroke:#85B7EB;   --ramp-blue-th:#B5D4F4;   --ramp-blue-ts:#85B7EB;
  --ramp-green-fill:#27500A;  --ramp-green-stroke:#97C459;  --ramp-green-th:#C0DD97;  --ramp-green-ts:#97C459;
  --ramp-amber-fill:#633806;  --ramp-amber-stroke:#EF9F27;  --ramp-amber-th:#FAC775;  --ramp-amber-ts:#EF9F27;
  --ramp-red-fill:#791F1F;    --ramp-red-stroke:#F09595;    --ramp-red-th:#F7C1C1;    --ramp-red-ts:#F09595;
  /* --- Common aliases (dark overrides) --- */
  --text: var(--color-text-primary);
  --foreground: var(--color-text-primary);
  --text-primary: var(--color-text-primary);
  --text-color: var(--color-text-primary);
  --color-text: var(--color-text-primary);
  --body-color: var(--color-text-primary);
  --muted: var(--color-text-secondary);
  --muted-foreground: var(--color-text-secondary);
  --text-muted: var(--color-text-secondary);
  --text-secondary: var(--color-text-secondary);
  --secondary: var(--color-text-secondary);
  --subtle: var(--color-text-tertiary);
  --text-tertiary: var(--color-text-tertiary);
  --bg: var(--color-bg-primary);
  --background: var(--color-bg-primary);
  --bg-primary: var(--color-bg-primary);
  --body-bg: var(--color-bg-primary);
  --color-bg: var(--color-bg-primary);
  --surface: var(--color-bg-secondary);
  --surface-1: var(--color-bg-secondary);
  --surface-2: var(--color-bg-tertiary);
  --card: var(--color-bg-secondary);
  --card-bg: var(--color-bg-secondary);
  --card-foreground: var(--color-text-primary);
  --card-background: var(--color-bg-secondary);
  --popover: var(--color-bg-secondary);
  --popover-foreground: var(--color-text-primary);
  --hover: rgba(255,255,255,0.06);
  --border: var(--color-border-tertiary);
  --border-color: var(--color-border-tertiary);
  --divider: var(--color-border-tertiary);
  --separator: var(--color-border-tertiary);
  --input: var(--color-border-tertiary);
  --ring: var(--color-border-secondary);
  --primary: #a78bfa;
  --primary-foreground: #1A1A1A;
  --accent: #a78bfa;
  --accent-foreground: #ffffff;
}
"""

# ---------------------------------------------------------------------------
# Injected CSS — SVG utility classes + color ramp selectors
# ---------------------------------------------------------------------------

SVG_CLASSES = """
/* --- Text --- */
.t  { font: 400 14px/1.4 var(--font-sans); fill: var(--color-text-primary); }
.ts { font: 400 12px/1.4 var(--font-sans); fill: var(--color-text-secondary); }
.th { font: 500 14px/1.4 var(--font-sans); fill: var(--color-text-primary); }

/* --- Shapes --- */
.box    { fill: var(--color-bg-secondary); stroke: var(--color-border-tertiary); stroke-width: 0.5; }
.node   { cursor: pointer; }
.node:hover { opacity: 0.85; }
.arr    { stroke: var(--color-border-secondary); stroke-width: 1.5; fill: none; }
.leader { stroke: var(--color-text-tertiary); stroke-width: 0.5; stroke-dasharray: 3 2; fill: none; }

/* --- Color ramp selectors (fill/stroke adapt via CSS vars) --- */
.c-purple>rect,.c-purple>circle,.c-purple>ellipse{fill:var(--ramp-purple-fill);stroke:var(--ramp-purple-stroke);stroke-width:.5}
.c-purple>.th{fill:var(--ramp-purple-th)!important} .c-purple>.ts{fill:var(--ramp-purple-ts)!important}
.c-teal>rect,.c-teal>circle,.c-teal>ellipse{fill:var(--ramp-teal-fill);stroke:var(--ramp-teal-stroke);stroke-width:.5}
.c-teal>.th{fill:var(--ramp-teal-th)!important} .c-teal>.ts{fill:var(--ramp-teal-ts)!important}
.c-coral>rect,.c-coral>circle,.c-coral>ellipse{fill:var(--ramp-coral-fill);stroke:var(--ramp-coral-stroke);stroke-width:.5}
.c-coral>.th{fill:var(--ramp-coral-th)!important} .c-coral>.ts{fill:var(--ramp-coral-ts)!important}
.c-pink>rect,.c-pink>circle,.c-pink>ellipse{fill:var(--ramp-pink-fill);stroke:var(--ramp-pink-stroke);stroke-width:.5}
.c-pink>.th{fill:var(--ramp-pink-th)!important} .c-pink>.ts{fill:var(--ramp-pink-ts)!important}
.c-gray>rect,.c-gray>circle,.c-gray>ellipse{fill:var(--ramp-gray-fill);stroke:var(--ramp-gray-stroke);stroke-width:.5}
.c-gray>.th{fill:var(--ramp-gray-th)!important} .c-gray>.ts{fill:var(--ramp-gray-ts)!important}
.c-blue>rect,.c-blue>circle,.c-blue>ellipse{fill:var(--ramp-blue-fill);stroke:var(--ramp-blue-stroke);stroke-width:.5}
.c-blue>.th{fill:var(--ramp-blue-th)!important} .c-blue>.ts{fill:var(--ramp-blue-ts)!important}
.c-green>rect,.c-green>circle,.c-green>ellipse{fill:var(--ramp-green-fill);stroke:var(--ramp-green-stroke);stroke-width:.5}
.c-green>.th{fill:var(--ramp-green-th)!important} .c-green>.ts{fill:var(--ramp-green-ts)!important}
.c-amber>rect,.c-amber>circle,.c-amber>ellipse{fill:var(--ramp-amber-fill);stroke:var(--ramp-amber-stroke);stroke-width:.5}
.c-amber>.th{fill:var(--ramp-amber-th)!important} .c-amber>.ts{fill:var(--ramp-amber-ts)!important}
.c-red>rect,.c-red>circle,.c-red>ellipse{fill:var(--ramp-red-fill);stroke:var(--ramp-red-stroke);stroke-width:.5}
.c-red>.th{fill:var(--ramp-red-th)!important} .c-red>.ts{fill:var(--ramp-red-ts)!important}
"""

# ---------------------------------------------------------------------------
# Injected CSS — Base resets & interactive element styles
# ---------------------------------------------------------------------------

BASE_STYLES = """
* { box-sizing: border-box; margin: 0; font-family: var(--font-sans); }
html, body { overflow: hidden; }
body { background: transparent; color: var(--color-text-primary); line-height: 1.5; padding: 8px; }
svg { overflow: visible; }
svg text { fill: var(--color-text-primary); }
h1 { font-size: 22px; font-weight: 500; color: var(--color-text-primary); margin-bottom: 12px; }
h2 { font-size: 18px; font-weight: 500; color: var(--color-text-primary); margin-bottom: 8px; }
h3 { font-size: 16px; font-weight: 500; color: var(--color-text-primary); margin-bottom: 6px; }
p  { font-size: 14px; color: var(--color-text-secondary); margin-bottom: 8px; }
button {
  background: transparent; border: 0.5px solid var(--color-border-secondary);
  border-radius: var(--radius-md); padding: 6px 14px; font-size: 13px;
  color: var(--color-text-primary); cursor: pointer; font-family: var(--font-sans);
}
button:hover { background: var(--color-bg-secondary); }
button.active { background: var(--color-bg-secondary); border-color: var(--color-border-primary); }
input[type="range"] {
  -webkit-appearance: none; width: 100%; height: 4px;
  background: var(--color-border-tertiary); border-radius: 2px; outline: none;
}
input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%;
  background: var(--color-bg-primary); border: 0.5px solid var(--color-border-secondary); cursor: pointer;
}
select {
  background: var(--color-bg-secondary); border: 0.5px solid var(--color-border-tertiary);
  border-radius: var(--radius-md); padding: 6px 10px; font-size: 13px;
  color: var(--color-text-primary); font-family: var(--font-sans);
}
code {
  font-family: var(--font-mono); font-size: 13px; background: var(--color-bg-tertiary);
  padding: 2px 6px; border-radius: 4px;
}
#iv-dl-wrap{position:fixed;top:4px;right:4px;z-index:9999}
#iv-dl-btn{width:26px;height:26px;padding:0;display:flex;align-items:center;justify-content:center;
  opacity:0.3;border-color:var(--color-border-tertiary);background:var(--color-bg-primary)}
#iv-dl-btn:hover{opacity:0.9;background:var(--color-bg-secondary)}
#iv-dl-btn svg{width:14px;height:14px;stroke:var(--color-text-secondary);fill:none;
  stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
/* --- Print ---
 * overflow:hidden on html/body clips content in print (needed on screen
 * for iframe sizing). Chart.js canvas scaling is handled by JS beforeprint
 * handler in BODY_SCRIPTS — it directly mutates inline styles that CSS
 * cannot reliably override in Chrome's print engine.
 */
@media print {
  @page { margin: 12mm; }
  html, body { overflow: visible !important; height: auto !important;
    background: #fff !important; }
  body { padding: 4px !important; }
  #iv-dl-wrap { display: none !important; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""

# ---------------------------------------------------------------------------
# Injected JavaScript — theme detection (head), height reporting & bridges (body)
# ---------------------------------------------------------------------------

# Runs in <head> BEFORE any user content so CSS variables resolve to the
# correct theme when model scripts read them at parse time.
# Also sets up a MutationObserver to react to live theme switches.
THEME_DETECTION_SCRIPT = """
<script>
(function() {
  function detectTheme(root) {
    return root.classList.contains('dark')
      || root.getAttribute('data-theme') === 'dark'
      || getComputedStyle(root).colorScheme === 'dark';
  }

  function applyTheme(isDark) {
    var theme = isDark ? 'dark' : 'light';
    if (document.documentElement.getAttribute('data-theme') === theme) return;
    document.documentElement.setAttribute('data-theme', theme);
    // Re-render Chart.js instances with updated theme colors
    if (window.Chart && Chart.instances) {
      var s = getComputedStyle(document.documentElement);
      var tc = s.getPropertyValue('--color-text-secondary').trim();
      var gc = s.getPropertyValue('--color-border-tertiary').trim();
      Chart.defaults.color = tc;
      Chart.defaults.borderColor = gc;
      Object.values(Chart.instances).forEach(function(chart) {
        Object.values(chart.options.scales || {}).forEach(function(scale) {
          if (scale.ticks) scale.ticks.color = tc;
          if (scale.grid) scale.grid.color = gc;
        });
        var leg = (chart.options.plugins || {}).legend;
        if (leg && leg.labels) leg.labels.color = tc;
        chart.update();
      });
    }
  }

  try {
    var p = parent.document.documentElement;
    applyTheme(detectTheme(p));
    // Watch for live theme changes on the parent
    new MutationObserver(function() {
      applyTheme(detectTheme(p));
    }).observe(p, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] });
  } catch(e) {
    // No same-origin access — fall back to OS preference
    var mq = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
    if (mq) {
      applyTheme(mq.matches);
      mq.addEventListener('change', function(e) { applyTheme(e.matches); });
    }
  }
})();
</script>
"""

BODY_SCRIPTS = """
<script>
// --- Height reporting ---
var _rh_last = 0;          // last reported height
var _rh_consecutive = 0;   // consecutive small-growth reports
var _rh_raf = 0;           // rAF id for debouncing ResizeObserver

function reportHeight() {
  var b = document.body;
  // Measure SVG overflow (content beyond viewBox) before collapsing body,
  // since getBoundingClientRect needs normal layout.
  var svgOverflow = 0;
  document.querySelectorAll('svg[viewBox]').forEach(function(svg) {
    try {
      var bbox = svg.getBBox();
      var vb = svg.viewBox.baseVal;
      if (vb && vb.width > 0 && vb.height > 0) {
        var overflow = bbox.y + bbox.height - (vb.y + vb.height);
        if (overflow > 0) {
          var scale = svg.getBoundingClientRect().width / vb.width;
          svgOverflow += Math.ceil(overflow * scale);
        }
      }
    } catch(e) {}
  });

  // Neutralize viewport-relative heights (100vh etc.) during measurement.
  // In an auto-sizing iframe, vh tracks iframe height → creates feedback loops.
  // Force body and all direct children to height:auto so we measure true content.
  var savedBody = b.style.cssText;
  b.style.setProperty('height', 'auto', 'important');
  b.style.setProperty('overflow', 'visible', 'important');
  b.style.setProperty('display', 'block', 'important');
  var saved = [];
  Array.from(b.children).forEach(function(el) {
    if (el.nodeType !== 1) return;
    saved.push({ el: el, css: el.style.cssText });
    el.style.setProperty('height', 'auto', 'important');
    el.style.setProperty('max-height', 'none', 'important');
    el.style.setProperty('min-height', '0', 'important');
    el.style.setProperty('overflow', 'visible', 'important');
  });
  var h = b.scrollHeight + svgOverflow;
  // Restore original inline styles
  b.style.cssText = savedBody;
  saved.forEach(function(s) { s.el.style.cssText = s.css; });

  // Safety net: detect residual feedback loops (e.g. nested vh elements).
  // 3+ consecutive small monotonic increases → stop reporting.
  var delta = h - _rh_last;
  if (_rh_last > 0 && delta > 0 && delta < 50) {
    _rh_consecutive++;
    if (_rh_consecutive >= 3) return;
  } else {
    _rh_consecutive = 0;
  }

  _rh_last = h;
  parent.postMessage({ type: 'iframe:height', height: h }, '*');
}
window.addEventListener('load', reportHeight);
window.addEventListener('resize', reportHeight);
// Debounce ResizeObserver through rAF to avoid tight synchronous loops
new ResizeObserver(function() {
  cancelAnimationFrame(_rh_raf);
  _rh_raf = requestAnimationFrame(reportHeight);
}).observe(document.body);
// Explicitly handle <details> toggle — ResizeObserver misses this in some browsers
document.addEventListener('toggle', function() {
  _rh_consecutive = 0;
  setTimeout(reportHeight, 50);
}, true);
// Watch for DOM mutations (SPA page swaps via innerHTML, dynamic content).
// ResizeObserver misses these when content changes inside overflow:auto containers.
var _rh_mutRaf = 0;
new MutationObserver(function() {
  _rh_consecutive = 0;
  cancelAnimationFrame(_rh_mutRaf);
  _rh_mutRaf = requestAnimationFrame(reportHeight);
}).observe(document.body, { childList: true, subtree: true });
// Reset loop detector on click — covers custom expand/collapse (style.display
// toggles, class changes) that MutationObserver childList doesn't catch.
document.addEventListener('click', function() {
  _rh_consecutive = 0;
  cancelAnimationFrame(_rh_mutRaf);
  _rh_mutRaf = requestAnimationFrame(reportHeight);
}, true);

// --- Post-render fixes (theme defaults, overlap prevention) ---
window.addEventListener('load', function() {
  // Chart.js theme defaults + legend overflow prevention
  if (window.Chart) {
    var s = getComputedStyle(document.documentElement);
    var textColor = s.getPropertyValue('--color-text-secondary').trim();
    var gridColor = s.getPropertyValue('--color-border-tertiary').trim();
    Chart.defaults.color = textColor;
    Chart.defaults.borderColor = gridColor;
    Chart.defaults.plugins.legend.labels.color = textColor;
    Chart.defaults.plugins.legend.maxHeight = 120;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.plugins.legend.labels.font = { size: 11 };
    // Re-render existing charts with corrected legend constraints
    Object.values(Chart.instances || {}).forEach(function(chart) {
      var leg = chart.options.plugins && chart.options.plugins.legend;
      if (leg) {
        leg.maxHeight = leg.maxHeight || 120;
        if (leg.labels) {
          leg.labels.boxWidth = leg.labels.boxWidth || 12;
        }
      }
      chart.update();
    });
  }

  // SVG axis-label overlap — stagger only labels in a tight horizontal band
  // (skips complex diagrams where text is scattered across the full canvas).
  // Opt-out: add data-no-stagger to any <svg> to disable for that element.
  document.querySelectorAll('svg').forEach(function(svg) {
    if (svg.hasAttribute('data-no-stagger')) return;
    var texts = Array.from(svg.querySelectorAll('text'));
    if (texts.length < 4) return;
    // Collect bounding info for all visible texts
    var items = [];
    texts.forEach(function(t) {
      var r = t.getBoundingClientRect();
      if (r.width < 1) return;
      items.push({ el: t, rect: r, cx: r.left + r.width / 2, cy: r.top + r.height / 2 });
    });
    if (items.length < 4) return;
    // Only stagger texts that sit in a narrow y-band (axis labels).
    // If texts span a wide vertical range, this is a diagram — skip entirely.
    var minY = Infinity, maxY = -Infinity;
    items.forEach(function(it) {
      if (it.cy < minY) minY = it.cy;
      if (it.cy > maxY) maxY = it.cy;
    });
    var ySpan = maxY - minY;
    if (ySpan < 1) return;
    // Find the y-band with the most texts (likely the axis row)
    var bandSize = 30; // px tolerance for "same row"
    var bestBand = [], bestCount = 0;
    items.forEach(function(anchor) {
      var band = items.filter(function(it) { return Math.abs(it.cy - anchor.cy) < bandSize; });
      if (band.length > bestCount) { bestCount = band.length; bestBand = band; }
    });
    // Only proceed if the best band has 3+ labels AND doesn't cover most texts
    // (if most texts are in the band, it's likely a simple chart; otherwise a diagram)
    if (bestBand.length < 3 || bestBand.length === items.length && ySpan > 60) return;
    // Use only the best-band texts for grouping/stagger
    var groups = [];
    bestBand.forEach(function(it) {
      for (var i = 0; i < groups.length; i++) {
        if (Math.abs(groups[i].cx - it.cx) < 15) {
          groups[i].items.push(it);
          return;
        }
      }
      groups.push({ cx: it.cx, items: [it] });
    });
    if (groups.length < 3) return;
    groups.sort(function(a, b) { return a.cx - b.cx; });
    var needsStagger = false;
    for (var i = 0; i < groups.length - 1; i++) {
      var maxR = 0, minL = Infinity;
      groups[i].items.forEach(function(it) { if (it.rect.right > maxR) maxR = it.rect.right; });
      groups[i+1].items.forEach(function(it) { if (it.rect.left < minL) minL = it.rect.left; });
      if (maxR > minL - 2) { needsStagger = true; break; }
    }
    if (needsStagger) {
      for (var i = 1; i < groups.length; i += 2) {
        groups[i].items.forEach(function(it) {
          var cy = parseFloat(it.el.getAttribute('y') || 0);
          it.el.setAttribute('y', String(cy + 18));
        });
      }
    }
  });

  setTimeout(reportHeight, 100);
});

// --- sendPrompt bridge (requires iframe Sandbox Allow Same Origin) ---
function sendPrompt(text) {
  try {
    // Use Open WebUI's native postMessage protocol.
    // submitPrompt automatically queues the message if the AI is still generating.
    parent.postMessage({ type: 'input:prompt:submit', text: text }, '*');
  } catch(e) { /* iframe sandbox restriction */ }
}

// --- Open link in parent window ---
function openLink(url) {
  try { parent.window.open(url, '_blank'); }
  catch(e) { window.open(url, '_blank'); }
}

// --- Print fix for Chart.js canvases ---
// Chart.js sets explicit pixel widths as inline styles on canvas and its
// container div at render time (e.g. style="width: 1400px"). CSS max-width
// from a stylesheet can't reliably override this in Chrome's print engine.
// Fix: directly mutate inline styles before print, restore after.
(function() {
  window.addEventListener('beforeprint', function() {
    document.querySelectorAll('canvas').forEach(function(c) {
      c.setAttribute('data-print-style', c.style.cssText);
      c.style.setProperty('width', '100%', 'important');
      c.style.setProperty('max-width', '100%', 'important');
      c.style.setProperty('height', 'auto', 'important');
      var p = c.parentElement;
      if (p) {
        p.setAttribute('data-print-style', p.style.cssText);
        p.style.setProperty('width', '100%', 'important');
        p.style.setProperty('max-width', '100%', 'important');
      }
    });
  });
  window.addEventListener('afterprint', function() {
    document.querySelectorAll('[data-print-style]').forEach(function(el) {
      el.style.cssText = el.getAttribute('data-print-style');
      el.removeAttribute('data-print-style');
    });
  });
})();

// --- Download visualization as self-contained HTML ---
var _ivLang = 'en';
var _ivStr = {
  // Required languages
  en: 'Download as HTML',
  de: 'Als HTML herunterladen',
  cs: 'Stáhnout jako HTML',
  hu: 'Letöltés HTML-ként',
  hr: 'Preuzmi kao HTML',
  pl: 'Pobierz jako HTML',
  fr: 'Télécharger en HTML',
  nl: 'Downloaden als HTML',
  // Western & Southern European
  es: 'Descargar como HTML',
  pt: 'Baixar como HTML',
  it: 'Scarica come HTML',
  ca: 'Baixa com a HTML',
  gl: 'Descargar como HTML',
  eu: 'Deskargatu HTML gisa',
  // Northern European
  da: 'Download som HTML',
  sv: 'Ladda ner som HTML',
  no: 'Last ned som HTML',
  fi: 'Lataa HTML-tiedostona',
  is: 'Hlaða niður sem HTML',
  // Eastern European & Slavic
  sk: 'Stiahnuť ako HTML',
  sl: 'Prenesi kot HTML',
  sr: 'Преузми као HTML',
  bs: 'Preuzmi kao HTML',
  bg: 'Изтегли като HTML',
  mk: 'Преземи како HTML',
  uk: 'Завантажити як HTML',
  ru: 'Скачать как HTML',
  be: 'Спампаваць як HTML',
  // Baltic
  lt: 'Atsisiųsti kaip HTML',
  lv: 'Lejupielādēt kā HTML',
  et: 'Laadi alla HTML-ina',
  // Other European
  ro: 'Descarcă ca HTML',
  el: 'Λήψη ως HTML',
  sq: 'Shkarko si HTML',
  // Middle Eastern
  tr: 'HTML olarak indir',
  ar: 'تحميل كـ HTML',

  he: 'הורד כ-HTML',
  // East & South Asian
  zh: '下载为HTML',
  ja: 'HTMLでダウンロード',
  ko: 'HTML로 다운로드',
  vi: 'Tải xuống dạng HTML',
  th: 'ดาวน์โหลดเป็น HTML',
  id: 'Unduh sebagai HTML',
  ms: 'Muat turun sebagai HTML',
  hi: 'HTML के रूप में डाउनलोड करें',
  bn: 'HTML হিসেবে ডাউনলোড করুন',
  // African
  sw: 'Pakua kama HTML'
};
(function() {
  function detectLang() {
    // 1. Pre-detected via __event_call__ (baked into HTML by the tool)
    var pre = document.documentElement.getAttribute('data-iv-lang');
    if (pre && _ivStr[pre]) return pre;
    // 2. Fallback: parent localStorage (needs same-origin)
    try {
      var s = parent.localStorage.getItem('locale')
           || parent.localStorage.getItem('language')
           || parent.localStorage.getItem('i18nextLng');
      if (s) { var l = s.split('-')[0].toLowerCase(); if (_ivStr[l]) return l; }
    } catch(e) {}
    // 3. Fallback: browser language (standalone HTML / no same-origin)
    try {
      var bl = (navigator.language || navigator.userLanguage || 'en').split('-')[0].toLowerCase();
      if (_ivStr[bl]) return bl;
    } catch(e) {}
    return 'en';
  }
  _ivLang = detectLang();
  var btn = document.getElementById('iv-dl-btn');
  if (btn) btn.title = _ivStr[_ivLang] || _ivStr.en;
})();

// ---------------------------------------------------------------------------
// Download as self-contained HTML
// ---------------------------------------------------------------------------
//
// Strategy — why blob <a download>, and why iOS needs special handling:
//
//   Desktop / Android:
//     Blob + <a download> triggers the browser's native "Save As" dialog.
//     target="_blank" is added as a safety net: if the iframe sandbox lacks
//     the allow-downloads permission, the click gracefully opens the HTML
//     in a new tab instead of navigating (and destroying) the iframe. The
//     user can then save from the new tab. Non-destructive fallback.
//
//   iOS (Safari AND PWA / standalone):
//     Blob + <a download> triggers the iOS share sheet / download manager.
//     This is the ONLY approach that works reliably on iOS:
//       - target="_blank" MUST NOT be set. In PWA / standalone mode it
//         navigates the entire app away from the chat with NO back button —
//         the user is stuck on the blob page and must re-launch the app.
//         In Safari it opens a new tab showing raw HTML source instead of
//         triggering the download sheet.
//       - The blob click is deferred via setTimeout(0) so the calling
//         function returns cleanly before WebKit processes the navigation.
//         Without this, iOS WebKit can throw a synchronous "Load failed"
//         TypeError that propagates as an error toast in Open WebUI.
//       - window.onerror and unhandledrejection listeners suppress the
//         "Load failed" error for 60 s, then restore the original handlers.
//         This is the same pattern used by the PDF export and Gamma
//         presentation actions, which discovered these iOS quirks through
//         extensive production testing.
//
// iOS detection: UA string catches iPhone/iPod; the MacIntel +
// maxTouchPoints > 1 heuristic catches iPadOS (reports as desktop Mac).
// ---------------------------------------------------------------------------

var _ivIsIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

function _ivDownload() {
  // Clean up the serialized HTML for standalone use:
  // - Remove download button (not needed in saved file)
  // - Strip overflow:hidden so the file is scrollable in a browser
  var w = document.getElementById('iv-dl-wrap');
  if (w) w.remove();
  var html = '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
  if (w) document.body.appendChild(w);
  html = html.replace('html, body { overflow: hidden; }', '');

  var fname = (document.title || 'visualization').replace(/[<>:"\\/|?*]+/g, '-').replace(/\s+/g, ' ').trim();
  if (!fname) fname = 'visualization';
  // Cap at 200 chars to stay within Windows 255-char filename limit
  // (leaves room for the .html extension and filesystem overhead).
  if (fname.length > 200) fname = fname.substring(0, 200).trim();
  fname += '.html';

  var blob = new Blob([html], {type: 'text/html;charset=utf-8'});
  var url = URL.createObjectURL(blob);

  if (_ivIsIOS) {
    // iOS path — deferred blob download with "Load failed" error
    // suppression. Mirrors the battle-tested approach from the PDF
    // export and Gamma presentation actions.
    setTimeout(function() {
      // Suppress iOS WebKit "Load failed" TypeError that fires on
      // blob <a> clicks. Without this, Open WebUI shows an error toast.
      var _origOnerror = window.onerror;
      window.onerror = function(msg) {
        if (typeof msg === 'string' && msg.indexOf('Load failed') !== -1) return true;
        if (_origOnerror) return _origOnerror.apply(this, arguments);
      };
      var _sup = function(ev) {
        var m = ev && (ev.message || (ev.reason && ev.reason.message) || '');
        if (m.indexOf('Load failed') !== -1) { ev.preventDefault(); ev.stopImmediatePropagation(); return true; }
      };
      window.addEventListener('error', _sup, true);
      window.addEventListener('unhandledrejection', _sup, true);

      var a = document.createElement('a');
      a.style.display = 'none';
      a.href = url;
      a.download = fname;
      // No target="_blank" — see comment block above.
      document.body.appendChild(a);
      a.click();

      // Restore original error handlers and clean up after 60 s.
      setTimeout(function() {
        window.onerror = _origOnerror;
        window.removeEventListener('error', _sup, true);
        window.removeEventListener('unhandledrejection', _sup, true);
        URL.revokeObjectURL(url);
        a.remove();
      }, 60000);
    }, 0);
  } else {
    // Desktop / Android path — straightforward blob download.
    var a = document.createElement('a');
    a.href = url;
    a.download = fname;
    // Safety net: if the iframe sandbox blocks the download,
    // open in a new tab rather than navigating the iframe.
    a.target = '_blank';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(function() { a.remove(); URL.revokeObjectURL(url); }, 60000);
  }
}
</script>
"""

# ---------------------------------------------------------------------------
# STRICT-mode script — query-parameter hygiene for link navigation.
# Strips search params from openLink(), window.open(), and <a href>.
# This is supplementary hygiene, NOT a hard exfiltration control —
# data can still appear in URL paths/fragments, and location.assign/
# replace are not intercepted. The primary exfil blocker is the CSP
# connect-src directive.
# ---------------------------------------------------------------------------

STRICT_SECURITY_SCRIPT = """
<script>
(function() {
  function stripParams(rawUrl) {
    try { var u = new URL(rawUrl, location.href); u.search = ''; return u.toString(); }
    catch(e) { return rawUrl; }
  }

  // Override openLink to strip query/hash parameters
  var _origOpenLink = window.openLink;
  window.openLink = function(url) {
    _origOpenLink(stripParams(url));
  };

  // Override window.open to strip query parameters
  var _origOpen = window.open;
  window.open = function(url) {
    arguments[0] = stripParams(url);
    return _origOpen.apply(this, arguments);
  };

  // Strip params from all existing and future <a> tags
  function sanitizeLinks(root) {
    (root.querySelectorAll ? root : document).querySelectorAll('a[href]').forEach(function(a) {
      a.href = stripParams(a.href);
    });
  }
  sanitizeLinks(document);
  new MutationObserver(function(muts) {
    muts.forEach(function(m) {
      m.addedNodes.forEach(function(n) { if (n.nodeType === 1) sanitizeLinks(n); });
    });
  }).observe(document.body, { childList: true, subtree: true });
})();
</script>
"""

# ---------------------------------------------------------------------------
# STREAMING mode — parasitic-wrapper observer
# ---------------------------------------------------------------------------
#
# In streaming mode the tool returns a wrapper containing an empty render
# area (#iv-render) + this observer script. The wrapper then watches the
# PARENT DOM (requires Same-Origin) for a ```visualization fenced code
# block in the model's streaming response and incrementally renders its
# contents into #iv-render.
#
# Design:
# - Markdown renders ```visualization as <code class="language-visualization">
# - On every MutationObserver tick, we read the code element's textContent
#   (the raw HTML source the model is streaming) and set it as innerHTML
#   on the render area. Browsers happily render partial HTML.
# - <script> tags are stripped during streaming (to avoid repeat
#   execution) and re-injected once the content stops changing for 600ms.
# - The original <pre>/CodeBlock wrapper in the chat is hidden after claim
#   so the user sees only the rendered visualization.
# - Each wrapper claims ONE code block by setting data-iv-claimed="true"
#   so multiple concurrent visualizations don't collide.
#
# Requires iframe Sandbox Allow Same Origin. If disabled, a visible
# explanation is rendered instead.
# ---------------------------------------------------------------------------

STREAMING_OBSERVER_SCRIPT = """
<script>
(function() {
  'use strict';
  var SENTINEL = 'visualization';
  var renderArea = document.getElementById('iv-render');
  if (!renderArea) return;

  // Require same-origin access to parent — otherwise show a helpful notice.
  var hasParentAccess = false;
  try { void parent.document.body; hasParentAccess = true; } catch(e) {}
  if (!hasParentAccess) {
    renderArea.innerHTML =
      '<div style="padding:16px 18px;border:0.5px solid var(--color-border-tertiary);' +
      'border-radius:var(--radius-md);background:var(--color-bg-secondary);' +
      'color:var(--color-text-primary);font-size:13px;line-height:1.5;">' +
      '<div style="font-weight:500;margin-bottom:6px;">Streaming visualization unavailable</div>' +
      '<div style="color:var(--color-text-secondary);">' +
      'Enable <b>iframe Sandbox Allow Same Origin</b> in Open WebUI ' +
      'Settings → Interface to use streaming mode.</div></div>';
    return;
  }

  // ---------------------------------------------------------------------
  // Claim strategy — DOM-local, no global counter.
  //
  // Each wrapper's iframe lives inside some parent DOM node (a tool-call
  // embed container inside an assistant message). The fence that belongs
  // to us is the first unclaimed `.language-visualization` we can reach by:
  //   (1) searching within our enclosing [id^="message-"] container,
  //   (2) if none, searching forward through subsequent messages.
  //
  // This is stable across chat navigations and page reloads: we don't rely
  // on a global counter that persists across chat switches. The previous
  // counter approach broke when opening a new chat — the counter from the
  // previous chat's wrappers leaked, making new wrappers wait for a fence
  // index that will never exist.
  //
  // Multiple wrappers in the same message claim in DOM order because each
  // sets data-iv-claimed="1" on the element they take, and subsequent
  // wrappers skip claimed elements.
  // ---------------------------------------------------------------------

  var claimedBlock = null;
  var hiddenWrapper = null;
  var lastRawText = '';
  var lastSafeRendered = '';
  var stableTimer = null;
  var finalizeTimer = null;
  var finalized = false;
  var myMessage = null;  // cached enclosing message container

  function findMyMessage() {
    if (myMessage && parent.document.contains(myMessage)) return myMessage;
    try {
      var f = window.frameElement;
      if (!f) return null;
      myMessage = f.closest && f.closest('[id^="message-"]');
      return myMessage;
    } catch(e) { return null; }
  }

  // ---- Claim: first unclaimed fence at or after our message -----------
  //
  // Open WebUI's CodeBlock defaults to edit mode (CodeMirror), so there is
  // NO <code class="language-X"> element — the `language-X` class lives on
  // the wrapper <div> at CodeBlock.svelte:547. We match any element with
  // that class and keep only the outermost per block.
  function getOutermostFences(root) {
    var raw = root.querySelectorAll(
      '[class~="language-' + SENTINEL + '"]'
    );
    var arr = Array.from(raw);
    return arr.filter(function(m) {
      for (var i = 0; i < arr.length; i++) {
        if (arr[i] !== m && arr[i].contains(m)) return false;
      }
      return true;
    });
  }

  function claim() {
    if (claimedBlock && parent.document.contains(claimedBlock)) return claimedBlock;
    var msg = findMyMessage();
    var candidates = [];
    if (msg) {
      // 1. Fences inside my own message
      candidates = getOutermostFences(msg);
      // 2. Fences in subsequent messages (tool call can spawn separate turn)
      if (candidates.length === 0 || candidates.every(hasBeenClaimed)) {
        var next = msg.nextElementSibling;
        while (next) {
          if (next.matches && next.matches('[id^="message-"]')) {
            var more = getOutermostFences(next);
            for (var i = 0; i < more.length; i++) candidates.push(more[i]);
            if (candidates.some(function(x) { return !hasBeenClaimed(x); })) break;
          }
          next = next.nextElementSibling;
        }
      }
    } else {
      // Fallback — whole document
      candidates = getOutermostFences(parent.document);
    }
    // First unclaimed, preferring the earliest
    for (var j = 0; j < candidates.length; j++) {
      if (!hasBeenClaimed(candidates[j])) {
        candidates[j].setAttribute('data-iv-claimed', '1');
        claimedBlock = candidates[j];
        hideWrapperOf(claimedBlock);
        return claimedBlock;
      }
    }
    return null;
  }

  function hasBeenClaimed(el) {
    return el.getAttribute('data-iv-claimed') === '1';
  }

  // Extract the streaming source text. CodeMirror renders into .cm-line
  // children inside .cm-content (and also renders gutter line numbers in
  // .cm-gutters, which we MUST skip). hljs-mode just has raw textContent
  // on the <code>.
  function readSource(el) {
    try {
      var cmContent = el.querySelector && el.querySelector('.cm-content');
      if (cmContent) {
        var lines = cmContent.querySelectorAll('.cm-line');
        if (lines.length > 0) {
          var out = [];
          for (var i = 0; i < lines.length; i++) {
            out.push(lines[i].textContent || '');
          }
          return out.join('\\n');
        }
        return cmContent.textContent || '';
      }
    } catch(e) {}
    return (el && el.textContent) || '';
  }

  // CodeBlock's top-level container is a div with `rounded-2xl border`
  // (CodeBlock.svelte:448). That's the thing we want to hide — it wraps
  // the header toolbar, the code, and any output panels.
  function hideWrapperOf(code) {
    try {
      var el = code;
      for (var i = 0; i < 12 && el; i++) {
        if (el.matches && el.matches('.rounded-2xl[class*="border"]')) {
          hiddenWrapper = el; el.style.display = 'none'; return;
        }
        el = el.parentElement;
      }
      // Fallbacks in DOM-structural order
      var pre = code.closest && code.closest('pre');
      if (pre) { hiddenWrapper = pre; pre.style.display = 'none'; return; }
      if (code.style) code.style.display = 'none';
    } catch(e) {}
  }

  // ---------------------------------------------------------------------
  // Safe-cut partial-HTML parser
  //
  // Returns the last index in `text` where markup is in a safe state to
  // flush to innerHTML: parser is in TEXT state (not mid-tag, not
  // mid-attribute, not inside script/style content), and no comment or
  // CDATA is mid-delimiter.
  //
  // We do NOT require depth === 0. Browsers' HTML parser auto-closes
  // open tags when innerHTML is set, so flushing `<svg><rect/><g>` is
  // perfectly valid — the resulting DOM is `<svg><rect/><g></g></svg>`
  // with an empty <g>. Next tick we flush `<svg><rect/><g><path/></g></svg>`
  // and the DOM updates. This is what enables progressive SVG render —
  // previously depth === 0 meant a single top-level <svg> only flushed
  // on its closing tag (no progressive render at all).
  // ---------------------------------------------------------------------
  var VOID_TAGS = {area:1,base:1,br:1,col:1,embed:1,hr:1,img:1,input:1,
                   link:1,meta:1,param:1,source:1,track:1,wbr:1};
  var RAW_TAGS = {script:1, style:1};

  function findSafeCut(text) {
    var i = 0, len = text.length;
    var state = 'TEXT';
    var quote = 0;
    var safeCut = 0;
    var tagNameBuf = '';
    var tagNameEnd = false;
    var inClosingTag = false;
    var selfClosing = false;
    var rawTag = '';  // active <script>/<style> close tag name

    while (i < len) {
      var ch = text.charCodeAt(i);

      if (state === 'RAW') {
        // Inside <script>/<style>. The contents are NOT a safe cut — we
        // have to wait for the full close tag before flushing, otherwise
        // innerHTML would include partial JS/CSS.
        var marker = '</' + rawTag;
        if (text.substr(i, marker.length).toLowerCase() === marker) {
          var end = text.indexOf('>', i + marker.length);
          if (end === -1) break;
          rawTag = '';
          state = 'TEXT';
          i = end + 1;
          safeCut = i;
          continue;
        }
        i++; continue;
      }

      if (state === 'TEXT') {
        if (ch === 60 /* < */) {
          if (text.substr(i, 4) === '<!--') {
            var ce = text.indexOf('-->', i + 4);
            if (ce === -1) break;
            i = ce + 3;
            safeCut = i;
            continue;
          }
          if (text.substr(i, 9) === '<![CDATA[') {
            var ke = text.indexOf(']]>', i + 9);
            if (ke === -1) break;
            i = ke + 3;
            safeCut = i;
            continue;
          }
          state = 'TAG';
          tagNameBuf = ''; tagNameEnd = false;
          inClosingTag = false; selfClosing = false;
          i++; continue;
        }
        i++;
        safeCut = i;
        continue;
      }

      if (state === 'TAG') {
        if (ch === 47 /* / */) {
          if (tagNameBuf === '' && !tagNameEnd) { inClosingTag = true; i++; continue; }
          selfClosing = true; i++; continue;
        }
        if (ch === 62 /* > */) {
          var tn = tagNameBuf.toLowerCase();
          if (!inClosingTag && !selfClosing && RAW_TAGS[tn]) {
            state = 'RAW'; rawTag = tn; i++; continue;
          }
          state = 'TEXT'; i++;
          safeCut = i;
          continue;
        }
        if (ch === 32 || ch === 9 || ch === 10 || ch === 13) {
          tagNameEnd = true; i++; state = 'ATTR_NAME'; continue;
        }
        if (!tagNameEnd) tagNameBuf += text.charAt(i);
        i++; continue;
      }

      if (state === 'ATTR_NAME') {
        if (ch === 62) {
          var tn2 = tagNameBuf.toLowerCase();
          if (!inClosingTag && !selfClosing && RAW_TAGS[tn2]) {
            state = 'RAW'; rawTag = tn2; i++; continue;
          }
          state = 'TEXT'; i++;
          safeCut = i;
          continue;
        }
        if (ch === 47) { selfClosing = true; i++; continue; }
        if (ch === 61 /* = */) { state = 'ATTR_VAL_START'; i++; continue; }
        i++; continue;
      }

      if (state === 'ATTR_VAL_START') {
        if (ch === 32 || ch === 9 || ch === 10 || ch === 13) { i++; continue; }
        if (ch === 34) { quote = 34; state = 'ATTR_VAL_Q'; i++; continue; }
        if (ch === 39) { quote = 39; state = 'ATTR_VAL_Q'; i++; continue; }
        if (ch === 62) { state = 'ATTR_NAME'; continue; }
        state = 'ATTR_VAL_U'; i++; continue;
      }

      if (state === 'ATTR_VAL_Q') {
        if (ch === quote) { state = 'ATTR_NAME'; i++; continue; }
        i++; continue;
      }

      if (state === 'ATTR_VAL_U') {
        if (ch === 32 || ch === 9 || ch === 10 || ch === 13) { state = 'ATTR_NAME'; i++; continue; }
        if (ch === 62) { state = 'ATTR_NAME'; continue; }
        i++; continue;
      }
    }
    return safeCut;
  }

  // ---- Fade-in animation for newly-complete elements ------------------
  function markAndAnimate(root) {
    var toAnimate = [];
    function visit(node, top) {
      if (!node || node.nodeType !== 1) return;
      var isSvgChild = node.ownerSVGElement != null;
      if ((top || isSvgChild || node.tagName === 'svg') && !node.hasAttribute('data-iv-faded')) {
        node.setAttribute('data-iv-faded', '1');
        toAnimate.push(node);
      }
      if (node.tagName === 'svg') {
        for (var c = node.firstElementChild; c; c = c.nextElementSibling) visit(c, false);
      }
    }
    for (var c = root.firstElementChild; c; c = c.nextElementSibling) visit(c, true);
    if (toAnimate.length === 0) return;
    requestAnimationFrame(function() {
      toAnimate.forEach(function(el) { el.classList.add('iv-fade-in'); });
    });
  }

  // ---- Height handling during streaming -------------------------------
  var heightRaf = 0;
  function scheduleHeight() {
    cancelAnimationFrame(heightRaf);
    heightRaf = requestAnimationFrame(function() {
      try { if (typeof reportHeight === 'function') reportHeight(); } catch(e) {}
    });
  }

  // ---- Finalize: run scripts, final height nudge ----------------------
  function finalize(fullText) {
    if (finalized) return;
    finalized = true;
    renderArea.innerHTML = fullText;
    hideLoader();
    renderArea.querySelectorAll('script').forEach(function(old) {
      var s = document.createElement('script');
      for (var a = 0; a < old.attributes.length; a++) {
        s.setAttribute(old.attributes[a].name, old.attributes[a].value);
      }
      s.textContent = old.textContent;
      old.parentNode.replaceChild(s, old);
    });
    // Animate everything in one final pass (skips nodes already marked).
    markAndAnimate(renderArea);
    // Kick the height reporter twice — once immediately, once after layout.
    scheduleHeight();
    setTimeout(scheduleHeight, 120);
    setTimeout(scheduleHeight, 400);
  }

  // ---- Is the enclosing assistant message still streaming? -----------
  // Open WebUI adds a .shimmer class to containers in "executing" state.
  // When nothing with .shimmer remains near our code block, the fence
  // has closed and we can safely finalize even if textContent is stable
  // only briefly.
  function isMessageDone(code) {
    try {
      var msg = code.closest('[id^="message-"]');
      if (!msg) return false;
      return !msg.querySelector('.shimmer');
    } catch(e) { return false; }
  }

  function tick() {
    if (finalized) return;
    var code = claim();
    if (!code) return;
    var raw = readSource(code);
    if (raw === lastRawText) return;
    lastRawText = raw;

    var cut = findSafeCut(raw);
    var safe = raw.substring(0, cut);

    if (safe !== lastSafeRendered && safe.length > 0) {
      lastSafeRendered = safe;
      // Live partial render — no scripts yet (final pass re-injects them).
      // The loader stays visible BELOW this during streaming.
      renderArea.innerHTML = safe.replace(/<script[\\s\\S]*?<\\/script>/gi, '')
                                 .replace(/<script[\\s\\S]*$/i, '');
      markAndAnimate(renderArea);
      scheduleHeight();
    }

    // Finalize when either:
    //   (a) the enclosing message is no longer streaming, OR
    //   (b) the source hasn't changed for a full 800ms.
    clearTimeout(finalizeTimer);
    finalizeTimer = setTimeout(function() {
      if (finalized) return;
      var latest = readSource(code);
      if (isMessageDone(code) || latest === raw) {
        finalize(latest);
      }
    }, 800);
  }

  // ---- Inject fade-in + loader CSS into our OWN document -------------
  (function injectFadeCss() {
    var s = document.createElement('style');
    s.textContent =
      '@keyframes iv-fade-in-kf {' +
      '  from { opacity: 0; transform: translateY(2px); }' +
      '  to   { opacity: 1; transform: none; }' +
      '}' +
      '@keyframes iv-fade-in-svg-kf {' +
      '  from { opacity: 0; } to { opacity: 1; }' +
      '}' +
      '#iv-render .iv-fade-in { animation: iv-fade-in-kf 500ms ease-out both; }' +
      '#iv-render svg .iv-fade-in { animation: iv-fade-in-svg-kf 500ms ease-out both; }' +
      // Loader shown while the wrapper is waiting for a fence to appear /
      // claim / produce its first safe-cut flush. Three pulsing dots +
      // subtle label; replaced the moment real content lands.
      '@keyframes iv-pulse-kf {' +
      '  0%, 80%, 100% { opacity: 0.25; transform: scale(0.85); }' +
      '  40%           { opacity: 1;    transform: scale(1); }' +
      '}' +
      '.iv-loading {' +
      '  display: flex; flex-direction: column; align-items: center;' +
      '  justify-content: center; gap: 12px;' +
      '  padding: 48px 20px; min-height: 120px;' +
      '  color: var(--color-text-tertiary);' +
      '  font-size: 12px; letter-spacing: 0.02em;' +
      '}' +
      '.iv-loading-dots { display: inline-flex; gap: 8px; }' +
      '.iv-loading-dots span {' +
      '  width: 8px; height: 8px; border-radius: 50%;' +
      '  background: var(--color-text-tertiary);' +
      '  animation: iv-pulse-kf 1.4s infinite ease-in-out both;' +
      '}' +
      '.iv-loading-dots span:nth-child(1) { animation-delay: -0.32s; }' +
      '.iv-loading-dots span:nth-child(2) { animation-delay: -0.16s; }' +
      '.iv-loading-label { opacity: 0.6; }';
    document.head.appendChild(s);
  })();

  // The loader (#iv-loader) is already rendered by the Python side as a
  // sibling BELOW #iv-render. The observer only needs to remove it once
  // streaming completes (see finalize()). This placement creates the
  // illusion of content flowing downward toward a pulsing progress head.
  function hideLoader() {
    try {
      var l = document.getElementById('iv-loader');
      if (l && l.parentNode) l.parentNode.removeChild(l);
    } catch(e) {}
  }

  // ---- Go ------------------------------------------------------------
  //
  // Defense in depth:
  //   1. Outer MutationObserver on parent.document.body — sees new fences
  //      appearing as the model streams.
  //   2. Inner MutationObserver scoped to the claimed block once we have
  //      one — catches CodeMirror internal DOM churn (line insertion,
  //      textContent updates) that the outer observer sometimes misses
  //      because CodeMirror uses reconciled child updates.
  //   3. 400ms poll as a safety net — cheap, guarantees forward progress
  //      even if both observers miss something (e.g. reactive DOM swaps
  //      during chat navigation).
  // ---------------------------------------------------------------------
  var innerMo = null;
  function attachInnerObserver() {
    if (innerMo || !claimedBlock) return;
    try {
      innerMo = new MutationObserver(tick);
      innerMo.observe(claimedBlock, {
        childList: true, subtree: true, characterData: true
      });
    } catch(e) {}
  }

  function tickWithInner() {
    tick();
    attachInnerObserver();
  }

  tickWithInner();
  try {
    new MutationObserver(tickWithInner).observe(parent.document.body, {
      childList: true, subtree: true, characterData: true
    });
  } catch(e) {}
  // Unconditional poll — belt-and-braces, ~2.5 ticks/sec, negligible cost.
  setInterval(tickWithInner, 400);
})();
</script>
"""


# Kept for backwards compatibility in case anything references the old name
INJECTED_SCRIPTS = BODY_SCRIPTS

DOWNLOAD_BUTTON = (
    '<div id="iv-dl-wrap">'
    '<button id="iv-dl-btn" onclick="_ivDownload()" title="Download">'
    '<svg viewBox="0 0 16 16"><path d="M8 2v8M5 7l3 3 3-3"/><path d="M3 12h10"/></svg>'
    '</button></div>'
)


# Only match wrapper tags at document boundaries — not globally — so that
# legitimate occurrences inside JS strings or template literals survive.
# Leading pattern: optional whitespace then any mix of DOCTYPE/html/head/
# body-open/meta tags (models hallucinate full document wrappers).
# Trailing pattern: </body> and </html> close tags at the end.
_LEADING_WRAPPER_RE = re.compile(
    r'^(\s*(?:<!DOCTYPE[^>]*>|</?html[^>]*>|</?head[^>]*>|<body[^>]*>|<meta[^>]*/?>)\s*)+',
    re.IGNORECASE,
)
_TRAILING_WRAPPER_RE = re.compile(
    r'(\s*(?:</body\s*>|</html\s*>)\s*)+$',
    re.IGNORECASE,
)


def _sanitize_content(content: str) -> str:
    """Strip document wrapper tags that models sometimes include.

    Only removes tags at the start and end of the content so that identical
    tokens appearing inside script strings or template literals are preserved.
    """
    content = _LEADING_WRAPPER_RE.sub('', content)
    content = _TRAILING_WRAPPER_RE.sub('', content)
    # Collapse runs of 3+ blank lines into a single blank line
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()


# ---------------------------------------------------------------------------
# CSP generation per security level
# ---------------------------------------------------------------------------

_KNOWN_CDNS = (
    "https://cdnjs.cloudflare.com"
    " https://cdn.jsdelivr.net"
    " https://unpkg.com"
)


def _build_csp_tag(level: str) -> str:
    """Return a <meta> CSP tag for the given security level, or empty string."""
    if level == "none":
        return ""

    if level == "strict":
        return (
            '<meta http-equiv="Content-Security-Policy" content="'
            f"default-src 'self'; "
            f"script-src 'unsafe-inline' {_KNOWN_CDNS}; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'none'; "
            "form-action 'none'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "media-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            '">' 
        )

    # balanced: block outbound connections & forms, allow external images
    return (
        '<meta http-equiv="Content-Security-Policy" content="'
        f"default-src 'self'; "
        f"script-src 'unsafe-inline' {_KNOWN_CDNS}; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'none'; "
        "form-action 'none'; "
        "img-src * data: blob:; "
        "font-src 'self' data:; "
        "media-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        '">' 
    )


def _build_html(content: str, security_level: str = "strict",
                title: str = "Visualization", lang: str = "en",
                streaming: bool = False) -> str:
    """Wrap a user-provided HTML/SVG fragment in the full Rich UI shell.

    If ``streaming`` is True, ``content`` is ignored and the body contains
    an empty render area (#iv-render) plus the parasitic-wrapper observer
    script, which tails the parent chat DOM for a ``` ``` ``visualization``
    fenced code block and renders its contents live.
    """
    csp_tag = _build_csp_tag(security_level)
    strict_script = STRICT_SECURITY_SCRIPT if security_level == "strict" else ""
    safe_title = (title.replace('&', '&amp;').replace('<', '&lt;')
                       .replace('>', '&gt;').replace('"', '&quot;'))
    # Sanitize lang to a simple lowercase BCP-47 primary subtag.
    # Split on '-' first so "zh-CN" → "zh", not "zhcn".
    safe_lang = re.sub(r'[^a-z]', '', lang.split('-')[0].lower()[:5]) or "en"

    if streaming:
        # Loader sits *below* the render area so content appears to flow
        # downward toward the pulsing dots — like a cursor following a pen.
        # The observer removes #iv-loader entirely on finalize().
        body_inner = (
            '<div id="iv-render"></div>\n'
            '<div id="iv-loader" class="iv-loading" aria-live="polite">'
            '<div class="iv-loading-dots"><span></span><span></span><span></span></div>'
            '<div class="iv-loading-label">Painting visualization\u2026</div>'
            '</div>\n'
            f'{DOWNLOAD_BUTTON}\n'
            f'{BODY_SCRIPTS}'
            f'{STREAMING_OBSERVER_SCRIPT}'
            f'{strict_script}'
        )
    else:
        body_inner = (
            f'{_sanitize_content(content)}\n'
            f'{DOWNLOAD_BUTTON}\n'
            f'{BODY_SCRIPTS}'
            f'{strict_script}'
        )

    return (
        f'<!DOCTYPE html><html data-iv-lang="{safe_lang}"><head>'
        f"<title>{safe_title}</title>"
        f"{csp_tag}"
        f"<style>{THEME_CSS}\n{SVG_CLASSES}\n{BASE_STYLES}</style>"
        f"{THEME_DETECTION_SCRIPT}"
        f"</head><body>\n{body_inner}\n</body></html>"
    )


# ---------------------------------------------------------------------------
# Valves (user-configurable settings)
# ---------------------------------------------------------------------------

# Developer reference for security levels:
#
#   STRICT   — Containment-oriented default. Blocks outbound fetch/XHR
#              (connect-src 'none'), form submissions, external images,
#              embedded objects, and base-URI hijacking. Injects a script
#              that strips URL query parameters from link navigation as
#              additional hygiene (query-only; does not cover path or
#              fragment, and does not intercept location.assign/replace).
#              Script execution within the visualization is intentionally
#              allowed ('unsafe-inline' + CDN allowlist) — this is
#              required for Chart.js, D3, and interactive visualizations.
#
#   BALANCED — Same as STRICT but allows external image loading (img-src *).
#              No URL parameter stripping. Note: img-src * permits
#              tracking pixels — this is an accepted privacy tradeoff
#              for visualizations that need external images.
#
#   NONE     — No CSP applied. Visualization can make arbitrary network
#              requests. Use only for visualizations that fetch live API
#              data (CORS restrictions still apply).
#
# Limitations that apply to ALL levels:
# - Script execution is always permitted (required for core features).
# - When iframe Same-Origin is enabled at the platform level, JS inside
#   the visualization can access the parent Open WebUI page. No CSP
#   level can prevent this — it is controlled by the platform setting.


class Tools:
    """Inline Visualizer — renders interactive HTML/SVG in chat.

    Security is controlled via the ``security_level`` valve, which applies
    a Content Security Policy to the rendered iframe.  Defaults to STRICT,
    which blocks outbound network requests (fetch/XHR) and form submissions.
    Script execution is always permitted — it is required for interactive
    visualizations, Chart.js, and D3.  See the developer reference above
    for the full security model and its limitations.
    """

    class Valves(BaseModel):
        security_level: Literal["strict", "balanced", "none"] = Field(
            default="strict",
            description="Strict (default): blocks outbound fetch/XHR, images, and forms; scripts always allowed. Balanced: also allows external images. None: no restrictions.",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def render_visualization(
        self,
        title: str = "Visualization",
        html_code: str | None = None,
        __event_call__=None,
    ) -> tuple:
        """
        Render an interactive HTML or SVG visualization inline in the chat.

        IMPORTANT: You MUST call view_skill("visualize") FIRST to load the design system
        before calling this tool. Never generate a visualization without reading the skill
        instructions first — they contain critical rules for colors, layout, SVG setup,
        chart patterns, and common failure points.

        === STREAMING MODE (DEFAULT, RECOMMENDED) ===

        Call this tool with ONLY ``title`` and omit ``html_code``. The tool will mount
        an empty visualization wrapper in the chat. Then, in your text response that
        follows, emit the HTML/SVG inside a ```visualization fenced code block:

            ```visualization
            <svg viewBox="0 0 680 240">...</svg>
            ```

        The wrapper parasitically tails your streaming text and renders the contents
        of that code block LIVE, token-by-token, into the iframe. Users see the
        visualization paint progressively as you generate it.

        The raw ```visualization fence is hidden from the chat once claimed, so the
        user sees only the rendered visualization. You may write explanatory prose
        before and after the fence — it renders normally in the chat.

        Requirements for streaming mode:
        - "iframe Sandbox Allow Same Origin" must be enabled in Open WebUI
          Settings → Interface. If disabled, the wrapper shows a notice telling
          the user to enable it.
        - Use the fence tag EXACTLY ``` ```visualization ``` — case-sensitive, no
          other tag is detected. Do NOT use ```html or ```svg for streaming.
        - Emit ONE fence per tool call. If you need multiple visualizations, call
          the tool multiple times (each call claims one fence in DOM order).

        === STATIC MODE (LEGACY, BACKWARD COMPAT) ===

        If you pass ``html_code``, the tool returns a pre-rendered wrapper with your
        content baked in. Nothing streams — the full visualization appears when the
        tool returns. Use this only when you already have the complete HTML and
        don't want streaming.

        === INJECTED HELPERS (both modes) ===

        The system automatically injects:
        - Theme CSS variables (auto-detected light/dark mode)
        - SVG utility classes: .t .ts .th .box .node .arr .leader
        - Color ramp classes: .c-purple .c-teal .c-coral .c-pink .c-gray .c-blue .c-green .c-amber .c-red
        - Base element styles (button, range, select, code, headings)
        - Height auto-sizing script
        - sendPrompt(text) function — sends a message to the chat (requires iframe Sandbox Allow Same Origin)
        - openLink(url) function — opens a URL in a new tab

        After calling this tool, do NOT repeat the HTML/SVG source as plain text — the
        visualization is rendered and visible to the user. Briefly describe what the
        visualization shows in plain language around (or after) the streaming fence.

        :param title: Short descriptive title for the visualization.
        :param html_code: Optional HTML or SVG content fragment. If provided, triggers
                          STATIC mode. If omitted (default), STREAMING mode is used and
                          you must emit the content inside a ```visualization fence in
                          your text response. Do NOT include DOCTYPE, html, head, or
                          body tags. Structure: <style> first, visible content next,
                          <script> last. Load Chart.js via CDN when needed:
                          <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>.
        :return: Interactive rich embed rendered in the chat, with LLM context.
        """
        streaming = html_code is None

        # Detect UI language via parent page JS (same pattern as PDF/Gamma actions)
        lang = "en"
        if __event_call__:
            try:
                lang_result = await __event_call__({
                    "type": "execute",
                    "data": {
                        "code": """
return (() => {
  try {
    const stored = localStorage.getItem('locale')
                || localStorage.getItem('language')
                || localStorage.getItem('i18nextLng');
    if (stored) {
      const l = stored.split('-')[0].toLowerCase();
      if (l) return l;
    }
  } catch (e) {}
  try {
    return (navigator.language || navigator.userLanguage || 'en').split('-')[0].toLowerCase();
  } catch (e) {}
  return 'en';
})();
"""
                    },
                })
                if isinstance(lang_result, str) and lang_result.strip():
                    lang = lang_result.strip()
            except Exception:
                pass

        response = HTMLResponse(
            content=_build_html(
                html_code or "",
                self.valves.security_level,
                title,
                lang,
                streaming=streaming,
            ),
            headers={"Content-Disposition": "inline"},
        )
        if streaming:
            result_context = (
                f'Visualization wrapper "{title}" is mounted and waiting for content. '
                f"Now emit the HTML/SVG content inside a ```visualization fenced code "
                f"block in your NEXT text response. The wrapper will tail your stream "
                f"and render it live. Use the fence tag EXACTLY: ```visualization on "
                f"its own line to open, ``` on its own line to close. Write explanatory "
                f"prose BEFORE and AFTER the fence — do not describe the HTML source "
                f"itself. Do NOT use ```html or ```svg — only ```visualization is "
                f"detected. Emit exactly ONE fence for this tool call."
            )
        else:
            result_context = (
                f'Visualization "{title}" is now rendered and visible to the user as an '
                f"interactive embed. DO NOT echo back the HTML/SVG source code. Instead, "
                f"briefly describe what the visualization shows in plain language. If the "
                f"visualization has interactive elements (clickable nodes, buttons, sliders), "
                f"mention what the user can interact with. DO NOT OUTPUT THE HTML/SVG source again!"
            )
        return response, result_context

