"""Montaggio automatico dei reel, secondo brand/montaggio.md (standard: reel «3 motivi», versione 4).

Passi: inquadrature (foto, video, immagini AI) -> clip con zoom lento -> transizioni sempre diverse
-> scritte e schermata finale con Remotion (cartella reel/) -> copertina sul primo fotogramma
-> musica a -14 LUFS (o la voce, nei reel parlati) -> file finale su Cloudinary.
"""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from . import catalog as cat
from . import cloudinary_api, config, imagegen
from .util import ApiError, http, redact

REEL_DIR = config.ROOT / "reel"
JOB = REEL_DIR / "public" / "job"
CACHE = REEL_DIR / "public" / "job-cache"
BRAND = REEL_DIR / "brand.json"

FPS = 30
XFADE = 0.35                 # durata di ogni transizione
SPAN_HOOK, SPAN_MID, SPAN_LAST = 3.15, 3.5, 4.6
GAP = 0.15                   # pausa tra una scritta e la successiva
END_CARD = 3.5               # schermata finale verde
MIN_SHOT = 1.4               # inquadratura piu' corta ammessa
MAX_SPOKEN = 90              # durata massima di un reel parlato
MUSIC_OFFSET = 5.0           # la musica parte da qui, cosi' la ritmica entra dopo il gancio
MAX_AI_PER_REEL = 4
# mai "dissolve": e' la dissolvenza granulosa che il titolare non vuole
TRANSITIONS = ["slideup", "smoothleft", "wipeleft", "fade", "slideleft", "smoothup", "circleopen",
               "wipeup", "smoothright", "slidedown", "fadeblack", "radial"]
MOVES = ["in", "up", "out", "right", "in", "left", "out", "up", "in", "right"]
END_LINES = ("Vieni a vedere lo studio", "Prendi un appuntamento, senza impegno")
AUDIO_FORMATS = ("mp3", "wav", "m4a", "aac", "ogg", "flac")

BOX_TOP = [70, 300, 940, 560]
BOX_LOW = [70, 1000, 940, 480]


# ---------------------------------------------------------------- strumenti

def _run(cmd: list, cwd=None, timeout=900) -> None:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-600:]
        raise ApiError(f"Montaggio: comando {Path(cmd[0]).name} fallito ({redact(tail)})")


def ensure_tools() -> None:
    """Su GitHub prepara ffmpeg e il motore Remotion solo quando serve un reel."""
    if not shutil.which("ffmpeg"):
        _run(["sudo", "apt-get", "update", "-qq"], timeout=600)
        _run(["sudo", "apt-get", "install", "-y", "-qq", "ffmpeg"], timeout=900)
    if not (REEL_DIR / "node_modules" / "remotion").exists():
        _run(["npm", "ci", "--no-audit", "--no-fund"], cwd=REEL_DIR, timeout=900)


