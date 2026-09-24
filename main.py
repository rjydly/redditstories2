import os
import re
import sys
import random
import asyncio
import subprocess
import urllib.request
import feedparser
from PIL import Image, ImageDraw, ImageFont
import edge_tts

SUBREDDIT_NAME = os.getenv("SUBREDDIT", "AskReddit")
VOICE = os.getenv("TTS_VOICE", "en-US-ChristopherNeural")

# Vídeos de fons directes (sense passar per YouTube per evitar el bloqueig anti-bot)
# Clips de Minecraft Parkour i GTA a Internet Archive
BG_VIDEO_URLS = [
    "https://archive.org/download/minecraft-parkour-gameplay-no-copyright_202302/minecraft-parkour.mp4",
    "https://archive.org/download/gta-5-stunt-races-gameplay-no-copyright/gta-5-stunt.mp4"
]

def get_reddit_post():
    """Llegeix el subreddit mitjançant RSS públic."""
    print(f"📥 Llegint r/{SUBREDDIT_NAME} via RSS públic...")
    url = f"https://www.reddit.com/r/{SUBREDDIT_NAME}/hot.rss"
    
    feed = feedparser.parse(url, agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) RSS Reader")
    
    if not feed.entries:
        raise Exception(f"No s'han pogut obtenir entrades RSS de r/{SUBREDDIT_NAME}.")

    for entry in feed.entries:
        title = entry.title
        if not title.startswith("[") and 20 < len(title) < 220:
            author_match = re.search(r"/user/([^/]+)", entry.get("author", ""))
            author = author_match.group(1) if author_match else "anònim"
            
            return {
                "id": entry.get("id", "post"),
                "title": title,
                "author": author,
                "subreddit": SUBREDDIT_NAME,
                "url": entry.link
            }
            
    prime = feed.entries[0]
    return {
        "id": prime.get("id", "post"),
        "title": prime.title,
        "author": "RedditUser",
        "subreddit": SUBREDDIT_NAME,
        "url": prime.link
    }

async def generate_audio(text, output_path="audio.mp3"):
    """Genera la veu amb Edge-TTS gratuït i calcula la durada exacta."""
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
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
        font_sub = ImageFont.truetype("DejaVuSans.ttf", 24)
    except:
        font_title = font_sub = ImageFont.load_default()

    # Capçalera
    draw.text((40, 40), f"r/{post['subreddit']}  •  Publicat per u/{post['author']}", fill=(129, 131, 132), font=font_sub)

    # Text del títol adaptat a múltiples línies
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
        y += 46

    draw.text((40, height - 60), "⬆️ Post Destacat  •  💬 Comentaris", fill=(129, 131, 132), font=font_sub)
    img.save(output_path)

def download_background(duration, output_path="bg.mp4"):
    """Descarrega el fons directament sense yt-dlp per evitar bloquejos de bots."""
    print("🎬 Descarregant vídeo de fons directe...")
    chosen_url = random.choice(BG_VIDEO_URLS)
    raw_video = "raw_bg.mp4"
    
    # Descarreguem el vídeo sencer o fragment inicial amb curl (suporta redireccions)
    subprocess.run(["curl", "-sL", chosen_url, "-o", raw_video], check=True)
    
    # Retallem un fragment a l'atzar amb ffmpeg segons la durada de l'àudio
    start_time = random.randint(10, 60)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", raw_video,
        "-t", str(int(duration) + 2),
        "-c:v", "copy",
        "-an",
        output_path
    ]
    subprocess.run(cmd, check=True)
    
    if os.path.exists(raw_video):
        os.remove(raw_video)

def render_video(duration, output_path="final_video.mp4"):
    """Munta el vídeo final 9:16 (1080x1920) amb targeta i àudio."""
    print("🎞️ Renderitzant vídeo vertical amb FFmpeg...")
    filter_complex = (
        "[0:v]crop=ih*(9/16):ih,scale=1080:1920[bg];"
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
    download_background(duration, "bg.mp4")
    render_video(duration, "final_video.mp4")
    
    size_mb = os.path.getsize("final_video.mp4") / (1024 * 1024)
    print(f"\n✅ Vídeo generat amb èxit! Mida: {size_mb:.2f} MB | Durada: {duration:.1f}s\n")

if __name__ == "__main__":
    asyncio.run(main())
