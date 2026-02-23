"""
Repo Clipper Service
====================
GitHub repository ingestion with LLM-powered file triage.

Two-stage flow:
1. Triage: Fetch repo metadata + file tree → LLM recommends interesting files
2. Import: Fetch selected file contents → assemble into extracted.txt with sections

Uses GitHub REST API (optional token for higher rate limits).
"""

import os
import re
import json
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from services.chat.service import ChatService

logger = logging.getLogger(__name__)

# GitHub API base
GITHUB_API = "https://api.github.com"

# Files/dirs to exclude from tree listing
NOISE_PATTERNS = {
    # Dependency directories
    "node_modules/", ".git/", "__pycache__/", "venv/", ".venv/",
    "vendor/", "bower_components/", ".tox/", ".nox/", ".mypy_cache/",
    ".pytest_cache/", ".ruff_cache/", "site-packages/",
    # Build output
    "dist/", "build/", "out/", ".next/", ".nuxt/", ".output/",
    "target/", "bin/", "obj/",
    # IDE
    ".idea/", ".vscode/", ".vs/",
    # Lock files and generated
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock",
    "poetry.lock", "Pipfile.lock", "composer.lock", "Gemfile.lock",
    # Binary / media extensions
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp",
    ".mp4", ".mp3", ".wav", ".ogg", ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe",
    ".db", ".sqlite", ".sqlite3",
    # Misc
    ".DS_Store", "Thumbs.db", ".env",
}

# Max size for individual file fetch (100KB)
MAX_FILE_SIZE = 100_000


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class RepoMetadata:
    owner: str
    name: str
    full_name: str
    description: str
    default_branch: str
    stars: int
    language: str
    topics: list[str]
    license: str


@dataclass
class TriageFile:
    path: str
    reason: str
    priority: str  # "high", "medium", "low"
    size_bytes: int = 0


@dataclass
class TriageResult:
    repo: RepoMetadata
    summary: str
    recommended_files: list[TriageFile]
    interest_tags: list[str]
    total_files: int
    readme_content: Optional[str]
    file_tree: list[str]  # filtered paths


@dataclass
class RepoClipResult:
    url: str
    owner: str
    repo_name: str
    title: str
    content: str
    content_path: str
    sections: list[dict]
    files_imported: list[str]
    metadata: dict


# =============================================================================
# GitHub API Functions
# =============================================================================

def _get_token() -> Optional[str]:
    return os.getenv("GITHUB_TOKEN")


def _build_headers(token: Optional[str] = None) -> dict:
    """Build request headers with optional auth token."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = token or _get_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def parse_github_url(url: str) -> tuple[str, str]:
    """
    Extract (owner, repo) from a GitHub URL.

    Handles:
    - https://github.com/owner/repo
    - https://github.com/owner/repo/tree/branch/...
    - https://github.com/owner/repo/blob/branch/...
    - github.com/owner/repo (no scheme)
    """
    url = url.strip().rstrip("/")

    # Remove scheme if present
    url_path = re.sub(r"^https?://", "", url)

    # Must start with github.com
    if not url_path.lower().startswith("github.com/"):
        raise ValueError(f"Not a GitHub URL: {url}")

    # Split path segments: github.com / owner / repo / ...
    parts = url_path.split("/")
    if len(parts) < 3:
        raise ValueError(f"Could not parse owner/repo from: {url}")

    owner = parts[1]
    repo = parts[2]

    # Strip .git suffix if present
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        raise ValueError(f"Could not parse owner/repo from: {url}")

    return owner, repo


async def fetch_repo_metadata(
    owner: str, repo: str, token: Optional[str] = None
) -> RepoMetadata:
    """Fetch repository metadata from GitHub API."""
    headers = _build_headers(token)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

    return RepoMetadata(
        owner=owner,
        name=data["name"],
        full_name=data["full_name"],
        description=data.get("description") or "",
        default_branch=data.get("default_branch", "main"),
        stars=data.get("stargazers_count", 0),
        language=data.get("language") or "Unknown",
        topics=data.get("topics", []),
        license=(data.get("license") or {}).get("spdx_id", ""),
    )


def _is_noise(path: str) -> bool:
    """Check if a path matches noise patterns."""
    path_lower = path.lower()
    for pattern in NOISE_PATTERNS:
        if pattern.endswith("/"):
            # Directory prefix
            if f"/{pattern}" in f"/{path_lower}/" or path_lower.startswith(pattern):
                return True
        else:
            # File suffix or exact name
            if path_lower.endswith(pattern) or path_lower.split("/")[-1] == pattern:
                return True
    return False


async def fetch_file_tree(
    owner: str, repo: str, branch: str, token: Optional[str] = None
) -> list[dict]:
    """
    Fetch recursive file tree, filtering noise.

    Returns list of {path, size, type} for blobs only (no tree entries).
    """
    headers = _build_headers(token)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    tree = data.get("tree", [])

    # Filter to files only, exclude noise
    filtered = []
    for item in tree:
        if item["type"] != "blob":
            continue
        if _is_noise(item["path"]):
            continue
        filtered.append({
            "path": item["path"],
            "size": item.get("size", 0),
        })

    return filtered


async def fetch_readme(
    owner: str, repo: str, token: Optional[str] = None
) -> Optional[str]:
    """Fetch README content as raw text."""
    headers = _build_headers(token)
    headers["Accept"] = "application/vnd.github.raw+json"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/readme",
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise


async def fetch_file_content(
    owner: str, repo: str, path: str, token: Optional[str] = None
) -> Optional[str]:
    """Fetch a single file's raw content."""
    headers = _build_headers(token)
    headers["Accept"] = "application/vnd.github.raw+json"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"File not found: {owner}/{repo}/{path}")
                return None
            raise