def _browser_flag() -> list:
    exe = os.environ.get("REMOTION_BROWSER") or next(
        (p for p in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable") if Path(p).exists()), "")
    return [f"--browser-executable={exe}"] if exe else []


def _probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- tempi

def plan(reel: dict) -> dict:
    """Calcola quando parte ogni scritta e ogni inquadratura. Le scene arrivano dalla scaletta."""
    scenes = reel.get("scene") or []
    if reel.get("tipo") == "parlato":
        da = float(reel.get("da") or 0)
        a = reel.get("a")
        length = (float(a) - da) if a else float(reel.get("_durata_video") or MAX_SPOKEN)
        length = max(5.0, min(length, MAX_SPOKEN))
        hook = scenes[0] if scenes else {}
        return {"tipo": "parlato", "totale": round(length, 3),
                "scene": [{**hook, "start": 0.0, "dur": min(3.0, length)}],
                "inquadrature": [{"video": reel["video"], "da": da, "start": 0.0, "dur": length}]}
    spans = []
    for i in range(len(scenes)):
        spans.append(SPAN_HOOK if i == 0 else SPAN_LAST if i == len(scenes) - 1 else SPAN_MID)
    out_scenes, shots, t = [], [], 0.0
    for i, (sc, span) in enumerate(zip(scenes, spans)):
        last = i == len(scenes) - 1
        out_scenes.append({**sc, "start": round(t, 3), "dur": round(span if last else span - GAP, 3)})
        items = list(sc.get("inquadrature") or [])[:3]
        while len(items) > 1 and span / len(items) < MIN_SHOT:
            items.pop()
        for j, it in enumerate(items):
            shots.append({**it, "start": round(t + j * span / len(items), 3)})
        t += span
    total = round(t, 3)
    for k, s in enumerate(shots):
        nxt = shots[k + 1]["start"] if k + 1 < len(shots) else None
        s["dur"] = round((nxt - s["start"] + XFADE) if nxt is not None else (total - s["start"]), 3)
    return {"tipo": "montaggio", "totale": total, "scene": out_scenes, "inquadrature": shots}


# ---------------------------------------------------------------- materiale

def _download(url: str, path: Path) -> Path:
    r = http("GET", url, timeout=300)
    if r.status_code != 200 or not r.content:
        raise ApiError(f"Download non riuscito (HTTP {r.status_code})")
    path.write_bytes(r.content)
    return path


def _ai_image(prompt: str, notes: list, budget: list):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / ("ai_" + hashlib.sha1(prompt.strip().lower().encode()).hexdigest()[:16] + ".img")
    if path.exists():
        return path
    if budget[0] <= 0:
        notes.append("troppe immagini AI richieste: ho usato una foto dello studio")
        return None
    budget[0] -= 1
    try:
        path.write_bytes(imagegen.generate(prompt))
        return path
    except (ApiError, RuntimeError) as e:
        notes.append(f"immagine AI non generata ({redact(e)[:120]}): ho usato una foto dello studio")
        return None


def _spare_photos(catalog: dict, used: set, entry: dict) -> list:
    ok = [a for a in cat.photos(catalog, min_quality=4)
          if a["sid"] not in used and (entry.get("persone_ok") or not a["persone"])]
    return sorted(ok, key=lambda a: (not a.get("verticale"), -a["qualita"], a["sid"]))


def fetch(timeline: dict, catalog: dict, entry: dict, notes: list) -> list:
    """Scarica o genera il file di ogni inquadratura. Restituisce [(percorso, tipo, inquadratura)]."""
    JOB.mkdir(parents=True, exist_ok=True)
    used = {s.get("foto") for s in timeline["inquadrature"] if s.get("foto")}
    budget = [MAX_AI_PER_REEL]
    out = []
    for i, s in enumerate(timeline["inquadrature"]):
        if s.get("ai"):
            p = _ai_image(s["ai"], notes, budget)
            if p:
                out.append((p, "foto", {**s, "e_ai": True}))
                continue
            spare = _spare_photos(catalog, used, entry)
            if not spare:
                raise ApiError("Montaggio: immagine AI non disponibile e nessuna foto di riserva")
            used.add(spare[0]["sid"])
            s = {**s, "foto": spare[0]["sid"]}
        sid = s.get("foto") or s.get("video")
        a = cat.by_sid(catalog, sid)
        if not a:
            raise ApiError(f"Montaggio: l'elemento {sid} non e' nella libreria")
        if a["tipo"] == "video":
            url = cloudinary_api.transform_url(a["url"], "f_mp4,vc_h264,ac_aac,c_limit,h_1920")
            out.append((_download(url, JOB / f"src{i:02d}.mp4"), "video", s))
        else:
            url = cloudinary_api.transform_url(a["url"], "c_limit,w_2160,h_3840,q_auto:good,f_jpg")
            out.append((_download(url, JOB / f"src{i:02d}.jpg"), "foto", s))
    return out


def pick_music(catalog: dict, entry: dict):
    tracks = cat.music(catalog)
    if not tracks:
        return None
    n = int(hashlib.sha1(entry["id"].encode()).hexdigest(), 16) % len(tracks)
    return tracks[n]


# ---------------------------------------------------------------- video

def _clip(src: Path, kind: str, shot: dict, move: str, out: Path, keep_audio=False) -> None:
    dur = shot["dur"]
    n = max(2, round(dur * FPS))
    if kind == "video":
        vf = (f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={FPS},"
              "format=yuv420p,setsar=1")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-ss", str(shot.get("da") or 0),
               "-i", str(src), "-t", f"{dur:.3f}", "-vf", vf, "-c:v", "libx264", "-crf", "16",
               "-preset", "fast", "-r", str(FPS)]
        cmd += ["-c:a", "aac", "-ar", "48000", "-ac", "2"] if keep_audio else ["-an"]
        _run(cmd + [str(out)])
        return
    pre = "scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840"
    if move == "in":
        z, x, y = f"1+0.10*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif move == "out":
        z, x, y = f"1.10-0.10*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif move == "up":
        z, x, y = "1.10", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-on/{n})"
    elif move == "left":
        z, x, y = "1.10", f"(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"
    else:
        z, x, y = "1.10", f"(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"
    vf = f"{pre},zoompan=z='{z}':x='{x}':y='{y}':d={n}:s=1080x1920:fps={FPS},format=yuv420p,setsar=1"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(src), "-vf", vf, "-frames:v", str(n),
          "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-r", str(FPS), "-an", str(out)])


