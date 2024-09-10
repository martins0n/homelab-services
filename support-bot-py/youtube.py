import re

from youtube_transcript_api import YouTubeTranscriptApi


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
    return full_text

    #summary_text = make_summary(full_text)
    #return summary_text


if __name__ == "__main__":
    link = "https://youtu.be/Ga6kh8QknlA?si=pnAt41i40toSbU2Y"
    text = get_transcript_summary(link)
    
    from summarizer import make_summary_single_call
    
    summary = make_summary_single_call(text)
    
    print(summary)
