# 🎨 Inline Visualizer — Streaming Edition

**Live, token-by-token interactive HTML/SVG visualizations inline in Open WebUI chat.** The iframe paints itself as the model types. No code block. No CodeMirror. No virtualization edge cases. Just a plain-text marker protocol that puts the visual *exactly* where you'd expect it — already alive by the time the model finishes writing it.

> [!TIP]
> **🚀 [Jump to Setup](#setup)** — up and running in under 90 seconds.

<table>
  <tr>
    <td><img src="assets/hero_streaming_live.png" alt="Transformer study card streaming live" width="420"/></td>
    <td><img src="assets/hero_dashboard.png" alt="Multi-card dashboard with Chart.js bars and D3 graph" width="420"/></td>
  </tr>
  <tr>
    <td align="center"><sub><b>Streaming</b> — the iframe fills in as the model types. No "tool executing" spinner, no final pop-in.</sub></td>
    <td align="center"><sub><b>Rich dashboards</b> — Chart.js, D3, SVG flowcharts, interactive forms, clickable drill-downs.</sub></td>
  </tr>
  <tr>
    <td><img src="assets/hero_flowchart.png" alt="SVG flowchart with color ramps" width="420"/></td>
    <td><img src="assets/hero_interactive.png" alt="Interactive slider with saveState persistence" width="420"/></td>
  </tr>
  <tr>
    <td align="center"><sub><b>Design system included</b> — 9-ramp color system, SVG utility classes, auto light/dark.</sub></td>
    <td align="center"><sub><b>Persistent state</b> — sliders, toggles, selected tabs survive reloads via <code>saveState</code>.</sub></td>
  </tr>
</table>

---

## ⚡ v2 vs v1 — what's new

If you came from the original [inline-visualizer](https://github.com/Classic298/open-webui-extras/tree/main/tools/inline-visualizer) plugin, **everything visible to the model stays the same** (still called `render_visualization`, still loads `view_skill("visualize")` first). Under the hood, it's been rewritten from scratch.

| | **v1 — classic** | **v2 — streaming** |
|---|---|---|
| **Rendering mode** | Static. Full HTML baked into the tool response, iframe appears once the model finishes | **Live streaming** — iframe paints token-by-token, user sees it grow |
| **Protocol** | ` ```visualization ` fenced code block routed through Open WebUI's CodeBlock → CodeMirror editor | Plain-text `@@@VIZ-START … @@@VIZ-END` markers — never touch CodeBlock or CodeMirror |
| **Refresh behavior** | Fine | Fine — observer reads the message's live DOM, state rehydrates from saved markdown on every mount |
| **Long-content reliability** | Breaks past CodeMirror's virtualization threshold (SVG backgrounds missing, lines evicted mid-scroll) | No virtualization — `textContent` is authoritative at every tick |
| **Flicker during stream** | N/A (no stream) | Incremental DOM reconciler — only appends new nodes; existing nodes never re-mount, animations don't re-trigger |
| **Bridges** | `sendPrompt`, `openLink` | `sendPrompt`, `openLink`, **`copyText`**, **`toast`**, **`saveState`**, **`loadState`** |
| **Done feedback** | — | Top-right localized toast + soft C-major chime on live-stream completion (silent on refresh) |
| **i18n** | Download button only (46 languages) | Download + loader label + unavailable notice + copied toast + "visualization ready" toast (46 languages each) |
| **Script loading** | N/A | External `<script src>` → inline script ordering is enforced (`async=false`) so `Chart`, `d3` etc. resolve before consumer code runs |
| **Tool-result detection** | N/A | `<details type="tool_calls">` subtrees are skipped by the scanner so the skill's own example markers never hijack the render |
| **Static-mode fallback** | Supported | **Removed.** Streaming is the only path |

### The one-line summary

> **v1 builds the visualization and shows you the finished poster. v2 hands the model a brush and a canvas and lets you watch it paint.**

---

## ✨ Features

### 🎬 Streaming render
The tool returns an empty wrapper. The model then emits HTML/SVG between `@@@VIZ-START` / `@@@VIZ-END` text markers in its response. An observer tails the parent chat's live DOM, extracts the growing block, and reconciles new nodes into the iframe in real time. You see cards, SVGs, and charts appear as the model writes them — not all at once when the message completes.

### 🧠 Zero-CodeMirror architecture
The v1 protocol went through Open WebUI's `CodeBlock.svelte` which wraps long code in a virtualized CodeMirror editor. That editor drops scrolled-off lines from the DOM, mangles whitespace at soft-wraps, and re-renders unpredictably on refresh. **v2's text markers are ordinary paragraph content** — they never hit the code path. No virtualization. No line eviction. No edge cases.

### 🌍 Built-in localization
Auto-detects the user's language from `<html data-iv-lang>` (injected server-side), then from parent `localStorage.locale`, then `navigator.language`. 46 languages for:
- Download button tooltip
- "Rendering visualization…" loader label
- "Streaming visualization unavailable" notice (shown if `allow-same-origin` is off)
- "Copied" confirmation toast
- "Visualization ready" done toast

### 🎨 Design system
- **9 color ramps** — purple, teal, coral, pink, gray, blue, green, amber, red — each with fill / stroke / text variants that auto-swap for light/dark mode
- **SVG utility classes** — `.t` `.ts` `.th` text, `.box` `.node` `.arr` `.leader` shapes, `.c-{ramp}` color application
- **Theme CSS variables** — dozens of aliases (`--bg`, `--fg`, `--surface`, `--border`, …) so the model can hardcode without breaking light/dark parity
- **Base element styles** — themed `button`, `input[type=range]`, `select`, `code`, `h1`–`h3`, `p`

### 🌉 Bridges — visualizations that talk back

| Bridge | What it does |
|---|---|
| `sendPrompt(text)` | Submits `text` as a user message in the chat. Makes any node a drill-down trigger. |
| `openLink(url)` | Opens `url` in a new tab (bypasses iframe sandbox weirdness on anchor clicks). |
| `copyText(text)` | Copies to clipboard (async API + legacy fallback) and fires a localized "Copied" toast. |
| `toast(msg, kind)` | Top-right auto-dismissing banner. `kind`: `success` / `info` / `warn` / `error`. |
| `saveState(key, value)` | Persists to `parent.localStorage` keyed by the assistant message id. |
| `loadState(key, fallback)` | Reads what `saveState` wrote. Survives reloads, scoped per-message. |

### 🔒 Configurable CSP

| Level | Outbound fetch | External images | Use case |
|---|:-:|:-:|---|
| **Strict** (default) | ❌ | ❌ | Maximum sandboxing. All core visuals work. |
| **Balanced** | ❌ | ✅ | Flags, logos, external image references. |
| **None** | ✅ | ✅ | Live API data pulls from inside the iframe. |

### 🎉 Done toast + chime
When a live stream finalizes, a localized "Visualization ready" toast slides in top-right and a soft three-note C-major arpeggio plays on Web Audio sine oscillators. Refreshes of completed messages are silent — the observer only celebrates when it actually witnessed the stream. Mute via `saveState('iv-sound', false)` per viz, or `localStorage['iv-sound-off']='1'` globally.

### 🧼 Efficient tick loop
- `msg.textContent` cached between ticks; unchanged → full pipeline short-circuits to a string compare
- DOM hide walker skips text nodes inside `<details type="tool_calls">` so the skill's own example markers never hijack detection
- Dynamic `<script>` insertion forces `async=false` so `Chart`, `d3`, etc. resolve before your consumer code runs
- Safe-cut HTML parser lets the reconciler flush partial markup (`<svg><rect/><g>` renders during stream) without breaking on unclosed tags

---

## 📦 Components

Two parts. Same as v1. Install both.

| File | Type | Install location |
|------|------|-----------------|
| `tool.py` | Tool | Workspace → Tools |
| `SKILL.md` | Skill | Workspace → Knowledge → Create Skill (name it **`visualize`**) |

The **tool** mounts the iframe wrapper, injects the design-system CSS/JS, and tails the chat for markers. The **skill** teaches the model the protocol (markers, color ramps, SVG patterns, when to use `sendPrompt` vs local JS, CDN libraries, common failures).

---

## 🛠️ Setup

> [!NOTE]
> **Prerequisite.** Works best with fast + strong models that follow protocol instructions precisely. Verified on Claude Sonnet 4.5, Claude Opus 4.7, GPT-4.1, Gemini 2.5 Pro, Qwen 3.5 72B.

### 1. Install the tool

1. Copy the contents of `tool.py`
2. In Open WebUI: **Workspace → Tools → + Create New**
3. Paste. **Save**.

### 2. Install the skill

1. Copy the contents of `SKILL.md`
2. In Open WebUI: **Workspace → Knowledge → Create Skill**
3. Name it exactly **`visualize`** (the tool calls `view_skill("visualize")` by this name)
4. Paste. **Save**.

### 3. Attach to your model

1. **Admin Panel → Settings → Models** → edit the model you want
2. Under **Tools**, enable **Inline Visualizer (Streaming)**
3. Under **Skills**, attach **visualize**
4. Ensure **native function calling** is enabled
5. Save.

### 4. Enable same-origin access (strongly recommended)

> [!IMPORTANT]
> Streaming mode **requires** iframe same-origin access. The observer needs to read the parent chat's live DOM to find the markers as they stream in.

1. **Settings → Interface**
2. Enable **iframe Sandbox Allow Same Origin**

> [!NOTE]
> Enabling same-origin means JavaScript inside a visualization can reach the parent Open WebUI page. That's the cost of the streaming architecture. If you need hard isolation, v1 (static mode) is still the right tool. If `allow-same-origin` is off, v2 shows a localized inline notice explaining how to enable it.

---

## 🎯 Usage

Ask for a visualization. The model calls `view_skill("visualize")` to load the design system, calls `render_visualization(title=…)` to mount the wrapper, then streams the HTML/SVG between `@@@VIZ-START` / `@@@VIZ-END` markers.

### Example prompts

- *"Visualize the architecture of a microservices system with clickable nodes."*
- *"Show me a flowchart of Git branching — let me click each stage for a drill-down."*
- *"Build an interactive study card for transformer LLMs: architecture diagram, parameter-count chart, temperature slider, SDK snippet."*
- *"Make me a periodic table where clicking an element asks you to explain it."*

### The protocol in one example

```
I'll chart the attention mechanism for you.

@@@VIZ-START
<svg viewBox="0 0 680 240">
  <!-- content streams in live -->
</svg>
@@@VIZ-END

As you can see, each query token attends to all key tokens simultaneously.
```

Everything between the markers is hidden from the chat body and piped into the iframe. Prose before and after renders normally.

---

## 🌉 Bridges — deep dive

### `sendPrompt(text)`
Turns any node into a conversational drill-down. The iframe `postMessage`s the parent with Open WebUI's native prompt-submit protocol.

```html
<g class="node c-purple" onclick="sendPrompt('Explain attention — how does softmax(QKᵀ/√d)V work and why scale by √d?')">
  <rect x="100" y="20" width="200" height="44" rx="8"/>
  <text class="th" x="200" y="42" text-anchor="middle" dominant-baseline="central">Attention</text>
</g>
```

### `openLink(url)`
Opens URLs in a new tab — safer than anchor tags inside sandboxed iframes.

```html
<button onclick="openLink('https://arxiv.org/abs/1706.03762')">View paper ↗</button>
```

### `copyText(text)` — fires a localized toast automatically

```html
<button onclick="copyText(document.getElementById('snippet').textContent)">Copy</button>
<pre id="snippet">from anthropic import Anthropic
client = Anthropic()
…</pre>
```

### `toast(msg, kind)` — standalone status banners

```html
<button onclick="recompute(); toast('Recomputed', 'info')">Recompute</button>
```

`kind` ∈ `success` (default) / `info` / `warn` / `error`.

### `saveState` / `loadState` — per-message persistence

```html
<script>
  const initial = loadState('showAdvanced', false);
  document.getElementById('adv').checked = initial;
  applyView(initial);

  function toggle(el) {
    saveState('showAdvanced', el.checked);
    applyView(el.checked);
  }
</script>
```

Keys are prefixed with the assistant message id, so a chart in Chat A and a chart in Chat B never share state. A slider value survives page reloads — the user's last setting is there when they come back.

---

## 🎨 Design system — at a glance

### Color ramps
```
purple · teal · coral · pink · gray · blue · green · amber · red
```
Apply via CSS class on any `<g>` — child `<rect>`, `<circle>`, `<ellipse>` get the ramp's fill + stroke automatically, child `.th` / `.ts` get the ramp's text colors. Light/dark adaptation is automatic.

```html
<g class="node c-teal">
  <rect x="100" y="20" width="180" height="44" rx="8"/>
  <text class="th" x="190" y="42" text-anchor="middle" dominant-baseline="central">Compute</text>
</g>
```

### SVG utility classes

| Class | Purpose |
|---|---|
| `.t` `.ts` `.th` | 14 px primary text / 12 px secondary / 14 px bold |
| `.box` | Neutral rect (secondary bg, tertiary border) |
| `.node` | Clickable element (cursor, hover opacity) |
| `.arr` | Arrow line (1.5 px, border-secondary) |
| `.leader` | Dashed guide line (0.5 px, tertiary) |
| `.c-{ramp}` | Apply a color ramp to all descendants |

### Themed HTML elements
Buttons, sliders, selects, code blocks, headings, paragraphs all get themed styles out of the box. The model writes `<button>` and gets a themed button — no class needed.

---

## 🌍 Localization

The tool bakes `<html data-iv-lang="{detected}">` on the server (reads parent `localStorage.locale` via `__event_call__`). Client-side fallbacks chain through `parent.localStorage` and `navigator.language`. 46 languages covered: en, de, cs, hu, hr, pl, fr, nl, es, pt, it, ca, gl, eu, da, sv, no, fi, is, sk, sl, sr, bs, bg, mk, uk, ru, be, lt, lv, et, ro, el, sq, tr, ar, he, zh, ja, ko, vi, th, id, ms, hi, bn, sw.

Five strings translated per language. That's **230 translations shipping** in the tool.

---

## 🔒 Security

Every visualization renders in a sandboxed iframe with a configurable Content Security Policy. Open **Workspace → Tools → Inline Visualizer → gear icon** to change the valve.

<img src="assets/screenshot_valves.png" alt="Security level valve" width="520"/>

| Level | Outbound requests | External images | URL param stripping | Use case |
|-------|:-:|:-:|:-:|---|
| **Strict** (default) | ❌ | ❌ | ✅ | Max safety. All core features work normally. |
| **Balanced** | ❌ | ✅ | — | Visualizations displaying external images (flags, logos). |
| **None** | ✅ | ✅ | — | Visualizations fetching live API data from within the iframe. |

> [!WARNING]
> With `allow-same-origin` enabled (required for streaming), JavaScript in a visualization has reach into the parent Open WebUI page. That is a platform-level permission — the tool cannot narrow it further. If you need full isolation, disable same-origin: v2 degrades gracefully with a localized "streaming unavailable" notice, and you can fall back to the original [inline-visualizer](https://github.com/Classic298/open-webui-extras/tree/main/tools/inline-visualizer) (static mode only) for that workflow.

> [!NOTE]
> Even in **None** mode, external API calls may still fail due to CORS — that's the remote server's policy, not ours.

---

## 🧰 Troubleshooting

<details>
<summary><b>The iframe shows a "Streaming visualization unavailable" notice</b></summary>

`allow-same-origin` is off. Enable it in **Settings → Interface → iframe Sandbox Allow Same Origin**.
</details>

<details>
<summary><b>The iframe is a thin empty strip</b></summary>

Usually means the model emitted an empty `@@@VIZ-START … @@@VIZ-END` block, or stopped mid-stream without closing the block and hit the idle-finalize fallback. Try regenerating. See the next entry for how the idle fallback works.
</details>

<details>
<summary><b>How does the plugin know when to stop streaming?</b></summary>

Two triggers:

1. **`@@@VIZ-END` marker arrives** — fires `finalize()` instantly. Scripts run, loader is replaced with the rendered viz, done toast + chime fire. This is the 99%+ case.
2. **Idle fallback — 30 seconds of completely stable source text.** Catches three edge cases: the user stopped generation mid-viz, the model forgot to close the block, or the network died.

The 30s window is deliberately much longer than any realistic inter-chunk stall. Gemini 3.1 Pro's 200-token chunks with 3-6s gaps, proxy buffering under poor network (10-20s silent pauses), and occasional Claude stalls all comfortably fit inside it. An earlier 5s fallback produced a thin-strip regression in ~40% of long streams; **30s is the sweet spot** between surviving real stalls and still recovering from a user-stop within half a minute.

**If a browser tab's network completely dies for more than 30s**, the fallback will finalize on whatever partial content arrived before the outage. At that point the stream is already gone, so a frozen loader-forever would be worse. Refresh the chat and the saved markdown (which has both markers) finalizes instantly on first tick.
</details>

<details>
<summary><b>Chart.js / D3 renders but nothing appears</b></summary>

Chart.js needs `<div style="position: relative; height: Xpx;">` around its canvas and `maintainAspectRatio: false` in options. See **Library init** in SKILL.md.
</details>

<details>
<summary><b>External images don't load</b></summary>

Strict CSP blocks external images. Switch to **Balanced** in the tool's valves.
</details>

<details>
<summary><b>fetch() fails with CORS</b></summary>

Set CSP to **None** AND the remote server must allow cross-origin requests. If it doesn't, there's nothing any client-side config can do.
</details>

<details>
<summary><b>The done chime is annoying</b></summary>

Run once in the browser console: `localStorage.setItem('iv-sound-off', '1')`. Sound off forever.
</details>

---

## 📐 Architecture

```
┌──────────────────── Assistant message ────────────────────┐
│                                                            │
│  <p>Here's the architecture:</p>                           │
│                                                            │
│  <p>@@@VIZ-START</p>       ← hidden by observer            │
│  <p>&lt;svg…&gt;…&lt;/svg&gt;</p>  ← hidden, piped to iframe    │
│  <p>@@@VIZ-END</p>         ← hidden by observer            │
│                                                            │
│  ┌──────────────── tool embed iframe ─────────────────┐    │
│  │ #iv-render      ← live SVG reconciles here         │    │
│  │ #iv-loader      ← dots + "Rendering visualization…"│    │
│  │ #iv-dl-wrap     ← download button                  │    │
│  │ #iv-toast-wrap  ← top-right toast stack            │    │
│  └────────────────────────────────────────────────────┘    │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

The observer inside the iframe uses `parent.document` (via `allow-same-origin`) to `getSearchableText(msg)` — a TreeWalker that excludes `<details type="tool_calls">` — runs a regex for the N-th `@@@VIZ-START…@@@VIZ-END` block (N = iframe's embed index), safe-cuts the partial HTML, parses into a detached tree, and reconciles into `#iv-render`. On `@@@VIZ-END` it finalizes: injects scripts (in insertion order via `async=false`), fires the done toast + chime, hides the loader.

### Finalize triggers

| Trigger | Delay | When it fires |
|---|---|---|
| `@@@VIZ-END` in source | instant | Model closed the block cleanly (the 99%+ case) |
| 30s of source stability | 30s | User stopped generation, model forgot END, or network died |

The idle fallback is deliberately much longer than any realistic inter-chunk stall — Gemini 3.1 Pro's 200-token chunks with 3-6s gaps, proxy buffering under poor network (10-20s silent pauses), and occasional stalls on other models all fit comfortably inside. If a stream genuinely dies for 30s+, the visualization is already gone — finalizing on the partial content beats a loader frozen forever, and refreshing the chat re-finalizes instantly from the saved markdown (which has both markers).

---

## 🙏 Credits

- Built on top of [**Open WebUI**](https://github.com/open-webui/open-webui) and its tool / skill system
- Protocol inspiration from the original [**inline-visualizer**](https://github.com/Classic298/open-webui-extras/tree/main/tools/inline-visualizer) by Classic298
- Color ramp palette derived from the Anthropic documentation design system
- Done chime is a three-note C-major arpeggio, synthesized on Web Audio sine oscillators with exponential decay envelopes — no audio file bundled

---

## 📜 License

Match the project you're integrating into.

---

<div align="center">
<sub>Built for the humans who want their models to <em>show</em>, not just tell.</sub>
</div>
