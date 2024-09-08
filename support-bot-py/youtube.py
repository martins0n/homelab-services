import re

from youtube_transcript_api import YouTubeTranscriptApi

from summarizer import make_summary


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
    video_id = get_youtube_id(req)
    trans = YouTubeTranscriptApi.get_transcript(video_id, languages=["ru", "en"])
    full_text = " ".join(t["text"] for t in trans)
    summary_text = make_summary(full_text)
    return summary_text


if __name__ == "__main__":
    link = "https://youtu.be/zzpnXw9xIvE?si=_GBXtpCKMwuyZtKS"
    print(get_transcript_summary(link))
