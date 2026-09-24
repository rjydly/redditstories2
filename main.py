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

# Configuració: Subreddit en anglès i veu anglesa d'alta qualitat
SUBREDDIT_NAME = os.getenv("SUBREDDIT", "AskReddit")
VOICE = os.getenv("TTS_VOICE", "en-US-ChristopherNeural")
TARGET_TOTAL_DURATION = 55  # Segons màxims per TikTok/Reels

def get_reddit_thread_with_comments():
    """Obté el títol i els millors comentaris en anglès."""
    print(f"📥 Fetching top thread and comments from r/{SUBREDDIT_NAME}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    # 1. Obtenir el post destacat via RSS
    rss_url = f"https://www.reddit.com/r/{SUBREDDIT_NAME}/hot.rss"
    feed = feedparser.parse(rss_url, agent=headers["User-Agent"])
    
    blocked_keywords = ["moderator", "looking for", "rules", "megathread", "weekly thread", "discord"]
    selected_entry = None
    
    for entry in feed.entries:
        title = entry.title.strip()
        if not any(kw in title.lower() for kw in blocked_keywords) and 20 < len(title) < 200:
            selected_entry = entry
            break
            
    if not selected_entry:
        selected_entry = feed.entries[1] if len(feed.entries) > 1 else feed.entries[0]

    post_url = selected_entry.link
    author_match = re.search(r"/user/([^/]+)", selected_entry.get("author", ""))
    post_author = author_match.group(1) if author_match else "RedditUser"

    # 2. Obtenir els comentaris reals
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
                ups = c_data.get("ups", random.randint(500, 4500))
                
                if body and body != "[deleted]" and body != "[removed]" and 40 < len(body) < 350:
                    clean_body = re.sub(r'http\S+', '', body)
                    comments.append({
                        "author": author,
                        "body": clean_body,
                        "ups": f"{ups:,}" if isinstance(ups, int) else str(ups)
                    })
                if len(comments) >= 5:
                    break
    except Exception as e:
        print(f"⚠️ Could not fetch comments via JSON ({e}), using fallback comments.")

    if not comments:
        comments = [
            {"author": "CuriousThinker", "body": "Honestly, the hardest part is realizing that nobody is coming to save you. You have to build the life you want yourself.", "ups": "3.4k"},
            {"author": "LifeTraveler", "body": "Most people are not thinking about you as much as you think they are. Everyone is busy dealing with their own problems.", "ups": "2.1k"},
            {"author": "RealistView", "body": "Time goes by way faster than you expect once your routine sets in. Cherish the quiet moments.", "ups": "1.8k"}
        ]

    return {
        "title": selected_entry.title.strip(),
        "author": post_author,
        "subreddit": SUBREDDIT_NAME,
        "comments": comments
    }

async def generate_speech(text, output_file):
    """Genera l'àudio TTS en anglès i en retorna la durada."""
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_file)
    
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", output_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    return float(result.stdout.strip())

