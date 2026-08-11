#!/usr/bin/env python3
"""
H3 Studio - a minimal local web UI for the MiniMax H3 FL2VA ComfyUI workflow.

Single file, standard library only, so it runs on the embedded Python that
ships with the isolated ComfyUI-H3 install. It wraps the ComfyUI HTTP API at
http://127.0.0.1:8189 with a simple form: pick an input image, edit the
prompt, set seed/length/output folder, press Generate, watch progress, and
play finished renders in a gallery.

Run it with:

    D:\\AI\\ComfyUI-H3\\python_embeded\\python.exe h3_studio.py

then open http://127.0.0.1:8190 in a browser.

Safety posture:
  - Only ever POSTs jobs to ComfyUI and appends to its own runs log.
  - Never deletes or overwrites any existing file. ComfyUI's own
    auto-increment (_00001_, _00002_, ...) prevents output collisions.
  - Binds to 127.0.0.1 only.

The base graph (the proven 15-node FL2VA single-shot graph) is loaded from
h3_ui_base_graph.json next to this script. If that file does not exist, the
app recovers the graph from the metadata that ComfyUI embeds in previously
rendered .mp4 files under the output root, then saves it for next time.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --------------------------------------------------------------------------
# Configuration. Edit here, or drop overrides into h3_ui_config.json next to
# this script (same keys, JSON object).
# --------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent

CONFIG = {
    "comfy_url": "http://127.0.0.1:8189",
    "listen_host": "127.0.0.1",
    "listen_port": 8190,
    "input_dir": r"D:\AI\Inputs\MiniMax-H3",
    "output_dir": r"D:\AI\Outputs\MiniMax-H3",
    "project_dir": r"D:\AI\Projects\H3_Khanh_Fight_2026-08-09",
    "runs_log": "",            # default: <project_dir>\h3_ui_runs.jsonl
    "base_graph_file": "",     # default: <script dir>\h3_ui_base_graph.json
    "default_subfolder": "claude_renders",
    "default_length": 121,
    "min_seed": 26080911,      # seeds below this are reserved by earlier work
    "ffprobe": "ffprobe",
    "gallery_limit": 30,
    "default_prompt": (
        "Immediate continuation of the same photoreal fight, beginning "
        "exactly from the supplied first frame with no reset, cut, new "
        "location, or return to an earlier pose. Preserve both adult "
        "identities, wardrobe, environment, camera side, lens, and cinematic "
        "color grade exactly. Normal real-time 1x speed. Keep the fighters "
        "at kicking and long range for the entire shot: a kickboxing "
        "exchange of legs and long-range strikes, not infighting. Every "
        "attack is a kick or long-range strike with full extension, a clean "
        "chamber, a snap, and a grounded landing. Keep both complete bodies, "
        "legs, and feet visible in a readable medium-wide lateral tracking "
        "shot. Realistic gravity, momentum, limb mechanics, choreographed "
        "contact, and stable faces. Do NOT drift into close-range hand "
        "exchanges, boxing combinations, clinching, grappling, or floor "
        "fighting. No slow motion, pose holds, repeated frames, blood, "
        "injury, weapons, extra people, text, logos, watermark, black bars, "
        "duplicated limbs, fused bodies, or identity swaps. Audio: ambience, "
        "clothing movement, footfalls, and controlled impact sounds only; "
        "no dialogue or music."
    ),
}

_cfg_file = SCRIPT_DIR / "h3_ui_config.json"
if _cfg_file.exists():
    try:
        CONFIG.update(json.loads(_cfg_file.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not parse {_cfg_file}: {exc}")

INPUT_DIR = Path(CONFIG["input_dir"])
OUTPUT_DIR = Path(CONFIG["output_dir"])
PROJECT_DIR = Path(CONFIG["project_dir"])
RUNS_LOG = Path(CONFIG["runs_log"]) if CONFIG["runs_log"] else PROJECT_DIR / "h3_ui_runs.jsonl"
BASE_GRAPH_FILE = (
    Path(CONFIG["base_graph_file"]) if CONFIG["base_graph_file"] else SCRIPT_DIR / "h3_ui_base_graph.json"
)

PROMPTS_FILE = SCRIPT_DIR / "h3_ui_prompts.json"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mov"}

_jobs_lock = threading.Lock()
_jobs = {}  # prompt_id -> record dict (also appended to runs log)

# mode_id -> {label, graph, source, images, prompt_node, seed_node,
#              seed_key, save_nodes, has_length}
TEMPLATES = {}


# --------------------------------------------------------------------------
# ComfyUI API helpers
# --------------------------------------------------------------------------
def comfy_get(path, timeout=10):
    with urllib.request.urlopen(CONFIG["comfy_url"] + path, timeout=timeout) as resp:
        return json.load(resp)


def comfy_post(path, payload, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        CONFIG["comfy_url"] + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


# --------------------------------------------------------------------------
# Base graph recovery
# --------------------------------------------------------------------------
def _looks_like_api_graph(data):
    return isinstance(data, dict) and any(
        isinstance(v, dict) and "class_type" in v for v in data.values()
    )


def extract_graph_from_video(path):
    """ComfyUI embeds the executed API graph in output-file metadata."""
    try:
        out = subprocess.run(
            [CONFIG["ffprobe"], "-v", "error", "-show_entries", "format_tags",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        tags = json.loads(out.stdout or "{}").get("format", {}).get("tags", {})
    except Exception:  # noqa: BLE001
        return None
    for key in ("prompt", "Prompt", "comment", "Comment", "workflow"):
        raw = tags.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if _looks_like_api_graph(data):
            return data
    return None


_prompt_cache = {}  # path str -> (mtime, prompt text or None)


def extract_prompt_from_video(path):
    """Pull the generation prompt out of a rendered file's embedded graph."""
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _prompt_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    graph = extract_graph_from_video(path)
    prompt = None
    if graph:
        for node in graph.values():
            if node.get("class_type") == "MiniMaxH3ImageToVideo":
                prompt = node.get("inputs", {}).get("prompt")
                break
    _prompt_cache[key] = (mtime, prompt)
    return prompt


