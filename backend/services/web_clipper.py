"""
Web Clipper Service
===================
Extracts readable content from web pages with rich formatting preserved.

Uses:
- trafilatura: Main content extraction (ignoring nav, ads, footers) + metadata
- markdownify: HTML → Markdown conversion (preserves bold, italic, code, lists)
- BeautifulSoup: HTML parsing and image extraction
- httpx: Async image downloading

Output format matches dots-ocr PDFs:
- [TITLE] for document title
- [SECTION] ## Heading for sections
- [FIGURE figure_1.jpg] for images (with local filename)
- [CAPTION] for image captions
- **bold**, *italic*, `code` inline formatting
- Bullet lists, numbered lists, blockquotes

Images are downloaded to a 'figures/' subfolder in the source directory.
"""

import httpx
import trafilatura
from trafilatura.settings import use_config
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass, field
import re
import hashlib
import json
import asyncio
from urllib.parse import urlparse, urljoin
from unidecode import unidecode
from bs4 import BeautifulSoup, NavigableString
from markdownify import markdownify as md, MarkdownConverter, chomp
import logging

logger = logging.getLogger(__name__)


@dataclass
class WebClipResult:
    """Result of web clipping operation."""
    url: str
    title: str
    author: Optional[str]
    date: Optional[str]
    content: str
    description: Optional[str]
    sitename: Optional[str]
    content_path: str
    word_count: int
    sections: List[dict]  # Parsed sections with offsets
    figures: List[dict] = field(default_factory=list)  # Downloaded figure metadata


def _sanitize_for_filename(text: str, max_length: int = 50) -> str:
    """
    Sanitize a string for use in a filename.
    Converts to ASCII, removes special chars, replaces spaces with underscores.
    """
    if not text:
        return "untitled"

    # Convert to ASCII
    text = unidecode(text)

    # Remove special characters, keep alphanumeric and spaces
    text = re.sub(r'[^\w\s-]', '', text)

    # Replace whitespace with underscores
    text = re.sub(r'\s+', '_', text.strip())

    # Truncate
    if len(text) > max_length:
        text = text[:max_length].rstrip('_')

    return text or "untitled"


def _extract_domain(url: str) -> str:
    """Extract the domain name from a URL."""
    parsed = urlparse(url)
    domain = parsed.netloc
    # Remove www. prefix if present
    if domain.startswith('www.'):
        domain = domain[4:]
    # Remove common suffixes for cleaner names
    domain = re.sub(r'\.(com|org|net|io|pub|ai)$', '', domain)
    return domain.replace('.', '-')


def _texts_similar(text1: str, text2: str) -> bool:
    """Check if two texts are similar (for title deduplication)."""
    t1 = re.sub(r'[^\w\s]', '', text1.lower()).strip()
    t2 = re.sub(r'[^\w\s]', '', text2.lower()).strip()
    return t1 in t2 or t2 in t1 or t1 == t2


def _extract_nextjs_content(html: str) -> Optional[Tuple[str, dict]]:
    """
    Extract article content from Next.js __NEXT_DATA__ JSON if present.

    Many modern sites (Vercel, tech blogs, Stripe) embed page content in
    <script id="__NEXT_DATA__"> as a JSON blob rather than in static HTML.
    The clipper's BeautifulSoup pipeline strips <script> tags, losing this content.

    Returns:
        Tuple of (content_string, metadata_dict) or None if not a Next.js page
        or no content found in the JSON.
    """
    soup = BeautifulSoup(html, 'html.parser')
    next_data_tag = soup.find('script', id='__NEXT_DATA__')
    if not next_data_tag or not next_data_tag.string:
        return None

    try:
        data = json.loads(next_data_tag.string)
    except (json.JSONDecodeError, TypeError):
        return None

    page_props = data.get('props', {}).get('pageProps', {})
    if not page_props:
        return None

    # Walk common Next.js blog content locations
    content = None
    metadata = {}

    for container_key in ['postData', 'post', 'article', 'data', 'entry', 'page']:
        container = page_props.get(container_key)
        if not isinstance(container, dict):
            continue
        for content_key in ['content', 'body', 'html', 'markdown', 'text', 'rawContent']:
            candidate = container.get(content_key)
            if isinstance(candidate, str) and len(candidate) > 200:
                content = candidate
                # Extract metadata from the same container
                metadata['title'] = container.get('title')
                metadata['date'] = container.get('date') or container.get('publishedAt')
                metadata['description'] = (
                    container.get('summary') or container.get('description')
                    or container.get('excerpt')
                )
                # Author may be string, list of strings, or list of dicts
                authors = container.get('authors') or container.get('author')
                if isinstance(authors, list):
                    metadata['author'] = ', '.join(
                        a if isinstance(a, str)
                        else a.get('name', a.get('slug', ''))
                        for a in authors
                    )
                elif isinstance(authors, str):
                    metadata['author'] = authors
                elif isinstance(authors, dict):
                    metadata['author'] = authors.get('name', '')
                break
        if content:
            break

    # Also try content directly on pageProps
    if not content:
        for content_key in ['content', 'body', 'markdown']:
            candidate = page_props.get(content_key)
            if isinstance(candidate, str) and len(candidate) > 200:
                content = candidate
                break

    if not content:
        return None

    logger.info(f"Extracted {len(content)} chars from Next.js __NEXT_DATA__")
    return content, metadata


