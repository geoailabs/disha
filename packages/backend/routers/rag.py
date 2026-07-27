from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pypdf import PdfReader
import docx

router = APIRouter()

# ── Document Parsing Helpers ──────────────────────────────────────────────────

def get_file_hash(path: Path) -> str:
    """Compute SHA256 of a local file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def get_pdf_pages_text(path: Path) -> list[tuple[int, str]]:
    """Extract selectable text page-by-page from a PDF."""
    pages = []
    reader = PdfReader(path)
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append((i + 1, text))
    return pages


def get_docx_text(path: Path) -> str:
    """Extract text from a Word document (.docx)."""
    doc = docx.Document(path)
    paragraphs = [para.text for para in doc.paragraphs]
    return "\n".join(paragraphs)


def get_text_file_content(path: Path) -> str:
    """Read plain text/markdown file contents."""
    return path.read_text(encoding="utf-8", errors="ignore")


def chunk_text(text: str, page_num: int, chunk_size: int = 1000, overlap: int = 200) -> list[dict]:
    """Split text into overlapping chunks of designated size."""
    chunks = []
    start = 0
    text_clean = text.strip()
    if not text_clean:
        return []
        
    while start < len(text_clean):
        end = min(start + chunk_size, len(text_clean))
        chunk = text_clean[start:end]
        chunks.append({
            "text": chunk,
            "page": page_num
        })
        if end == len(text_clean):
            break
        start += chunk_size - overlap
    return chunks


# ── RAG Async Search ──────────────────────────────────────────────────────────

async def query_rag_index_async(query: str, api_key: str, workspace: str, top_k: int = 4, threshold: float = 0.3) -> list[dict]:
    """Vector search over the workspace index using Cosine Similarity (Dot Product)."""
    index_file = Path(workspace) / ".disha" / "rag_index.json"
    if not index_file.exists():
        return []

    try:
        index_data = json.loads(index_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[RAG] Error reading index file: {e}")
        return []

    all_chunks = []
    documents = index_data.get("documents", {})
    for doc_path, doc_info in documents.items():
        doc_name = doc_info.get("fileName", "Document")
        for chunk in doc_info.get("chunks", []):
            if "embedding" in chunk:
                all_chunks.append({
                    "text": chunk.get("text", ""),
                    "page": chunk.get("page", 1),
                    "docName": doc_name,
                    "embedding": chunk["embedding"]
                })

    if not all_chunks:
        return []

    # Get query embedding
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key.strip())
    try:
        resp = await client.embeddings.create(
            model="text-embedding-3-small",
            input=[query]
        )
        query_vector = np.array(resp.data[0].embedding)
    except Exception as e:
        print(f"[RAG] Failed to embed query: {e}")
        return []

    # Calculate similarity matches (since text-embeddings-3 are unit-normalized, dot product is cosine similarity)
    results = []
    for chunk in all_chunks:
        chunk_vector = np.array(chunk["embedding"])
        similarity = float(np.dot(query_vector, chunk_vector))
        if similarity >= threshold:
            results.append((similarity, chunk))

    results.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in results[:top_k]]


# ── API Routing Endpoints ──────────────────────────────────────────────────────

@router.get("/status")
async def rag_status(file_path: str, workspace: str):
    """Check whether a specific document path has already been indexed."""
    try:
        ws_dir = Path(workspace)
        index_file = ws_dir / ".disha" / "rag_index.json"
        if not index_file.exists():
            return {"indexed": False}
            
        data = json.loads(index_file.read_text(encoding="utf-8"))
        docs = data.get("documents", {})
        
        target_path = str(Path(file_path).resolve())
        for doc_path, doc_info in docs.items():
            if str(Path(doc_path).resolve()) == target_path:
                current_hash = get_file_hash(Path(file_path))
                if doc_info.get("fileHash") == current_hash:
                    return {"indexed": True}
                break
    except Exception as e:
        print(f"[RAG] Status check failed: {e}")
        
    return {"indexed": False}


@router.post("/index")
async def rag_index(body: dict):
    """Parse local document, fetch vector embeddings from OpenAI, and write to workspace index."""
    file_path = body.get("file_path", "")
    workspace = body.get("workspace", "")
    api_key = body.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")

    if not file_path or not workspace:
        raise HTTPException(status_code=400, detail="file_path and workspace parameters are required")

    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API Key is missing. Configure it in settings.")

    p = Path(file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    ext = p.suffix.lower()
    chunks = []

    try:
        if ext == ".pdf":
            pages = get_pdf_pages_text(p)
            for page_num, text in pages:
                chunks.extend(chunk_text(text, page_num))
        elif ext == ".docx":
            text = get_docx_text(p)
            chunks = chunk_text(text, 1)
        elif ext in (".txt", ".md"):
            text = get_text_file_content(p)
            chunks = chunk_text(text, 1)
        else:
            raise ValueError(f"Unsupported document format: {ext}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse local document: {e}")

    if not chunks:
        raise HTTPException(status_code=400, detail="No extractable text found in this document.")

    # Call OpenAI embeddings in batches
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key.strip())
    batch_size = 100
    all_embeddings = []

    try:
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i + batch_size]
            texts = [c["text"] for c in batch_chunks]
            resp = await client.embeddings.create(
                model="text-embedding-3-small",
                input=texts
            )
            for item in resp.data:
                all_embeddings.append(item.embedding)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch embeddings: {e}")

    # Bind embeddings back to chunk payload
    for idx, emb in enumerate(all_embeddings):
        chunks[idx]["embedding"] = emb

    # Write back to RAG index under .disha/rag_index.json
    ws_dir = Path(workspace)
    index_file = ws_dir / ".disha" / "rag_index.json"
    
    index_data = {"documents": {}}
    if index_file.exists():
        try:
            index_data = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    target_path = str(p.resolve())
    index_data["documents"][target_path] = {
        "fileName": p.name,
        "fileHash": get_file_hash(p),
        "chunks": chunks
    }

    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text(json.dumps(index_data, indent=2), encoding="utf-8")

    return {"status": "indexed", "chunks": len(chunks)}
