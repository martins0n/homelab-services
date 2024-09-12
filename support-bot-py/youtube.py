import re

from youtube_transcript_api import YouTubeTranscriptApi

from settings import Settings
from summarizer import make_summary_single_call
from loguru import logger

settings = Settings()

def get_youtube_id(url):
    youtube_regex = (
        r'(https?://)?(www\.)?'
        '(youtube|youtu|youtube-nocookie)\.(com|be)/'
        '(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    
    match = re.search(youtube_regex, url)
    if match:
        return match.group(6)
    else:
        return None

def get_transcript_summary(req: str):
    logger.info(f"Getting transcript summary for {req}")
    video_id = get_youtube_id(req)
    logger.info(f"Video ID: {video_id}")
    if settings.youtube_proxy_url:
        proxies = {"https": settings.youtube_proxy_url}
    else:
        proxies = None
    trans = YouTubeTranscriptApi.get_transcript(
        video_id, languages=["ru", "en"],
        proxies=proxies,
        cookies=None
    )

    full_text = " ".join(t["text"] for t in trans)
    summary_text = make_summary_single_call(full_text)
    return summary_text


if __name__ == "__main__":
    link = "https://youtu.be/Ga6kh8QknlA?si=pnAt41i40toSbU2Y"
    text = get_transcript_summary(link)

    print(text)
