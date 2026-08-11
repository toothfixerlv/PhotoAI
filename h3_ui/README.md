# H3 Studio

A minimal local web UI for the MiniMax H3 FL2VA workflow, so you don't have
to touch the ComfyUI node graph for routine generations. Single Python file,
standard library only — it runs on the embedded Python that ships with the
isolated ComfyUI-H3 install. It talks to the existing server at
`http://127.0.0.1:8189` and changes nothing about ComfyUI itself.

## Quick start (on the Windows workstation)

1. Copy this `h3_ui` folder somewhere convenient, e.g.
   `C:\Users\Tooth\Documents\ChatGPT\MiniMax Local\h3_ui`.
2. Make sure the H3 server is running (`D:\AI\ComfyUI-H3\run_minimax_h3.bat`).
3. Run:

   ```powershell
   & 'D:\AI\ComfyUI-H3\python_embeded\python.exe' .\h3_studio.py
   ```

4. Open **http://127.0.0.1:8190** in a browser.

On first start the app needs a **base graph** (the proven 15-node FL2VA
single-shot graph). It looks for `h3_ui_base_graph.json` next to the script;
if missing, it automatically recovers the graph from the metadata that
ComfyUI embeds in previously rendered `.mp4` files under
`D:\AI\Outputs\MiniMax-H3`, then saves it as `h3_ui_base_graph.json` for
next time. (Alternatively, ask the local Claude session to copy its saved
candidate graph JSON to that filename.)

## What it does

- **Form**: input image (picked from `D:\AI\Inputs\MiniMax-H3`, with
  preview), prompt (prefilled with the proven kicks-at-range template),
  seed (auto-suggests the next unused one), length (121/141 — enforced
  `4n+1`), output subfolder and name.
- **Submit**: patches only those fields into the base graph (nodes located
  by class type: LoadImage, MiniMaxH3ImageToVideo, RandomNoise, SaveVideo)
  and POSTs to `/prompt`.
- **Jobs panel**: live queue/history status per submission, with links to
  finished outputs.
- **Gallery**: newest renders playable inline (byte-range streaming, so
  scrubbing works).
- **Run log**: every submission is appended to
  `D:\AI\Projects\H3_Khanh_Fight_2026-08-09\h3_ui_runs.jsonl`
  (timestamp, generator, prompt ID, seed, length, image, output prefix,
  full prompt text) so the manifest never goes stale.

## Provenance: telling Claude output apart from Codex output

Both AIs share the same ComfyUI server and output root, so provenance is
by convention, enforced by this app:

- **Folder**: everything submitted through this UI lands in the
  `claude_renders/` subfolder of `D:\AI\Outputs\MiniMax-H3` by default
  (older Codex-era renders live in `fight_scene/`).
- **Filename**: the default output name is `H3_claude_seed<seed>` — the
  word `claude` is in every filename unless you override it.
- **Run log**: every record in `h3_ui_runs.jsonl` carries
  `"generator": "claude-h3-studio"`, plus the prompt ID that also appears
  in ComfyUI history and in the metadata embedded in the rendered file.

If Codex keeps writing to its own folders/prefixes, a glance at the path or
filename answers "who made this" — and the run log is the authoritative
record for anything Claude submitted.

## Safety posture

- Binds to `127.0.0.1` only.
- Only ever POSTs jobs to ComfyUI and appends to its own run log; it never
  deletes or overwrites existing files (ComfyUI's `_00001_` auto-increment
  prevents output collisions; seeds already in the run log are refused).
- Serves files only from the configured input/output folders, with path
  traversal blocked.

## Configuration

Defaults are at the top of `h3_studio.py`. To override without editing the
script, create `h3_ui_config.json` next to it, e.g.:

```json
{
  "listen_port": 8190,
  "default_subfolder": "claude_renders",
  "min_seed": 26080911
}
```

`min_seed` guards the seed number range used by earlier work — the
auto-suggested seed is always at least this value and never one already in
the run log.
