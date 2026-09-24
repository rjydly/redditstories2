import os
import re
import sys
import random
import asyncio
import subprocess
from PIL import Image, ImageDraw, ImageFont
import edge_tts
import feedparser

SUBREDDIT_NAME = os.getenv("SUBREDDIT", "AskReddit")
VOICE = os.getenv("TTS_VOICE", "en-US-ChristopherNeural")

# Vídeo de prova lliure de drets allotjat a Wikimedia Commons (CDN d'alta disponibilitat)
FALLBACK_VIDEO_URL = "https://upload.wikimedia.org/wikipedia/commons/transcoded/f/f1/Big_Buck_Bunny_4K_30fps_HD.webm/Big_Buck_Bunny_4K_30fps_HD.webm.720p.vp9.webm"

def get_reddit_post():
    """Llegeix el subreddit mitjançant RSS públic ignorant anuncis de moderadors."""
    print(f"📥 Llegint r/{SUBREDDIT_NAME} via RSS públic...")
    url = f"https://www.reddit.com/r/{SUBREDDIT_NAME}/hot.rss"
    
    feed = feedparser.parse(url, agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) RSS Reader")
    
    if not feed.entries:
        raise Exception(f"No s'han pogut obtenir entrades RSS de r/{SUBREDDIT_NAME}.")

    blocked_keywords = ["moderator", "looking for", "rules", "megathread", "weekly thread", "discord"]

    for entry in feed.entries:
        title = entry.title.strip()
        title_lower = title.lower()

        # Filtrar que no sigui un post administratiu i que tingui una mida lògica
        is_mod_post = any(kw in title_lower for kw in blocked_keywords)
        if not is_mod_post and 25 < len(title) < 220:
            author_match = re.search(r"/user/([^/]+)", entry.get("author", ""))
            author = author_match.group(1) if author_match else "anònim"
            
            return {
                "title": title,
                "author": author,
                "subreddit": SUBREDDIT_NAME,
                "url": entry.link
            }
            
    # Si tots són moderació, agafem el segon per evitar l'anunci principal
    entry = feed.entries[1] if len(feed.entries) > 1 else feed.entries[0]
    return {
        "title": entry.title,
        "author": "RedditUser",
        "subreddit": SUBREDDIT_NAME,
        "url": entry.link
    }

async def generate_audio(text, output_path="audio.mp3"):
    """Genera l'àudio TTS i en mesura la durada exacta."""
    print(f"🗣️ Generant àudio ({VOICE})...")
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_path)
    
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", output_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    return float(result.stdout.strip())

def create_reddit_card(post, output_path="card.png"):
    """Dibuixa la targeta d'estil Reddit Dark Mode."""
    print("🎨 Dibuixant la targeta del post...")
    width, height = 900, 450
    img = Image.new("RGBA", (width, height), color=(26, 26, 27, 255))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
        font_sub = ImageFont.truetype("DejaVuSans.ttf", 24)
    except:
        font_title = font_sub = ImageFont.load_default()

    draw.text((40, 40), f"r/{post['subreddit']}  •  Publicat per u/{post['author']}", fill=(129, 131, 132), font=font_sub)

    words = post["title"].split()
    lines, current_line = [], []
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > 35:
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))

    y = 105
    for line in lines[:5]:
        draw.text((40, y), line, fill=(215, 218, 220), font=font_title)
        y += 44

    draw.text((40, height - 60), "⬆️ Post Destacat  •  💬 Comentaris", fill=(129, 131, 132), font=font_sub)
    img.save(output_path)

def prepare_background(duration, output_path="bg.mp4"):
    """Prepara el fons. Si ja tens 'background.mp4' al repo el fa servir; si no, el genera amb FFmpeg."""
    print("🎬 Preparant el vídeo de fons...")
    
    # 1. Opció preferent: L'usuari ha posat un background.mp4 al seu repo
    if os.path.exists("background.mp4"):
        print("📁 Utilitzant 'background.mp4' del propi repositori!")
        subprocess.run([
            "ffmpeg", "-y", "-ss", "10", "-i", "background.mp4",
            "-t", str(int(duration) + 2), "-c:v", "libx264", "-an", output_path
        ], check=True)
        return

    # 2. Si no hi és al repo, intentem descarregar el vídeo fiable de Wikimedia
    raw_video = "temp_bg.webm"
    try:
        print("🌐 Descarregant clip fiable...")
        subprocess.run(["curl", "-fSL", FALLBACK_VIDEO_URL, "-o", raw_video], check=True, timeout=30)
        subprocess.run([
            "ffmpeg", "-y", "-ss", "30", "-i", raw_video,
            "-t", str(int(duration) + 2), "-c:v", "libx264", "-an", output_path
        ], check=True)
        if os.path.exists(raw_video):
            os.remove(raw_video)
        return
    except Exception as e:
        print(f"⚠️ No s'ha pogut descarregar el vídeo extern ({e}). Generant fons dinàmic amb FFmpeg...")

    # 3. Fallback d'emergència: generador de fons de colors fluid natiu de FFmpeg (mai falla)
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"mptestsrc=s=1080x1920:d={int(duration) + 2}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path
    ], check=True)

def render_video(duration, output_path="final_video.mp4"):
    """Munta el vídeo final vertical 9:16 (1080x1920)."""
    print("🎞️ Renderitzant vídeo amb FFmpeg...")
    filter_complex = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[bg];"
        "[1:v]scale=950:-1[card];"
        "[bg][card]overlay=(W-w)/2:(H-h)/2[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", "bg.mp4",
        "-i", "card.png",
        "-i", "audio.mp3",
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "2:a",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        output_path
    ]
    subprocess.run(cmd, check=True)

async def main():
    post = get_reddit_post()
    print(f"\n📌 Post triat: {post['title']}")
    
    duration = await generate_audio(post["title"], "audio.mp3")
    create_reddit_card(post, "card.png")
    prepare_background(duration, "bg.mp4")
    render_video(duration, "final_video.mp4")
    
    size_mb = os.path.getsize("final_video.mp4") / (1024 * 1024)
    print(f"\n✅ Vídeo generat amb èxit! Mida: {size_mb:.2f} MB | Durada: {duration:.1f}s\n")

if __name__ == "__main__":
    asyncio.run(main())
