import asyncio

import httpx
from loguru import logger
from openai import AsyncOpenAI
from youtube_transcript_api import NoTranscriptFound, YouTubeTranscriptApi

from settings import Settings
from summarizer import make_summary_single_call
from youtube import get_youtube_id

# Module-level cache for Telegraph access token
_telegraph_token = None


def _convert_markdown_to_telegraph(text: str) -> str:
    """Convert basic markdown to plain text for Telegraph."""
    import re

    # Remove markdown headers (### -> nothing, just the text)
    text = re.sub(r'^###\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+', '', text, flags=re.MULTILINE)

    # Convert **bold** to plain text (Telegraph will handle formatting differently)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)

    # Convert *italic* to plain text
    text = re.sub(r'\*([^*]+)\*', r'\1', text)

    return text


async def _create_telegraph_page(title: str, content: str) -> str | None:
    """Create Telegraph page using API. Returns URL or None on failure."""
    global _telegraph_token

    try:
        async with httpx.AsyncClient() as client:
            # Create account if needed
            if not _telegraph_token:
                response = await client.post(
                    'https://api.telegra.ph/createAccount',
                    json={'short_name': 'YouTubeBot', 'author_name': 'Anonymous'}
                )
                data = response.json()
                _telegraph_token = data['result']['access_token']
                logger.info(f"Created Telegraph account with token: {_telegraph_token[:10]}...")

            # Clean markdown from content
            clean_content = _convert_markdown_to_telegraph(content)

            # Convert content to Telegraph format (array of paragraph nodes)
            # Split by double newlines for paragraphs
            paragraphs = clean_content.split('\n\n')

            # Create Telegraph nodes (each paragraph is a separate node)
            telegraph_nodes = []
            for para in paragraphs:
                if para.strip():
                    # Replace single newlines with <br> tags within paragraphs
                    # Telegraph expects each line as a separate text node
                    lines = para.split('\n')
                    children = []
                    for i, line in enumerate(lines):
                        if line.strip():
                            children.append(line)
                            if i < len(lines) - 1:  # Add br except for last line
                                children.append({'tag': 'br'})

                    if children:
                        telegraph_nodes.append({'tag': 'p', 'children': children})

            # Create page
            response = await client.post(
                'https://api.telegra.ph/createPage',
                json={
                    'access_token': _telegraph_token,
                    'title': title[:256],  # Telegraph limit
                    'content': telegraph_nodes,
                    'return_content': False
                }
            )
            data = response.json()
            page_url = f"https://telegra.ph/{data['result']['path']}"
            logger.info(f"Created Telegraph page: {page_url}")
            return page_url
    except Exception as e:
        logger.error(f"Telegraph error: {e}")
        return None


async def process_youtube_transcript(url: str) -> dict:
    """
    Process YouTube video and create transcript + summary with Telegraph pages.

    Args:
        url: YouTube video URL

    Returns:
        dict with keys:
            - video_id: str
            - original_language: str
            - transcript_url: str | None
            - summary_url: str | None
            - summary_text: str

    Raises:
        NoTranscriptFound: If no transcript is available for the video
    """
    settings = Settings()
    video_id = get_youtube_id(url)
    logger.info(f"Processing YouTube video: {video_id}")

    # Get transcript with language fallback
    if settings.youtube_proxy_url:
        proxies = {"https": settings.youtube_proxy_url}
    else:
        proxies = None

    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, proxies=proxies)
    transcript_data = None
    original_lang = None

    # Try English -> Russian -> first available
    try:
        transcript = transcript_list.find_transcript(['en'])
        transcript_data = transcript.fetch()
        original_lang = 'en'
        logger.info("Found English transcript")
    except:
        try:
            transcript = transcript_list.find_transcript(['ru'])
            transcript_data = transcript.fetch()
            original_lang = 'ru'
            logger.info("Found Russian transcript")
        except:
            # Get first available
            for t in transcript_list:
                transcript_data = t.fetch()
                original_lang = t.language_code
                logger.info(f"Using fallback transcript in language: {original_lang}")
                break

    if not transcript_data:
        raise NoTranscriptFound(video_id)

    # Convert to text
    # .fetch() returns a list - check if items are dicts or objects
    if transcript_data:
        first_item = transcript_data[0]
        logger.debug(f"Transcript item type: {type(first_item)}, has 'text': {hasattr(first_item, 'text')}")

        # Handle both dict format and object format
        if isinstance(first_item, dict):
            full_text = " ".join(item['text'] for item in transcript_data)
        else:
            # FetchedTranscriptSnippet objects
            full_text = " ".join(item.text for item in transcript_data)
    else:
        full_text = ""

    logger.info(f"Transcript length: {len(full_text)} characters")

    # Translate to English
    logger.info("Translating transcript to English...")
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    translation_response = await openai_client.chat.completions.create(
        model=settings.model_transcript,
        messages=[{
            "role": "user",
            "content": f"Translate the following YouTube transcript to English. If already in English, improve grammar and readability while preserving meaning:\n\n{full_text}"
        }]
    )
    translated_text = translation_response.choices[0].message.content
    logger.info("Translation complete")

    # Generate summary
    logger.info("Generating summary...")
    summary_text = await asyncio.to_thread(make_summary_single_call, translated_text)
    logger.info("Summary complete")

    # Create Telegraph pages
    logger.info("Creating Telegraph pages...")

    # For transcript page: put summary at the top, then full transcript
    transcript_with_summary = f"SUMMARY\n\n{summary_text}\n\n{'=' * 50}\n\nFULL TRANSCRIPT\n\n{translated_text}"

    transcript_url = await _create_telegraph_page(
        f"YouTube Transcript: {video_id}",
        transcript_with_summary
    )

    summary_url = await _create_telegraph_page(
        f"YouTube Summary: {video_id}",
        summary_text
    )

    return {
        'video_id': video_id,
        'original_language': original_lang,
        'transcript_url': transcript_url,
        'summary_url': summary_url,
        'summary_text': summary_text
    }


if __name__ == "__main__":
    # Example usage for local testing
    import sys

    # Example YouTube URL - you can replace with any video
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        # Default example: short video
        test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        print(f"No URL provided, using example: {test_url}")
        print("Usage: python youtube_transcript.py <youtube_url>")
        print()

    print(f"Processing: {test_url}\n")

    # Run the async function
    result = asyncio.run(process_youtube_transcript(test_url))

    # Print results
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Video ID: {result['video_id']}")
    print(f"Original Language: {result['original_language']}")
    print()

    if result['transcript_url']:
        print(f"📄 Transcript URL: {result['transcript_url']}")
    else:
        print("⚠️  Transcript Telegraph page creation failed")

    if result['summary_url']:
        print(f"📝 Summary URL: {result['summary_url']}")
    else:
        print("⚠️  Summary Telegraph page creation failed")

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(result['summary_text'])
