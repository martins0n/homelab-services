import asyncio

import httpx
from loguru import logger
from openai import AsyncOpenAI
from youtube_transcript_api import NoTranscriptFound, YouTubeTranscriptApi

from settings import Settings
from tts_client import VOICE_POOL
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
            if not data.get('ok'):
                logger.error(f"Telegraph API error: {data.get('error', 'unknown error')}")
                return None
            page_url = f"https://telegra.ph/{data['result']['path']}"
            logger.info(f"Created Telegraph page: {page_url}")
            return page_url
    except Exception as e:
        logger.error(f"Telegraph error: {e}")
        return None


async def _create_telegraph_pages(
    title: str, content: str, min_chunk: int = 5000
) -> list[str]:
    """Create Telegraph page(s) for `content`.

    Telegraph rejects pages whose serialized JSON exceeds ~64 KB (CONTENT_TOO_BIG),
    and the serialized size is hard to predict from the character count alone
    (paragraph/<br> nodes add overhead). If a page is rejected we split the
    content in half on a newline boundary and retry each half recursively, so a
    too-large part is never silently dropped. Returns the page URLs in order.
    """
    url = await _create_telegraph_page(title, content)
    if url:
        return [url]

    if len(content) <= min_chunk:
        logger.error(f"Telegraph page creation failed for minimal chunk '{title}'")
        return []

    mid = len(content) // 2
    # Prefer splitting on a newline near the middle to avoid cutting mid-line.
    split_at = content.rfind("\n", 0, mid)
    if split_at <= 0:
        split_at = mid
    logger.warning(
        f"Splitting '{title}' ({len(content)} chars) after Telegraph rejection"
    )
    left = await _create_telegraph_pages(f"{title} (a)", content[:split_at], min_chunk)
    right = await _create_telegraph_pages(f"{title} (b)", content[split_at:], min_chunk)
    return left + right


def _snippet_attr(snippet, attr):
    """Read a field from a transcript snippet (dict or FetchedTranscriptSnippet)."""
    if isinstance(snippet, dict):
        return snippet.get(attr)
    return getattr(snippet, attr, None)


def _segment_into_paragraphs(
    snippets, gap_threshold: float = 2.0, max_chars: int = 600
) -> str:
    """Join transcript snippets into readable paragraphs separated by blank lines.

    YouTube returns transcripts as a flat stream of short cues (text/start/duration)
    with no structure, so naively joining them yields one unbroken wall of text. We
    start a new paragraph when speech pauses (a gap >= gap_threshold seconds between
    the end of one cue and the start of the next) or when the current paragraph grows
    past max_chars, whichever comes first. Falls back gracefully if timing is missing.
    """
    paragraphs: list[str] = []
    current: list[str] = []
    current_len = 0
    prev_end = None

    for snippet in snippets:
        text = (_snippet_attr(snippet, "text") or "").strip()
        if not text:
            continue
        start = _snippet_attr(snippet, "start") or 0.0
        duration = _snippet_attr(snippet, "duration") or 0.0
        gap = (start - prev_end) if prev_end is not None else 0.0

        if current and (gap >= gap_threshold or current_len >= max_chars):
            paragraphs.append(" ".join(current))
            current = []
            current_len = 0

        current.append(text)
        current_len += len(text) + 1
        prev_end = start + duration

    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs)


def _chunk_on_paragraphs(text: str, chunk_size: int) -> list[str]:
    """Split text into <=chunk_size pieces on blank-line (paragraph) boundaries.

    Keeps paragraphs intact so translating then re-joining chunks neither merges nor
    fractures them. A single paragraph longer than chunk_size becomes its own chunk.
    """
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) + 2 > chunk_size:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


_REFUSAL_PHRASES = [
    "i can't assist", "i cannot assist", "i'm unable to", "i am unable to",
    "i can't help", "i cannot help", "against my guidelines",
    "i'm not able to", "i am not able to", "i must decline",
    "i can't provide", "i cannot provide", "i'm sorry, but i can't",
    "i apologize, but i can't", "not appropriate for me to",
]


