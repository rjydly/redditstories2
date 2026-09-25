import os
import re
import sys
import csv
import random
import asyncio
import subprocess
from PIL import Image, ImageDraw, ImageFont
import edge_tts

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
    """Genera veu i timestamps de cada paraula."""
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

    # Fallback si no hi ha metadades de paraules
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

def wrap_text(text, font, max_width, draw):
    """Ajusta el text perquè no superi l'amplada màxima de la targeta."""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        test_str = " ".join(current_line)
        if draw.textlength(test_str, font=font) > max_width:
            current_line.pop()
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def create_engain_template_card(post, output_path="temp/title_card.png"):
    """
    Dibuixa la targeta d'Engain amb:
    - Títol gran
    - Text del post a sota (cos de la publicació)
    - Botons vectorials nets (zero caràcters trencats [])
    - Espaiat calculat automàticament
    """
    width = 940
    padding_x = 44
    padding_y = 36
    max_text_width = width - (padding_x * 2)
    
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 32)
        font_body = ImageFont.truetype("DejaVuSans.ttf", 22)
        font_sub = ImageFont.truetype("DejaVuSans-Bold.ttf", 21)
        font_meta = ImageFont.truetype("DejaVuSans.ttf", 19)
        font_pill = ImageFont.truetype("DejaVuSans-Bold.ttf", 19)
    except:
        font_title = font_body = font_sub = font_meta = font_pill = ImageFont.load_default()

    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    # 1. Ajustar línies del títol
    title_lines = wrap_text(post["title"], font_title, max_text_width, dummy_draw)

    # 2. Agafar i ajustar les primeres línies del text del post (cos de la confessió)
    story_raw = post.get("story", "")
    # Mostrem les primeres 4-5 línies del text a la targeta
    story_lines = wrap_text(story_raw, font_body, max_text_width, dummy_draw)[:5]
    if len(story_lines) == 5:
        story_lines[-1] = story_lines[-1].rstrip("., ") + "..."

    # Calcular alçades exactes
    title_h = sum(dummy_draw.textbbox((0, 0), l, font=font_title)[3] - dummy_draw.textbbox((0, 0), l, font=font_title)[1] + 10 for l in title_lines)
    body_h = sum(dummy_draw.textbbox((0, 0), l, font=font_body)[3] - dummy_draw.textbbox((0, 0), l, font=font_body)[1] + 8 for l in story_lines)

    header_h = 42
    pills_h = 44
    gap = 20

    card_height = padding_y + header_h + gap + title_h + (gap if story_lines else 0) + body_h + gap + pills_h + padding_y

    img = Image.new("RGBA", (width, card_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fons blanc arrodonit
    draw.rounded_rectangle([(0, 0), (width, card_height)], radius=24, fill=(255, 255, 255, 255), outline=(225, 230, 234, 255), width=2)

    # Capçalera (Avatar + Subreddit + Temps sense xocs de text)
    curr_y = padding_y
    avatar_radius = 18
    draw.ellipse([(padding_x, curr_y), (padding_x + avatar_radius * 2, curr_y + avatar_radius * 2)], fill=(217, 57, 0))
    draw.text((padding_x + 9, curr_y + 6), "r/", fill=(255, 255, 255), font=font_sub)

    sub_x = padding_x + avatar_radius * 2 + 14
    sub_text = f"r/{post['subreddit']}"
    draw.text((sub_x, curr_y + 4), sub_text, fill=(46, 54, 64), font=font_sub)
    
    sub_w = dummy_draw.textlength(sub_text, font=font_sub)
    dot_x = sub_x + sub_w + 10
    draw.text((dot_x, curr_y + 4), "•", fill=(92, 108, 116), font=font_meta)
    
    time_x = dot_x + dummy_draw.textlength("•", font=font_meta) + 10
    draw.text((time_x, curr_y + 5), "2 hr. ago", fill=(92, 108, 116), font=font_meta)

    # Dibuixar el Títol
    curr_y += header_h + gap
    for line in title_lines:
        draw.text((padding_x, curr_y), line, fill=(17, 21, 26), font=font_title)
        bbox = dummy_draw.textbbox((0, 0), line, font=font_title)
        curr_y += (bbox[3] - bbox[1]) + 10

    # Dibuixar el Cos de la Publicació (Text del post)
    if story_lines:
        curr_y += 6
        for line in story_lines:
            draw.text((padding_x, curr_y), line, fill=(60, 72, 82), font=font_body)
            bbox = dummy_draw.textbbox((0, 0), line, font=font_body)
            curr_y += (bbox[3] - bbox[1]) + 8

    # Botons inferiors (Pills amb icones vectorials pures)
    curr_y += gap
    
    # 1. Pill Vots (Taronja #D93900)
    vote_w = 175
    draw.rounded_rectangle([(padding_x, curr_y), (padding_x + vote_w, curr_y + pills_h)], radius=22, fill=(217, 57, 0))
    # Triangle fletxa amunt
    draw.polygon([(padding_x + 22, curr_y + 16), (padding_x + 16, curr_y + 26), (padding_x + 28, curr_y + 26)], fill=(255, 255, 255))
    # Text vots
    draw.text((padding_x + 40, curr_y + 11), post.get("upvotes", "42.8k"), fill=(255, 255, 255), font=font_pill)
    # Triangle fletxa avall
    draw.polygon([(padding_x + vote_w - 22, curr_y + 26), (padding_x + vote_w - 28, curr_y + 16), (padding_x + vote_w - 16, curr_y + 16)], fill=(255, 255, 255))

    # 2. Pill Comentaris (Gris #E5EBEE)
    com_x = padding_x + vote_w + 14
    com_w = 125
    draw.rounded_rectangle([(com_x, curr_y), (com_x + com_w, curr_y + pills_h)], radius=22, fill=(229, 235, 238))
    # Vector bafarada de xat (zero emojis trencats [])
    bx, by = com_x + 18, curr_y + 15
    draw.rounded_rectangle([(bx, by), (bx + 16, by + 12)], radius=3, fill=(17, 21, 26))
    draw.polygon([(bx + 3, by + 12), (bx + 3, by + 16), (bx + 8, by + 12)], fill=(17, 21, 26))
    draw.text((com_x + 48, curr_y + 11), post.get("comments", "3.2k"), fill=(17, 21, 26), font=font_pill)

    # 3. Pill Compartir (Gris #E5EBEE)
    share_x = com_x + com_w + 14
    share_w = 120
    draw.rounded_rectangle([(share_x, curr_y), (share_x + share_w, curr_y + pills_h)], radius=22, fill=(229, 235, 238))
    # Vector fletxa compartir
    sx, sy = share_x + 18, curr_y + 16
    draw.line([(sx, sy + 12), (sx + 10, sy + 2)], fill=(17, 21, 26), width=3)
    draw.polygon([(sx + 12, sy), (sx + 4, sy), (sx + 12, sy + 8)], fill=(17, 21, 26))
    draw.text((share_x + 46, curr_y + 11), "Share", fill=(17, 21, 26), font=font_pill)

    img.save(output_path)

def format_ass_time(seconds):
    """Format de temps per a subtítols ASS: H:MM:SS.cs"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"

def generate_single_word_subtitles(words_list, output_path="temp/captions.ass"):
    """
    Subtítols TikTok D'UNA SOLA PARAULA AL CENTRE (1 by 1):
    - Format gran (84pt), majúscules, negreta.
    - Color groc elèctric (&H0000FFFF&) amb vora negra de 8px.
    - Suavitzat entre paraules per evitar parpelleig.
    """
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,DejaVu Sans,84,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,8,2,5,80,80,80,1

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
        
        # Allargar lleugerament si la següent paraula comença immediatament (evita parpelleig)
        if i + 1 < len(words_list) and (words_list[i+1]["start"] - end_sec) < 0.25:
            end_sec = words_list[i+1]["start"]

        start_t = format_ass_time(start_sec)
        end_t = format_ass_time(end_sec)

        # UNA SOLA PARAULA EN GRAN AL CENTRE
        dialogues.append(f"Dialogue: 0,{start_t},{end_t},TikTok,,0,0,0,,{cleaned}")

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
    
    # 1. Targeta inicial amb títol + text de la publicació
    print("🗣️ Generating speech for Title...")
    title_audio = os.path.abspath("temp/title.mp3")
    title_dur, _ = await generate_speech_with_word_timestamps(story_data["title"], title_audio)
    
    title_card = os.path.abspath("temp/title_card.png")
    create_engain_template_card(story_data, title_card)

    # 2. Història amb subtítols d'1 sola paraula
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

    # 4. Fitxer de subtítols d'1 sola paraula
    ass_path = os.path.abspath("temp/captions.ass")
    generate_single_word_subtitles(adjusted_words, ass_path)

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

    # 6. Muntatge amb targeta i subtítols 1 by 1
    print("🎞️ Rendering final video...")
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
    print(f"\n🎉 SUCCESS! final_video.mp4 generat ({size_mb:.2f} MB, {total_video_duration:.1f}s)")

if __name__ == "__main__":
    asyncio.run(main())
