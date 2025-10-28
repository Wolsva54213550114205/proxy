from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, Response
import yt_dlp
import requests
from bs4 import BeautifulSoup
import re

app = FastAPI(title="YouTube Extractor API", version="1.0")

IMAGE_EXTS = {"mhtml", "jpg", "jpeg", "webp", "png", "gif"}

def extract_best_sources(url: str):
    """Récupère les meilleures sources vidéo et audio"""
    ydl_opts = {"quiet": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get("formats", [])

        # meilleure vidéo
        video_formats = [f for f in formats if f.get("vcodec") not in (None, "none")]
        best_video = max(video_formats, key=lambda f: f.get("height") or 0, default=None)

        # meilleur audio (dernier réel format audio)
        best_audio = None
        for f in reversed(formats):
            url_field = f.get("url")
            if not url_field:
                continue
            acodec = f.get("acodec")
            vcodec = f.get("vcodec")
            ext = (f.get("ext") or "").lower()
            if (acodec and acodec != "none") or (vcodec == "none" and ext not in IMAGE_EXTS):
                best_audio = f
                break

        return info, best_video, best_audio


@app.get("/youtube/info")
def get_youtube_info(url: str = Query(..., description="Lien complet de la vidéo YouTube")):
    try:
        info, best_video, best_audio = extract_best_sources(url)

        data = {
            "id": info.get("id"),
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "thumbnail": info.get("thumbnail"),
            "video": {
                "url": best_video.get("url") if best_video else None,
                "height": best_video.get("height") if best_video else None
            },
            "audio": {
                "url": best_audio.get("url") if best_audio else None
            }
        }

        return JSONResponse(content=data)

    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/youtube/download")
def get_youtube_download(url: str = Query(..., description="Lien complet de la vidéo YouTube")):
    try:
        info, best_video, best_audio = extract_best_sources(url)

        if not best_video or not best_audio:
            return JSONResponse(content={"error": "Impossible de trouver les flux vidéo/audio"}, status_code=404)

        video_url = best_video.get("url")
        audio_url = best_audio.get("url")

        # structure M3U8
        m3u8_content = f"""#EXTM3U

#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio Français",DEFAULT=YES,AUTOSELECT=YES,URI="{video_url}"

#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,AUDIO="audio"
{audio_url}
"""

        # réponse HTTP avec forçage du téléchargement
        headers = {
            "Content-Disposition": 'attachment; filename="index.m3u8"',
            "Content-Type": "application/vnd.apple.mpegurl"
        }

        return Response(content=m3u8_content, headers=headers)

    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/extract_video")
def extract_video(url: str = Query(..., description="Lien de la page Sibnet")):
    headers_browser = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Referer": "https://video.sibnet.ru/",
    }

    # Récupérer le HTML
    resp = requests.get(url, headers=headers_browser)
    if resp.status_code != 200:
        return {"error": f"Impossible de récupérer la page, statut {resp.status_code}"}
    
    html = resp.text

    # Parser le HTML
    soup = BeautifulSoup(html, 'html.parser')

    # Extraire meta og
    meta_og_video = soup.find('meta', {'property': 'og:video'})
    meta_og_title = soup.find('meta', {'property': 'og:title'})
    meta_og_image = soup.find('meta', {'property': 'og:image'})

    og_video = meta_og_video['content'] if meta_og_video and meta_og_video.get('content') else None
    og_title = meta_og_title['content'] if meta_og_title and meta_og_title.get('content') else None
    og_image = meta_og_image['content'] if meta_og_image and meta_og_image.get('content') else None

    # Extraire le player.src([{src:...}) via regex
    match = re.search(r'player\.src\(\[\{src:\s*"(.*?)"', html)
    if not match:
        return {"error": "Impossible de trouver la source vidéo dans player.src."}

    src_path = match.group(1)
    src_initial = "https://video.sibnet.ru" + src_path if src_path.startswith('/') else src_path

    # Requête GET vers la vidéo pour obtenir le lien final
    headers_video = {
        "Referer": url,
        "User-Agent": headers_browser["User-Agent"]
    }
    video_resp = requests.get(src_initial, headers=headers_video, stream=True, allow_redirects=True)
    src_final = video_resp.url

    return {
        "src_final": src_final,
        "meta_og_video": og_video,
        "meta_og_title": og_title,
        "meta_og_image": f"https{og_image}"
    }