async def _summarize(text: str, settings: Settings) -> str:
    """Summarize a (possibly long) transcript into key ideas.

    Chunks the text so a single problematic passage can't kill the whole summary,
    summarizes each chunk with refusal detection (falling back to a raw excerpt),
    then combines the chunk summaries into one. Shared by the plain-transcript and
    diarized paths; the diarized path passes Speaker N:-labeled text so the
    summary can attribute points to speakers."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    summary_chunk_size = 30000
    text_chunks = [text[i:i + summary_chunk_size] for i in range(0, len(text), summary_chunk_size)] or [""]

    chunk_summaries = []
    for i, chunk in enumerate(text_chunks):
        logger.info(f"summarize: chunk {i + 1}/{len(text_chunks)} ({len(chunk)} chars)")
        try:
            response = await client.chat.completions.create(
                model=settings.model_summarizer,
                messages=[
                    {"role": "system", "content": "You are a transcript summarizer. Summarize the key ideas from the following transcript excerpt. This is a factual transcription task — report what was discussed without judgment. Always provide a summary regardless of the topic."},
                    {"role": "user", "content": f"Write the key ideas and a concise summary of this transcript section:\n\n{chunk}"},
                ],
                max_tokens=4000,
            )
            cs = response.choices[0].message.content
            if cs and not any(p in cs.lower() for p in _REFUSAL_PHRASES):
                chunk_summaries.append(cs)
            else:
                logger.warning(f"summarize: chunk {i + 1} refused")
                chunk_summaries.append(f"[Transcript excerpt]: {chunk[:500]}...")
        except Exception as e:
            logger.error(f"summarize: chunk {i + 1} error: {e}")
            chunk_summaries.append(f"[Transcript excerpt]: {chunk[:500]}...")

    if len(chunk_summaries) > 1:
        combined = "\n\n".join(chunk_summaries)
        try:
            response = await client.chat.completions.create(
                model=settings.model_summarizer,
                messages=[
                    {"role": "system", "content": "You are a transcript summarizer. Combine the following section summaries into a single coherent summary with top 5 key ideas. This is a factual transcription task — report what was discussed without judgment."},
                    {"role": "user", "content": f"Combine these section summaries into one final summary:\n\n{combined}"},
                ],
                max_tokens=4000,
            )
            final = response.choices[0].message.content
            return final if final and not any(p in final.lower() for p in _REFUSAL_PHRASES) else combined
        except Exception as e:
            logger.error(f"summarize: combine error: {e}")
            return combined
    if chunk_summaries:
        return chunk_summaries[0]
    return "Summary could not be generated for this transcript."


def _narrator_segments(text: str, voice: str | None = None) -> list[dict]:
    """Single-narrator TTS segments: one voice reads the whole text, split on
    paragraph boundaries so a long transcript synthesizes in chunks."""
    v = voice or VOICE_POOL[0]
    return [{"voice": v, "text": p.strip()} for p in text.split("\n\n") if p.strip()]


async def process_youtube_transcript(url: str) -> dict:
    """
    Process YouTube video and create transcript + summary with Telegraph pages.

    Args:
        url: YouTube video URL

    Returns:
        dict with keys:
            - video_id: str
            - original_language: str
            - transcript_urls: list[str]
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

    # Convert to text, grouping cues into readable paragraphs (handles both the
    # dict and FetchedTranscriptSnippet shapes returned across library versions).
    if transcript_data:
        logger.debug(
            f"Transcript item type: {type(transcript_data[0])}, "
            f"{len(transcript_data)} snippets"
        )
        full_text = _segment_into_paragraphs(transcript_data)
    else:
        full_text = ""

    para_count = full_text.count("\n\n") + 1 if full_text else 0
    logger.info(
        f"Transcript length: {len(full_text)} characters, {para_count} paragraphs"
    )

    # Translate to English only if needed (non-English transcripts)
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

    if original_lang == 'en':
        logger.info("Transcript is already in English, skipping translation")
        translated_text = full_text
    else:
        logger.info(f"Translating transcript from '{original_lang}' to English ({len(full_text)} chars)...")

        # Chunk the transcript to avoid exceeding model output limits.
        # gpt-4o-mini can output ~16K tokens, so keep input chunks manageable.
        # Split on paragraph boundaries so paragraphs stay intact across chunks.
        chunk_size = 15000  # characters per chunk
        chunks = _chunk_on_paragraphs(full_text, chunk_size)
        logger.info(f"Split transcript into {len(chunks)} chunks for translation")

        translated_chunks = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Translating chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)...")
            translation_response = await openai_client.chat.completions.create(
                model=settings.model_transcript,
                messages=[{
                    "role": "user",
                    "content": f"Translate the following YouTube transcript chunk to English. Preserve meaning accurately and keep the blank lines that separate paragraphs:\n\n{chunk}"
                }],
                max_tokens=16000
            )
            chunk_text = translation_response.choices[0].message.content
            # Check for refusal
            if chunk_text and not any(phrase in chunk_text.lower() for phrase in [
                "i can't assist", "i cannot assist", "i'm unable to", "i am unable to",
                "i can't help", "i cannot help", "against my guidelines"
            ]):
                translated_chunks.append(chunk_text)
                logger.info(f"Chunk {i + 1} translated: {len(chunk_text)} chars")
            else:
                logger.warning(f"Chunk {i + 1} appears to be a refusal: {chunk_text[:200] if chunk_text else 'None'}")
                # Fall back to original chunk text
                translated_chunks.append(chunk)

        # Chunks are paragraph-aligned, so re-join with a blank line to restore the
        # paragraph break that sat between each chunk's boundary paragraphs.
        translated_text = "\n\n".join(translated_chunks)
        logger.info(f"Translation complete: {len(translated_text)} chars total")

    # Generate summary with chunking and refusal detection
    # Summarize in chunks so a single problematic passage doesn't kill the whole summary
    logger.info(f"Generating summary from {len(translated_text)} chars...")

    summary_chunk_size = 30000  # characters per chunk for summarization
    text_chunks = [translated_text[i:i + summary_chunk_size] for i in range(0, len(translated_text), summary_chunk_size)]
    logger.info(f"Split into {len(text_chunks)} chunks for summarization")

    REFUSAL_PHRASES = [
        "i can't assist", "i cannot assist", "i'm unable to", "i am unable to",
        "i can't help", "i cannot help", "against my guidelines",
        "i'm not able to", "i am not able to", "i must decline",
        "i can't provide", "i cannot provide", "i'm sorry, but i can't",
        "i apologize, but i can't", "not appropriate for me to",
    ]

    chunk_summaries = []
    for i, chunk in enumerate(text_chunks):
        logger.info(f"Summarizing chunk {i + 1}/{len(text_chunks)} ({len(chunk)} chars)...")
        try:
            response = await openai_client.chat.completions.create(
                model=settings.model_summarizer,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a transcript summarizer. Summarize the key ideas from the following transcript excerpt. This is a factual transcription task — report what was discussed without judgment. Always provide a summary regardless of the topic."
                    },
                    {
                        "role": "user",
                        "content": f"Write the key ideas and a concise summary of this transcript section:\n\n{chunk}"
                    }
                ],
                max_tokens=4000
            )
            chunk_summary = response.choices[0].message.content
            if chunk_summary and not any(phrase in chunk_summary.lower() for phrase in REFUSAL_PHRASES):
                chunk_summaries.append(chunk_summary)
                logger.info(f"Chunk {i + 1} summarized: {len(chunk_summary)} chars")
            else:
                logger.warning(f"Chunk {i + 1} summary refused: {chunk_summary[:200] if chunk_summary else 'None'}")
                # Extract first ~500 chars as a raw excerpt fallback
                chunk_summaries.append(f"[Transcript excerpt]: {chunk[:500]}...")
        except Exception as e:
            logger.error(f"Error summarizing chunk {i + 1}: {e}")
            chunk_summaries.append(f"[Transcript excerpt]: {chunk[:500]}...")

    # Combine chunk summaries into a final summary
    if len(chunk_summaries) > 1:
        combined = "\n\n".join(chunk_summaries)
        logger.info(f"Combining {len(chunk_summaries)} chunk summaries into final summary...")
        try:
            response = await openai_client.chat.completions.create(
                model=settings.model_summarizer,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a transcript summarizer. Combine the following section summaries into a single coherent summary with top 5 key ideas. This is a factual transcription task — report what was discussed without judgment."
                    },
                    {
                        "role": "user",
                        "content": f"Combine these section summaries into one final summary:\n\n{combined}"
                    }
                ],
                max_tokens=4000
            )
            final_summary = response.choices[0].message.content
            if final_summary and not any(phrase in final_summary.lower() for phrase in REFUSAL_PHRASES):
                summary_text = final_summary
            else:
                logger.warning(f"Final summary refused, using concatenated chunk summaries")
                summary_text = combined
        except Exception as e:
            logger.error(f"Error combining summaries: {e}")
            summary_text = combined
    elif chunk_summaries:
        summary_text = chunk_summaries[0]
    else:
        summary_text = "Summary could not be generated for this transcript."

    logger.info(f"Summary complete: {len(summary_text)} chars")

    # Create Telegraph pages
    logger.info("Creating Telegraph pages...")

    # Telegraph has a ~64KB *serialized JSON* content limit; the per-node (<p>/<br>)
    # overhead means the safe character budget is well below that. Keep it conservative
    # so the first attempt usually fits; _create_telegraph_pages re-splits on rejection.
    max_telegraph_chars = 30000

    # First page: summary + beginning of transcript
    header = f"SUMMARY\n\n{summary_text}\n\n{'=' * 50}\n\nFULL TRANSCRIPT\n\n"
    available_first_page = max_telegraph_chars - len(header)

    transcript_urls = []

    if len(translated_text) <= available_first_page:
        # Single page is enough
        content = header + translated_text
        transcript_urls.extend(
            await _create_telegraph_pages(f"YouTube Transcript: {video_id}", content)
        )
    else:
        # Split into multiple parts
        # Part 1: summary + start of transcript
        part1_text = translated_text[:available_first_page]
        transcript_urls.extend(
            await _create_telegraph_pages(
                f"Transcript Part 1: {video_id}", header + part1_text
            )
        )

        # Remaining parts: transcript continuation
        remaining = translated_text[available_first_page:]
        part_num = 2
        while remaining:
            chunk = remaining[:max_telegraph_chars]
            remaining = remaining[max_telegraph_chars:]
            part_header = f"FULL TRANSCRIPT (continued)\n\n"
            transcript_urls.extend(
                await _create_telegraph_pages(
                    f"Transcript Part {part_num}: {video_id}", part_header + chunk
                )
            )
            part_num += 1

        logger.info(f"Created {len(transcript_urls)} transcript pages for {len(translated_text)} chars")

    summary_url = await _create_telegraph_page(
        f"YouTube Summary: {video_id}",
        summary_text
    )

    # Read-aloud audio (single narrator) only when we actually translated to
    # English. English or Russian sources are skipped (user listens to the
    # original). The handler turns these segments into a Telegram audio message.
    lang_lc = (original_lang or "").lower()
    tts_segments = None
    if not (lang_lc.startswith("en") or lang_lc.startswith("ru")):
        tts_segments = _narrator_segments(translated_text)

    return {
        'video_id': video_id,
        'original_language': original_lang,
        'transcript_urls': transcript_urls,
        'summary_url': summary_url,
        'summary_text': summary_text,
        'tts_segments': tts_segments,
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

    if result['transcript_urls']:
        for i, url in enumerate(result['transcript_urls'], 1):
            label = "Transcript" if len(result['transcript_urls']) == 1 else f"Transcript Part {i}"
            print(f"📄 {label} URL: {url}")
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