def _markdown_to_scholia_format(text: str) -> str:
    """
    Convert standard markdown headings to Scholia [SECTION] markers.
    Other markdown formatting (bold, italic, code, links, lists) passes through
    unchanged since Scholia content is already markdown-based.
    """
    lines = text.split('\n')
    result = []
    for line in lines:
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            hashes = heading_match.group(1)
            heading_text = heading_match.group(2).strip()
            result.append(f'\n[SECTION] {hashes} {heading_text}\n')
        else:
            result.append(line)
    return '\n'.join(result)


class ScholiaMarkdownConverter(MarkdownConverter):
    """
    Custom markdown converter that produces Scholia-formatted output.

    - Converts headings to [SECTION] markers
    - Converts images to [FIGURE] markers
    - Preserves inline formatting (bold, italic, code)
    """

    def __init__(self, base_url: str = '', **kwargs):
        super().__init__(**kwargs)
        self.base_url = base_url
        self.figure_count = 0
        self.figures = []  # Track figures for potential download

    def convert_hn(self, n: int, el, text: str, **kwargs) -> str:
        """Convert h1-h6 to [SECTION] markers."""
        text = text.strip()
        if not text:
            return ''

        # Strip inline markdown formatting from headings - they're already emphasized
        # **bold** → bold, *italic* → italic, `code` → code, [text](url) → text
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # bold
        text = re.sub(r'\*([^*]+)\*', r'\1', text)    # italic
        text = re.sub(r'`([^`]+)`', r'\1', text)      # code
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # links

        # Use # symbols to indicate level (like markdown headings)
        hashes = '#' * n
        return f'\n\n[SECTION] {hashes} {text}\n\n'

    def convert_h1(self, el, text, **kwargs):
        return self.convert_hn(1, el, text, **kwargs)

    def convert_h2(self, el, text, **kwargs):
        return self.convert_hn(2, el, text, **kwargs)

    def convert_h3(self, el, text, **kwargs):
        return self.convert_hn(3, el, text, **kwargs)

    def convert_h4(self, el, text, **kwargs):
        return self.convert_hn(4, el, text, **kwargs)

    def convert_h5(self, el, text, **kwargs):
        return self.convert_hn(5, el, text, **kwargs)

    def convert_h6(self, el, text, **kwargs):
        return self.convert_hn(6, el, text, **kwargs)

    def convert_img(self, el, text, **kwargs):
        """Convert images to [FIGURE] markers with filename reference."""
        src = el.get('src', '')
        alt = el.get('alt', '')

        if not src:
            return ''

        # Skip tiny images (likely icons, spacers, tracking pixels)
        width = el.get('width', '')
        height = el.get('height', '')
        if width and height:
            try:
                if int(width) < 50 or int(height) < 50:
                    return ''
            except ValueError:
                pass

        # Skip data: URLs that are tiny (base64 tracking pixels)
        if src.startswith('data:') and len(src) < 500:
            return ''

        # Make URL absolute
        if src.startswith('//'):
            src = 'https:' + src
        elif not src.startswith(('http://', 'https://', 'data:')):
            # Ensure base_url ends with / for proper urljoin behavior
            # Without trailing /, urljoin treats the last path segment as a file
            # e.g., urljoin('https://arxiv.org/html/123', 'x.png') → 'https://arxiv.org/html/x.png' (wrong)
            # vs urljoin('https://arxiv.org/html/123/', 'x.png') → 'https://arxiv.org/html/123/x.png' (correct)
            base = self.base_url
            if base and not base.endswith('/'):
                base = base + '/'
            src = urljoin(base, src)

        self.figure_count += 1

        # Determine file extension from URL or content type
        ext = self._guess_extension(src)
        filename = f"figure_{self.figure_count}{ext}"

        self.figures.append({
            'index': self.figure_count,
            'src': src,
            'alt': alt,
            'filename': filename
        })

        # Output figure marker with filename reference
        result = f'\n\n[FIGURE {filename}]\n'
        if alt:
            result += f'[CAPTION] {alt}\n'

        return result

    def convert_a(self, el, text, parent_tags):
        """Convert links with proper URL resolution.

        - Absolute URLs (http/https/mailto): pass through as-is
        - Anchor-only links (#ref): resolve to full URL on the source page
        - Relative links (/path, ../path): resolve against base_url
        """
        if '_noformat' in parent_tags:
            return text

        prefix, suffix, text = chomp(text)
        if not text:
            return ''

        href = el.get('href')
        if not href:
            return text

        # Resolve the URL
        if href.startswith(('http://', 'https://', 'mailto:')):
            # Already absolute — keep as-is
            resolved = href
        elif href.startswith('#'):
            # Anchor link — point back to original page's anchor
            resolved = self.base_url + href if self.base_url else href
        else:
            # Relative URL — resolve against base
            base = self.base_url
            if base and not base.endswith('/'):
                base = base + '/'
            resolved = urljoin(base, href) if base else href

        title = el.get('title')
        title_part = ' "%s"' % title.replace('"', r'\"') if title else ''
        return '%s[%s](%s%s)%s' % (prefix, text, resolved, title_part, suffix)

    def _guess_extension(self, url: str) -> str:
        """Guess image extension from URL."""
        if url.startswith('data:'):
            # data:image/png;base64,... or data:image/jpeg;base64,...
            if 'png' in url[:30]:
                return '.png'
            elif 'gif' in url[:30]:
                return '.gif'
            elif 'webp' in url[:30]:
                return '.webp'
            elif 'svg' in url[:30]:
                return '.svg'
            return '.jpg'

        # Check URL path
        parsed = urlparse(url)
        path = parsed.path.lower()
        for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg']:
            if path.endswith(ext):
                return ext if ext != '.jpeg' else '.jpg'

        return '.jpg'  # Default

    def convert_figure(self, el, text, **kwargs):
        """Handle <figure> elements which may contain img + figcaption."""
        # The img inside will be processed separately
        # Look for figcaption
        figcaption = el.find('figcaption')
        caption_text = ''
        if figcaption:
            caption_text = figcaption.get_text(strip=True)

        # Process children (will include img conversion)
        result = text

        # If there's a caption and it wasn't already added via img alt
        if caption_text and f'[CAPTION] {caption_text}' not in result:
            result = result.rstrip() + f'\n[CAPTION] {caption_text}\n'

        return result

    def convert_pre(self, el, text, **kwargs):
        """Convert <pre> blocks to fenced code blocks."""
        code = el.find('code')
        if code:
            # Try to detect language from class
            classes = code.get('class', [])
            lang = ''
            for cls in classes:
                if cls.startswith('language-'):
                    lang = cls.replace('language-', '')
                    break
                elif cls.startswith('lang-'):
                    lang = cls.replace('lang-', '')
                    break

            code_text = code.get_text()
        else:
            lang = ''
            code_text = el.get_text()

        return f'\n\n```{lang}\n{code_text.strip()}\n```\n\n'

    def convert_code(self, el, text, **kwargs):
        """Convert inline <code> to backticks."""
        # Check if inside a <pre> - if so, let convert_pre handle it
        if el.parent and el.parent.name == 'pre':
            return text
        return f'`{text}`'

    def convert_blockquote(self, el, text, **kwargs):
        """Convert blockquotes with > prefix."""
        lines = text.strip().split('\n')
        quoted = '\n'.join(f'> {line}' for line in lines)
        return f'\n\n{quoted}\n\n'

    def convert_table(self, el, text, **kwargs):
        """Preserve tables as HTML for proper rendering."""
        # Get the original HTML of the table
        table_html = str(el)
        return f'\n\n[TABLE]\n{table_html}\n\n'


