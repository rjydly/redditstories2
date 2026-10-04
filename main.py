import os
import re
import sys
import csv
import random
import shutil
import asyncio
import subprocess
import edge_tts
from playwright.async_api import async_playwright
from pydub import AudioSegment

# CONFIGURACIÓ DE VEU: JennyNeural (+35%, +12Hz)
VOICE = os.getenv("TTS_VOICE", "en-US-JennyNeural")
VOICE_RATE = os.getenv("TTS_RATE", "+35%")
VOICE_PITCH = os.getenv("TTS_PITCH", "+12Hz")

# Pausa màxima permesa després d'un punt (0.22s = ritme ràpid sense buits)
MAX_PAUSE_BETWEEN_SENTENCES = 0.22

def strip_sfx_tags(text):
    """Elimina les etiquetes [sfx:nom] per al text visual de la targeta i Edge-TTS."""
    cleaned = re.sub(r'\[sfx:\s*[\w\-]+\]', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+([.,!?;:])', r'\1', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()

def parse_text_and_sfx(text):
    """
    Extreu el text net mantenint tota la puntuació original
    i calcula la posició de cada efecte de so.
    """
    sfx_pattern = re.compile(r'\[sfx:\s*([\w\-]+)\]', re.IGNORECASE)
    sfx_markers = []
    
    for match in sfx_pattern.finditer(text):
        sfx_name = match.group(1).lower()
        text_before = text[:match.start()]
        clean_before = sfx_pattern.sub('', text_before)
        word_count = len(clean_before.split())
        sfx_markers.append((word_count, sfx_name))
        
    clean_text = sfx_pattern.sub('', text)
    clean_text = re.sub(r'\s+([.,!?;:])', r'\1', clean_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text, sfx_markers

def trim_and_compress_audio(audio_path, words, output_path, max_pause_sec=MAX_PAUSE_BETWEEN_SENTENCES):
    """
    Conserva la puntuació i entonació humana, però retalla els silencis
    morts entre frases perquè comencin ràpidament sense pauses llargues.
    """
    if not words or not os.path.exists(audio_path):
        return 0.0, words

    audio = AudioSegment.from_file(audio_path)
    
    first_start = words[0]["start"]
    initial_trim_sec = 0.0
    if first_start > 0.08:
        initial_trim_sec = first_start - 0.04
        initial_trim_ms = int(initial_trim_sec * 1000)
        audio = audio[initial_trim_ms:]
    
    current_words = []
    for w in words:
        current_words.append({
            "word": w["word"],
            "start": max(0.0, w["start"] - initial_trim_sec),
            "end": max(0.0, w["end"] - initial_trim_sec)
        })

    cuts = []
    for i in range(len(current_words) - 1):
        w_end = current_words[i]["end"]
        next_start = current_words[i+1]["start"]
        gap = next_start - w_end
        if gap > max_pause_sec:
            cut_start = w_end + max_pause_sec
            cut_end = next_start
            cuts.append((cut_start, cut_end))

    if not cuts:
        last_end = current_words[-1]["end"]
        final_keep_ms = min(len(audio), int((last_end + 0.12) * 1000))
        audio = audio[:final_keep_ms]
        audio.export(output_path, format="mp3")
        return len(audio) / 1000.0, current_words

    new_audio = AudioSegment.empty()
    last_pos_ms = 0
    time_removed = 0.0
    final_words = []
    word_idx = 0

    for cut_start, cut_end in cuts:
        cut_start_ms = int(cut_start * 1000)
        cut_end_ms = int(cut_end * 1000)
        cut_dur = cut_end - cut_start

        new_audio += audio[last_pos_ms:cut_start_ms]
        last_pos_ms = cut_end_ms

        while word_idx < len(current_words) and current_words[word_idx]["start"] < cut_start:
            cw = current_words[word_idx]
            final_words.append({
                "word": cw["word"],
                "start": max(0.0, cw["start"] - time_removed),
                "end": max(0.0, cw["end"] - time_removed)
            })
            word_idx += 1

        time_removed += cut_dur

    new_audio += audio[last_pos_ms:]

    while word_idx < len(current_words):
        cw = current_words[word_idx]
        final_words.append({
            "word": cw["word"],
            "start": max(0.0, cw["start"] - time_removed),
            "end": max(0.0, cw["end"] - time_removed)
        })
        word_idx += 1

    if final_words:
        last_end = final_words[-1]["end"]
        final_keep_ms = min(len(new_audio), int((last_end + 0.12) * 1000))
        new_audio = new_audio[:final_keep_ms]

    new_audio.export(output_path, format="mp3")
    total_dur = len(new_audio) / 1000.0
    return total_dur, final_words

def mix_sfx_into_audio(base_audio_path, sfx_events, output_path):
    """
    Barreja els efectes de so sobre la veu.
    Si un so és al final (com el FAAAH), estén la pista perquè NO es talli mai.
    """
    possible_dirs = [
        os.path.abspath("audios"),
        os.path.abspath("assets/audios"),
        os.path.abspath("assets/audio"),
        os.path.abspath("audio")
    ]
    base = AudioSegment.from_file(base_audio_path)

    if not sfx_events:
        shutil.copy(base_audio_path, output_path)
        return output_path, len(base) / 1000.0

    for timestamp_sec, sfx_name in sfx_events:
        sfx_path = None
        for d in possible_dirs:
            if os.path.exists(d):
                for ext in [".mp3", ".wav", ".ogg", ".aac", ".m4a"]:
                    candidate = os.path.join(d, f"{sfx_name}{ext}")
                    if os.path.exists(candidate):
                        sfx_path = candidate
                        break
            if sfx_path:
                break
                
        if not sfx_path:
            if sfx_name != "pop":
                print(f"⚠️ Alerta: Efecte de so '{sfx_name}' no trobat a audios/ ni a assets/audios/")
            continue

        sfx_audio = AudioSegment.from_file(sfx_path)
        sfx_audio = sfx_audio - 2
        pos_ms = max(0, int(timestamp_sec * 1000))
        
        # SI EL SO SUPERA LA DURADA DE LA VEU (ex: FAAAH al final), ESTENEM LA PISTA
        required_duration_ms = pos_ms + len(sfx_audio) + 150
        if required_duration_ms > len(base):
            silence_padding = AudioSegment.silent(duration=required_duration_ms - len(base))
            base = base + silence_padding

        base = base.overlay(sfx_audio, position=pos_ms)
        folder_found = os.path.basename(os.path.dirname(sfx_path))
        print(f"🔊 SFX afegit: '{sfx_name}' al segon {timestamp_sec:.2f}s (des de {folder_found}/)")

    base.export(output_path, format="mp3")
    final_duration_sec = len(base) / 1000.0
    return output_path, final_duration_sec

def get_story_from_csv(csv_path="stories.csv"):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No s'ha trobat el fitxer {csv_path}.")

    rows = []
    selected_story = None

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if not selected_story and row.get("status", "pending") == "pending":
                selected_story = row
                row["status"] = "done"
            rows.append(row)

    if not selected_story:
        if not rows:
            raise ValueError("El fitxer stories.csv està buit.")
        selected_story = rows[0]

    with open(csv_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return selected_story

def find_all_asset_videos():
    search_dirs = ["assets", "assets/backgrounds"]
    found = []
    for d in search_dirs:
        if os.path.exists(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
                        full_path = os.path.join(root, f)
                        if not any(x in f.lower() for x in ["temp", "final_video", "title_card"]):
                            found.append(full_path)
    return list(set(found))

def get_clean_background_video(target_duration):
    temp_dir = os.path.abspath("temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_bg = os.path.join(temp_dir, "bg.mp4")
    used_file = "used_backgrounds.txt"

    used_items = set()
    if os.path.exists(used_file):
        with open(used_file, "r", encoding="utf-8") as f:
            used_items = set(line.strip() for line in f if line.strip())

    local_vids = find_all_asset_videos()
    if local_vids:
        print(f"📁 S'han detectat {len(local_vids)} vídeos a la carpeta assets/")
        unused_vids = [v for v in local_vids if os.path.basename(v) not in used_items]
        
        if not unused_vids:
            print("🔄 S'han utilitzat tots els vídeos d'assets! Reiniciant el cicle de rotació...")
            unused_vids = local_vids
            with open(used_file, "w", encoding="utf-8") as f:
                f.write("")

        chosen = random.choice(unused_vids)
        chosen_name = os.path.basename(chosen)
        print(f"💎 Fent servir vídeo seleccionat d'assets: '{chosen_name}'")

        with open(used_file, "a", encoding="utf-8") as f:
            f.write(chosen_name + "\n")

        subprocess.run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-ss", "0",
            "-i", os.path.abspath(chosen),
            "-t", str(int(target_duration) + 2),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an",
            temp_bg
        ], check=True)
        return temp_bg

    for f in ["background.mp4", "Background.mp4"]:
        if os.path.exists(f):
            subprocess.run([
                "ffmpeg", "-y", "-stream_loop", "-1", "-ss", "0",
                "-i", os.path.abspath(f), "-t", str(int(target_duration) + 2),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an", temp_bg
            ], check=True)
            return temp_bg

    return None

async def generate_speech_with_word_timestamps(text, audio_path):
    communicate = edge_tts.Communicate(
        text,
        VOICE,
        rate=VOICE_RATE,
        pitch=VOICE_PITCH,
        boundary="WordBoundary"
    )
    words = []
    
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start_sec = chunk["offset"] / 10_000_000
                dur_sec = chunk["duration"] / 10_000_000
                raw_token = chunk["text"].strip()
                
                if "-" in raw_token and len(raw_token) > 5:
                    parts = [p for p in raw_token.split("-") if p]
                    if parts:
                        sub_dur = dur_sec / len(parts)
                        for idx, p in enumerate(parts):
                            words.append({
                                "word": p,
                                "start": start_sec + (idx * sub_dur),
                                "end": start_sec + ((idx + 1) * sub_dur)
                            })
                        continue

                words.append({
                    "word": raw_token,
                    "start": start_sec,
                    "end": start_sec + dur_sec
                })

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    total_dur = float(result.stdout.strip())

    if not words and text:
        w_list = text.split()
        if w_list:
            step = total_dur / len(w_list)
            for idx, w in enumerate(w_list):
                words.append({
                    "word": w,
                    "start": idx * step,
                    "end": (idx + 1) * step
                })

    return total_dur, words

def build_card_html(post):
    clean_story = strip_sfx_tags(post.get("story", ""))
    clean_title = strip_sfx_tags(post.get("title", ""))

    preview_words = clean_story.split()[:22]
    story_preview = " ".join(preview_words) + "..."

    upvotes = f"{random.uniform(30.0, 160.0):.1f}k"
    comments = f"{random.uniform(7.0, 20.0):.1f}k"
    subreddit = post.get("subreddit", "confessions")

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: transparent;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      display: inline-block;
      padding: 30px;
    }}
    #reddit-card {{
      background: rgba(255, 255, 255, 0.86);
      border-radius: 28px;
      padding: 34px 38px;
      box-shadow: 0 16px 44px rgba(0, 0, 0, 0.28);
      border: 1.5px solid rgba(255, 255, 255, 0.55);
      width: 760px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .header {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .avatar {{
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: #D93900;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }}
    .avatar svg {{
      width: 28px;
      height: 28px;
      fill: #ffffff;
    }}
    .meta {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 17px;
    }}
    .subreddit {{
      font-weight: 700;
      color: #2E3640;
    }}
    .separator {{
      color: #5C6C74;
    }}
    .time {{
      color: #5C6C74;
      font-weight: 400;
    }}
    .title {{
      font-size: 33px;
      line-height: 1.32;
      font-weight: 800;
      color: #11151A;
      letter-spacing: -0.4px;
    }}
    .body-text {{
      font-size: 21px;
      line-height: 1.48;
      color: #374151;
      font-weight: 500;
    }}
    .pills-container {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 6px;
    }}
    .pill {{
      background-color: rgba(229, 235, 238, 0.92);
      border-radius: 9999px;
      display: flex;
      align-items: center;
      padding: 9px 16px;
      gap: 8px;
      font-size: 16px;
      font-weight: 700;
      color: #11151A;
    }}
    .vote-pill {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 16px;
    }}
    .icon {{
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .icon svg {{
      width: 19px;
      height: 19px;
    }}
  </style>
</head>
<body>
  <div id="reddit-card">
    <div class="header">
      <div class="avatar">
        <svg viewBox="0 0 20 20">
          <path d="M16.67 10a1.46 1.46 0 0 0-2.47-1 6.84 6.84 0 0 0-3.85-1.23L11 4.29l2.15.46a1 1 0 1 0 .22-.72l-2.48-.53a.35.35 0 0 0-.41.27L10 6.6a6.84 6.84 0 0 0-3.87 1.23 1.46 1.46 0 1 0-1.61 2.39 2.87 2.87 0 0 0 0 .78 1.46 1.46 0 0 0 .93 2.14 4.5 4.5 0 0 0 4.55 1.86 4.5 4.5 0 0 0 4.55-1.86 1.46 1.46 0 0 0 .93-2.14 2.87 2.87 0 0 0 0-.78 1.45 1.45 0 0 0 .59-1.33zM7.5 10.75A1 1 0 1 1 8.5 9.75a1 1 0 0 1-1 1zm5.8 2.22a3.3 3.3 0 0 1-3.3 0 .25.25 0 0 1 .25-.43 2.8 2.8 0 0 0 2.8 0 .25.25 0 0 1 .25.43zm-.8-2.22a1 1 0 1 1 1-1 1 1 0 0 1-1 1z"/>
        </svg>
      </div>
      <div class="meta">
        <span class="subreddit">r/{subreddit}</span>
        <span class="separator">•</span>
        <span class="time">2 hr. ago</span>
      </div>
    </div>

    <div class="title">{clean_title}</div>
    <div class="body-text">{story_preview}</div>

    <div class="pills-container">
      <div class="pill vote-pill">
        <div class="icon">
          <svg viewBox="0 0 20 20" fill="none" stroke="#11151A" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M10 3.5l-6 6h4v7h4v-7h4l-6-6z"/>
          </svg>
        </div>
        <span>{upvotes}</span>
        <div class="icon">
          <svg viewBox="0 0 20 20" fill="none" stroke="#11151A" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M10 16.5l6-6h-4v-7h-4v7h-4l6 6z"/>
          </svg>
        </div>
      </div>

      <div class="pill">
        <div class="icon">
          <svg fill="#11151A" viewBox="0 0 20 20">
            <path d="M10 1a9 9 0 0 0-9 9c0 1.947.79 3.58 1.935 4.957L.231 17.661A.784.784 0 0 0 .785 19H10a9 9 0 0 0 9-9 9 9 0 0 0-9-9m0 16.2H6.162c-.994.004-1.907.053-3.045.144l-.076-.188a37 37 0 0 0 2.328-2.087l-1.05-1.263C3.297 12.576 2.8 11.331 2.8 10c0-3.97 3.23-7.2 7.2-7.2s7.2 3.23 7.2 7.2-3.23 7.2-7.2 7.2"/>
          </svg>
        </div>
        <span>{comments}</span>
      </div>

      <div class="pill">
        <div class="icon">
          <svg fill="none" stroke="#11151A" stroke-width="2" viewBox="0 0 24 24">
            <circle cx="12" cy="8" r="6"/>
            <path d="M15.477 12.89L17 22l-5-3-5 3 1.523-9.11"/>
          </svg>
        </div>
      </div>

      <div class="pill">
        <div class="icon">
          <svg fill="#11151A" viewBox="0 0 20 20">
            <path d="m12.8 17.524 6.89-6.887a.9.9 0 0 0 0-1.273L12.8 2.477a1.64 1.64 0 0 0-1.782-.349 1.64 1.64 0 0 0-1.014 1.518v2.593C4.054 6.728 1.192 12.075 1 17.376a1.35 1.35 0 0 0 .862 1.32 1.35 1.35 0 0 0 1.531-.364l.334-.381c1.705-1.944 3.323-3.791 6.277-4.103v2.509c0 .667.398 1.262 1.014 1.518a1.64 1.64 0 0 0 1.783-.349zm-.994-1.548V12h-.9c-3.969 0-6.162 2.1-8.001 4.161.514-4.011 2.823-8.16 8-8.16h.9V4.024L17.784 10z"/>
          </svg>
        </div>
      </div>
    </div>
  </div>
</body>
</html>"""

async def render_html_to_card_png(post, output_image_path):
    html_content = build_card_html(post)
    html_file = os.path.abspath("temp/card.html")
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1200, "height": 1100}, device_scale_factor=2)
        await page.goto(f"file://{html_file}")
        card_el = page.locator("#reddit-card")
        await card_el.screenshot(path=output_image_path, omit_background=True)
        await browser.close()

def format_ass_time(seconds):
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"

def generate_popin_word_subtitles(words_list, output_path="temp/captions.ass"):
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,Impact,86,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,8,3,5,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogues = []
    
    for i, item in enumerate(words_list):
        cleaned = item["word"].upper().strip()
        cleaned = re.sub(r'^[^\w]+|[^\w]+$', '', cleaned)
        if not cleaned:
            continue

        start_sec = item["start"]
        end_sec = item["end"]
        
        if i + 1 < len(words_list) and (words_list[i+1]["start"] - end_sec) < 0.25:
            end_sec = words_list[i+1]["start"]

        start_t = format_ass_time(start_sec)
        end_t = format_ass_time(end_sec)

        fs_override = ""
        if len(cleaned) >= 9:
            adjusted_fs = max(56, int(86 * (8.5 / len(cleaned))))
            fs_override = f"\\fs{adjusted_fs}"

        anim_tags = rf"{{\fscx75\fscy75\t(0,70,\fscx125\fscy125)\t(70,140,\fscx100\fscy100){fs_override}}}"
        dialogues.append(f"Dialogue: 0,{start_t},{end_t},TikTok,,0,0,0,,{anim_tags}{cleaned}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogues) + "\n")

def get_sfx_timestamp(word_idx, words_list, fallback_time):
    if not words_list:
        return fallback_time
    if word_idx <= 0:
        return words_list[0]["start"]
    if word_idx < len(words_list):
        return words_list[word_idx]["start"]
    return words_list[-1]["end"]

async def main():
    os.makedirs("temp", exist_ok=True)
    os.makedirs("audios", exist_ok=True)
    os.makedirs("assets/audios", exist_ok=True)
    
    story_data = get_story_from_csv("stories.csv")
    print(f"\n📖 Story #{story_data.get('id', '1')}: {story_data['title']}")

    # 1. Parsejar text i sfx de títol i història
    title_clean, title_sfx_markers = parse_text_and_sfx(story_data["title"])
    story_clean, story_sfx_markers = parse_text_and_sfx(story_data["story"])

    # Renderitzar targeta visual de Reddit
    title_card = os.path.abspath("temp/title_card.png")
    await render_html_to_card_png(story_data, title_card)

    # 2. Generar àudio del Títol amb JennyNeural
    print("🗣️ Generant àudio del Títol amb JennyNeural...")
    raw_title_audio = os.path.abspath("temp/raw_title.mp3")
    title_dur_raw, title_words_raw = await generate_speech_with_word_timestamps(title_clean, raw_title_audio)
    
    title_audio = os.path.abspath("temp/title.mp3")
    title_dur, title_words = trim_and_compress_audio(raw_title_audio, title_words_raw, title_audio)

    # 3. Generar àudio de la Història amb JennyNeural
    print("🗣️ Generant àudio de la Història amb JennyNeural...")
    raw_story_audio = os.path.abspath("temp/raw_story.mp3")
    story_dur_raw, story_words_raw = await generate_speech_with_word_timestamps(story_clean, raw_story_audio)

    story_audio = os.path.abspath("temp/story.mp3")
    story_dur, story_words = trim_and_compress_audio(raw_story_audio, story_words_raw, story_audio)

    # Ajustar paraules de la història a la línia de temps global
    adjusted_words = []
    for w in story_words:
        adjusted_words.append({
            "word": w["word"],
            "start": w["start"] + title_dur,
            "end": w["end"] + title_dur
        })

    # 4. Calcular timestamps exactes dels SFX
    all_sfx_events = []
    
    # 💥 Pop automàtic sincronitzat amb la targeta d'inici (segon 0.0s)
    all_sfx_events.append((0.0, "pop"))

    for word_idx, sfx_name in title_sfx_markers:
        t = get_sfx_timestamp(word_idx, title_words, 0.0)
        all_sfx_events.append((t, sfx_name))
        
    for word_idx, sfx_name in story_sfx_markers:
        t = get_sfx_timestamp(word_idx, story_words, 0.0)
        all_sfx_events.append((title_dur + t, sfx_name))

    # 5. Concatenar àudios i barrejar efectes de so (amb extensió si el FAAAH sobrepassa la veu)
    raw_full_audio = os.path.abspath("temp/raw_full_audio.mp3")
    mixed_full_audio = os.path.abspath("temp/full_audio.mp3")
    list_path = os.path.abspath("temp/audio_list.txt")
    
    with open(list_path, "w") as f:
        f.write(f"file '{title_audio}'\n")
        f.write(f"file '{story_audio}'\n")
            
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", raw_full_audio], check=True)
    
    # mix_sfx_into_audio ens retorna la durada real final (tenint en compte el FAAAH)
    mixed_full_audio, total_video_duration = mix_sfx_into_audio(raw_full_audio, all_sfx_events, mixed_full_audio)
    print(f"\n⏱️ Durada final del vídeo (amb SFX complets): {total_video_duration:.1f}s")

    # 6. Fitxer de subtítols
    ass_path = os.path.abspath("temp/captions.ass")
    generate_popin_word_subtitles(adjusted_words, ass_path)

    # 7. Fons de vídeo en alta definició (CRF 18)
    temp_bg = get_clean_background_video(total_video_duration)

    # 8. Muntatge final FFmpeg (CRF 19 - Preset fast)
    print("🎞️ Renderitzant vídeo final...")
    escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
    fade_out_start = max(0.0, title_dur - 0.25)

    filter_complex = (
        f"[0:v]null[v0];"
        f"[1:v]format=yuva420p,"
        f"scale=w='trunc((880 * if(lt(t,0.15), 0.75 + 0.30*(t/0.15), if(lt(t,0.25), 1.05 - 0.05*((t-0.15)/0.10), 1.0)))/2)*2':h=-2:eval=frame,"
        f"fade=t=in:st=0:d=0.15:alpha=1,"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.25:alpha=1[card];"
        f"[v0][card]overlay=(W-w)/2:(H-h)/2:enable='between(t,0,{title_dur:.2f})'[v1];"
        f"[v1]subtitles='{escaped_ass}'[v]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", temp_bg,
        "-framerate", "30",
        "-loop", "1",
        "-t", str(title_dur),
        "-i", title_card,
        "-i", mixed_full_audio,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "2:a",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "19",
        "-threads", "0",
        "-c:a", "aac",
        "-t", str(total_video_duration),
        "-pix_fmt", "yuv420p",
        "final_video.mp4"
    ]
    
    subprocess.run(cmd, check=True)
    
    size_mb = os.path.getsize("final_video.mp4") / (1024 * 1024)
    print(f"\n🎉 SUCCESS! final_video.mp4 generat amb èxit ({size_mb:.2f} MB, {total_video_duration:.1f}s)")

if __name__ == "__main__":
    asyncio.run(main())