"""Upload / Paste router for ingesting documents into the knowledge store."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
from typing import List, Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from openjarvis.connectors.store import KnowledgeStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/connectors/upload", tags=["upload"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx"}


def _chunk_text(text: str, max_chars: int = 1000) -> List[str]:
    """Split *text* into ~max_chars pieces at paragraph boundaries."""
    paragraphs = text.split("\n\n")
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        chunks.append(current.strip())
    # Guard against very large paragraphs that exceed max_chars
    final: List[str] = []
    for chunk in chunks:
        while len(chunk) > max_chars:
            # Find last space within limit
            split_at = chunk.rfind(" ", 0, max_chars)
            if split_at == -1:
                split_at = max_chars
            final.append(chunk[:split_at].strip())
            chunk = chunk[split_at:].strip()
        if chunk:
            final.append(chunk)
    return final


def _extract_text_from_pdf(data: bytes) -> str:
    """Extract text from a PDF using pdfplumber or PyPDF2."""
    # Try pdfplumber first
    try:
        import pdfplumber  # type: ignore[import-untyped]

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n\n".join(pages)
    except ImportError:
        pass

    # Fall back to PyPDF2
    try:
        from PyPDF2 import PdfReader  # type: ignore[import-untyped]

        reader = PdfReader(io.BytesIO(data))
        pages = [p.extract_text() or "" for p in reader.pages]
        return "\n\n".join(pages)
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail=(
                "PDF parsing requires pdfplumber or PyPDF2. "
                "Install one with: pip install pdfplumber"
            ),
        )


def _extract_text_from_docx(data: bytes) -> str:
    """Extract text from a .docx file using python-docx."""
    try:
        from docx import Document  # type: ignore[import-untyped]

        doc = Document(io.BytesIO(data))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail=(
                "DOCX parsing requires python-docx. "
                "Install with: pip install python-docx"
            ),
        )


def _get_store() -> KnowledgeStore:
    """Return a KnowledgeStore pointing at the default knowledge DB."""
    return KnowledgeStore()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PasteRequest(BaseModel):
    title: str = ""
    content: str


class IngestResponse(BaseModel):
    chunks_added: int
    source: str = "upload"
    reference: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/ingest", response_model=IngestResponse)
async def ingest_paste(body: PasteRequest) -> IngestResponse:
    """Ingest pasted text into the knowledge store."""
    text = body.content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Content is empty")

    doc_id = str(uuid.uuid4())
    reference = f"upload:{uuid.uuid4().hex}"
    chunks = _chunk_text(text)

    with _get_store() as store:
        for idx, chunk in enumerate(chunks):
            store.store(
                chunk,
                source="upload",
                source_id=reference,
                doc_type="paste",
                doc_id=doc_id,
                title=body.title or "Pasted text",
                chunk_index=idx,
            )

    logger.info("Ingested %d chunks from pasted text (doc_id=%s)", len(chunks), doc_id)
    return IngestResponse(chunks_added=len(chunks), reference=reference)


@router.post("/ingest/files", response_model=IngestResponse)
async def ingest_files(
    files: List[UploadFile] = File(...),
    title: Optional[str] = Form(None),
) -> IngestResponse:
    """Ingest uploaded files into the knowledge store."""
    documents: list[tuple[str, str, list[str]]] = []

    for upload in files:
        filename = upload.filename or "untitled"
        ext = ""
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()

        if ext not in _ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(_ALLOWED_EXTENSIONS))
            raise HTTPException(
                status_code=400,
                detail=(f"Unsupported file type: {ext}. Allowed: {allowed}"),
            )

        chunks = _file_chunks(ext, await upload.read())
        if chunks:
            documents.append((title or filename, ext.lstrip("."), chunks))
    return _index_file_batch(documents)


@router.post("/ingest/gmail/{message_id}", response_model=IngestResponse)
def ingest_gmail_evidence(message_id: str) -> IngestResponse:
    """Index supported attachments from a single selected Gmail message."""
    from openjarvis.connectors.gmail import GmailAuthError, fetch_message_evidence

    with _get_store() as store:
        if store.gmail_indexed_message(f"gmail:{message_id}") is None:
            raise HTTPException(
                status_code=404, detail="Gmail message is not indexed."
            )
    documents = []
    try:
        attachments = fetch_message_evidence(message_id, _ALLOWED_EXTENSIONS)
        for filename, content in attachments:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
            chunks = _file_chunks(ext, content)
            if chunks:
                documents.append((filename, ext.lstrip("."), chunks))
    except GmailAuthError as exc:
        raise HTTPException(
            status_code=409, detail="Connect Gmail before importing attachments."
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Gmail attachments could not be retrieved."
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not documents:
        raise HTTPException(
            status_code=422, detail="No readable evidence files were found."
        )
    return _index_file_batch(
        documents, source_url=f"https://mail.google.com/mail/u/0/#all/{message_id}"
    )


def _file_chunks(ext: str, data: bytes) -> list[str]:
    if ext == ".pdf":
        text = _extract_text_from_pdf(data)
    elif ext == ".docx":
        text = _extract_text_from_docx(data)
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
    return _chunk_text(text.strip())


def _index_file_batch(
    documents: list[tuple[str, str, list[str]]], *, source_url: str = ""
) -> IngestResponse:
    if source_url:
        # Gmail imports are retriable. Every unchanged batch uses the same
        # chunk keys, while changed evidence gets a new immutable reference.
        documents = sorted(documents)
        encoded = json.dumps([source_url, documents], separators=(",", ":")).encode()
        batch_id = hashlib.sha256(encoded).hexdigest()[:32]
    else:
        batch_id = uuid.uuid4().hex
    reference = f"upload:{batch_id}"
    total_chunks = 0
    with _get_store() as store:
        for index, (filename, doc_type, chunks) in enumerate(documents):
            doc_id = f"{reference}:{index}" if source_url else str(uuid.uuid4())
            for idx, chunk in enumerate(chunks):
                store.store(
                    chunk,
                    source="upload",
                    source_id=reference,
                    doc_type=doc_type,
                    doc_id=doc_id,
                    title=filename,
                    url=source_url or None,
                    chunk_index=total_chunks + idx,
                )
            total_chunks += len(chunks)

    return IngestResponse(
        chunks_added=total_chunks, reference=reference if total_chunks else None
    )