async def _download_figures(
    figures: List[dict],
    output_dir: Path,
    timeout: float = 15.0
) -> List[dict]:
    """
    Download all figures to the output directory.

    Args:
        figures: List of figure dicts with 'src', 'filename', 'alt', 'index'
        output_dir: Directory to save figures (will create 'figures/' subfolder)
        timeout: Timeout per image download

    Returns:
        Updated figures list with 'downloaded' and 'local_path' fields
    """
    if not figures:
        return []

    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    async def download_one(fig: dict) -> dict:
        """Download a single figure."""
        src = fig['src']
        filename = fig['filename']
        local_path = figures_dir / filename

        try:
            if src.startswith('data:'):
                # Handle base64 data URLs
                import base64
                # data:image/png;base64,iVBORw0KGgo...
                header, data = src.split(',', 1)
                image_data = base64.b64decode(data)
                local_path.write_bytes(image_data)
                fig['downloaded'] = True
                fig['local_path'] = str(local_path)
                logger.debug(f"Saved base64 figure: {filename}")
            else:
                # Download from URL
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    response = await client.get(src, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    response.raise_for_status()

                    # Check content type - but be lenient since some servers misconfigure
                    content_type = response.headers.get('content-type', '').lower()
                    is_image_content = content_type.startswith('image/')
                    is_octet_stream = 'octet-stream' in content_type

                    # If content-type isn't image/, check if URL has image extension
                    url_looks_like_image = any(
                        src.lower().endswith(ext)
                        for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg']
                    )

                    if not is_image_content and not (is_octet_stream and url_looks_like_image):
                        logger.warning(f"Skipping non-image: {src} ({content_type})")
                        fig['downloaded'] = False
                        fig['error'] = f"Not an image: {content_type}"
                        return fig

                    # Check size (skip if too small - likely tracking pixel)
                    if len(response.content) < 1000:
                        logger.debug(f"Skipping tiny image: {src} ({len(response.content)} bytes)")
                        fig['downloaded'] = False
                        fig['error'] = "Image too small"
                        return fig

                    local_path.write_bytes(response.content)
                    fig['downloaded'] = True
                    fig['local_path'] = str(local_path)
                    fig['size'] = len(response.content)
                    logger.debug(f"Downloaded figure: {filename} ({len(response.content)} bytes)")

        except Exception as e:
            logger.warning(f"Failed to download {src}: {e}")
            fig['downloaded'] = False
            fig['error'] = str(e)

        return fig

    # Download all figures concurrently (with limit)
    tasks = [download_one(fig) for fig in figures]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out exceptions and failed downloads
    downloaded = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            figures[i]['downloaded'] = False
            figures[i]['error'] = str(result)
            downloaded.append(figures[i])
        else:
            downloaded.append(result)

    return downloaded


def _html_to_scholia_markdown(html: str, base_url: str = '') -> Tuple[str, List[dict]]:
    """
    Convert HTML to Scholia-formatted markdown.

    Returns:
        Tuple of (markdown_content, figures_list)
    """
    converter = ScholiaMarkdownConverter(
        base_url=base_url,
        heading_style='ATX',
        bullets='-',
        strong_em_symbol='*',
        strip=['script', 'style', 'nav', 'footer', 'aside', 'form'],
    )

    # Parse HTML
    soup = BeautifulSoup(html, 'html.parser')

    # Remove unwanted elements
    for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'aside',
                              'form', 'iframe', 'noscript']):
        tag.decompose()

    # Convert to markdown
    markdown = converter.convert_soup(soup)

    # Clean up excessive whitespace
    markdown = re.sub(r'\n{4,}', '\n\n\n', markdown)
    markdown = markdown.strip()

    return markdown, converter.figures


