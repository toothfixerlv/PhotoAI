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

BASE_GRAPH = None
BASE_GRAPH_SOURCE = ""


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


def load_base_graph():
    global BASE_GRAPH, BASE_GRAPH_SOURCE
    if BASE_GRAPH_FILE.exists():
        data = json.loads(BASE_GRAPH_FILE.read_text(encoding="utf-8"))
        if _looks_like_api_graph(data):
            BASE_GRAPH = data
            BASE_GRAPH_SOURCE = str(BASE_GRAPH_FILE)
            return
        print(f"WARNING: {BASE_GRAPH_FILE} is not an API-format graph; ignoring it.")
    # Fall back: newest videos under the output root, most recent first.
    candidates = sorted(
        (p for p in OUTPUT_DIR.rglob("*") if p.suffix.lower() in VIDEO_EXTS),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for video in candidates[:15]:
        graph = extract_graph_from_video(video)
        if graph and find_required_nodes(graph):
            BASE_GRAPH = graph
            BASE_GRAPH_SOURCE = f"metadata of {video.name}"
            if not BASE_GRAPH_FILE.exists():
                BASE_GRAPH_FILE.write_text(
                    json.dumps(graph, indent=2), encoding="utf-8"
                )
                print(f"Saved recovered base graph to {BASE_GRAPH_FILE}")
            return
    BASE_GRAPH = None
    BASE_GRAPH_SOURCE = ""


def find_required_nodes(graph):
    """Locate the four nodes we patch, by class_type. Returns None if the
    graph is ambiguous (multiple candidates) or incomplete."""
    wanted = {
        "LoadImage": None,
        "MiniMaxH3ImageToVideo": None,
        "RandomNoise": None,
        "SaveVideo": None,
    }
    for node_id, node in graph.items():
        ctype = node.get("class_type")
        if ctype in wanted:
            if wanted[ctype] is not None:
                return None  # ambiguous graph; require a single-shot graph
            wanted[ctype] = node_id
    if any(v is None for v in wanted.values()):
        return None
    return wanted


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
    if BASE_GRAPH is None:
        return None, "No base graph loaded. See the banner at the top of the page."
    nodes = find_required_nodes(BASE_GRAPH)
    if not nodes:
        return None, "Base graph is missing or has duplicate required nodes."

    image = form.get("image", "")
    if image not in list_input_images():
        return None, f"Input image not found in {INPUT_DIR}: {image!r}"

    prompt_text = (form.get("prompt") or "").strip()
    if not prompt_text:
        return None, "Prompt is empty."

    try:
        seed = int(form.get("seed", ""))
        length = int(form.get("length", ""))
    except ValueError:
        return None, "Seed and length must be integers."
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
    graph = copy.deepcopy(BASE_GRAPH)
    graph[nodes["LoadImage"]]["inputs"]["image"] = image
    graph[nodes["MiniMaxH3ImageToVideo"]]["inputs"]["prompt"] = prompt_text
    graph[nodes["MiniMaxH3ImageToVideo"]]["inputs"]["length"] = length
    graph[nodes["RandomNoise"]]["inputs"]["noise_seed"] = seed
    graph[nodes["SaveVideo"]]["inputs"]["filename_prefix"] = prefix

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
        "prompt_id": prompt_id,
        "seed": seed,
        "length": length,
        "image": image,
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
<label>Input image (from Inputs\\MiniMax-H3)</label>
<select id="image"></select>
<img id="thumb" alt="input preview">
<label>Prompt library (presets, past runs, recovered from renders)</label>
<select id="library"><option value="">&mdash; pick a past prompt &mdash;</option></select>
<label>Prompt</label>
<textarea id="prompt"></textarea>
<div class="row">
<div><label>Seed</label><input id="seed" type="number"></div>
<div><label>Length (4n+1)</label>
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
    const sel=$('image');
    if(sel.options.length!==s.inputs.length){
      const cur=sel.value;sel.innerHTML='';
      for(const n of s.inputs){const o=document.createElement('option');
        o.value=o.textContent=n;sel.appendChild(o)}
      if([...sel.options].some(o=>o.value===cur))sel.value=cur;
      showThumb();}
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
function showThumb(){const v=$('image').value;
  if(v){$('thumb').src='/media/input/'+encodeURIComponent(v);
    $('thumb').style.display='block'}else{$('thumb').style.display='none'}}
$('image').addEventListener('change',showThumb);
$('library').addEventListener('change',()=>{const v=$('library').value;
  if(v!=='')$('prompt').value=lib[+v].prompt});
$('go').addEventListener('click',async()=>{
  $('go').disabled=true;$('msg').textContent='Submitting...';$('msg').className='';
  try{
    const body={image:$('image').value,prompt:$('prompt').value,
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
    server_version = "H3Studio/1.1"

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
            "base_graph_ok": BASE_GRAPH is not None,
            "base_graph_msg": (
                f"loaded from {BASE_GRAPH_SOURCE}" if BASE_GRAPH else
                "place an API-format graph at "
                f"{BASE_GRAPH_FILE} or render once from ComfyUI so a video "
                "with embedded metadata exists under the output folder."
            ),
            "inputs": list_input_images(),
            "gallery": list_output_videos(),
            "jobs": job_statuses(),
            "prompt_library": prompt_library(),
            "next_seed": next_seed(),
            "default_prompt": CONFIG["default_prompt"],
            "default_subfolder": CONFIG["default_subfolder"],
        }


def main():
    load_base_graph()
    if BASE_GRAPH:
        print(f"Base graph: {BASE_GRAPH_SOURCE}")
    else:
        print("WARNING: no base graph found yet - the UI will explain how to fix this.")
    addr = (CONFIG["listen_host"], CONFIG["listen_port"])
    httpd = ThreadingHTTPServer(addr, Handler)
    print(f"H3 Studio running at http://{addr[0]}:{addr[1]}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
