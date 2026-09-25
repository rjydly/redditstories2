import os
import re
import sys
import random
import asyncio
import subprocess
import requests
import feedparser
from PIL import Image, ImageDraw, ImageFont
import edge_tts

# Configuració
SUBREDDIT_NAME = os.getenv("SUBREDDIT", "AskReddit")
VOICE = os.getenv("TTS_VOICE", "en-US-ChristopherNeural")
TARGET_TOTAL_DURATION = 55  # Durada màxima recomanada

def get_reddit_thread_with_comments():
    """Obté el títol i els comentaris en anglès."""
    print(f"📥 Fetching top thread and comments from r/{SUBREDDIT_NAME}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    rss_url = f"https://www.reddit.com/r/{SUBREDDIT_NAME}/hot.rss"
    feed = feedparser.parse(rss_url, agent=headers["User-Agent"])
    
    blocked_keywords = ["moderator", "looking for", "rules", "megathread", "weekly thread", "discord"]
    selected_entry = None
    
    for entry in feed.entries:
        title = entry.title.strip()
        if not any(kw in title.lower() for kw in blocked_keywords) and 25 < len(title) < 200:
            selected_entry = entry
            break
            
    if not selected_entry:
        selected_entry = feed.entries[1] if len(feed.entries) > 1 else feed.entries[0]

    post_url = selected_entry.link
    author_match = re.search(r"/user/([^/]+)", selected_entry.get("author", ""))
    post_author = author_match.group(1) if author_match else "RedditUser"

    json_url = post_url.rstrip("/") + ".json"
    comments = []
    
    try:
        res = requests.get(json_url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            comment_children = data[1]["data"]["children"]
            for child in comment_children:
                c_data = child.get("data", {})
                body = c_data.get("body", "").strip()
                author = c_data.get("author", "anonymous")
                
                if body and body != "[deleted]" and body != "[removed]" and 30 < len(body) < 320:
                    clean_body = re.sub(r'http\S+', '', body)
                    # Netejar salts de línia estranys per a una narració fluida
                    clean_body = " ".join(clean_body.split())
                    comments.append({"author": author, "body": clean_body})
                if len(comments) >= 4:
                    break
    except Exception as e:
        print(f"⚠️ Could not fetch comments via JSON ({e}), using fallback comments.")

    if not comments:
        comments = [
            {"author": "CuriousThinker", "body": "Honestly, the hardest part is realizing that nobody is coming to save you. You have to build the life you want yourself."},
            {"author": "LifeTraveler", "body": "Most people are not thinking about you as much as you think they are. Everyone is busy dealing with their own problems."},
            {"author": "RealistView", "body": "Time goes by way faster than you expect once your routine sets in. Cherish the quiet moments."}
        ]

    return {
        "title": selected_entry.title.strip(),
        "author": post_author,
        "subreddit": SUBREDDIT_NAME,
        "comments": comments
    }

async def generate_speech_with_word_timestamps(text, audio_path):
    """Genera l'àudio TTS i extreu els mil·lisegons exactes de cada paraula."""
    communicate = edge_tts.Communicate(text, VOICE)
    words = []
    
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # L'offset i la durada vénen en unitats de 100ns (ticks)
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
    return total_dur, words

def create_title_card(author, text, subreddit, output_path="temp/title_card.png"):
    """Dibuixa la targeta del post (que només es veurà durant el títol)."""
    width = 900
    padding_x = 42
    padding_y = 32
    
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 32)
        font_meta = ImageFont.truetype("DejaVuSans.ttf", 20)
        font_meta_bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
    except:
        font_title = font_meta = font_meta_bold = ImageFont.load_default()

    words = text.split()
    lines, current_line = [], []
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > 40:
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))

    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    total_text_h = 0
    line_heights = []
    for line in lines:
        bbox = dummy_draw.textbbox((0, 0), line, font=font_title)
        h = bbox[3] - bbox[1]
        line_heights.append(h)
        total_text_h += h + 10
    total_text_h -= 10

    card_height = padding_y + 40 + 22 + total_text_h + 22 + 30 + padding_y

    img = Image.new("RGBA", (width, card_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fons fosc i vora
    draw.rounded_rectangle([(0, 0), (width, card_height)], radius=18, fill=(26, 26, 27, 250), outline=(52, 53, 54, 255), width=2)

    # Insígnia r/ i autor
    badge_radius = 16
    draw.ellipse([(padding_x, padding_y), (padding_x + badge_radius * 2, padding_y + badge_radius * 2)], fill=(255, 69, 0))
    draw.text((padding_x + 9, padding_y + 4), "r/", fill=(255, 255, 255), font=font_meta_bold)
    draw.text((padding_x + badge_radius * 2 + 14, padding_y + 6), f"r/{subreddit}  •  Posted by u/{author}  •  Today", fill=(138, 141, 143), font=font_meta)

    # Títol
    y = padding_y + 40 + 22
    for i, line in enumerate(lines):
        draw.text((padding_x, y), line, fill=(240, 242, 243), font=font_title)
        y += line_heights[i] + 10

    # Peu de la targeta
    y += 14
    draw.text((padding_x, y), "💬 Discussion   ↗ Share   ⬆️ Vote", fill=(138, 141, 143), font=font_meta)
    img.save(output_path)

def format_ass_time(seconds):
    """Converteix segons al format H:MM:SS.cs necessari per al fitxer ASS."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis == 100:
        centis = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"

def generate_tiktok_ass_subtitles(words_list, output_path="temp/captions.ass"):
    """
    Genera subtítols ASS d'estil TikTok / MrBeast:
    - Text gran, negreta, centrat al mig de la pantalla.
    - S'agrupen de 3 en 3 paraules.
    - La paraula que s'està pronunciant es pinta en GROC brillant (&H0000FFFF&).
    """
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,DejaVu Sans,68,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,6,0,5,80,80,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogues = []
    
    # Agrupar les paraules en blocs de 3 paraules
    chunk_size = 3
    for i in range(0, len(words_list), chunk_size):
        chunk = words_list[i:i + chunk_size]
        
        # Per a cada paraula dins del bloc, es crea una línia activa
        for active_idx, target_word in enumerate(chunk):
            start_t = format_ass_time(target_word["start"])
            end_t = format_ass_time(target_word["end"])
            
            # Construir la frase on la paraula activa és groga i les altres blanques
            phrase_parts = []
            for j, w in enumerate(chunk):
                cleaned_word = w["word"].upper().strip()
                if j == active_idx:
                    phrase_parts.append(r"{\c&H0000FFFF&}" + cleaned_word + r"{\c&H00FFFFFF&}")
                else:
                    phrase_parts.append(cleaned_word)
                    
            line_text = " ".join(phrase_parts)
            dialogues.append(f"Dialogue: 0,{start_t},{end_t},TikTok,,0,0,0,,{line_text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogues) + "\n")

def find_local_background():
    """Busca el teu background.mp4 al repo."""
    for fitxer in ["background.mp4", "Background.mp4", "assets/background.mp4"]:
        if os.path.exists(fitxer):
            return fitxer
    for fitxer in os.listdir("."):
        if fitxer.lower().endswith(".mp4") and fitxer not in ["final_video.mp4", "bg.mp4"]:
            return fitxer
    return None

async def main():
    thread = get_reddit_thread_with_comments()
    print(f"\n📌 Post: {thread['title']}")
    
    os.makedirs("temp", exist_ok=True)
    
    # 1. GENERAR EL TÍTOL (Només àudio i targeta, sense subtítols)
    print("🗣️ Generating Title audio...")
    title_audio = os.path.abspath("temp/title.mp3")
    title_dur, _ = await generate_speech_with_word_timestamps(thread["title"], title_audio)
    
    title_card = os.path.abspath("temp/title_card.png")
    create_title_card(thread["author"], thread["title"], thread["subreddit"], title_card)
    
    audio_files = [title_audio]
    all_comment_words = []
    current_time_offset = title_dur

    # 2. GENERAR ELS COMENTARIS (Àudio + timestamps per paraula)
    for idx, c in enumerate(thread["comments"]):
        if current_time_offset >= TARGET_TOTAL_DURATION:
            break
            
        print(f"🗣️ Generating Comment {idx + 1} (u/{c['author']})...")
        c_audio = os.path.abspath(f"temp/c_{idx}.mp3")
        c_dur, words = await generate_speech_with_word_timestamps(c["body"], c_audio)
        
        # Desplaçar els temps de les paraules perquè comencin després del títol
        for w in words:
            all_comment_words.append({
                "word": w["word"],
                "start": w["start"] + current_time_offset,
                "end": w["end"] + current_time_offset
            })
            
        audio_files.append(c_audio)
        current_time_offset += c_dur

    total_video_duration = current_time_offset
    print(f"\n⏱️ Total video duration: {total_video_duration:.1f}s")
    print(f"📝 Total animated words for comments: {len(all_comment_words)}")

    # 3. Concatenar tots els fitxers d'àudio
    list_path = os.path.abspath("temp/audio_list.txt")
    full_audio = os.path.abspath("temp/full_audio.mp3")
    with open(list_path, "w") as f:
        for a_file in audio_files:
            f.write(f"file '{a_file}'\n")
            
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", full_audio], check=True)

    # 4. Generar el fitxer de subtítols animats (.ass)
    ass_path = os.path.abspath("temp/captions.ass")
    generate_tiktok_ass_subtitles(all_comment_words, ass_path)

    # 5. Preparar el fons de vídeo
    bg_file = find_local_background()
    temp_bg = os.path.abspath("temp/bg.mp4")
    if bg_file:
        print(f"📁 Using local background: {bg_file}")
        start_time = random.randint(0, 30)
        subprocess.run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-ss", str(start_time),
            "-i", bg_file, "-t", str(int(total_video_duration) + 2),
            "-c:v", "libx264", "-an", temp_bg
        ], check=True)
    else:
        print("⚠️ No local background found. Generating studio color background...")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=#0f172a:s=1080x1920:r=30:d={int(total_video_duration) + 2}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", temp_bg
        ], check=True)

    # 6. MUNTATGE FINAL AMB FFMPEG:
    # - El vídeo de fons es retalla a vertical (1080x1920)
    # - La targeta del títol només és visible entre 0 i title_dur
    # - Els subtítols animats s'estampen sobre el vídeo
    print("🎞️ Assembling final video with title card and animated word captions...")
    
    # Escapar la ruta per al filtre de subtítols de FFmpeg
    escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
    
    filter_complex = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v0];"
        f"[v0][1:v]overlay=(W-w)/2:(H-h)/2:enable='between(t,0,{title_dur:.2f})'[v1];"
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
    print(f"\n🎉 SUCCESS! Video generated: final_video.mp4 ({size_mb:.2f} MB, {total_video_duration:.1f}s)")

if __name__ == "__main__":
    asyncio.run(main())
