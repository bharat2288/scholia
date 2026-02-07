"""
Video Clipper Service
=====================
Extracts video transcripts and metadata from YouTube (and potentially other platforms).

Uses:
- youtube-transcript-api for fetching transcripts (no API key required)
- yt-dlp for metadata (title, channel, duration, etc.)

Output format matches other source types:
- [TITLE] for video title
- [SECTION] # markers for structure
- [TIMESTAMP HH:MM:SS] markers for navigation
- Transcript text with inline timestamps

Files saved to data/sources/videos/{channel}_{video_id}/
"""

import re
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    """A single segment of the transcript with timing info."""
    text: str
    start: float  # Start time in seconds
    duration: float


@dataclass
class Chapter:
    """A chapter/section in the video."""
    title: str
    start_time: float  # seconds
    end_time: float  # seconds


@dataclass
class VideoMetadata:
    """Metadata about the video."""
    video_id: str
    platform: str  # 'youtube', 'vimeo', etc.
    url: str
    title: str
    channel: str
    channel_id: Optional[str] = None
    duration_seconds: Optional[int] = None
    duration_formatted: Optional[str] = None
    publish_date: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    chapters: List[Chapter] = field(default_factory=list)
    fetched_at: Optional[str] = None


@dataclass
class VideoClipResult:
    """Result of video clipping operation."""
    url: str
    video_id: str
    platform: str
    title: str
    channel: str
    content: str
    content_path: str
    duration_formatted: Optional[str]
    publish_date: Optional[str]
    word_count: int
    segment_count: int
    sections: List[dict]
    metadata: VideoMetadata