def _build_structured_content(
    markdown: str,
    title: str,
    metadata: dict
) -> Tuple[str, List[dict]]:
    """
    Build final structured content with title, metadata section, and body.

    Returns:
        Tuple of (final_content, sections_list)
    """
    lines = []
    sections = []
    current_offset = 0

    # Add title
    title_line = f"[TITLE] {title}"
    lines.append(title_line)
    lines.append("")
    current_offset = len(title_line) + 2

    # Add metadata section
    meta_parts = []
    if metadata.get('author'):
        meta_parts.append(f"**Author:** {metadata['author']}")
    if metadata.get('date'):
        meta_parts.append(f"**Date:** {metadata['date']}")
    if metadata.get('sitename'):
        meta_parts.append(f"**Source:** {metadata['sitename']}")
    if metadata.get('url'):
        meta_parts.append(f"**URL:** {metadata['url']}")

    if meta_parts:
        section_marker = "[SECTION] # Source Info"
        lines.append(section_marker)
        section_start = current_offset
        current_offset += len(section_marker) + 1

        for part in meta_parts:
            lines.append(part)
            current_offset += len(part) + 1
        lines.append("")
        current_offset += 1

        sections.append({
            "title": "Source Info",
            "level": 1,
            "start_offset": section_start,
            "end_offset": current_offset
        })

    # Check if content has a title-like first section that duplicates our title
    first_section_match = re.match(r'\[SECTION\]\s*#\s*(.+?)(?:\n|$)', markdown)
    if first_section_match:
        first_heading = first_section_match.group(1).strip()
        if _texts_similar(first_heading, title):
            # Remove the duplicate title heading
            markdown = markdown[first_section_match.end():].lstrip()

    # Parse sections from the markdown content
    section_pattern = r'\[SECTION\]\s*(#{1,6})\s*(.+?)(?=\n|$)'

    # If no sections in content, wrap everything in an "Article" section
    if not re.search(section_pattern, markdown):
        lines.append("")
        current_offset += 1

        article_marker = "[SECTION] # Article"
        lines.append(article_marker)
        article_start = current_offset
        current_offset += len(article_marker) + 1

        lines.append("")
        current_offset += 1

        sections.append({
            "title": "Article",
            "level": 1,
            "start_offset": article_start,
            "end_offset": article_start  # Will be updated
        })

    # Add the main content
    lines.append(markdown)
    current_offset += len(markdown)

    # Now parse all sections from the final content
    final_content = '\n'.join(lines)

    # Re-parse sections with correct offsets
    sections = []
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

    # If still no sections, create a fallback
    if not sections:
        sections.append({
            "title": "Article",
            "level": 1,
            "start_offset": 0,
            "end_offset": len(final_content)
        })

    return final_content, sections