# =============================================================================
# LLM Triage
# =============================================================================

TRIAGE_PROMPT = """You are analyzing a GitHub repository to recommend which files are most interesting to read.

## Repository
- **Name:** {full_name}
- **Description:** {description}
- **Language:** {language}
- **Stars:** {stars}
- **Topics:** {topics}

## README (truncated)
{readme}

## File Tree ({total_files} files after filtering)
{file_tree}

{intent_clause}

## Task
Analyze this repository and recommend the most interesting files to read. Focus on:
- Core logic and architecture (entry points, main modules)
- Novel or interesting implementations
- Configuration that reveals design decisions
- Documentation beyond README

Return valid JSON only, no markdown fences:
{{"summary": "2-3 sentence description of what this repo does and why it's interesting", "recommended_files": [{{"path": "exact/path/from/tree", "reason": "why this file is interesting", "priority": "high|medium|low"}}], "interest_tags": ["tag1", "tag2"]}}

Recommend 5-15 files. Prioritize quality over quantity. Only recommend files that appear in the tree above."""


async def triage_repo(
    repo: RepoMetadata,
    file_tree: list[dict],
    readme_content: Optional[str],
    intent: Optional[str] = None,
    model_id: str = "claude-haiku",
) -> TriageResult:
    """Use LLM to analyze repo and recommend interesting files."""
    # Build file tree string (paths only, with sizes for context)
    tree_lines = []
    for f in file_tree:
        size_kb = f["size"] / 1024
        if size_kb >= 1:
            tree_lines.append(f"{f['path']}  ({size_kb:.0f}KB)")
        else:
            tree_lines.append(f["path"])
    tree_str = "\n".join(tree_lines)

    # Truncate README for prompt
    readme_truncated = (readme_content or "No README found.")[:8000]

    intent_clause = ""
    if intent:
        intent_clause = f"## User's Interest\n{intent}\n\nPrioritize files relevant to this interest."

    prompt = TRIAGE_PROMPT.format(
        full_name=repo.full_name,
        description=repo.description or "No description",
        language=repo.language,
        stars=repo.stars,
        topics=", ".join(repo.topics) if repo.topics else "none",
        readme=readme_truncated,
        file_tree=tree_str,
        total_files=len(file_tree),
        intent_clause=intent_clause,
    )

    # Call LLM
    service = ChatService(verbose=False)
    result = await service.chat(
        model_id=model_id,
        messages=[{"role": "user", "content": prompt}],
        system="You are a code analyst. Return only valid JSON.",
        max_tokens=2048,
    )
    logger.info(f"Triage LLM result: success={result.get('success')}, error={result.get('error')}, content_len={len(result.get('content') or '')}")

    # Parse LLM response
    recommended = []
    summary = ""
    interest_tags = []

    if result.get("success") and result.get("content"):
        try:
            # Strip markdown fences if present
            content = result["content"].strip()
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            parsed = json.loads(content)
            summary = parsed.get("summary", "")
            interest_tags = parsed.get("interest_tags", [])

            # Build size lookup for enrichment
            size_lookup = {f["path"]: f["size"] for f in file_tree}
            tree_paths = set(size_lookup.keys())

            raw_recs = parsed.get("recommended_files", [])
            for rec in raw_recs:
                path = rec.get("path", "").strip()

                # Normalize: strip leading ./ or /
                path = re.sub(r"^\.?/", "", path)

                # Try exact match first, then case-insensitive
                if path in tree_paths:
                    recommended.append(TriageFile(
                        path=path,
                        reason=rec.get("reason", ""),
                        priority=rec.get("priority", "medium"),
                        size_bytes=size_lookup.get(path, 0),
                    ))
                else:
                    # Case-insensitive fallback
                    path_lower = path.lower()
                    for tp in tree_paths:
                        if tp.lower() == path_lower:
                            recommended.append(TriageFile(
                                path=tp,
                                reason=rec.get("reason", ""),
                                priority=rec.get("priority", "medium"),
                                size_bytes=size_lookup.get(tp, 0),
                            ))
                            break
                    else:
                        logger.warning(
                            f"Triage recommended '{path}' but not in tree"
                        )

            if not recommended and raw_recs:
                logger.warning(
                    f"LLM recommended {len(raw_recs)} files but none matched tree. "
                    f"First 3 LLM paths: {[r.get('path') for r in raw_recs[:3]]}. "
                    f"Sample tree paths: {list(tree_paths)[:5]}"
                )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse triage LLM response: {e}")
            logger.debug(f"Raw LLM content: {result.get('content', '')[:500]}")
    else:
        logger.warning(
            f"Triage LLM call failed: success={result.get('success')}, "
            f"error={result.get('error')}"
        )

    # Fallback: if LLM gave nothing, pick common entry points
    if not recommended:
        summary = repo.description or f"Repository: {repo.full_name}"
        common_entries = [
            "README.md", "main.py", "app.py", "index.ts", "index.js",
            "src/main.py", "src/index.ts", "src/app.py", "src/main.rs",
            "lib/index.ts", "cmd/main.go", "Makefile", "setup.py",
            "pyproject.toml", "package.json",
        ]
        tree_paths = {f["path"] for f in file_tree}
        size_lookup = {f["path"]: f["size"] for f in file_tree}
        for entry in common_entries:
            if entry in tree_paths:
                recommended.append(TriageFile(
                    path=entry,
                    reason="Common entry point",
                    priority="medium",
                    size_bytes=size_lookup.get(entry, 0),
                ))

    return TriageResult(
        repo=repo,
        summary=summary,
        recommended_files=recommended,
        interest_tags=interest_tags,
        total_files=len(file_tree),
        readme_content=readme_content,
        file_tree=[f["path"] for f in file_tree],
    )