def base_video(timeline: dict, sources: list, seed: str) -> Path:
    """Unisce le inquadrature con transizioni sempre diverse. Restituisce reel/public/job/video.mp4."""
    off = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    clips = []
    spoken = timeline["tipo"] == "parlato"
    for i, (src, kind, shot) in enumerate(sources):
        c = JOB / f"clip{i:02d}.mp4"
        _clip(src, kind, shot, MOVES[(off + i) % len(MOVES)], c, keep_audio=spoken)
        clips.append(c)
    out = JOB / "video.mp4"
    if len(clips) == 1:
        shutil.copyfile(clips[0], out)
        return out
    inputs, fc, prev = [], [], "[0:v]"
    for c in clips:
        inputs += ["-i", str(c)]
    shots = timeline["inquadrature"]
    for i in range(1, len(clips)):
        tr = TRANSITIONS[(off + i - 1) % len(TRANSITIONS)]
        fc.append(f"{prev}[{i}:v]xfade=transition={tr}:duration={XFADE}:offset={shots[i]['start']:.3f}[v{i}]")
        prev = f"[v{i}]"
    _run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc), "-map", prev,
          "-t", f"{timeline['totale']:.3f}", "-c:v", "libx264", "-crf", "16", "-preset", "fast",
          "-pix_fmt", "yuv420p", "-an", str(out)])
    return out


def props(timeline: dict) -> dict:
    brand = json.loads(BRAND.read_text(encoding="utf-8"))
    scenes = []
    spoken = timeline["tipo"] == "parlato"
    for i, sc in enumerate(timeline["scene"]):
        text = {"lines": list(sc.get("righe") or []), "accent": sc.get("accento") or ""}
        if sc.get("etichetta"):
            text["label"] = sc["etichetta"]
        scenes.append({
            "id": f"c{i + 1:02d}", "type": "hook", "mode": "overlay", "start": sc["start"], "dur": sc["dur"],
            "variant": "slam", "text": text, "box": BOX_LOW if (i or spoken) else BOX_TOP,
            "source": {"kind": "brief", "ref": "brand/montaggio.md"}, "what": "", "why": "",
            "hide_subtitles": True, "transition_in": "cut" if i == 0 else "slide", "transition_out": "fade",
            "tone": "feature"})
    return {"video": "job/video.mp4", "captions": {"duration": timeline["totale"], "segments": [], "words": []},
            "brand": brand, "style": "marker", "inserts": [], "subtitles": "none", "drift": False, "hook": None,
            "corner": True, "endCard": {"line1": END_LINES[0], "line2": END_LINES[1], "seconds": END_CARD},
            "sceneTone": "feature", "scenes": scenes}


def render(p: dict) -> tuple:
    """Scritte e schermata finale con Remotion. Restituisce (video muto, copertina jpg)."""
    props_path = JOB / "props.json"
    props_path.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    muted, cover = JOB / "render.mp4", JOB / "cover.jpg"
    conc = str(max(1, min(4, (os.cpu_count() or 2) - 1)))
    common = [f"--props={props_path}", "--log=error", *_browser_flag()]
    _run(["npx", "remotion", "render", "src/index.ts", "ReelKit", str(muted), "--muted", "--crf=18",
          f"--concurrency={conc}", *common], cwd=REEL_DIR, timeout=1500)
    # la copertina e' il gancio gia' completo (il titolo entra in meno di un secondo)
    _run(["npx", "remotion", "still", "src/index.ts", "ReelKit", str(cover), "--frame=24",
          "--image-format=jpeg", "--jpeg-quality=92", *common], cwd=REEL_DIR, timeout=600)
    return muted, cover