def extract_video_id(url: str) -> Tuple[str, str]:
    """
    Extract video ID and platform from URL.

    Supports:
    - youtube.com/watch?v=VIDEO_ID
    - youtu.be/VIDEO_ID
    - youtube.com/embed/VIDEO_ID
    - vimeo.com/VIDEO_ID

    Returns:
        (video_id, platform)

    Raises:
        ValueError: If URL format not recognized
    """
    parsed = urlparse(url)

    # YouTube
    if 'youtube.com' in parsed.netloc or 'youtu.be' in parsed.netloc:
        if 'youtu.be' in parsed.netloc:
            video_id = parsed.path.lstrip('/').split('/')[0]
            if video_id:
                return video_id, 'youtube'

        if parsed.path == '/watch':
            query_params = parse_qs(parsed.query)
            if 'v' in query_params:
                return query_params['v'][0], 'youtube'

        for pattern in ['/embed/', '/v/']:
            if pattern in parsed.path:
                video_id = parsed.path.split(pattern)[1].split('/')[0].split('?')[0]
                if video_id:
                    return video_id, 'youtube'

        # Regex fallback
        match = re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})(?:[&?/]|$)', url)
        if match:
            return match.group(1), 'youtube'

    # Vimeo
    if 'vimeo.com' in parsed.netloc:
        match = re.search(r'vimeo\.com/(\d+)', url)
        if match:
            return match.group(1), 'vimeo'

    raise ValueError(f"Could not extract video ID from URL: {url}")


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _fetch_youtube_transcript(video_id: str) -> Tuple[List[TranscriptSegment], str]:
    """
    Fetch YouTube transcript using youtube-transcript-api.

    Returns:
        (segments, full_text)
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
        )
    except ImportError:
        raise ImportError(
            "youtube-transcript-api is required. "
            "Install with: pip install youtube-transcript-api"
        )

    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        # Try manual transcripts first (usually higher quality)
        try:
            transcript = transcript_list.find_manually_created_transcript(['en'])
        except NoTranscriptFound:
            try:
                transcript = transcript_list.find_generated_transcript(['en'])
            except NoTranscriptFound:
                transcript = transcript_list.find_transcript(['en'])

        transcript_data = transcript.fetch()

    except TranscriptsDisabled:
        raise ValueError(f"Transcripts are disabled for video: {video_id}")
    except VideoUnavailable:
        raise ValueError(f"Video unavailable: {video_id}")
    except NoTranscriptFound:
        raise ValueError(f"No transcript found for video: {video_id}")

    segments = [
        TranscriptSegment(
            text=snippet.text,
            start=snippet.start,
            duration=snippet.duration
        )
        for snippet in transcript_data
    ]

    full_text = " ".join(seg.text for seg in segments)

    return segments, full_text


def _fetch_youtube_metadata(video_id: str, url: str) -> VideoMetadata:
    """
    Fetch YouTube metadata using yt-dlp.
    """
    try:
        import yt_dlp
    except ImportError:
        logger.warning("yt-dlp not installed, using basic metadata")
        return VideoMetadata(
            video_id=video_id,
            platform='youtube',
            url=url,
            title=f"Video {video_id}",
            channel="Unknown",
            fetched_at=datetime.utcnow().isoformat() + "Z"
        )

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:
            logger.warning(f"Failed to fetch metadata via yt-dlp: {e}")
            return VideoMetadata(
                video_id=video_id,
                platform='youtube',
                url=url,
                title=f"Video {video_id}",
                channel="Unknown",
                fetched_at=datetime.utcnow().isoformat() + "Z"
            )

    # Format duration
    duration_secs = info.get('duration')
    duration_fmt = None
    if duration_secs:
        hours, remainder = divmod(duration_secs, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            duration_fmt = f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
        else:
            duration_fmt = f"{int(minutes)}:{int(seconds):02d}"

    # Parse upload date
    upload_date = info.get('upload_date')
    publish_date = None
    if upload_date and len(upload_date) == 8:
        publish_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

    # Extract chapters if available
    chapters = []
    raw_chapters = info.get('chapters') or []
    for ch in raw_chapters:
        if ch.get('title') and ch.get('start_time') is not None:
            chapters.append(Chapter(
                title=ch['title'],
                start_time=float(ch['start_time']),
                end_time=float(ch.get('end_time', ch['start_time']))
            ))

    if chapters:
        logger.info(f"Found {len(chapters)} chapters for video {video_id}")

    return VideoMetadata(
        video_id=video_id,
        platform='youtube',
        url=url,
        title=info.get('title', f"Video {video_id}"),
        channel=info.get('channel', info.get('uploader', 'Unknown')),
        channel_id=info.get('channel_id'),
        duration_seconds=duration_secs,
        duration_formatted=duration_fmt,
        publish_date=publish_date,
        view_count=info.get('view_count'),
        like_count=info.get('like_count'),
        description=info.get('description', '')[:500] if info.get('description') else None,
        thumbnail_url=info.get('thumbnail'),
        chapters=chapters,
        fetched_at=datetime.utcnow().isoformat() + "Z"
    )


def _build_content(
    metadata: VideoMetadata,
    segments: List[TranscriptSegment],
    full_text: str
) -> Tuple[str, List[dict]]:
    """
    Build Scholia-formatted content from video data.

    Format:
    - [TITLE] Video title
    - [SECTION] # Video Info (metadata)
    - If chapters exist: [SECTION] # {chapter_title} for each chapter
    - If no chapters: [SECTION] # Transcript (with timestamps every ~60 seconds)

    Returns:
        (formatted_content, sections_list)
    """
    lines = []
    sections = []

    # Title
    title_line = f"[TITLE] {metadata.title}"
    lines.append(title_line)
    lines.append("")

    # Video Info section
    lines.append("[SECTION] # Video Info")
    lines.append("")

    info_lines = [
        f"**Channel:** {metadata.channel}",
        f"**URL:** {metadata.url}",
    ]
    if metadata.duration_formatted:
        info_lines.append(f"**Duration:** {metadata.duration_formatted}")
    if metadata.publish_date:
        info_lines.append(f"**Published:** {metadata.publish_date}")
    if metadata.view_count:
        info_lines.append(f"**Views:** {metadata.view_count:,}")

    lines.extend(info_lines)
    lines.append("")

    CHUNK_INTERVAL = 60  # seconds between timestamp markers

    if metadata.chapters:
        # Build content organized by chapters
        _build_content_with_chapters(lines, metadata.chapters, segments, CHUNK_INTERVAL)
    else:
        # Fallback: single Transcript section with timestamps
        _build_content_without_chapters(lines, segments, CHUNK_INTERVAL)

    final_content = '\n'.join(lines)

    # Parse sections
    section_pattern = r'\[SECTION\]\s*(#{1,6})\s*(.+?)(?=\n|$)'
    for match in re.finditer(section_pattern, final_content):
        level = len(match.group(1))
        section_title = match.group(2).strip()
        sections.append({
            "title": section_title,
            "level": level,
            "start_offset": match.start(),
            "end_offset": match.start()
        })

    # Calculate end offsets
    for i, section in enumerate(sections):
        if i + 1 < len(sections):
            section["end_offset"] = sections[i + 1]["start_offset"]
        else:
            section["end_offset"] = len(final_content)

    return final_content, sections


def _build_content_with_chapters(
    lines: List[str],
    chapters: List[Chapter],
    segments: List[TranscriptSegment],
    chunk_interval: int
) -> None:
    """
    Build content organized by YouTube chapters.

    Each chapter becomes a [SECTION], and transcript segments are grouped
    under the chapter they fall into. Timestamps are added within each chapter.
    """
    for i, chapter in enumerate(chapters):
        # Chapter header with timestamp
        chapter_ts = format_timestamp(chapter.start_time)
        lines.append(f"[SECTION] # {chapter.title}")
        lines.append("")

        # Add chapter start timestamp
        lines.append(f"[TIMESTAMP {chapter_ts}]")

        # Find segments that belong to this chapter
        chapter_end = chapters[i + 1].start_time if i + 1 < len(chapters) else float('inf')
        chapter_segments = [
            seg for seg in segments
            if chapter.start_time <= seg.start < chapter_end
        ]

        if not chapter_segments:
            lines.append("(No transcript for this chapter)")
            lines.append("")
            continue

        # Group segments into ~60 second chunks within the chapter
        current_chunk_start = int(chapter_segments[0].start // chunk_interval) * chunk_interval
        current_chunk_lines = []

        for segment in chapter_segments:
            # Check if we need a new timestamp marker
            if segment.start >= current_chunk_start + chunk_interval:
                # Emit current chunk
                if current_chunk_lines:
                    lines.append(" ".join(current_chunk_lines))
                    lines.append("")

                # New chunk with timestamp
                current_chunk_start = int(segment.start // chunk_interval) * chunk_interval
                ts = format_timestamp(current_chunk_start)
                lines.append(f"[TIMESTAMP {ts}]")
                current_chunk_lines = []

            current_chunk_lines.append(segment.text)

        # Emit final chunk for this chapter
        if current_chunk_lines:
            lines.append(" ".join(current_chunk_lines))
            lines.append("")


def _build_content_without_chapters(
    lines: List[str],
    segments: List[TranscriptSegment],
    chunk_interval: int
) -> None:
    """
    Build content as a single Transcript section (fallback when no chapters).
    """
    lines.append("[SECTION] # Transcript")
    lines.append("")

    current_chunk_start = 0
    current_chunk_lines = []

    for segment in segments:
        # Check if we need to start a new chunk
        if segment.start >= current_chunk_start + chunk_interval:
            # Emit current chunk with timestamp marker
            if current_chunk_lines:
                ts = format_timestamp(current_chunk_start)
                lines.append(f"[TIMESTAMP {ts}]")
                lines.append(" ".join(current_chunk_lines))
                lines.append("")

            current_chunk_start = int(segment.start // chunk_interval) * chunk_interval
            current_chunk_lines = []

        current_chunk_lines.append(segment.text)

    # Emit final chunk
    if current_chunk_lines:
        ts = format_timestamp(current_chunk_start)
        lines.append(f"[TIMESTAMP {ts}]")
        lines.append(" ".join(current_chunk_lines))
        lines.append("")


def _sanitize_folder_name(name: str, max_length: int = 50) -> str:
    """Sanitize a string for use as a folder name."""
    # Remove/replace problematic characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    sanitized = re.sub(r'\s+', '_', sanitized)
    sanitized = sanitized.strip('._')

    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip('_')

    return sanitized or "video"


async def clip_video(
    url: str,
    output_dir: Path,
    timeout: float = 60.0
) -> VideoClipResult:
    """
    Clip a video and save transcript to the output directory.

    Args:
        url: Video URL (YouTube, Vimeo)
        output_dir: Base directory for video sources
        timeout: Request timeout (not used currently, for future async)

    Returns:
        VideoClipResult with metadata and content path

    Raises:
        ValueError: If URL invalid or transcript unavailable
    """
    # Extract video ID and platform
    video_id, platform = extract_video_id(url)

    logger.info(f"Clipping {platform} video: {video_id}")

    # Fetch based on platform
    if platform == 'youtube':
        segments, full_text = _fetch_youtube_transcript(video_id)
        metadata = _fetch_youtube_metadata(video_id, url)
    elif platform == 'vimeo':
        # Vimeo support would go here
        raise ValueError("Vimeo support coming soon")
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    # Build content
    content, sections = _build_content(metadata, segments, full_text)

    # Create output folder
    channel_safe = _sanitize_folder_name(metadata.channel, 30)
    folder_name = f"{channel_safe}_{video_id}"
    clip_folder = output_dir / folder_name
    clip_folder.mkdir(parents=True, exist_ok=True)

    # Save content
    content_filename = f"{folder_name}--video--extracted.txt"
    content_path = clip_folder / content_filename
    content_path.write_text(content, encoding='utf-8')

    # Save metadata JSON
    metadata_dict = {
        "video_id": metadata.video_id,
        "platform": metadata.platform,
        "url": metadata.url,
        "title": metadata.title,
        "channel": metadata.channel,
        "channel_id": metadata.channel_id,
        "duration_seconds": metadata.duration_seconds,
        "duration_formatted": metadata.duration_formatted,
        "publish_date": metadata.publish_date,
        "view_count": metadata.view_count,
        "like_count": metadata.like_count,
        "description": metadata.description,
        "thumbnail_url": metadata.thumbnail_url,
        "chapters": [
            {
                "title": ch.title,
                "start_time": ch.start_time,
                "end_time": ch.end_time,
                "start_formatted": format_timestamp(ch.start_time)
            }
            for ch in metadata.chapters
        ] if metadata.chapters else [],
        "fetched_at": metadata.fetched_at,
        "clipped_at": datetime.now().isoformat(),
        "word_count": len(full_text.split()),
        "segment_count": len(segments),
        "chapter_count": len(metadata.chapters),
    }

    metadata_path = clip_folder / "video.json"
    metadata_path.write_text(
        json.dumps(metadata_dict, indent=2),
        encoding='utf-8'
    )

    logger.info(f"Saved video transcript: {content_path}")

    return VideoClipResult(
        url=url,
        video_id=video_id,
        platform=platform,
        title=metadata.title,
        channel=metadata.channel,
        content=content,
        content_path=str(content_path),
        duration_formatted=metadata.duration_formatted,
        publish_date=metadata.publish_date,
        word_count=len(full_text.split()),
        segment_count=len(segments),
        sections=sections,
        metadata=metadata
    )