# =============================================================================
# Content Assembly
# =============================================================================

def _detect_language(path: str) -> str:
    """Detect code fence language from file extension."""
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "tsx", ".jsx": "jsx", ".rs": "rust", ".go": "go",
        ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c",
        ".rb": "ruby", ".php": "php", ".swift": "swift",
        ".kt": "kotlin", ".scala": "scala", ".sh": "bash",
        ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
        ".json": "json", ".xml": "xml", ".html": "html",
        ".css": "css", ".scss": "scss", ".sql": "sql",
        ".md": "markdown", ".txt": "", ".cfg": "", ".ini": "ini",
    }
    ext = Path(path).suffix.lower()
    return ext_map.get(ext, "")


def _clean_readme_for_reader(readme: str) -> str:
    """
    Clean README markdown for better rendering in the Scholia Reader.

    The Reader handles: **bold**, *italic*, `code`, ```code blocks```,
    > blockquotes, but NOT headings (##), images, or links.

    Strategy: convert markdown headings to bold labels, strip HTML/images,
    convert links to text with URL.
    """
    lines = readme.split("\n")
    cleaned = []

    for line in lines:
        # Strip HTML img tags (screenshots, badges)
        if re.match(r'\s*<img\s', line, re.IGNORECASE):
            continue

        # Strip markdown badge images: [![alt](img)](link)
        if re.match(r'\s*\[!\[', line):
            continue

        # Strip standalone image lines: ![alt](url)
        if re.match(r'\s*!\[.*\]\(.*\)\s*$', line):
            continue

        # Convert markdown headings to bold labels
        # ## Heading → **Heading**
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            text = heading_match.group(2).strip()
            cleaned.append(f"**{text}**")
            continue

        # Convert markdown links to readable format: [text](url) → **text** (url)
        line = re.sub(
            r'\[([^\]]+)\]\((https?://[^)]+)\)',
            r'**\1** (\2)',
            line,
        )

        # Strip HTML tags (but keep text content)
        line = re.sub(r'</?(?:div|span|p|br|hr|details|summary)[^>]*>', '', line)

        cleaned.append(line)

    return "\n".join(cleaned)


