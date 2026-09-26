import os
import re
import sys
import csv
import random
import asyncio
import subprocess
import edge_tts
from playwright.async_api import async_playwright

VOICE = os.getenv("TTS_VOICE", "en-US-ChristopherNeural")

def get_story_from_csv(csv_path="stories.csv"):
    """Llegeix la primera història pendent del CSV."""
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
        selected_story = rows[0]

    with open(csv_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return selected_story

async def generate_speech_with_word_timestamps(text, audio_path):
    """Genera àudio amb Edge-TTS i extreu els timestamps exactes de cada paraula."""
    communicate = edge_tts.Communicate(text, VOICE, boundary="WordBoundary")
    words = []
    
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start_sec = chunk["offset"] / 10_000_000
                dur_sec = chunk["duration"] / 10_000_000
                words.append({
                    "word": chunk["text"],
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
    """Construeix l'HTML clonat al 100% de la plantilla d'Engain."""
    story_text = post.get("story", "")
    preview_words = story_text.split()[:45]
    story_preview = " ".join(preview_words) + ("..." if len(story_text.split()) > 45 else "")

    upvotes = post.get("upvotes", "436")
    comments = post.get("comments", "57")
    subreddit = post.get("subreddit", "confessions")

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: transparent;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      display: inline-block;
      padding: 30px;
    }}
    #reddit-card {{
      background: #ffffff;
      border-radius: 20px;
      padding: 22px 26px;
      box-shadow: 0 12px 36px rgba(0, 0, 0, 0.18);
      width: 840px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .header {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .avatar {{
      width: 38px;
      height: 38px;
      border-radius: 50%;
      background: #D93900;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }}
    .avatar svg {{
      width: 24px;
      height: 24px;
      fill: #ffffff;
    }}
    .meta {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 15px;
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
      font-size: 23px;
      line-height: 1.35;
      font-weight: 700;
      color: #11151A;
      letter-spacing: -0.2px;
    }}
    .body-text {{
      font-size: 15px;
      line-height: 1.5;
      color: #374151;
      font-weight: 400;
    }}
    .pills-container {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 4px;
    }}
    .pill {{
      background-color: #E5EBEE;
      border-radius: 9999px;
      display: flex;
      align-items: center;
      padding: 7px 13px;
      gap: 7px;
      font-size: 13px;
      font-weight: 600;
      color: #11151A;
    }}
    .vote-pill {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 13px;
    }}
    .icon {{
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .icon svg {{
      width: 16px;
      height: 16px;
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

    <div class="title">{post['title']}</div>
    <div class="body-text">{story_preview}</div>

    <div class="pills-container">
      <div class="pill vote-pill">
        <div class="icon">
          <svg viewBox="0 0 20 20" fill="none" stroke="#11151A" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M10 3.5l-6 6h4v7h4v-7h4l-6-6z"/>
          </svg>
        </div>
        <span>{upvotes}</span>
        <div class="icon">
          <svg viewBox="0 0 20 20" fill="none" stroke="#11151A" stroke-width="1.8">
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
          <svg fill="none" stroke="#11151A" stroke-width="1.8" viewBox="0 0 24 24">
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
        <span>8</span>
      </div>
    </div>
  </div>
</body>
</html>"""

async def render_html_to_card_png(post, output_image_path="temp/title_card.png"):
    """Renderitza l'HTML clonat a PNG utilitzant Chromium."""
    print("🎨 Renderitzant la targeta des de plantilla HTML idèntica...")
    html_content = build_card_html(post)
    html_file = os.path.abspath("temp/card.html")
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1200, "height": 900}, device_scale_factor=2)
        await page.goto(f"file://{html_file}")
        
        card_el = page.locator("#reddit-card")
        await card_el.screenshot(path=output_image_path, omit_background=True)
        await browser.close()

def format_ass_time(seconds):
    """Format de temps per a subtítols ASS: H:MM:SS.cs"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"

def generate_popin_word_subtitles(words_list, output_path="temp/captions.ass"):
    """
    Subtítols TikTok D'UNA SOLA PARAULA AL CENTRE amb animació POP-IN BOUNCE:
    - Comença al 75% de mida
    - 0-70ms: Explota al 125% (impacte Pop)
    - 70-140ms: Rebot elàstic al 100%
    - Tipografia Impact / DejaVu Sans Bold, 88pt, groc elèctric amb vora negra de 8px.
    """
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,Impact,88,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,8,3,5,60,60,60,1

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
        
        # Allarguem lleugerament si la següent paraula comença aviat per continuïtat
        if i + 1 < len(words_list) and (words_list[i+1]["start"] - end_sec) < 0.25:
            end_sec = words_list[i+1]["start"]

        start_t = format_ass_time(start_sec)
        end_t = format_ass_time(end_sec)

        # L'animació física de rebot pop-in
        anim_tags = r"{\fscx75\fscy75\t(0,70,\fscx125\fscy125)\t(70,140,\fscx100\fscy100)}"
        dialogues.append(f"Dialogue: 0,{start_t},{end_t},TikTok,,0,0,0,,{anim_tags}{cleaned}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogues) + "\n")

def find_local_background():
    """Busca el fitxer de vídeo al repositori."""
    for f in ["background.mp4", "Background.mp4", "assets/background.mp4"]:
        if os.path.exists(f):
            return f
    for f in os.listdir("."):
        if f.lower().endswith(".mp4") and f not in ["final_video.mp4", "bg.mp4"]:
            return f
    return None

async def main():
    os.makedirs("temp", exist_ok=True)
    
    story_data = get_story_from_csv("stories.csv")
    print(f"\n📖 Story #{story_data.get('id', '1')}: {story_data['title']}")
    
    # 1. Targeta inicial
    print("🗣️ Generating speech for Title...")
    title_audio = os.path.abspath("temp/title.mp3")
    title_dur, _ = await generate_speech_with_word_timestamps(story_data["title"], title_audio)
    
    title_card = os.path.abspath("temp/title_card.png")
    await render_html_to_card_png(story_data, title_card)

    # 2. Història amb subtítols Pop-In
    print("🗣️ Generating speech for Story...")
    story_audio = os.path.abspath("temp/story.mp3")
    story_dur, story_words = await generate_speech_with_word_timestamps(story_data["story"], story_audio)
    
    adjusted_words = []
    for w in story_words:
        adjusted_words.append({
            "word": w["word"],
            "start": w["start"] + title_dur,
            "end": w["end"] + title_dur
        })

    total_video_duration = title_dur + story_dur
    print(f"\n⏱️ Durada total: {total_video_duration:.1f}s ({(total_video_duration/60):.2f} minuts)")

    # 3. Concatenar àudios
    list_path = os.path.abspath("temp/audio_list.txt")
    full_audio = os.path.abspath("temp/full_audio.mp3")
    with open(list_path, "w") as f:
        f.write(f"file '{title_audio}'\n")
        f.write(f"file '{story_audio}'\n")
            
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", full_audio], check=True)

    # 4. Fitxer de subtítols amb animació Pop-In
    ass_path = os.path.abspath("temp/captions.ass")
    generate_popin_word_subtitles(adjusted_words, ass_path)

    # 5. Fons de vídeo
    bg_file = find_local_background()
    temp_bg = os.path.abspath("temp/bg.mp4")
    if bg_file:
        print(f"📁 Using background: {bg_file}")
        start_time = random.randint(0, 15)
        subprocess.run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-ss", str(start_time),
            "-i", bg_file, "-t", str(int(total_video_duration) + 2),
            "-c:v", "libx264", "-an", temp_bg
        ], check=True)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=#0f172a:s=1080x1920:r=30:d={int(total_video_duration) + 2}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", temp_bg
        ], check=True)

    # 6. Muntatge corregit: escala la targeta a 920px per deixar 80px de marge a cada costat
    print("🎞️ Rendering final video with fitted card and Pop-In captions...")
    escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
    
    filter_complex = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v0];"
        f"[1:v]scale=920:-2[card];"
        f"[v0][card]overlay=(W-w)/2:(H-h)/2:enable='between(t,0,{title_dur:.2f})'[v1];"
        f"[v1]subtitles='{escaped_ass}'[v]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", temp_bg,
        "-i", title_card,
        "-i", full_audio,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "2:a",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-t", str(total_video_duration),
        "-pix_fmt", "yuv420p",
        "final_video.mp4"
    ]
    
    subprocess.run(cmd, check=True)
    
    size_mb = os.path.getsize("final_video.mp4") / (1024 * 1024)
    print(f"\n🎉 SUCCESS! final_video.mp4 generat ({size_mb:.2f} MB, {total_video_duration:.1f}s)")

if __name__ == "__main__":
    asyncio.run(main())