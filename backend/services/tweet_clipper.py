"""
Tweet Clipper Service
=====================
Extracts tweets and threads from Twitter/X.

Primary approach: Twitter oEmbed API (reliable, no auth needed)
Fallback: Nitter instances (for additional metadata when available)

Output format matches web clipper:
- [TITLE] for thread title
- [SECTION] # markers for thread structure
- [FIGURE filename] for media
- [CAPTION] for image captions
- [TWEET n/N] markers for individual tweets

Files saved to data/sources/threads/{username}_{tweet_id}/
"""

import httpx
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
import re
import json
import asyncio
from urllib.parse import urlparse, urljoin, quote
from datetime import datetime
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)


# Nitter instances for fallback (updated Jan 2026)
# Most have bot protection now, but keeping for potential future use
NITTER_INSTANCES = [
    "xcancel.com",
    "nitter.poast.org",
    "nitter.privacyredirect.com",
]


@dataclass
class TweetData:
    """Data for a single tweet."""
    text: str
    author_handle: str
    author_display: str
    timestamp: Optional[str] = None
    media: List[Dict] = field(default_factory=list)  # [{url, type, alt}]
    is_retweet: bool = False
    is_quote: bool = False


@dataclass
class TweetClipResult:
    """Result of tweet clipping operation."""
    url: str
    tweet_id: str
    author_handle: str
    author_display: str
    title: str
    content: str
    timestamp: Optional[str]
    content_path: str
    thread_length: int
    sections: List[dict]  # Parsed sections with offsets
    media: List[dict] = field(default_factory=list)  # Downloaded media metadata
    is_reply: bool = False
    parent_tweet_id: Optional[str] = None
    nitter_instance: Optional[str] = None
    source_type: str = "thread"  # "thread" for tweets, "web" for articles
    is_article: bool = False
    warning: Optional[str] = None  # Warning message (e.g., possible incomplete thread)
    thread_tweet_ids: List[str] = field(default_factory=list)  # All tweet IDs in thread (for dedup)


def extract_tweet_info(url: str) -> Tuple[str, str]:
    """
    Extract tweet_id and username from a Twitter/X URL.

    Supports:
    - twitter.com/user/status/1234567890
    - x.com/user/status/1234567890
    - With or without query params

    Returns:
        (tweet_id, username)

    Raises:
        ValueError: If URL is not a valid tweet URL
    """
    pattern = r'(?:twitter\.com|x\.com)/([^/]+)/status/(\d+)'
    match = re.search(pattern, url)
    if match:
        username = match.group(1)
        tweet_id = match.group(2)
        return tweet_id, username
    raise ValueError(f"Invalid tweet URL: {url}")


async def _fetch_fxtwitter(tweet_id: str, timeout: float = 20.0) -> Dict:
    """
    Fetch tweet data using FxTwitter API.

    FxTwitter is a third-party service that provides full tweet content,
    including long-form tweets (Twitter Notes) that are truncated by official APIs.

    Returns:
        Dict with full tweet data including:
        - Full text (not truncated)
        - Media URLs
        - User info
        - Engagement metrics

    Raises:
        ValueError: If tweet not found or API error
    """
    fxtwitter_url = f"https://api.fxtwitter.com/status/{tweet_id}"

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
    ) as client:
        response = await client.get(fxtwitter_url)

        if response.status_code == 404:
            raise ValueError(f"Tweet not found (id: {tweet_id})")
        elif response.status_code != 200:
            raise ValueError(f"FxTwitter API error: HTTP {response.status_code}")

        data = response.json()

        # FxTwitter wraps tweet in a 'tweet' object
        if 'tweet' in data:
            return data['tweet']

        return data


async def _fetch_syndication(tweet_id: str, timeout: float = 20.0) -> Dict:
    """
    Fallback: Fetch tweet data using Twitter's syndication API.
    Note: This API truncates long tweets (Twitter Notes).

    Returns:
        Dict with tweet data

    Raises:
        ValueError: If tweet not found or API error
    """
    syndication_url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=en&token=a"

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    ) as client:
        response = await client.get(syndication_url)

        if response.status_code == 404:
            raise ValueError(f"Tweet not found (id: {tweet_id})")
        elif response.status_code != 200:
            raise ValueError(f"Syndication API error: HTTP {response.status_code}")

        data = response.json()

        # Check for error responses
        if data.get('__typename') == 'TweetTombstone':
            raise ValueError(f"Tweet unavailable: {data.get('tombstone', {}).get('text', 'Unknown reason')}")

        return data


async def _fetch_oembed(url: str, timeout: float = 20.0) -> Dict:
    """
    Fallback: Fetch tweet data using Twitter's oEmbed API.
    Note: oEmbed truncates long tweets, prefer _fetch_syndication.

    Returns:
        Dict with author_name, author_url, html, url

    Raises:
        ValueError: If tweet not found or API error
    """
    tweet_id, username = extract_tweet_info(url)
    canonical_url = f"https://twitter.com/{username}/status/{tweet_id}"

    oembed_url = f"https://publish.twitter.com/oembed?url={quote(canonical_url, safe='')}"

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    ) as client:
        response = await client.get(oembed_url)

        if response.status_code == 404:
            raise ValueError(f"Tweet not found: {url}")
        elif response.status_code != 200:
            raise ValueError(f"oEmbed API error: HTTP {response.status_code}")

        return response.json()