async def import_repo_files(
    owner: str,
    repo: str,
    branch: str,
    file_paths: list[str],
    readme_content: Optional[str],
    repo_metadata: RepoMetadata,
    output_dir: Path,
    token: Optional[str] = None,
) -> RepoClipResult:
    """
    Fetch selected files and assemble into extracted.txt with sections.

    Section format matches Scholia conventions:
    - [SECTION] markers with # for level 1, ## for level 2
    - Offsets calculated for each section
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Fetch all files concurrently (limit concurrency to 10)
    semaphore = asyncio.Semaphore(10)

    async def _fetch_one(path: str) -> tuple[str, Optional[str]]:
        async with semaphore:
            content = await fetch_file_content(owner, repo, path, token)
            return path, content

    tasks = [_fetch_one(p) for p in file_paths]
    results = await asyncio.gather(*tasks)

    # Build content with sections
    parts = []
    sections = []
    files_imported = []

    # Title
    title_line = f"[TITLE] {owner}/{repo}\n\n"
    parts.append(title_line)
    offset = len(title_line)

    # Section 1: Repository Info (level 1)
    info_header = "[SECTION] # Repository Info\n"
    info_body_lines = [
        f"**Repository:** {repo_metadata.full_name}  |  **Stars:** {repo_metadata.stars}  |  **Language:** {repo_metadata.language}",
    ]
    if repo_metadata.description:
        info_body_lines.append("")
        info_body_lines.append(f"> {repo_metadata.description}")
    if repo_metadata.topics:
        info_body_lines.append("")
        info_body_lines.append(f"**Topics:** {', '.join(repo_metadata.topics)}")
    if repo_metadata.license:
        info_body_lines.append(f"**License:** {repo_metadata.license}")
    info_body_lines.append("")
    info_body_lines.append(f"**Branch:** `{branch}`  |  **Files imported:** {len(file_paths)}")

    info_body = "\n".join(info_body_lines) + "\n\n"
    info_text = info_header + info_body

    section_start = offset
    parts.append(info_text)
    offset += len(info_text)

    sections.append({
        "title": "Repository Info",
        "level": 1,
        "start_offset": section_start,
        "end_offset": offset,
    })

    # Section 2: README (level 1)
    if readme_content:
        readme_header = "[SECTION] # README\n"
        cleaned_readme = _clean_readme_for_reader(readme_content)
        readme_body = cleaned_readme.rstrip() + "\n\n"
        readme_text = readme_header + readme_body

        section_start = offset
        parts.append(readme_text)
        offset += len(readme_text)

        sections.append({
            "title": "README",
            "level": 1,
            "start_offset": section_start,
            "end_offset": offset,
        })

    # File sections (level 2)
    for path, content in results:
        if content is None:
            continue

        # Truncate very large files
        if len(content) > MAX_FILE_SIZE:
            content = content[:MAX_FILE_SIZE] + f"\n\n... [truncated at {MAX_FILE_SIZE // 1000}KB]"

        lang = _detect_language(path)
        lang_label = lang.upper() if lang else "TEXT"
        fence = f"```{lang}" if lang else "```"
        size_kb = len(content) / 1024

        # File header with metadata line before code fence
        file_header = f"[SECTION] ## {path}\n"
        meta_line = f"`{lang_label}` | {size_kb:.1f} KB\n\n"
        file_body = f"{fence}\n{content.rstrip()}\n```\n\n"
        file_text = file_header + meta_line + file_body

        section_start = offset
        parts.append(file_text)
        offset += len(file_text)

        sections.append({
            "title": path,
            "level": 2,
            "start_offset": section_start,
            "end_offset": offset,
        })

        files_imported.append(path)

    # Write extracted.txt
    full_content = "".join(parts)
    content_filename = f"{owner}_{repo}--repo--extracted.txt"
    content_path = output_dir / content_filename
    content_path.write_text(full_content, encoding="utf-8")

    # Write repo.json metadata
    meta = {
        "owner": owner,
        "repo_name": repo,
        "full_name": repo_metadata.full_name,
        "default_branch": branch,
        "stars": repo_metadata.stars,
        "language": repo_metadata.language,
        "topics": repo_metadata.topics,
        "license": repo_metadata.license,
        "description": repo_metadata.description,
        "files_imported": files_imported,
    }
    meta_path = output_dir / "repo.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    url = f"https://github.com/{owner}/{repo}"

    return RepoClipResult(
        url=url,
        owner=owner,
        repo_name=repo,
        title=f"{owner}/{repo}",
        content=full_content,
        content_path=str(content_path),
        sections=sections,
        files_imported=files_imported,
        metadata=meta,
    )


# =============================================================================
# Append Files
# =============================================================================

async def append_files_to_repo(
    source_id: str,
    owner: str,
    repo: str,
    branch: str,
    new_paths: list[str],
    existing_content_path: str,
    existing_sections: list[dict],
    token: Optional[str] = None,
) -> tuple[str, list[dict]]:
    """
    Append new files to an existing repo source.

    Returns (updated_content, new_sections) where new_sections have
    correct offsets calculated from the append point.
    """
    # Read existing content
    content_path = Path(existing_content_path)
    existing_content = content_path.read_text(encoding="utf-8")
    offset = len(existing_content)

    # Calculate next order_index from existing sections
    max_order = max((s.get("order_index", 0) for s in existing_sections), default=-1)

    # Fetch new files concurrently
    semaphore = asyncio.Semaphore(10)

    async def _fetch_one(path: str) -> tuple[str, Optional[str]]:
        async with semaphore:
            content = await fetch_file_content(owner, repo, path, token)
            return path, content

    tasks = [_fetch_one(p) for p in new_paths]
    results = await asyncio.gather(*tasks)

    # Assemble new sections
    new_parts = []
    new_sections = []

    for i, (path, content) in enumerate(results):
        if content is None:
            continue

        if len(content) > MAX_FILE_SIZE:
            content = content[:MAX_FILE_SIZE] + f"\n\n... [truncated at {MAX_FILE_SIZE // 1000}KB]"

        lang = _detect_language(path)
        lang_label = lang.upper() if lang else "TEXT"
        fence = f"```{lang}" if lang else "```"
        size_kb = len(content) / 1024

        file_header = f"[SECTION] ## {path}\n"
        meta_line = f"`{lang_label}` | {size_kb:.1f} KB\n\n"
        file_body = f"{fence}\n{content.rstrip()}\n```\n\n"
        file_text = file_header + meta_line + file_body

        section_start = offset
        new_parts.append(file_text)
        offset += len(file_text)

        new_sections.append({
            "title": path,
            "level": 2,
            "start_offset": section_start,
            "end_offset": offset,
            "order_index": max_order + 1 + i,
        })

    # Append to content and write
    updated_content = existing_content + "".join(new_parts)
    content_path.write_text(updated_content, encoding="utf-8")

    return updated_content, new_sections
