"""
Metadata Lookup Router
======================
API endpoints for fetching bibliographic metadata from external sources.

Supported sources:
- Crossref (DOI lookup)
- Open Library (ISBN lookup)

These endpoints allow users to auto-populate document metadata by entering
an identifier and fetching details from external databases.
"""

from fastapi import APIRouter, HTTPException
import httpx
from typing import Optional

router = APIRouter()

# Timeout for external API calls
TIMEOUT = 15.0


@router.get("/lookup/doi/{doi:path}")
async def lookup_doi(doi: str):
    """
    Fetch metadata from Crossref by DOI.

    Args:
        doi: Digital Object Identifier (e.g., "10.1145/3442188.3445922")

    Returns:
        Dict with: title, author, year, journal, volume, issue, pages, publisher, doi
    """
    # Clean the DOI
    clean_doi = doi.strip()
    if clean_doi.startswith("https://doi.org/"):
        clean_doi = clean_doi[16:]
    elif clean_doi.startswith("http://doi.org/"):
        clean_doi = clean_doi[15:]
    elif clean_doi.startswith("doi:"):
        clean_doi = clean_doi[4:]

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(
                f"https://api.crossref.org/works/{clean_doi}",
                headers={
                    "User-Agent": "Scholia/1.0 (https://github.com/scholia; mailto:research@example.com)"
                }
            )
        except httpx.TimeoutException:
            raise HTTPException(504, "Crossref API timeout")
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach Crossref: {str(e)}")

        if resp.status_code == 404:
            raise HTTPException(404, "DOI not found in Crossref")
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Crossref API error: {resp.status_code}")

        try:
            data = resp.json()["message"]
        except (KeyError, ValueError):
            raise HTTPException(500, "Invalid response from Crossref")

    # Extract author names
    authors = []
    for author in data.get("author", []):
        given = author.get("given", "")
        family = author.get("family", "")
        if given and family:
            authors.append(f"{given} {family}")
        elif family:
            authors.append(family)
        elif given:
            authors.append(given)

    # Extract year from various date fields
    year = None
    for date_field in ["published-print", "published-online", "issued", "created"]:
        if date_field in data:
            date_parts = data[date_field].get("date-parts", [[]])
            if date_parts and date_parts[0]:
                year = date_parts[0][0]
                break

    return {
        "title": data.get("title", [None])[0] if data.get("title") else None,
        "author": "; ".join(authors) if authors else None,
        "year": year,
        "journal": data.get("container-title", [None])[0] if data.get("container-title") else None,
        "volume": data.get("volume"),
        "issue": data.get("issue"),
        "pages": data.get("page"),
        "publisher": data.get("publisher"),
        "doi": clean_doi,
    }


@router.get("/lookup/isbn/{isbn}")
async def lookup_isbn(isbn: str):
    """
    Fetch metadata from Open Library by ISBN.

    Args:
        isbn: ISBN-10 or ISBN-13 (hyphens optional)

    Returns:
        Dict with: title, author, year, publisher, pages, isbn
    """
    # Clean ISBN (remove hyphens, spaces)
    clean_isbn = isbn.replace("-", "").replace(" ", "").strip()

    # Validate format
    if not (len(clean_isbn) == 10 or len(clean_isbn) == 13):
        raise HTTPException(400, "Invalid ISBN format. Must be ISBN-10 or ISBN-13.")

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        # First, get the book data
        try:
            resp = await client.get(f"https://openlibrary.org/isbn/{clean_isbn}.json")
        except httpx.TimeoutException:
            raise HTTPException(504, "Open Library API timeout")
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach Open Library: {str(e)}")

        if resp.status_code == 404:
            raise HTTPException(404, "ISBN not found in Open Library")
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Open Library API error: {resp.status_code}")

        try:
            data = resp.json()
        except ValueError:
            raise HTTPException(500, "Invalid response from Open Library")

        # Get author names (requires additional API calls)
        authors = []
        for author_ref in data.get("authors", []):
            author_key = author_ref.get("key")
            if author_key:
                try:
                    author_resp = await client.get(f"https://openlibrary.org{author_key}.json")
                    if author_resp.status_code == 200:
                        author_data = author_resp.json()
                        name = author_data.get("name") or author_data.get("personal_name")
                        if name:
                            authors.append(name)
                except Exception:
                    pass  # Skip failed author lookups

        # Extract year from publish_date (formats vary: "2020", "January 2020", "2020-01-15")
        year = None
        publish_date = data.get("publish_date", "")
        if publish_date:
            # Try to find a 4-digit year
            import re
            year_match = re.search(r'\b(1[0-9]{3}|20[0-9]{2})\b', publish_date)
            if year_match:
                year = int(year_match.group(1))

        # Get publisher
        publishers = data.get("publishers", [])
        publisher = publishers[0] if publishers else None

        return {
            "title": data.get("title"),
            "author": "; ".join(authors) if authors else None,
            "year": year,
            "publisher": publisher,
            "pages": str(data.get("number_of_pages")) if data.get("number_of_pages") else None,
            "isbn": clean_isbn,
        }