def prompt_library():
    """Reusable prompts: presets file, then run log, then past renders."""
    lib, seen = [], set()

    def add(label, text):
        if text and text.strip() and text not in seen:
            seen.add(text)
            lib.append({"label": label, "prompt": text})

    if PROMPTS_FILE.exists():
        try:
            for item in json.loads(PROMPTS_FILE.read_text(encoding="utf-8")):
                add(item.get("label", "preset"), item.get("prompt"))
        except Exception:  # noqa: BLE001
            pass
    for rec in reversed(read_runs_log()[-20:]):
        add(f"run seed {rec.get('seed')}", rec.get("prompt_text"))
    if OUTPUT_DIR.exists():
        vids = sorted(
            (p for p in OUTPUT_DIR.rglob("*") if p.suffix.lower() in VIDEO_EXTS),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        for v in vids[:10]:
            add(f"render: {v.stem[:60]}", extract_prompt_from_video(v))
    return lib[:20]


def analyze_graph(graph):
    """Find the patchable slots in an API-format graph, generically:
    every LoadImage node becomes an image picker (labelled from its
    _meta.title if the workflow author set one), plus the prompt, seed,
    and save nodes."""
    info = {"images": [], "prompt_node": None, "seed_node": None,
            "seed_key": "noise_seed", "save_nodes": [], "has_length": False}
    prompt_candidates = []
    for nid, node in graph.items():
        if not isinstance(node, dict):
            continue
        ctype = node.get("class_type", "")
        ins = node.get("inputs", {}) or {}
        title = (node.get("_meta") or {}).get("title") or ""
        if ctype == "LoadImage":
            info["images"].append(
                {"node": nid, "label": title or f"Image (node {nid})"}
            )
        if isinstance(ins.get("prompt"), str):
            prompt_candidates.append((0 if "length" in ins else 1, len(nid), nid))
        if "noise_seed" in ins or "seed" in ins:
            if info["seed_node"] is None:
                info["seed_node"] = nid
                info["seed_key"] = "noise_seed" if "noise_seed" in ins else "seed"
        if "filename_prefix" in ins:
            info["save_nodes"].append(nid)
    if prompt_candidates:
        prompt_candidates.sort()
        nid = prompt_candidates[0][2]
        info["prompt_node"] = nid
        info["has_length"] = "length" in (graph[nid].get("inputs") or {})
    info["images"].sort(key=lambda s: (len(s["node"]), s["node"]))
    return info


def _template_ok(info):
    return bool(info["prompt_node"] and info["seed_node"] and info["save_nodes"])


def load_templates():
    """Build the mode list: the default first-frame FL2VA graph plus any
    h3_ui_graph_<mode>.json files placed next to this script."""
    TEMPLATES.clear()

    def register(mode_id, label, graph, source):
        info = analyze_graph(graph)
        if not _template_ok(info):
            print(f"WARNING: template {mode_id} ({source}) lacks "
                  "prompt/seed/save nodes; skipped.")
            return
        TEMPLATES[mode_id] = dict(info, label=label, graph=graph, source=source)

    graph, source = None, ""
    if BASE_GRAPH_FILE.exists():
        data = json.loads(BASE_GRAPH_FILE.read_text(encoding="utf-8"))
        if _looks_like_api_graph(data):
            graph, source = data, str(BASE_GRAPH_FILE)
        else:
            print(f"WARNING: {BASE_GRAPH_FILE} is not an API-format graph; ignoring it.")
    if graph is None:
        # Fall back: newest videos under the output root, most recent first.
        candidates = sorted(
            (p for p in OUTPUT_DIR.rglob("*") if p.suffix.lower() in VIDEO_EXTS),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        for video in candidates[:15]:
            data = extract_graph_from_video(video)
            if data and _template_ok(analyze_graph(data)):
                graph, source = data, f"metadata of {video.name}"
                if not BASE_GRAPH_FILE.exists():
                    BASE_GRAPH_FILE.write_text(
                        json.dumps(data, indent=2), encoding="utf-8"
                    )
                    print(f"Saved recovered base graph to {BASE_GRAPH_FILE}")
                break
    if graph is not None:
        register("first_frame", "First frame → video (FL2VA)", graph, source)

    for path in sorted(SCRIPT_DIR.glob("h3_ui_graph_*.json")):
        mode_id = path.stem[len("h3_ui_graph_"):]
        if not mode_id or mode_id in TEMPLATES:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"WARNING: could not parse {path.name}: {exc}")
            continue
        if _looks_like_api_graph(data):
            register(mode_id, mode_id.replace("_", " ").title(), data, str(path))


# --------------------------------------------------------------------------
# Filesystem helpers
# --------------------------------------------------------------------------
def list_input_images():
    if not INPUT_DIR.exists():
        return []
    files = [p for p in INPUT_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in files]


def list_output_videos():
    if not OUTPUT_DIR.exists():
        return []
    vids = [p for p in OUTPUT_DIR.rglob("*") if p.suffix.lower() in VIDEO_EXTS]
    vids.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in vids[: CONFIG["gallery_limit"]]:
        st = p.stat()
        out.append({
            "rel": p.relative_to(OUTPUT_DIR).as_posix(),
            "name": p.name,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return out


def read_runs_log():
    if not RUNS_LOG.exists():
        return []
    records = []
    for line in RUNS_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def next_seed():
    seeds = [r.get("seed", 0) for r in read_runs_log() if isinstance(r.get("seed"), int)]
    base = max(seeds, default=CONFIG["min_seed"] - 1)
    return max(base + 1, CONFIG["min_seed"])


def append_run(record):
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUNS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


_SUBFOLDER_RE = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def safe_under(root, relpath):
    """Resolve relpath under root, refusing traversal outside it."""
    target = (root / relpath).resolve()
    root = root.resolve()
    if root != target and root not in target.parents:
        return None
    return target


# --------------------------------------------------------------------------
# Job submission
# --------------------------------------------------------------------------
def submit_job(form):
    if not TEMPLATES:
        return None, "No workflow templates loaded. See the banner at the top of the page."
    mode = form.get("mode") or next(iter(TEMPLATES))
    tpl = TEMPLATES.get(mode)
    if not tpl:
        return None, f"Unknown mode: {mode!r}"

    inputs_avail = set(list_input_images())
    images = form.get("images") or {}
    if not isinstance(images, dict):
        return None, "images must be an object mapping node id to filename."
    for slot in tpl["images"]:
        chosen = images.get(slot["node"], "")
        if not chosen:
            return None, f"Missing image for slot: {slot['label']}"
        if chosen not in inputs_avail:
            return None, f"Input image not found in {INPUT_DIR}: {chosen!r}"

    prompt_text = (form.get("prompt") or "").strip()
    if not prompt_text:
        return None, "Prompt is empty."

    try:
        seed = int(form.get("seed", ""))
    except ValueError:
        return None, "Seed must be an integer."
    length = None
    if tpl["has_length"]:
        try:
            length = int(form.get("length", ""))
        except ValueError:
            return None, "Length must be an integer."
        if length < 5 or length > 241 or (length - 1) % 4 != 0:
            return None, "Length must be 4n+1 (e.g. 121 or 141)."
    used = {r.get("seed") for r in read_runs_log()}
    if seed in used:
        return None, f"Seed {seed} already used in the runs log; pick a new one."

    subfolder = (form.get("subfolder") or CONFIG["default_subfolder"]).strip().strip("/")
    if not _SUBFOLDER_RE.match(subfolder):
        return None, "Output subfolder may only contain letters, digits, _ - and /."
    name = (form.get("name") or f"H3_claude_seed{seed}").strip()
    if not _NAME_RE.match(name):
        return None, "Name may only contain letters, digits, _ and -."
    prefix = f"{subfolder}/{name}"

    import copy
    graph = copy.deepcopy(tpl["graph"])
    for slot in tpl["images"]:
        graph[slot["node"]]["inputs"]["image"] = images[slot["node"]]
    graph[tpl["prompt_node"]]["inputs"]["prompt"] = prompt_text
    if length is not None:
        graph[tpl["prompt_node"]]["inputs"]["length"] = length
    graph[tpl["seed_node"]]["inputs"][tpl["seed_key"]] = seed
    for nid in tpl["save_nodes"]:
        graph[nid]["inputs"]["filename_prefix"] = prefix

    try:
        result = comfy_post("/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})
    except urllib.error.URLError as exc:
        return None, f"ComfyUI unreachable: {exc}"
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        return None, f"Submission rejected: {json.dumps(result)[:500]}"

    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "claude-h3-studio",
        "mode": mode,
        "prompt_id": prompt_id,
        "seed": seed,
        "length": length,
        "images": {slot["label"]: images[slot["node"]] for slot in tpl["images"]},
        "filename_prefix": prefix,
        "prompt_text": prompt_text,
    }
    append_run(record)
    with _jobs_lock:
        _jobs[prompt_id] = dict(record, status="queued")
    return record, None


def job_statuses():
    """Merge in-memory jobs with live queue/history state."""
    with _jobs_lock:
        jobs = {pid: dict(rec) for pid, rec in _jobs.items()}
    if not jobs:
        for rec in read_runs_log()[-10:]:
            pid = rec.get("prompt_id")
            if pid:
                jobs[pid] = dict(rec, status="unknown")
    try:
        queue = comfy_get("/queue")
        running = {item[1] for item in queue.get("queue_running", [])}
        pending = {item[1] for item in queue.get("queue_pending", [])}
    except Exception:  # noqa: BLE001
        running, pending = set(), set()
    for pid, rec in jobs.items():
        if pid in running:
            rec["status"] = "running"
        elif pid in pending:
            rec["status"] = "pending"
        else:
            try:
                hist = comfy_get(f"/history/{pid}")
            except Exception:  # noqa: BLE001
                hist = {}
            entry = hist.get(pid)
            if entry:
                status = entry.get("status", {})
                rec["status"] = "completed" if status.get("completed") else status.get("status_str", "done")
                outs = []
                for node_out in entry.get("outputs", {}).values():
                    for key in ("images", "video", "videos", "gifs"):
                        for item in node_out.get(key, []) or []:
                            fn = item.get("filename")
                            sub = item.get("subfolder", "")
                            if fn:
                                outs.append((Path(sub) / fn).as_posix() if sub else fn)
                if outs:
                    rec["outputs"] = outs
            elif rec.get("status") not in ("completed",):
                rec["status"] = rec.get("status", "unknown")
    return sorted(jobs.values(), key=lambda r: r.get("ts", ""), reverse=True)


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------
PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>H3 Studio</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#101418;--panel:#1a2028;--edge:#2b3442;--fg:#dde5ee;--dim:#8595a8;
--accent:#4da3ff;--ok:#4ec98a;--warn:#e6b34d;--err:#e66a6a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 "Segoe UI",system-ui,sans-serif}
header{display:flex;align-items:center;gap:12px;padding:10px 18px;
background:var(--panel);border-bottom:1px solid var(--edge)}
header h1{font-size:16px;margin:0;font-weight:600}
#server-dot{width:10px;height:10px;border-radius:50%;background:var(--err)}
#server-dot.ok{background:var(--ok)}
#banner{padding:8px 18px;background:#3a2b20;color:var(--warn);display:none}
main{display:grid;grid-template-columns:minmax(320px,430px) 1fr;gap:16px;
padding:16px 18px;max-width:1500px}
@media(max-width:900px){main{grid-template-columns:1fr}}
section{background:var(--panel);border:1px solid var(--edge);
border-radius:10px;padding:14px 16px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;
color:var(--dim);margin:0 0 10px}
label{display:block;margin:10px 0 4px;color:var(--dim);font-size:12px}
input,select,textarea{width:100%;background:#0d1116;color:var(--fg);
border:1px solid var(--edge);border-radius:6px;padding:7px 9px;font:inherit}
textarea{min-height:170px;resize:vertical}
.row{display:flex;gap:10px}.row>div{flex:1}
button{margin-top:14px;width:100%;padding:10px;border:0;border-radius:8px;
background:var(--accent);color:#08121f;font-weight:700;font-size:15px;
cursor:pointer}
button:disabled{background:#31404f;color:var(--dim);cursor:default}
#thumb{max-width:100%;border-radius:8px;margin-top:8px;display:none}
#msg{margin-top:10px;font-size:13px;white-space:pre-wrap}
#msg.err{color:var(--err)}#msg.ok{color:var(--ok)}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:5px 8px;border-bottom:1px solid var(--edge);text-align:left}
.status-running{color:var(--warn)}.status-pending{color:var(--dim)}
.status-completed{color:var(--ok)}
#gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));
gap:12px;margin-top:6px}
.card{background:#0d1116;border:1px solid var(--edge);border-radius:8px;
overflow:hidden}
.card video{width:100%;display:block;background:#000}
.card .meta{padding:6px 9px;font-size:12px;color:var(--dim);
word-break:break-all}
</style></head><body>
<header><div id="server-dot"></div><h1>H3 Studio</h1>
<span id="server-info" style="color:var(--dim);font-size:12px"></span></header>
<div id="banner"></div>
<main>
<section>
<h2>New generation</h2>
<label>Mode</label>
<select id="mode"></select>
<div id="modehint" style="font-size:12px;color:var(--dim);margin-top:4px"></div>
<div id="imageslots"></div>
<label>Prompt library (presets, past runs, recovered from renders)</label>
<select id="library"><option value="">&mdash; pick a past prompt &mdash;</option></select>
<label>Prompt</label>
<textarea id="prompt"></textarea>
<div class="row">
<div><label>Seed</label><input id="seed" type="number"></div>
<div id="lengthwrap"><label>Length (4n+1)</label>
<select id="length"><option>121</option><option>141</option></select></div>
</div>
<div class="row">
<div><label>Output subfolder</label><input id="subfolder"></div>
<div><label>Name</label><input id="name" placeholder="auto"></div>
</div>
<button id="go">Generate</button>
<div id="msg"></div>
</section>
<div style="display:flex;flex-direction:column;gap:16px">
<section><h2>Jobs</h2>
<table><thead><tr><th>Time (UTC)</th><th>Seed</th><th>Len</th>
<th>Status</th><th>Output</th></tr></thead>
<tbody id="jobs"></tbody></table></section>
<section><h2>Gallery (newest first)</h2><div id="gallery"></div></section>
</div>
</main>
<script>
const $=id=>document.getElementById(id);
let lastGallery="";let lib=[];let libKey="";
let modes=[];let modeKey="";let inputsList=[];let inputsKey="";
function renderSlots(){
  const m=modes.find(x=>x.id===$('mode').value)||modes[0];
  const c=$('imageslots');
  const prev={};c.querySelectorAll('select').forEach(s=>prev[s.dataset.node]=s.value);
  c.innerHTML='';
  if(!m)return;
  $('lengthwrap').style.display=m.has_length?'':'none';
  $('modehint').textContent=modes.length<=1?
    'Only first-frame mode is loaded. Add Ref2VA / first+last modes by saving graphs as h3_ui_graph_<name>.json - see README.':'';
  for(const slot of m.images){
    const lab=document.createElement('label');lab.textContent=
      slot.label+'  (from Inputs\\\\MiniMax-H3)';
    const sel=document.createElement('select');sel.dataset.node=slot.node;
    for(const n of inputsList){const o=document.createElement('option');
      o.value=o.textContent=n;sel.appendChild(o)}
    if(prev[slot.node]&&[...sel.options].some(o=>o.value===prev[slot.node]))
      sel.value=prev[slot.node];
    const img=document.createElement('img');
    img.style.cssText='max-width:100%;border-radius:8px;margin-top:6px';
    const upd=()=>{if(sel.value){img.src='/media/input/'+
      encodeURIComponent(sel.value);img.style.display='block'}
      else img.style.display='none'};
    sel.addEventListener('change',upd);upd();
    c.appendChild(lab);c.appendChild(sel);c.appendChild(img);
  }
}
async function j(url,opts){const r=await fetch(url,opts);return r.json()}
function esc(s){return String(s).replace(/[&<>"']/g,
c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
async function refreshState(){
  try{
    const s=await j('/api/state');
    $('server-dot').className=s.server_ok?'ok':'';
    $('server-info').textContent=s.server_ok?
      ('ComfyUI OK - VRAM free '+s.vram_free_gb+' GB'):'ComfyUI unreachable';
    if(!s.base_graph_ok){$('banner').style.display='block';
      $('banner').textContent='No base graph available: '+s.base_graph_msg;}
    else{$('banner').style.display='none'}
    const mk=JSON.stringify((s.modes||[]).map(m=>m.id+':'+m.images.length));
    const ik=JSON.stringify(s.inputs);
    if(mk!==modeKey){modeKey=mk;modes=s.modes||[];
      const M=$('mode');const cur=M.value;M.innerHTML='';
      for(const m of modes){const o=document.createElement('option');
        o.value=m.id;o.textContent=m.label;M.appendChild(o)}
      if([...M.options].some(o=>o.value===cur))M.value=cur;
      inputsList=s.inputs;inputsKey=ik;renderSlots();}
    else if(ik!==inputsKey){inputsList=s.inputs;inputsKey=ik;renderSlots();}
    const lk=JSON.stringify((s.prompt_library||[]).map(p=>p.label));
    if(lk!==libKey){libKey=lk;lib=s.prompt_library||[];
      const L=$('library');const cur=L.value;
      L.innerHTML='<option value="">&mdash; pick a past prompt &mdash;</option>';
      lib.forEach((p,i)=>{const o=document.createElement('option');
        o.value=i;o.textContent=p.label;L.appendChild(o)});
      if([...L.options].some(o=>o.value===cur))L.value=cur;}
    if(!$('seed').value)$('seed').value=s.next_seed;
    if(!$('prompt').value)$('prompt').value=s.default_prompt;
    if(!$('subfolder').value)$('subfolder').value=s.default_subfolder;
    const jb=$('jobs');jb.innerHTML='';
    for(const job of s.jobs){
      const tr=document.createElement('tr');
      const out=(job.outputs||[]).map(o=>
        '<a style="color:var(--accent)" href="/media/output/'+
        encodeURIComponent(o).replace(/%2F/g,'/')+'" target="_blank">'+
        esc(o.split('/').pop())+'</a>').join('<br>');
      tr.innerHTML='<td>'+esc((job.ts||'').replace('T',' ').replace('+00:00',''))+
        '</td><td>'+esc(job.seed)+'</td><td>'+esc(job.length)+
        '</td><td class="status-'+esc(job.status)+'">'+esc(job.status)+
        '</td><td>'+out+'</td>';
      jb.appendChild(tr);}
    const gKey=JSON.stringify(s.gallery.map(g=>g.rel));
    if(gKey!==lastGallery){lastGallery=gKey;
      const g=$('gallery');g.innerHTML='';
      for(const v of s.gallery){
        const d=document.createElement('div');d.className='card';
        d.innerHTML='<video controls preload="metadata" src="/media/output/'+
          encodeURIComponent(v.rel).replace(/%2F/g,'/')+'"></video>'+
          '<div class="meta">'+esc(v.rel)+'<br>'+esc(v.mtime)+' - '+
          (v.size/1048576).toFixed(1)+' MB</div>';
        g.appendChild(d);}}
  }catch(e){$('server-dot').className='';}
}
$('mode').addEventListener('change',renderSlots);
$('library').addEventListener('change',()=>{const v=$('library').value;
  if(v!=='')$('prompt').value=lib[+v].prompt});
$('go').addEventListener('click',async()=>{
  $('go').disabled=true;$('msg').textContent='Submitting...';$('msg').className='';
  try{
    const imgs={};
    $('imageslots').querySelectorAll('select').forEach(s=>imgs[s.dataset.node]=s.value);
    const body={mode:$('mode').value,images:imgs,prompt:$('prompt').value,
      seed:$('seed').value,length:$('length').value,
      subfolder:$('subfolder').value,name:$('name').value};
    const r=await j('/api/generate',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(r.error){$('msg').textContent=r.error;$('msg').className='err'}
    else{$('msg').textContent='Submitted. Prompt ID: '+r.prompt_id;
      $('msg').className='ok';$('seed').value='';$('name').value='';}
  }catch(e){$('msg').textContent='Request failed: '+e;$('msg').className='err'}
  $('go').disabled=false;refreshState();
});
refreshState();setInterval(refreshState,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "H3Studio/1.2"

    def log_message(self, fmt, *args):  # quieter console
        pass

    # -- helpers ----------------------------------------------------------
    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type):
        """Serve a file with byte-range support (needed for video scrubbing)."""
        try:
            size = path.stat().st_size
        except OSError:
            self.send_error(404)
            return
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        status = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                elif m.group(1):
                    end = size - 1
                if start > end or start >= size:
                    self.send_error(416)
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    # -- routes -----------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = urllib.parse.unquote(parsed.path)
        if route == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif route == "/api/state":
            self.send_json(self.state())
        elif route.startswith("/media/input/"):
            target = safe_under(INPUT_DIR, route[len("/media/input/"):])
            if target and target.is_file() and target.suffix.lower() in IMAGE_EXTS:
                ctype = "image/png" if target.suffix.lower() == ".png" else "image/jpeg"
                self.send_file(target, ctype)
            else:
                self.send_error(404)
        elif route.startswith("/media/output/"):
            target = safe_under(OUTPUT_DIR, route[len("/media/output/"):])
            if target and target.is_file() and target.suffix.lower() in VIDEO_EXTS:
                self.send_file(target, "video/mp4")
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/generate":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            form = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self.send_json({"error": "Bad request body."}, 400)
            return
        record, error = submit_job(form)
        if error:
            self.send_json({"error": error}, 400)
        else:
            self.send_json(record)

    def state(self):
        server_ok, vram_free = False, None
        try:
            stats = comfy_get("/system_stats", timeout=4)
            server_ok = True
            devs = stats.get("devices") or []
            if devs:
                vram_free = round(devs[0].get("vram_free", 0) / 1024**3, 1)
        except Exception:  # noqa: BLE001
            pass
        return {
            "server_ok": server_ok,
            "vram_free_gb": vram_free,
            "base_graph_ok": bool(TEMPLATES),
            "base_graph_msg": (
                "; ".join(f"{t['label']}: {t['source']}" for t in TEMPLATES.values())
                if TEMPLATES else
                "place an API-format graph at "
                f"{BASE_GRAPH_FILE} or render once from ComfyUI so a video "
                "with embedded metadata exists under the output folder."
            ),
            "modes": [
                {"id": mid, "label": t["label"], "images": t["images"],
                 "has_length": t["has_length"]}
                for mid, t in TEMPLATES.items()
            ],
            "inputs": list_input_images(),
            "gallery": list_output_videos(),
            "jobs": job_statuses(),
            "prompt_library": prompt_library(),
            "next_seed": next_seed(),
            "default_prompt": CONFIG["default_prompt"],
            "default_subfolder": CONFIG["default_subfolder"],
        }


def main():
    load_templates()
    if TEMPLATES:
        for mid, t in TEMPLATES.items():
            print(f"Mode '{mid}' ({t['label']}): {t['source']} "
                  f"[{len(t['images'])} image slot(s)]")
    else:
        print("WARNING: no workflow templates found yet - the UI will explain how to fix this.")
    addr = (CONFIG["listen_host"], CONFIG["listen_port"])
    httpd = ThreadingHTTPServer(addr, Handler)
    print(f"H3 Studio running at http://{addr[0]}:{addr[1]}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
