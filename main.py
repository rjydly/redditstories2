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

def get_reddit_post():
    """Llegeix el subreddit mitjançant RSS públic ignorant anuncis."""
    print(f"📥 Llegint r/{SUBREDDIT_NAME} via RSS públic...")
    url = f"https://www.reddit.com/r/{SUBREDDIT_NAME}/hot.rss"
    
    feed = feedparser.parse(url, agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) RSS Reader")
    
    if not feed.entries:
        raise Exception(f"No s'han pogut obtenir entrades RSS de r/{SUBREDDIT_NAME}.")

    blocked_keywords = ["moderator", "looking for", "rules", "megathread", "weekly thread", "discord"]

    for entry in feed.entries:
        title = entry.title.strip()
        title_lower = title.lower()

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

def find_local_background():
    """Cerca automàticament qualsevol fitxer de vídeo al repositori."""
    posibles_noms = [
        "background.mp4", "Background.mp4", "BACKGROUND.mp4", "BACKGROUND.MP4",
        "bg.mp4", "gameplay.mp4", "video.mp4",
        "assets/background.mp4", "assets/Background.mp4"
    ]
    for nom in posibles_noms:
        if os.path.exists(nom):
            return nom
            
    # Si no coincideix el nom, cerca el primer .mp4 que trobi que no sigui temporal
    for fitxer in os.listdir("."):
        if fitxer.lower().endswith(".mp4") and fitxer not in ["final_video.mp4", "bg.mp4", "temp_bg.mp4"]:
            return fitxer
    return None

def prepare_background(duration, output_path="bg.mp4"):
    """Prepara el fons aprofitant el teu vídeo local."""
    print("🎬 Preparant el vídeo de fons...")
    dur_sec = max(5, int(duration) + 2)

    local_bg = find_local_background()

    if local_bg:
        print(f"📁 S'ha trobat el vídeo del repositori: '{local_bg}'!")
        start_time = random.randint(0, 30)
        subprocess.run([
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-ss", str(start_time),
            "-i", local_bg,
            "-t", str(dur_sec),
            "-c:v", "libx264",
            "-an",
            output_path
        ], check=True)
        return

    print("⚠️ No s'ha trobat cap .mp4 al repositori. Generant fons intern de seguretat...")
    # Generador d'estudi de FFmpeg (100% infal·lible, sense internet)
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=#0f172a:s=1080x1920:r=30:d={dur_sec}",
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