def _parse_oembed_html(html: str) -> Tuple[str, Optional[str]]:
    """
    Parse tweet text and timestamp from oEmbed HTML.

    The HTML looks like:
    <blockquote class="twitter-tweet">
        <p>Tweet text here</p>
        — Author Name (@handle) <a href="...">April 25, 2022</a>
    </blockquote>

    Returns:
        (tweet_text, timestamp)
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Extract tweet text from <p> tag
    p_tag = soup.find('p')
    tweet_text = p_tag.get_text(separator='\n', strip=True) if p_tag else ""

    # Extract timestamp from the date link
    timestamp = None
    links = soup.find_all('a')
    for link in links:
        href = link.get('href', '')
        if 'status/' in href and '?ref_src' in href:
            # This is the date link
            timestamp = link.get_text(strip=True)
            break

    return tweet_text, timestamp


def _extract_handle_from_url(author_url: str) -> str:
    """Extract username handle from author URL."""
    # https://twitter.com/username -> username
    parts = author_url.rstrip('/').split('/')
    return parts[-1] if parts else "unknown"


def _apply_text_formatting(text: str, facets: List[Dict]) -> str:
    """
    Apply formatting from facets to text, converting to markdown.

    Facets contain formatting info like:
    {"type": "bold", "indices": [67, 82]}
    {"type": "italic", "indices": [100, 110]}

    Returns text with markdown formatting applied.
    """
    if not facets:
        return text

    # Sort facets by start index in reverse order (process from end to avoid offset issues)
    sorted_facets = sorted(facets, key=lambda f: f.get('indices', [0, 0])[0], reverse=True)

    result = text
    for facet in sorted_facets:
        facet_type = facet.get('type', '')
        indices = facet.get('indices', [])

        if len(indices) != 2:
            continue

        start, end = indices

        # Validate indices
        if start < 0 or end > len(result) or start >= end:
            continue

        # Get the text segment
        segment = result[start:end]

        # Apply markdown formatting based on type
        if facet_type == 'bold':
            formatted = f"**{segment}**"
        elif facet_type == 'italic':
            formatted = f"*{segment}*"
        elif facet_type == 'link':
            url = facet.get('url', '')
            formatted = f"[{segment}]({url})" if url else segment
        else:
            # Unknown type, skip
            continue

        # Replace in text
        result = result[:start] + formatted + result[end:]

    return result


async def _try_fetch_media_from_meta(url: str, timeout: float = 15.0) -> List[Dict]:
    """
    Try to fetch media URLs from Twitter's meta tags.

    Twitter pages include og:image meta tags that may contain media.
    This is a best-effort approach since it may be blocked.
    """
    media = []

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        ) as client:
            response = await client.get(url)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # Look for og:image meta tags
                for meta in soup.find_all('meta', property='og:image'):
                    content = meta.get('content', '')
                    if content and 'pbs.twimg.com' in content:
                        media.append({
                            'url': content,
                            'type': 'image',
                            'alt': ''
                        })

    except Exception as e:
        logger.debug(f"Could not fetch media metadata: {e}")

    return media


async def _download_media(
    media_items: List[Dict],
    output_dir: Path,
    timeout: float = 15.0
) -> List[Dict]:
    """
    Download media files to the output directory.

    Args:
        media_items: List of {url, type, alt} dicts
        output_dir: Directory to save media (will create 'media/' subfolder)
        timeout: Timeout per download

    Returns:
        Updated media list with 'downloaded', 'filename', 'local_path' fields
    """
    if not media_items:
        return []

    media_dir = output_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    async def download_one(item: Dict, index: int) -> Dict:
        """Download a single media file."""
        url = item['url']

        # Determine extension
        ext = '.jpg'  # Default
        if '.png' in url.lower():
            ext = '.png'
        elif '.gif' in url.lower():
            ext = '.gif'
        elif '.webp' in url.lower():
            ext = '.webp'
        elif '.mp4' in url.lower():
            ext = '.mp4'

        filename = f"media_{index + 1}{ext}"
        local_path = media_dir / filename

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                # Skip tiny files (tracking pixels)
                if len(response.content) < 1000:
                    item['downloaded'] = False
                    item['error'] = "File too small"
                    return item

                local_path.write_bytes(response.content)
                item['downloaded'] = True
                item['filename'] = filename
                item['local_path'] = str(local_path)
                item['size'] = len(response.content)
                logger.debug(f"Downloaded media: {filename}")

        except Exception as e:
            logger.warning(f"Failed to download {url}: {e}")
            item['downloaded'] = False
            item['error'] = str(e)

        return item

    # Download concurrently
    tasks = [download_one(item.copy(), i) for i, item in enumerate(media_items)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle exceptions
    downloaded = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            media_items[i]['downloaded'] = False
            media_items[i]['error'] = str(result)
            downloaded.append(media_items[i])
        else:
            downloaded.append(result)

    return downloaded


def _build_content(
    tweet_text: str,
    author_handle: str,
    author_display: str,
    timestamp: Optional[str],
    media_items: List[Dict],
    tweet_id: str,
    original_url: str
) -> Tuple[str, List[Dict]]:
    """
    Build Scholia-formatted content from tweet data.

    Returns:
        (formatted_content, sections_list)
    """
    lines = []
    sections = []
    current_offset = 0

    # Build title
    title = f"Tweet by @{author_handle}"

    title_line = f"[TITLE] {title}"
    lines.append(title_line)
    lines.append("")
    current_offset = len(title_line) + 2

    # Tweet Info section
    section_marker = "[SECTION] # Tweet Info"
    lines.append(section_marker)
    section_start = current_offset
    current_offset += len(section_marker) + 1

    info_lines = [
        f"**Author:** {author_display} (@{author_handle})",
        f"**URL:** {original_url}",
    ]
    if timestamp:
        info_lines.insert(1, f"**Date:** {timestamp}")

    for line in info_lines:
        lines.append(line)
        current_offset += len(line) + 1
    lines.append("")
    current_offset += 1

    sections.append({
        "title": "Tweet Info",
        "level": 1,
        "start_offset": section_start,
        "end_offset": current_offset
    })

    # Tweet Content section
    section_marker = "[SECTION] # Content"
    lines.append(section_marker)
    section_start = current_offset
    current_offset += len(section_marker) + 1
    lines.append("")
    current_offset += 1

    # Tweet text
    lines.append(tweet_text)
    current_offset += len(tweet_text) + 1

    # Add media
    for i, media in enumerate(media_items):
        if media.get('downloaded'):
            filename = media.get('filename', f'media_{i + 1}.jpg')
            figure_line = f"\n[FIGURE {filename}]"
            lines.append(figure_line)
            current_offset += len(figure_line) + 1

            if media.get('alt'):
                caption_line = f"[CAPTION] {media['alt']}"
                lines.append(caption_line)
                current_offset += len(caption_line) + 1

    lines.append("")
    current_offset += 1

    sections.append({
        "title": "Content",
        "level": 1,
        "start_offset": section_start,
        "end_offset": current_offset
    })

    final_content = '\n'.join(lines)

    # Re-parse sections with correct offsets
    sections = []
    section_pattern = r'\[SECTION\]\s*(#{1,6})\s*(.+?)(?=\n|$)'
    for match in re.finditer(section_pattern, final_content):
        level = len(match.group(1))
        section_title = match.group(2).strip()
        sections.append({
            "title": section_title,
            "level": level,
            "start_offset": match.start(),
            "end_offset": match.start()  # Will be updated
        })

    # Calculate end offsets
    for i, section in enumerate(sections):
        if i + 1 < len(sections):
            section["end_offset"] = sections[i + 1]["start_offset"]
        else:
            section["end_offset"] = len(final_content)

    return final_content, sections


def _extract_media_from_fxtwitter(data: Dict) -> List[Dict]:
    """Extract media URLs from FxTwitter API response."""
    media_items = []

    # FxTwitter provides media in 'media' object with 'all' array
    media_obj = data.get('media', {})
    all_media = media_obj.get('all', [])

    for item in all_media:
        media_type = item.get('type', '')
        url = item.get('url', '')

        if media_type == 'photo' and url:
            media_items.append({
                'url': url,
                'type': 'image',
                'alt': item.get('altText', ''),
                'width': item.get('width'),
                'height': item.get('height'),
            })
        elif media_type == 'video':
            # For videos, use thumbnail_url instead of the video file
            thumbnail_url = item.get('thumbnail_url', '')
            if thumbnail_url:
                media_items.append({
                    'url': thumbnail_url,
                    'type': 'video_thumbnail',
                    'alt': 'Video thumbnail',
                    'width': item.get('width'),
                    'height': item.get('height'),
                })
        elif media_type == 'gif' and url:
            media_items.append({
                'url': url,
                'type': 'gif',
                'alt': 'GIF',
            })

    # Also check mediaURLs array (simpler format)
    media_urls = data.get('mediaURLs', [])
    if not media_items and media_urls:
        for url in media_urls:
            if url:
                media_items.append({
                    'url': url,
                    'type': 'image',
                    'alt': '',
                })

    return media_items


def _extract_media_from_syndication(data: Dict) -> List[Dict]:
    """Extract media URLs from syndication API response (fallback)."""
    media_items = []

    # Check for photos
    photos = data.get('photos', [])
    for photo in photos:
        url = photo.get('url', '')
        if url:
            if '?' not in url:
                url = f"{url}?format=jpg&name=large"
            media_items.append({
                'url': url,
                'type': 'image',
                'alt': photo.get('alt_text', ''),
                'width': photo.get('width'),
                'height': photo.get('height'),
            })

    # Check for video
    video = data.get('video', {})
    if video:
        poster = video.get('poster')
        if poster:
            media_items.append({
                'url': poster,
                'type': 'video_poster',
                'alt': 'Video thumbnail',
            })

    return media_items


def _format_syndication_timestamp(created_at: str) -> str:
    """Format syndication API timestamp to readable format."""
    try:
        # Parse ISO format: 2022-04-25T16:12:30.000Z
        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        return dt.strftime('%B %d, %Y')
    except Exception:
        return created_at


def _format_fxtwitter_timestamp(created_at: str) -> str:
    """Format FxTwitter timestamp to readable format."""
    try:
        # FxTwitter format: "Sun Jan 26 15:30:00 +0000 2026"
        from datetime import datetime
        dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime('%B %d, %Y')
    except Exception:
        return created_at


async def _fetch_thread_chain(
    start_tweet_id: str,
    author_handle: str,
    timeout: float = 20.0
) -> List[Dict]:
    """
    Follow the reply chain upward to get all tweets in a thread by the same author.

    Starts from the given tweet and follows in_reply_to_status_id until:
    - We hit a tweet with no parent (root of thread)
    - We hit a tweet by a different author (end of author's thread)
    - We hit a deleted/unavailable tweet

    Returns:
        List of tweet data dicts in chronological order (root first)
    """
    tweets = []
    current_id = start_tweet_id
    seen_ids = set()  # Prevent infinite loops

    while current_id and current_id not in seen_ids:
        seen_ids.add(current_id)

        try:
            data = await _fetch_fxtwitter(current_id, timeout)
        except Exception as e:
            logger.warning(f"Failed to fetch tweet {current_id}: {e}")
            break

        # Check if this tweet is by the same author
        tweet_author = data.get('author', {}).get('screen_name', '').lower()
        if tweet_author != author_handle.lower():
            # Different author - stop here (don't include this tweet)
            logger.info(f"Thread chain ended: different author @{tweet_author}")
            break

        # Add this tweet to our collection
        tweets.append(data)

        # Check for parent tweet (same author replying to themselves)
        # FxTwitter uses 'replying_to' for the username and 'replying_to_status' for the tweet ID
        replying_to_user = (data.get('replying_to') or '').lower()
        parent_id = data.get('replying_to_status')

        # Only follow if replying to self
        if parent_id and replying_to_user == author_handle.lower():
            current_id = parent_id
            logger.debug(f"Following thread chain to parent: {parent_id}")
        else:
            # No parent or replying to someone else - this is the root
            break

    # Reverse to get chronological order (root first)
    tweets.reverse()

    logger.info(f"Found {len(tweets)} tweets in thread by @{author_handle}")
    return tweets


def _build_thread_content(
    tweets: List[Dict],
    author_handle: str,
    author_display: str,
    media_items_by_tweet: Dict[str, List[Dict]],
    original_url: str
) -> Tuple[str, List[Dict]]:
    """
    Build Scholia-formatted content from a thread of tweets.

    Args:
        tweets: List of tweet data dicts in chronological order
        author_handle: Author's handle
        author_display: Author's display name
        media_items_by_tweet: Dict mapping tweet_id to downloaded media items
        original_url: Original URL that was clipped

    Returns:
        (formatted_content, sections_list)
    """
    thread_length = len(tweets)
    lines = []
    sections = []

    # Title
    if thread_length == 1:
        title = f"Tweet by @{author_handle}"
    else:
        title = f"Thread by @{author_handle} ({thread_length} tweets)"

    lines.append(f"[TITLE] {title}")
    lines.append("")

    # Thread Info section
    lines.append("[SECTION] # Thread Info")
    lines.append(f"**Author:** {author_display} (@{author_handle})")
    lines.append(f"**Thread Length:** {thread_length} tweet{'s' if thread_length > 1 else ''}")

    # Get timestamp from first tweet
    first_tweet = tweets[0] if tweets else {}
    created_at = first_tweet.get('created_at', '')
    if created_at:
        timestamp = _format_fxtwitter_timestamp(created_at)
        lines.append(f"**Date:** {timestamp}")

    lines.append(f"**URL:** {original_url}")
    lines.append("")

    sections.append({"title": "Thread Info", "level": 1})

    # Each tweet as a section
    for i, tweet_data in enumerate(tweets, 1):
        tweet_id = tweet_data.get('id', '')

        # Section marker
        if thread_length == 1:
            section_title = "Content"
        else:
            section_title = f"Tweet {i}/{thread_length}"

        lines.append(f"[SECTION] # {section_title}")
        lines.append("")

        # Extract and format tweet text
        raw_text_obj = tweet_data.get('raw_text', {})
        if raw_text_obj and raw_text_obj.get('facets'):
            tweet_text = raw_text_obj.get('text', tweet_data.get('text', ''))
            facets = raw_text_obj.get('facets', [])
            tweet_text = _apply_text_formatting(tweet_text, facets)
        else:
            tweet_text = tweet_data.get('text', '')

        lines.append(tweet_text)

        # Add media for this tweet
        tweet_media = media_items_by_tweet.get(tweet_id, [])
        for media in tweet_media:
            if media.get('downloaded'):
                filename = media.get('filename', '')
                lines.append(f"\n[FIGURE {filename}]")
                if media.get('alt'):
                    lines.append(f"[CAPTION] {media['alt']}")

        lines.append("")
        sections.append({"title": section_title, "level": 1})

    final_content = '\n'.join(lines)

    # Calculate section offsets
    section_pattern = r'\[SECTION\]\s*(#{1,6})\s*(.+?)(?=\n|$)'
    offset_sections = []
    for match in re.finditer(section_pattern, final_content):
        level = len(match.group(1))
        section_title = match.group(2).strip()
        offset_sections.append({
            "title": section_title,
            "level": level,
            "start_offset": match.start(),
            "end_offset": match.start()
        })

    # Calculate end offsets
    for i, section in enumerate(offset_sections):
        if i + 1 < len(offset_sections):
            section["end_offset"] = offset_sections[i + 1]["start_offset"]
        else:
            section["end_offset"] = len(final_content)

    return final_content, offset_sections


def _extract_media_from_article(article: Dict) -> List[Dict]:
    """
    Extract media URLs from Twitter Article's media_entities.

    Articles store images in media_entities array with full URLs.
    Handles both ApiImage (direct images) and ApiVideo (video thumbnails).
    """
    media_items = []
    media_entities = article.get('media_entities', [])

    for entity in media_entities:
        media_info = entity.get('media_info', {})
        typename = media_info.get('__typename', '')

        # For ApiImage: URL is directly in media_info
        # For ApiVideo: URL is in media_info.preview_image (video thumbnail)
        if typename == 'ApiVideo':
            preview = media_info.get('preview_image', {})
            url = preview.get('original_img_url', '')
            width = preview.get('original_img_width')
            height = preview.get('original_img_height')
        else:
            url = media_info.get('original_img_url', '')
            width = media_info.get('original_img_width')
            height = media_info.get('original_img_height')

        if url:
            media_items.append({
                'url': url,
                'type': 'image',
                'alt': '',
                'media_id': entity.get('media_id'),
                'width': width,
                'height': height,
            })

    return media_items


def _apply_inline_styles(text: str, style_ranges: List[Dict]) -> str:
    """
    Apply inline styles (bold, italic) from Draft.js format.

    style_ranges format: [{"length": 11, "offset": 178, "style": "Bold"}]
    """
    if not style_ranges or not text:
        return text

    # Sort by offset in reverse to apply from end to start
    sorted_ranges = sorted(style_ranges, key=lambda r: r.get('offset', 0), reverse=True)

    result = text
    for style_range in sorted_ranges:
        offset = style_range.get('offset', 0)
        length = style_range.get('length', 0)
        style = style_range.get('style', '')

        if offset < 0 or offset + length > len(result):
            continue

        segment = result[offset:offset + length]

        if style == 'Bold':
            formatted = f"**{segment}**"
        elif style == 'Italic':
            formatted = f"*{segment}*"
        else:
            continue

        result = result[:offset] + formatted + result[offset + length:]

    return result


def _parse_article_blocks(
    article: Dict,
    media_items: List[Dict]
) -> Tuple[str, List[Dict]]:
    """
    Parse Draft.js blocks from Twitter Article into Scholia format.

    Block types:
    - unstyled: Regular paragraph
    - header-two: H2 heading → [SECTION] ## Title
    - blockquote: Quoted text → > prefixed
    - atomic: Media placeholder → [FIGURE filename]

    Returns:
        (formatted_content, sections_list)
    """
    content = article.get('content', {})
    blocks = content.get('blocks', [])
    raw_entity_map = content.get('entityMap', {})

    # entityMap can be a list of {key, value} or a dict - normalize to dict
    if isinstance(raw_entity_map, list):
        entity_map = {}
        for item in raw_entity_map:
            key = str(item.get('key', ''))
            value = item.get('value', {})
            entity_map[key] = value
    else:
        entity_map = raw_entity_map

    # Build media_id to filename mapping
    media_id_to_filename = {}
    for i, item in enumerate(media_items):
        if item.get('downloaded') and item.get('media_id'):
            media_id_to_filename[item['media_id']] = item.get('filename', f'figure_{i + 1}.jpg')

    lines = []
    sections = []
    figure_index = 0

    for block in blocks:
        block_type = block.get('type', 'unstyled')
        text = block.get('text', '').strip()
        style_ranges = block.get('inlineStyleRanges', [])
        entity_ranges = block.get('entityRanges', [])

        if block_type == 'header-two':
            # H2 heading → section marker
            lines.append(f"\n[SECTION] ## {text}")
            sections.append({
                "title": text,
                "level": 2
            })

        elif block_type == 'blockquote':
            # Blockquote → prefixed lines
            styled_text = _apply_inline_styles(text, style_ranges)
            for line in styled_text.split('\n'):
                lines.append(f"> {line}")

        elif block_type == 'atomic':
            # Atomic blocks reference entities in entityMap (media, code, etc.)
            for entity_ref in entity_ranges:
                key = str(entity_ref.get('key', ''))
                entity = entity_map.get(key, {})
                entity_type = entity.get('type', '')

                if entity_type == 'MEDIA':
                    media_data = entity.get('data', {})
                    media_items_ref = media_data.get('mediaItems', [])

                    for media_item in media_items_ref:
                        media_id = media_item.get('mediaId', '')
                        filename = media_id_to_filename.get(media_id)

                        if filename:
                            lines.append(f"\n[FIGURE {filename}]")
                        else:
                            # Fallback: use index-based naming
                            figure_index += 1
                            lines.append(f"\n[FIGURE figure_{figure_index}.jpg]")

                elif entity_type == 'MARKDOWN':
                    # Code blocks stored as markdown in entity data
                    markdown = entity.get('data', {}).get('markdown', '')
                    if markdown:
                        lines.append(f"\n{markdown}\n")

                elif entity_type == 'TWEET':
                    # Embedded tweet reference
                    tweet_id = entity.get('data', {}).get('tweetId', '')
                    if tweet_id:
                        lines.append(f"\n[EMBEDDED_TWEET {tweet_id}]\n")

                elif entity_type == 'DIVIDER':
                    # Horizontal rule
                    lines.append("\n---\n")

        elif block_type == 'unstyled':
            # Regular paragraph - needs blank line after for proper spacing
            if not text:
                lines.append("")
            else:
                styled_text = _apply_inline_styles(text, style_ranges)
                # Handle bullet points (text starting with "- ")
                # Don't add blank line after bullets (they're part of a list)
                if styled_text.startswith('- ') or styled_text.startswith('* '):
                    lines.append(styled_text)
                else:
                    lines.append(styled_text)
                    lines.append("")  # Blank line after paragraph

        else:
            # Unknown block type, treat as paragraph
            if text:
                styled_text = _apply_inline_styles(text, style_ranges)
                lines.append(styled_text)
                lines.append("")  # Blank line after paragraph

    # Join lines - paragraphs already have trailing blank lines
    final_content = '\n'.join(lines)
    # Clean up multiple consecutive blank lines
    while '\n\n\n' in final_content:
        final_content = final_content.replace('\n\n\n', '\n\n')

    # Calculate section offsets
    for i, section in enumerate(sections):
        pattern = f"[SECTION] ## {section['title']}"
        idx = final_content.find(pattern)
        if idx >= 0:
            section['start_offset'] = idx
            if i + 1 < len(sections):
                next_pattern = f"[SECTION] ## {sections[i + 1]['title']}"
                next_idx = final_content.find(next_pattern)
                section['end_offset'] = next_idx if next_idx > 0 else len(final_content)
            else:
                section['end_offset'] = len(final_content)

    return final_content, sections


def _build_article_content(
    article: Dict,
    author_handle: str,
    author_display: str,
    timestamp: Optional[str],
    media_items: List[Dict],
    original_url: str
) -> Tuple[str, List[Dict]]:
    """
    Build Scholia-formatted content from Twitter Article.

    Returns:
        (formatted_content, sections_list)
    """
    title = article.get('title', 'Untitled Article')

    # Parse article blocks
    article_content, article_sections = _parse_article_blocks(article, media_items)

    # Build header
    lines = []
    lines.append(f"[TITLE] {title}")
    lines.append("")

    # Article Info section
    lines.append("[SECTION] # Article Info")
    lines.append(f"**Author:** {author_display} (@{author_handle})")
    if timestamp:
        lines.append(f"**Date:** {timestamp}")
    lines.append(f"**URL:** {original_url}")
    lines.append("")

    # Main content
    lines.append("[SECTION] # Content")
    lines.append(article_content)

    final_content = '\n'.join(lines)

    # Build sections list with Article Info and Content as top-level
    sections = [
        {"title": "Article Info", "level": 1, "start_offset": 0, "end_offset": 0},
        {"title": "Content", "level": 1, "start_offset": 0, "end_offset": 0},
    ]
    # Add article's internal sections (H2s become level 2)
    sections.extend(article_sections)

    # Recalculate offsets
    section_pattern = r'\[SECTION\]\s*(#{1,6})\s*(.+?)(?=\n|$)'
    for match in re.finditer(section_pattern, final_content):
        level = len(match.group(1))
        section_title = match.group(2).strip()

        for section in sections:
            if section['title'] == section_title:
                section['start_offset'] = match.start()
                section['level'] = level
                break

    # Calculate end offsets
    for i, section in enumerate(sections):
        if i + 1 < len(sections):
            section['end_offset'] = sections[i + 1].get('start_offset', len(final_content))
        else:
            section['end_offset'] = len(final_content)

    return final_content, sections


async def clip_tweet(
    url: str,
    output_dir: Path,
    timeout: float = 30.0
) -> TweetClipResult:
    """
    Clip a tweet and save to the output directory.

    Uses FxTwitter API for full tweet data including:
    - Complete text (not truncated, including long-form tweets)
    - Media attachments (images, videos, GIFs)
    - User info
    - Engagement metrics

    Falls back to Twitter's syndication API if FxTwitter fails.

    Args:
        url: Twitter/X URL
        output_dir: Base directory for tweet sources
        timeout: Request timeout

    Returns:
        TweetClipResult with metadata and content path

    Raises:
        ValueError: If URL is invalid or tweet not found
        httpx.HTTPError: If fetch fails
    """
    # Parse URL
    tweet_id, username = extract_tweet_info(url)

    # Try FxTwitter first (provides full text for long tweets)
    data = None
    source_api = None

    try:
        logger.info(f"Fetching tweet via FxTwitter API: {url}")
        data = await _fetch_fxtwitter(tweet_id, timeout)
        source_api = 'fxtwitter'
    except Exception as e:
        logger.warning(f"FxTwitter failed: {e}, trying syndication API")
        try:
            data = await _fetch_syndication(tweet_id, timeout)
            source_api = 'syndication'
        except Exception as e2:
            raise ValueError(f"Failed to fetch tweet: {e2}")

    # Extract author info (same for tweets and articles)
    if source_api == 'fxtwitter':
        author_handle = data.get('author', {}).get('screen_name', username)
        author_display = data.get('author', {}).get('name', author_handle)
        created_at = data.get('created_at', '')
        timestamp = _format_fxtwitter_timestamp(created_at) if created_at else None
    else:
        user = data.get('user', {})
        author_handle = user.get('screen_name', username)
        author_display = user.get('name', author_handle)
        created_at = data.get('created_at', '')
        timestamp = _format_syndication_timestamp(created_at) if created_at else None

    # Check if this is a Twitter Article (long-form content)
    article = data.get('article') if source_api == 'fxtwitter' else None
    is_article = article is not None and article.get('content')

    if is_article:
        # ========== ARTICLE HANDLING (source_type='web') ==========
        logger.info(f"Detected Twitter Article: {article.get('title', 'Untitled')}")

        # Extract media from article
        media_items = _extract_media_from_article(article)
        logger.info(f"Found {len(media_items)} media items in article")

        # Create output folder (in web/ directory, passed by caller)
        folder_name = f"{author_handle}_{tweet_id}"
        clip_folder = output_dir / folder_name
        clip_folder.mkdir(parents=True, exist_ok=True)

        # Download media to figures/ subfolder (web source convention)
        downloaded_media = []
        if media_items:
            figures_dir = clip_folder / "figures"
            figures_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"Downloading {len(media_items)} article images")
            # Download to figures/ subfolder
            downloaded_media = await _download_media(media_items, clip_folder, timeout=15.0)

            # Move from media/ to figures/ (web convention)
            media_subdir = clip_folder / "media"
            if media_subdir.exists():
                import shutil
                for f in media_subdir.iterdir():
                    dest = figures_dir / f.name
                    # Use shutil.move to handle cross-device and existing files
                    if dest.exists():
                        dest.unlink()
                    shutil.move(str(f), str(dest))
                    # Update downloaded_media paths
                    for m in downloaded_media:
                        if m.get('filename') == f.name:
                            m['local_path'] = str(dest)
                try:
                    media_subdir.rmdir()
                except OSError:
                    pass  # Ignore if not empty

            # Save figures metadata
            figures_json = clip_folder / "figures.json"
            figures_json.write_text(
                json.dumps(downloaded_media, indent=2),
                encoding='utf-8'
            )

            success_count = sum(1 for m in downloaded_media if m.get('downloaded'))
            logger.info(f"Downloaded {success_count}/{len(media_items)} article images")

        # Build article content
        content, sections = _build_article_content(
            article,
            author_handle,
            author_display,
            timestamp,
            downloaded_media,
            url
        )

        # Save content (web source convention)
        content_filename = f"{folder_name}--web--extracted.txt"
        content_path = clip_folder / content_filename
        content_path.write_text(content, encoding='utf-8')

        # Save raw data
        article_json = {
            "tweet_id": tweet_id,
            "article_id": article.get('id'),
            "author_handle": author_handle,
            "author_display": author_display,
            "title": article.get('title', 'Untitled Article'),
            "timestamp": timestamp,
            "clipped_at": datetime.now().isoformat(),
            "original_url": url,
            "source_api": source_api,
            "is_article": True,
            "api_data": data,
            "likes": data.get('likes') or data.get('favorite_count'),
            "replies": data.get('replies') or data.get('conversation_count'),
            "retweets": data.get('retweets'),
            "views": data.get('views'),
            "bookmarks": data.get('bookmarks'),
        }

        article_json_path = clip_folder / "article.json"
        article_json_path.write_text(
            json.dumps(article_json, indent=2),
            encoding='utf-8'
        )

        title = article.get('title', f"Article by @{author_handle}")

        return TweetClipResult(
            url=url,
            tweet_id=tweet_id,
            author_handle=author_handle,
            author_display=author_display,
            title=title,
            content=content,
            timestamp=timestamp,
            content_path=str(content_path),
            thread_length=1,
            sections=sections,
            media=downloaded_media,
            is_reply=False,
            parent_tweet_id=None,
            nitter_instance=None,
            source_type="web",
            is_article=True
        )

    else:
        # ========== REGULAR TWEET HANDLING (source_type='thread') ==========
        # Auto-detect if this is part of a thread by the same author
        # and fetch the full chain if so

        thread_warning = None  # Track if we detected a potential incomplete thread

        if source_api == 'fxtwitter':
            # Check if this tweet is part of a thread (author replying to themselves)
            replying_to_user = (data.get('replying_to') or '').lower()
            parent_id = data.get('replying_to_status')

            # Fetch full thread chain if author is replying to themselves
            if parent_id and replying_to_user == author_handle.lower():
                logger.info(f"Detected thread - fetching full chain for @{author_handle}")
                thread_tweets = await _fetch_thread_chain(tweet_id, author_handle, timeout)
            else:
                # Single tweet or root of thread - just use what we have
                thread_tweets = [data]

                # Check if this might be part of a thread we can't traverse forward
                # (root tweet that has self-replies we can't see from here)
                reply_count = data.get('replies', 0)
                if reply_count and reply_count > 0 and not parent_id:
                    thread_warning = (
                        f"Tip: If this is part of a thread by the same author, "
                        f"use the last tweet's URL to capture all tweets."
                    )
                    logger.info(thread_warning)
        else:
            # Syndication API doesn't give us reply chain info reliably
            thread_tweets = [data]

        thread_length = len(thread_tweets)
        logger.info(f"Processing thread with {thread_length} tweet(s)")

        # Create output folder (use root tweet ID for folder name if thread)
        root_tweet = thread_tweets[0]
        root_tweet_id = root_tweet.get('id', tweet_id)
        folder_name = f"{author_handle}_{root_tweet_id}"
        clip_folder = output_dir / folder_name
        clip_folder.mkdir(parents=True, exist_ok=True)

        # Extract and download media for all tweets in thread
        all_media_items = []
        media_items_by_tweet = {}
        media_index = 0

        for tweet_data in thread_tweets:
            tid = tweet_data.get('id', '')
            if source_api == 'fxtwitter':
                tweet_media = _extract_media_from_fxtwitter(tweet_data)
            else:
                tweet_media = _extract_media_from_syndication(tweet_data)

            # Assign unique indices for filenames
            for item in tweet_media:
                item['_global_index'] = media_index
                media_index += 1

            all_media_items.extend(tweet_media)
            media_items_by_tweet[tid] = tweet_media

        logger.info(f"Found {len(all_media_items)} total media items across {thread_length} tweets")

        # Download all media
        downloaded_media = []
        if all_media_items:
            logger.info(f"Downloading {len(all_media_items)} media files")
            downloaded_media = await _download_media(all_media_items, clip_folder, timeout=15.0)

            # Update media_items_by_tweet with download info
            for media in downloaded_media:
                global_idx = media.get('_global_index')
                if global_idx is not None:
                    # Find which tweet this belongs to
                    for tid, tweet_media in media_items_by_tweet.items():
                        for tm in tweet_media:
                            if tm.get('_global_index') == global_idx:
                                tm.update(media)

            # Save media metadata
            media_json_path = clip_folder / "media.json"
            media_json_path.write_text(
                json.dumps(downloaded_media, indent=2),
                encoding='utf-8'
            )

            success_count = sum(1 for m in downloaded_media if m.get('downloaded'))
            logger.info(f"Downloaded {success_count}/{len(all_media_items)} media files")

        # Build content using thread formatter
        content, sections = _build_thread_content(
            thread_tweets,
            author_handle,
            author_display,
            media_items_by_tweet,
            url
        )

        # Save content
        content_filename = f"{folder_name}--thread--extracted.txt"
        content_path = clip_folder / content_filename
        content_path.write_text(content, encoding='utf-8')

        # Get timestamp from first tweet
        first_tweet = thread_tweets[0]
        created_at = first_tweet.get('created_at', '')
        timestamp = _format_fxtwitter_timestamp(created_at) if created_at else None

        # Collect all tweet IDs in thread
        thread_tweet_ids = [t.get('id', '') for t in thread_tweets]

        # Save raw data
        tweet_json = {
            "tweet_id": root_tweet_id,
            "author_handle": author_handle,
            "author_display": author_display,
            "timestamp": timestamp,
            "thread_length": thread_length,
            "thread_tweet_ids": thread_tweet_ids,
            "clipped_at": datetime.now().isoformat(),
            "original_url": url,
            "source_api": source_api,
            "api_data": thread_tweets,  # All tweets in thread
            "likes": first_tweet.get('likes') or first_tweet.get('favorite_count'),
            "replies": first_tweet.get('replies') or first_tweet.get('conversation_count'),
            "retweets": first_tweet.get('retweets'),
        }

        tweet_json_path = clip_folder / "thread.json"
        tweet_json_path.write_text(
            json.dumps(tweet_json, indent=2),
            encoding='utf-8'
        )

        if thread_length == 1:
            title = f"Tweet by @{author_handle}"
        else:
            title = f"Thread by @{author_handle} ({thread_length} tweets)"

        return TweetClipResult(
            url=url,
            tweet_id=root_tweet_id,
            author_handle=author_handle,
            author_display=author_display,
            title=title,
            content=content,
            timestamp=timestamp,
            content_path=str(content_path),
            thread_length=thread_length,
            sections=sections,
            media=downloaded_media,
            is_reply=False,
            parent_tweet_id=None,
            nitter_instance=None,
            source_type="thread",
            is_article=False,
            warning=thread_warning,
            thread_tweet_ids=thread_tweet_ids
        )