def create_card_image(author, text, subreddit=None, is_title=False, output_path="card.png"):
    """Dibuixa targetes visuals d'estil Reddit Dark Mode."""
    width, height = 920, 480
    img = Image.new("RGBA", (width, height), color=(24, 25, 26, 255))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 32)
        font_sub = ImageFont.truetype("DejaVuSans.ttf", 22)
    except:
        font_title = font_sub = ImageFont.load_default()

    if is_title:
        header = f"r/{subreddit}  •  Posted by u/{author}"
    else:
        header = f"u/{author}  •  Top Comment"
    draw.text((45, 40), header, fill=(138, 141, 143), font=font_sub)

    words = text.split()
    lines, current_line = [], []
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > 38:
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))

    y = 100
    for line in lines[:6]:
        draw.text((45, y), line, fill=(225, 227, 229), font=font_title)
        y += 44

    footer = "⬆️ Upvote  •  💬 Reply  •  Share"
    draw.text((45, height - 55), footer, fill=(138, 141, 143), font=font_sub)

    img.save(output_path)

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
    
    # 1. Generar àudio i targeta del TÍTOL
    print("🗣️ Generating speech for Title...")
    title_audio = os.path.abspath("temp/title.mp3")
    title_dur = await generate_speech(thread["title"], title_audio)
    
    title_img = os.path.abspath("temp/card_0.png")
    create_card_image(thread["author"], thread["title"], subreddit=thread["subreddit"], is_title=True, output_path=title_img)
    
    segments = [{
        "audio": title_audio,
        "duration": title_dur,
        "image": title_img
    }]
    
    current_total_duration = title_dur
    
    # 2. Generar àudio i targetes dels COMENTARIS
    for idx, c in enumerate(thread["comments"]):
        if current_total_duration >= TARGET_TOTAL_DURATION:
            break
            
        print(f"🗣️ Generating speech for Comment {idx + 1} (u/{c['author']})...")
        c_audio = os.path.abspath(f"temp/c_{idx}.mp3")
        c_dur = await generate_speech(c["body"], c_audio)
        
        c_img = os.path.abspath(f"temp/card_{idx + 1}.png")
        create_card_image(c["author"], c["body"], is_title=False, output_path=c_img)
        
        segments.append({
            "audio": c_audio,
            "duration": c_dur,
            "image": c_img
        })
        current_total_duration += c_dur

    print(f"\n⏱️ Total video duration planned: {current_total_duration:.1f}s ({len(segments)} cards)")

    # 3. Concatenar tots els àudios (rutes absolutes = zero errors)
    list_path = os.path.abspath("temp/audio_list.txt")
    full_audio = os.path.abspath("temp/full_audio.mp3")
    with open(list_path, "w") as f:
        for seg in segments:
            f.write(f"file '{seg['audio']}'\n")
            
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_path, "-c", "copy", full_audio
    ], check=True)

    # 4. Preparar el vídeo de fons
    bg_file = find_local_background()
    temp_bg = os.path.abspath("temp/bg.mp4")
    if bg_file:
        print(f"📁 Using local background: {bg_file}")
        start_time = random.randint(0, 30)
        subprocess.run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-ss", str(start_time),
            "-i", bg_file, "-t", str(int(current_total_duration) + 2),
            "-c:v", "libx264", "-an", temp_bg
        ], check=True)
    else:
        print("⚠️ No local background found. Generating studio color background...")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=#0f172a:s=1080x1920:r=30:d={int(current_total_duration) + 2}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", temp_bg
        ], check=True)

    # 5. Muntar el vídeo amb canvis de targeta sincronitzats
    print("🎞️ Assembling final video with synchronized card switches...")
    
    inputs = ["-i", temp_bg]
    for seg in segments:
        inputs.extend(["-i", seg["image"]])
    inputs.extend(["-i", full_audio])
    
    filter_chains = ["[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v0];"]
    
    running_time = 0.0
    for i, seg in enumerate(segments):
        start_t = running_time
        end_t = running_time + seg["duration"]
        running_time = end_t
        
        in_tag = f"[v{i}]"
        out_tag = f"[v{i+1}]"
        card_idx = i + 1
        
        filter_chains.append(
            f"[{card_idx}:v]scale=920:-2[scaled_c{i}];"
            f"{in_tag}[scaled_c{i}]overlay=(W-w)/2:(H-h)/2:enable='between(t,{start_t:.2f},{end_t:.2f})'{out_tag};"
        )
        
    last_v_tag = f"[v{len(segments)}]"
    filter_complex_str = "".join(filter_chains)
    
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex_str,
        "-map", last_v_tag,
        "-map", f"{len(segments) + 1}:a",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-t", str(current_total_duration),
        "-pix_fmt", "yuv420p",
        "final_video.mp4"
    ]
    
    subprocess.run(cmd, check=True)
    
    size_mb = os.path.getsize("final_video.mp4") / (1024 * 1024)
    print(f"\n🎉 SUCCESS! Full Reddit video generated: final_video.mp4 ({size_mb:.2f} MB, {current_total_duration:.1f}s)")

if __name__ == "__main__":
    asyncio.run(main())
