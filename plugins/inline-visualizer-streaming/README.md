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

If you came from the original [inline-visualizer](https://github.com/Classic298/open-webui-extras/tree/main/tools/inline-visualizer) plugin, **everything visible to the model stays the same** (still called `render_visualization`, still loads `view_skill("visualize")` first). Under the hood, it's been rewritten from scratch. Every row below is an actual behavior delta, not marketing copy.

| | **v1 — classic** | **v2 — streaming** |
|---|---|---|
| **Rendering timing** | Static. Model finishes writing → tool assembles a complete HTML payload → iframe pops in fully formed. User stares at a blank wrapper for the entire generation. | **Live.** Iframe fills in token-by-token as the model types. First SVG elements render within ~50 ms of the opening marker arriving. Charts, cards, and diagrams appear incrementally — the user watches it materialize. |
| **Protocol** | ` ```visualization ` fenced code block. Routes through Open WebUI's `CodeBlock.svelte` → CodeMirror. | Plain-text `@@@VIZ-START … @@@VIZ-END` markers. Tokenizes as ordinary paragraph/html content — **never touches CodeBlock, CodeMirror, virtualizers, or editors of any kind**. |
| **Long-content reliability** | **Breaks** past CodeMirror's virtualization threshold: scrolled-off lines get evicted from the DOM mid-scroll, SVG backgrounds go missing, refresh corrupts whitespace at soft-wraps. Every fix uncovered a new CodeMirror edge case. | **Bulletproof.** `message.textContent` is authoritative at every tick. No virtualization, no line eviction, no soft-wrap mangling. 80k-char SVGs render identically to 800-char ones. |
| **Mid-stream rendering** | N/A — user waits for the full response. | Custom safe-cut HTML parser flushes the longest valid prefix on each chunk. Incremental DOM reconciler only appends new nodes — **existing nodes never re-mount, animations never re-trigger, zero flicker**. |
| **Refresh / reload behavior** | Fine (static HTML stored in `message.embeds[]`). | Equal to v1. On mount, the observer scans the saved markdown for its marker pair, reconstructs the iframe state, fires `finalize()` immediately. No re-streaming needed. |
| **Bridges** | `sendPrompt`, `openLink` | `sendPrompt`, `openLink`, **`copyText`** (auto-toast), **`toast(msg, kind)`** (success/info/warn/error, auto-dismiss), **`saveState(k,v)`** / **`loadState(k,fallback)`** (per-message `localStorage` scope, survives reloads) |
| **Stream-completion feedback** | — | Localized top-right "Visualization ready" toast + three-note C-major arpeggio synthesized on Web Audio sine oscillators. Fires **only** when the stream was witnessed live — refreshes of completed messages stay silent via a growth-based detector, never by heuristic. |
| **i18n surface** | 1 string (download tooltip) × 46 languages = 46 translations | 5 strings × 46 languages = **230 translations baked in** — download, loader label, "unavailable" notice, "Copied" toast, "Visualization ready" toast. Auto-detected from `<html data-iv-lang>`, `localStorage.locale`, and `navigator.language`. |
| **External script loading** | N/A | External `<script src>` + inline scripts **serialized via a Promise chain**. Each script awaits `onload` of all previously-queued scripts before executing. `Chart`, `d3`, `vega-embed` etc. are guaranteed defined before your consumer code runs. |
| **HTML-parser safety** | Model-generated code goes straight to `innerHTML`. | Safe-cut parser tracks the tokenizer state across script-data-escape and double-escape transitions, so embedded `<!--` / `<script` literals inside the model's code can't break our own script boundary. |
| **Tool-result-example bleed** | N/A | TreeWalker excludes `<details type="tool_calls" \| reasoning \| code_execution \| code_interpreter>` when scanning, so the skill's own example markers inside the tool-call details never hijack the regex. |
| **`navigator.vibrate` spam** | — | Silently stubbed to a no-op inside every iframe so Chrome's `[Intervention] Blocked call to navigator.vibrate…` logs don't pollute the console when a model reaches for haptic feedback. |
| **Per-tick efficiency** | — | `msg.textContent` is cached between ticks; unchanged → the full pipeline (regex extract, DOM walk, reconciler) short-circuits to a string compare. Only one tick per real DOM mutation does real work. |
| **Finalize-fallback tuning** | — | 30-second idle window chosen empirically to survive Gemini 3.1 Pro's 200-token chunk spacing + proxy buffering under degraded network — premature finalize on partial content can't happen. |
| **Static-mode fallback** | Supported | **Removed.** Streaming is the only path. `tool.py` dropped ~200 lines of dual-mode branching and `_sanitize_content` logic. |
| **Plugin footprint** | `tool.py` + `SKILL.md` | Same two files, same install flow — **no Open WebUI core patches**. Everything sits in a parasitic same-origin iframe observer. |

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
- Dynamic `<script>` insertion serialized through a promise chain — external `<script src>` tags are awaited via `onload` before any subsequent inline `<script>` executes, so `Chart` / `d3` / `vega-embed` / etc. are always defined by the time your consumer code runs
- `navigator.vibrate` is silently stubbed inside the iframe — models sometimes reach for haptic feedback on click, and Chrome logs an `[Intervention]` line every time without a user gesture; the stub keeps the console clean
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

### 4. Enable same-origin access — **required**

> [!IMPORTANT]
> Streaming mode **does not work without this setting.** The observer's entire job is reading the parent chat's DOM to find markers as they stream in — that requires cross-frame access, which the browser blocks unless the iframe is allowed same-origin. With the setting off, every visualization renders a localized "Streaming visualization unavailable" notice instead of content.

Steps:

1. **User Settings → Interface**
2. Scroll down
3. Enable **Allow iframe same origin**

> [!NOTE]
> Enabling same-origin means JavaScript inside a visualization can reach the parent Open WebUI page. That is a platform-level permission the tool cannot narrow — it's the cost of this streaming architecture. If your threat model can't accept that, use the [original v1 inline-visualizer](https://github.com/Classic298/open-webui-extras/tree/main/tools/inline-visualizer) instead (static mode doesn't need same-origin).

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

### What works in Strict mode

Chart.js, D3.js, Vega-Lite, and any other pure-client-side library load and render normally — the three major CDN hosts (cdnjs, jsdelivr, unpkg) are on the `script-src` allowlist, and `'unsafe-eval'` is granted so runtime expression compilers (Vega's `new Function(...)`, some templating libs) work. Visualizations with **inline data** (data arrays hardcoded in the SVG/HTML source) work without limits. The SKILL tells the model to inline data by default, so this covers 99% of prompts.

**What Strict blocks:** runtime `fetch()` calls, `d3.csv('https://…')`, Vega-Lite specs with `data: { url: '…' }`, external images, form submits. If you want a live-updating weather widget or a chart that pulls a CSV at render time, switch to **None**.

> [!NOTE]
> Strict allows `'unsafe-inline'` and `'unsafe-eval'` for scripts because LLM-generated visualizations ship their own inline code and some libraries compile expressions at runtime. Those relaxations don't create exfil channels — the real outbound blockers (`connect-src 'none'`, `form-action 'none'`, `img-src` restricted, `object-src 'none'`) stay in place regardless. If you need a truly locked-down iframe, disable JavaScript entirely at the Open WebUI level; the tool can't render anything useful without `'unsafe-inline'` scripts.

### Why `script-src` allows a CDN but `connect-src` doesn't

Loading a library from a CDN is a plain `GET` of a fixed public URL — zero data leaves the browser. Allowing `fetch()` to the same CDN opens an exfiltration channel: the URL itself becomes the payload (`fetch('https://cdn.example/?data=' + userContent)` gets logged server-side even if it returns 404). Different directions, different risks — Strict grants "read known public asset", denies "write arbitrary data anywhere". This is intentional, not an oversight.

### Sourcemap warnings in DevTools

When DevTools is open, the browser attempts to fetch `.map` files for loaded libraries from the same CDN. Strict blocks those via `connect-src 'none'` — you'll see lines like `Connecting to 'https://cdn.jsdelivr.net/npm/vega.min.js.map' violates CSP…` in the console. Those are DevTools-only noise (end users with DevTools closed never see them). We intentionally don't relax `connect-src` to fix this because that would reopen the exfil surface above for all users.

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

Open **Workspace → Tools → Inline Visualizer (Streaming) → gear icon**, flip the **`chime`** valve to off, save. Chime disabled globally — the function definition is stripped from the iframe entirely (not shipped as a silent no-op), saving ~1 KB per visualization.
</details>

<details>
<summary><b>I updated <code>tool.py</code> and nothing changed</b></summary>

Open WebUI doesn't hot-reload tool source from disk. You have to paste the new contents into **Workspace → Tools → Inline Visualizer (Streaming) → Save** again.

Additionally, existing chats keep their old iframe baked into `message.embeds[]` — only newly-triggered tool calls pick up the update.

On **multi-worker deployments** (`UVICORN_WORKERS > 1`), each worker process has its own in-memory tool module cache. A save updates the worker that handled the save request; every other worker keeps its old compiled module until the backend restarts. If you're on a multi-worker setup and you see stale behavior even from fresh chats, restart the backend — or use the separate [`claude/cross-worker-plugin-cache`](https://github.com/Classic298/open-webui/tree/claude/cross-worker-plugin-cache) branch which adds Redis pub/sub invalidation across workers.
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

The observer inside the iframe uses `parent.document` (via `allow-same-origin`) to `getSearchableText(msg)` — a TreeWalker that excludes `<details type="tool_calls">` — runs a regex for the N-th `@@@VIZ-START…@@@VIZ-END` block (N = iframe's embed index), safe-cuts the partial HTML, parses into a detached tree, and reconciles into `#iv-render`. On `@@@VIZ-END` it finalizes: injects scripts via a promise chain (external waits on `onload` before the next inline script executes), fires the done toast + chime, hides the loader.

### Finalize triggers

| Trigger | Delay | When it fires |
|---|---|---|
| `@@@VIZ-END` in source | instant | Model closed the block cleanly (the 99%+ case) |
| 30s of source stability | 30s | User stopped generation, model forgot END, or network died |

The idle fallback is deliberately much longer than any realistic inter-chunk stall — Gemini 3.1 Pro's 200-token chunks with 3-6s gaps, proxy buffering under poor network (10-20s silent pauses), and occasional stalls on other models all fit comfortably inside. If a stream genuinely dies for 30s+, the visualization is already gone — finalizing on the partial content beats a loader frozen forever, and refreshing the chat re-finalizes instantly from the saved markdown (which has both markers).

---

## 🙏 Credits

Built on top of [**Open WebUI**](https://github.com/open-webui/open-webui) and its tool / skill system.

---

<div align="center">
<sub>Built for the humans who want their models to <em>show</em>, not just tell.</sub>
</div>