def audio_track(timeline: dict, music_path, out: Path) -> Path:
    total = timeline["totale"] + END_CARD
    norm = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if timeline["tipo"] == "parlato":
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(JOB / "clip00.mp4"), "-vn", "-af",
              f"apad=whole_dur={total:.3f},afade=t=out:st={timeline['totale']:.3f}:d=0.6,{norm}",
              "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(out)])
        return out
    fade_at = max(0.0, total - 2.5)
    _run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-ss", str(MUSIC_OFFSET), "-i",
          str(music_path), "-t", f"{total:.3f}", "-af",
          f"afade=t=in:st=0:d=0.4,afade=t=out:st={fade_at:.3f}:d=2.5,{norm}",
          "-ar", "48000", "-ac", "2", str(out)])
    return out


def finish(muted: Path, cover: Path, audio, out: Path) -> Path:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(muted), "-i", str(cover)]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-filter_complex", "[1:v]scale=1080:1920[c];[0:v][c]overlay=enable='eq(n\\,0)'[v]", "-map", "[v]"]
    if audio:
        cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-movflags", "+faststart", str(out)]
    _run(cmd)
    return out


def frames(video: Path, timeline: dict) -> list:
    """Fotogrammi per il critico: copertina, il centro di ogni scena, la schermata finale."""
    times = [0.0] + [sc["start"] + sc["dur"] / 2 for sc in timeline["scene"]] + [timeline["totale"] + 2.0]
    out = []
    for i, t in enumerate(times):
        p = JOB / f"frame{i:02d}.jpg"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
              "-vf", "scale=540:960", "-q:v", "3", str(p)])
        out.append(p.read_bytes())
    return out


# ---------------------------------------------------------------- tutto insieme

def outline(timeline: dict, sources: list) -> str:
    """La scaletta in parole, per il titolare e per il critico."""
    rows = []
    for i, sc in enumerate(timeline["scene"]):
        txt = " / ".join(sc.get("righe") or [])
        lab = f"[{sc['etichetta']}] " if sc.get("etichetta") else ""
        rows.append(f"{sc['start']:.1f}s  {lab}{txt}")
    kinds = []
    for _, kind, shot in sources:
        kinds.append("AI" if shot.get("e_ai") else ("video" if kind == "video" else "foto"))
    rows.append(f"{timeline['totale']:.1f}s  schermata finale: {END_LINES[0]}")
    rows.append("Inquadrature: " + ", ".join(kinds))
    return "\n".join(rows)


def build(entry: dict, draft: dict, catalog: dict, version) -> dict:
    """Monta il reel e lo carica su Cloudinary. Restituisce le grafiche nel formato della pipeline."""
    ensure_tools()
    if JOB.exists():
        shutil.rmtree(JOB)
    JOB.mkdir(parents=True)
    reel = dict(draft["reel"])
    notes = []
    if reel.get("tipo") == "parlato":
        v = cat.by_sid(catalog, reel.get("video", ""))
        reel["_durata_video"] = (v or {}).get("durata")
    timeline = plan(reel)
    sources = fetch(timeline, catalog, entry, notes)
    base_video(timeline, sources, entry["id"])
    muted, cover = render(props(timeline))
    audio = None
    if timeline["tipo"] == "parlato":
        audio = audio_track(timeline, None, JOB / "audio.wav")
    else:
        track = pick_music(catalog, entry)
        if track:
            audio = audio_track(timeline, _download(track["url"], JOB / "musica.audio"), JOB / "audio.wav")
        else:
            notes.append("nessuna musica nella libreria (file che iniziano con MUSICA): reel senza audio")
    final = finish(muted, cover, audio, JOB / "reel.mp4")
    critic_frames = frames(final, timeline)

    base_id = f"{config.PREVIEW_PREFIX}/{entry['id']}_v{version}"
    vid = cloudinary_api.upload_bytes(final.read_bytes(), base_id + "_reel", resource_type="video")
    cov = cloudinary_api.upload_bytes(cover.read_bytes(), base_id + "_copertina")
    video_url = vid["secure_url"]
    ai_used = any(s.get("e_ai") for _, _, s in sources)
    return {"video": video_url,
            "anteprima_video": cloudinary_api.transform_url(video_url, "c_limit,w_720,q_auto:good"),
            "copertina": cov["secure_url"], "immagini": [], "fotogrammi": critic_frames,
            "ai": ai_used, "scaletta": outline(timeline, sources), "note_montaggio": notes,
            "public_ids": ["video:" + vid["public_id"], cov["public_id"]]}
