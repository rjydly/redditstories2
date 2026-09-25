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
    """Llegeix la primera història pendent del CSV i la marca com a feta."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No s'ha trobat el fitxer {csv_path}. Assegura't de pujar-lo al repositori.")

    rows = []
    selected_story = None

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if not selected_story and row.get("status", "pending") == "pending":
                selected_story = row
                row["status"] = "done"  # Marquem com a utilitzada
            rows.append(row)

    if not selected_story:
        # Si totes estan fetes, agafa la primera com a fallback
        selected_story = rows[0]

    # Guardar l'estat actualitzat
    with open(csv_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return selected_story

async def generate_speech_with_word_timestamps(text, audio_path):
    """
    Genera àudio amb Edge-TTS i extreu els timestamps exactes de cada paraula.
    IMPORTANT: boundary='WordBoundary' és imprescindible per rebre els timestamps!
    """
    communicate = edge_tts.Communicate(text, VOICE, boundary="WordBoundary")
    words = []
    
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset i durada vénen en ticks (10,000,000 ticks = 1 segon)
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

    # Sistema de seguretat infal·lible: si la xarxa no ha retornat metadades, calculem el ritme
    if not words and text:
        print("⚠️ Warning: Estimant timestamps de paraules pel ritme d'àudio...")
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

def create_engain_template_card(post, output_path="temp/title_card.png"):
    """
    Dibuixa la targeta exacta del disseny d'Engain (Reddit Post Template):
    - Fons blanc net amb cantonades arrodonides grans (rounded-2xl).
    - Avatar circular taronja de Reddit.
    - Botons en càpsula: Taronja oficial (#D93900) per a vots i gris (#E5EBEE) per a comentaris i compartir.
    """
    width = 920
    padding_x = 44
    padding_y = 36
    
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
        font_sub = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
        font_meta = ImageFont.truetype("DejaVuSans.ttf", 20)
        font_pill = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
    except:
        font_title = font_sub = font_meta = font_pill = ImageFont.load_default()

    # Ajust automàtic de línies per al títol
    words = post["title"].split()
    lines, current_line = [], []
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > 38:
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
        total_text_h += h + 12
    total_text_h -= 12

    card_height = padding_y + 44 + 20 + total_text_h + 26 + 48 + padding_y

    img = Image.new("RGBA", (width, card_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Targeta blanca amb cantonades arrodonides i subtil ombra/vora
    draw.rounded_rectangle(
        [(0, 0), (width, card_height)],
        radius=24,
        fill=(255, 255, 255, 255),
        outline=(230, 235, 238, 255),
        width=2
    )

    # 2. Capçalera (Avatar Snoo taronja + Subreddit + Temps)
    curr_y = padding_y
    avatar_radius = 20
    draw.ellipse(
        [(padding_x, curr_y), (padding_x + avatar_radius * 2, curr_y + avatar_radius * 2)],
        fill=(217, 57, 0)
    )
    # Silueta Snoo / Text r/
    draw.text((padding_x + 11, curr_y + 8), "r/", fill=(255, 255, 255), font=font_sub)

    sub_x = padding_x + avatar_radius * 2 + 14
    draw.text((sub_x, curr_y + 2), f"r/{post['subreddit']}", fill=(46, 54, 64), font=font_sub)
    draw.text((sub_x + 160, curr_y + 4), "•", fill=(92, 108, 116), font=font_meta)
    draw.text((sub_x + 180, curr_y + 4), "2 hr. ago", fill=(92, 108, 116), font=font_meta)

    # 3. Títol
    curr_y += 44 + 20
    for i, line in enumerate(lines):
        draw.text((padding_x, curr_y), line, fill=(17, 21, 26), font=font_title)
        curr_y += line_heights[i] + 12

    # 4. Botons inferiors d'Engain (Pills)
    curr_y += 18
    pill_h = 44
    
    # Pill 1: Vots en Taronja (#D93900)
    vote_w = 170
    draw.rounded_rectangle([(padding_x, curr_y), (padding_x + vote_w, curr_y + pill_h)], radius=22, fill=(217, 57, 0))
    draw.text((padding_x + 16, curr_y + 11), "▲", fill=(255, 255, 255), font=font_pill)
    draw.text((padding_x + 46, curr_y + 10), post.get("upvotes", "436"), fill=(255, 255, 255), font=font_pill)
    draw.text((padding_x + vote_w - 32, curr_y + 11), "▼", fill=(255, 255, 255), font=font_pill)

    # Pill 2: Comentaris en Gris (#E5EBEE)
    com_x = padding_x + vote_w + 14
    com_w = 120
    draw.rounded_rectangle([(com_x, curr_y), (com_x + com_w, curr_y + pill_h)], radius=22, fill=(229, 235, 238))
    draw.text((com_x + 16, curr_y + 10), "💬", fill=(0, 0, 0), font=font_pill)
    draw.text((com_x + 50, curr_y + 10), post.get("comments", "57"), fill=(17, 21, 26), font=font_pill)

    # Pill 3: Compartir en Gris (#E5EBEE)
    share_x = com_x + com_w + 14
    share_w = 110
    draw.rounded_rectangle([(share_x, curr_y), (share_x + share_w, curr_y + pill_h)], radius=22, fill=(229, 235, 238))
    draw.text((share_x + 16, curr_y + 10), "↗", fill=(0, 0, 0), font=font_pill)
    draw.text((share_x + 46, curr_y + 10), "Share", fill=(17, 21, 26), font=font_pill)

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

def generate_tiktok_ass_subtitles(words_list, output_path="temp/captions.ass"):
    """
    Genera subtítols animats TikTok / MrBeast:
    - Text gran, majúscules, centrat al mig exacte (Alignment 5).
    - Agrupats de 3 en 3 paraules.
    - La paraula activa es pinta en GROC BRILLANT (&H0000FFFF&) amb vora negra gruixuda.
    """
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,DejaVu Sans,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,7,2,5,80,80,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogues = []
    chunk_size = 3
    
    for i in range(0, len(words_list), chunk_size):
        chunk = words_list[i:i + chunk_size]
        for active_idx, target_word in enumerate(chunk):
            start_t = format_ass_time(target_word["start"])
            end_t = format_ass_time(target_word["end"])
            
            phrase_parts = []
            for j, w in enumerate(chunk):
                cleaned = w["word"].upper().strip()
                if j == active_idx:
                    phrase_parts.append(r"{\c&H0000FFFF&}" + cleaned + r"{\c&H00FFFFFF&}")
                else:
                    phrase_parts.append(cleaned)
                    
            line_text = " ".join(phrase_parts)
            dialogues.append(f"Dialogue: 0,{start_t},{end_t},TikTok,,0,0,0,,{line_text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogues) + "\n")

def find_local_background():
    """Busca background.mp4 al repo."""
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
    print(f"\n📖 Loaded Story #{story_data.get('id', '1')} from CSV: {story_data['title']}")
    
    # 1. GENERAR ÀUDIO I TARGETA DEL TÍTOL (0 a title_dur)
    print("🗣️ Generating speech for Title...")
    title_audio = os.path.abspath("temp/title.mp3")
    title_dur, _ = await generate_speech_with_word_timestamps(story_data["title"], title_audio)
    
    title_card = os.path.abspath("temp/title_card.png")
    create_engain_template_card(story_data, title_card)

    # 2. GENERAR ÀUDIO I SUBTÍTOLS DE LA HISTÒRIA COMPLETA (> 1.5 min)
    print("🗣️ Generating speech and word timestamps for the full Story...")
    story_audio = os.path.abspath("temp/story.mp3")
    story_dur, story_words = await generate_speech_with_word_timestamps(story_data["story"], story_audio)
    
    # Desplacem els subtítols perquè comencin EXACTAMENT quan s'acaba el títol
    adjusted_words = []
    for w in story_words:
        adjusted_words.append({
            "word": w["word"],
            "start": w["start"] + title_dur,
            "end": w["end"] + title_dur
        })

    total_video_duration = title_dur + story_dur
    print(f"\n⏱️ Durada total del vídeo: {total_video_duration:.1f} segons ({(total_video_duration/60):.2f} minuts)")
    print(f"📝 Total paraules animades: {len(adjusted_words)}")

    # 3. Concatenar àudio del títol + història
    list_path = os.path.abspath("temp/audio_list.txt")
    full_audio = os.path.abspath("temp/full_audio.mp3")
    with open(list_path, "w") as f:
        f.write(f"file '{title_audio}'\n")
        f.write(f"file '{story_audio}'\n")
            
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", full_audio], check=True)

    # 4. Generar el fitxer ASS de subtítols
    ass_path = os.path.abspath("temp/captions.ass")
    generate_tiktok_ass_subtitles(adjusted_words, ass_path)

    # 5. Vídeo de fons (Minecraft)
    bg_file = find_local_background()
    temp_bg = os.path.abspath("temp/bg.mp4")
    if bg_file:
        print(f"📁 Using background: {bg_file}")
        start_time = random.randint(0, 20)
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

    # 6. Muntatge Final:
    # - La targeta només apareix de t=0 a t=title_dur
    # - Els subtítols animats apareixen al centre quan la targeta desapareix
    print("🎞️ Rendering final video with Title Card and Center Animated Captions...")
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