async def clip_url(
    url: str,
    output_dir: Path,
    timeout: float = 30.0
) -> WebClipResult:
    """
    Clip content from a URL and save to the output directory.

    Preserves rich formatting:
    - **bold** and *italic* text
    - `code` blocks and inline code
    - Lists (bullet and numbered)
    - Blockquotes
    - Tables (as HTML)
    - Images as [FIGURE] markers

    Args:
        url: The URL to clip
        output_dir: Directory to save the extracted content
        timeout: Request timeout in seconds

    Returns:
        WebClipResult with metadata and content path

    Raises:
        httpx.HTTPError: If the URL cannot be fetched
        ValueError: If no content could be extracted
    """
    # Fetch the page
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

    # Extract metadata with trafilatura (it's good at this)
    metadata = trafilatura.extract_metadata(html)

    title = metadata.title if metadata else None
    author = metadata.author if metadata else None
    date = metadata.date if metadata else None
    description = metadata.description if metadata else None
    sitename = metadata.sitename if metadata else None

    # Fallbacks for title
    if not title:
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
            # Clean common suffixes like " | Site Name" or " - Site Name"
            title = re.sub(r'\s*[\|\-–—]\s*[^|\-–—]+$', '', title)
        else:
            title = _extract_domain(url)

    # ── Try Next.js __NEXT_DATA__ extraction first ──
    # Many modern sites (Vercel, tech blogs, Stripe) embed content in JSON
    # inside <script id="__NEXT_DATA__"> rather than in static HTML.
    nextjs_result = _extract_nextjs_content(html)
    if nextjs_result:
        raw_content, nextjs_meta = nextjs_result
        # Next.js JSON metadata is more authoritative than trafilatura's heuristics
        if nextjs_meta.get('author'):
            author = nextjs_meta['author']
        if nextjs_meta.get('date'):
            date = nextjs_meta['date']
        if nextjs_meta.get('description'):
            description = nextjs_meta['description']
        if nextjs_meta.get('title'):
            title = nextjs_meta['title']

        # Detect content format: HTML vs markdown/plaintext
        if re.search(r'<(?:p|h[1-6]|div|section|article|ul|ol|table)\b', raw_content):
            # HTML content — run through the normal conversion pipeline
            markdown, figures = _html_to_scholia_markdown(raw_content, base_url=url)
        else:
            # Markdown/plaintext — convert headings to [SECTION] markers
            markdown = _markdown_to_scholia_format(raw_content)
            figures = []

    if not nextjs_result or not markdown.strip():
        # ── Standard BeautifulSoup extraction ──
        # Extract main content using BeautifulSoup
        # trafilatura's HTML output strips headings, so we extract directly
        soup = BeautifulSoup(html, 'html.parser')

        # Remove boilerplate elements
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'aside',
                                  'header', 'form', 'iframe', 'noscript',
                                  'svg', 'button', 'input']):
            tag.decompose()

        # Try to find the main content area
        # Priority: article > main > [role=main] > .article > .content > .post > body
        main_content = None
        for selector in ['article', 'main', '[role="main"]', '.article-content',
                         '.post-content', '.entry-content', '.article', '.content',
                         '.post', '#content', '#main']:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if not main_content:
            # Fallback: use body
            main_content = soup.find('body')
            if not main_content:
                raise ValueError(f"Could not extract content from {url}")

        # Additional cleanup on main content
        for tag in main_content.find_all(['nav', 'footer', 'aside', 'form', 'button']):
            tag.decompose()

        # Remove common non-content classes
        for cls in ['sidebar', 'comments', 'related', 'share', 'social', 'newsletter']:
            for tag in main_content.find_all(class_=lambda x: x and cls in x.lower()):
                tag.decompose()

        extracted_html = str(main_content)

        # Convert HTML to Scholia markdown format
        markdown, figures = _html_to_scholia_markdown(extracted_html, base_url=url)

        if not markdown.strip():
            raise ValueError(f"No content extracted from {url}")

    # Build metadata dict
    meta_dict = {
        'author': author,
        'date': date,
        'sitename': sitename,
        'url': url
    }

    # Build final structured content
    formatted_content, sections = _build_structured_content(
        markdown,
        title,
        meta_dict
    )

    # Build folder and file names
    domain = _extract_domain(url)
    sanitized_title = _sanitize_for_filename(title, max_length=40)

    # Create a short hash for uniqueness
    url_hash = hashlib.md5(url.encode()).hexdigest()[:6]

    # Folder name: Domain_Title_Hash
    folder_name = f"{_sanitize_for_filename(domain, 20)}_{sanitized_title}_{url_hash}"

    # Create the output folder
    clip_folder = output_dir / folder_name
    clip_folder.mkdir(parents=True, exist_ok=True)

    # Download figures
    downloaded_figures = []
    if figures:
        logger.info(f"Downloading {len(figures)} figures for {title}")
        downloaded_figures = await _download_figures(figures, clip_folder)

        # Save figures metadata to JSON
        figures_json_path = clip_folder / "figures.json"
        figures_json_path.write_text(
            json.dumps(downloaded_figures, indent=2),
            encoding='utf-8'
        )

        # Count successful downloads
        success_count = sum(1 for f in downloaded_figures if f.get('downloaded'))
        logger.info(f"Downloaded {success_count}/{len(figures)} figures")

    # Save the content
    content_filename = f"{folder_name}--web--extracted.txt"
    content_path = clip_folder / content_filename
    content_path.write_text(formatted_content, encoding='utf-8')

    # Count words
    word_count = len(re.findall(r'\b\w+\b', formatted_content))

    return WebClipResult(
        url=url,
        title=title,
        author=author,
        date=date,
        content=formatted_content,
        description=description,
        sitename=sitename,
        content_path=str(content_path),
        word_count=word_count,
        sections=sections,
        figures=downloaded_figures
    )


def parse_sections_from_web_content(content: str, source_id: str) -> list:
    """
    Parse [SECTION] markers from web content to build section list.
    This is a fallback for when sections aren't provided by clip_url.
    """
    sections = []

    # Find all section markers
    pattern = r"\[SECTION\]\s*(#{1,6})\s*(.+?)(?=\n|$)"

    for match in re.finditer(pattern, content):
        level = len(match.group(1))
        section_title = match.group(2).strip()
        start_offset = match.start()

        sections.append({
            "title": section_title,
            "level": level,
            "start_offset": start_offset,
            "end_offset": start_offset  # Will be updated
        })

    # Calculate end offsets
    for i, section in enumerate(sections):
        if i + 1 < len(sections):
            section["end_offset"] = sections[i + 1]["start_offset"]
        else:
            section["end_offset"] = len(content)

    # If no sections found, create a single "Full Article" section
    if not sections:
        sections.append({
            "title": "Full Article",
            "level": 1,
            "start_offset": 0,
            "end_offset": len(content)
        })

    return sections
