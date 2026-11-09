import os
import json
import uuid
from datetime import datetime, timezone

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# --- Local model configuration -------------------------------------------
# Sim now talks to a local llama.cpp `llama-server` (Gemma 4) through its
# OpenAI-compatible API. No API key is required: the model runs on your own
# machine / Docker network. LLM_API_KEY is only sent if you set one (e.g. if
# you put llama-server behind --api-key or a proxy).
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://model:8080/v1").rstrip("/")
MODEL = os.environ.get("SIM_MODEL", "gemma-4-E4B-it")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sim:sim@db:5432/sim")
SYSTEM_PROMPT = os.environ.get(
    "SIM_SYSTEM_PROMPT",
    "You are Sim, a helpful self-hosted AI assistant that can chat and help with code.",
)

app = FastAPI(title="Sim API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this once you're past local dev
    allow_methods=["*"],
    allow_headers=["*"],
)

pool: asyncpg.Pool | None = None


@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id UUID PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New chat',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS messages (
                id UUID PRIMARY KEY,
                conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


@app.on_event("shutdown")
async def shutdown():
    if pool:
        await pool.close()


class NewMessage(BaseModel):
    conversation_id: str | None = None
    content: str


class MayaRequest(BaseModel):
    job_posting: str
    company_name: str | None = None
    tone: str | None = "professional"


def load_resume() -> str:
    resume_path = os.path.join(os.path.dirname(__file__), "data", "resume.txt")
    try:
        with open(resume_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


# --- Model client helpers --------------------------------------------------

def _llm_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    return headers


def build_http_client() -> httpx.AsyncClient:
    """Factory kept separate so tests can inject a mock transport."""
    return httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0))


def _content_to_text(content) -> str:
    """OpenAI-style content can be a string or a list of content parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text", "") or "")
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)


def extract_stream_token(obj: dict) -> str:
    """Pull the token text out of one streamed chat-completion chunk."""
    try:
        choices = obj.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or {}
        return _content_to_text(delta.get("content"))
    except Exception:
        return ""


def parse_sse_line(line: str) -> str | None:
    """Return the token for one SSE line from llama-server, '' for a valid
    JSON line with no content, or None for keep-alive / [DONE] lines."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("data:"):
        line = line[len("data:"):].strip()
    if not line or line == "[DONE]":
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return extract_stream_token(obj)


async def iter_model_tokens(messages: list[dict], max_tokens: int = 4096):
    """Stream tokens from the local model, yielding text as it arrives."""
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": messages,
    }
    async with build_http_client() as client:
        async with client.stream(
            "POST",
            f"{LLM_BASE_URL}/chat/completions",
            json=payload,
            headers=_llm_headers(),
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")[:500]
                raise HTTPException(502, f"Model server error {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                token = parse_sse_line(line)
                if token:
                    yield token


async def complete_chat(messages: list[dict], max_tokens: int = 1024) -> str:
    """Non-streaming completion (used by Maya)."""
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "stream": False,
        "messages": messages,
    }
    async with build_http_client() as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            json=payload,
            headers=_llm_headers(),
        )
        if resp.status_code >= 400:
            raise HTTPException(502, f"Model server error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return _content_to_text(message.get("content"))


# --- API endpoints ---------------------------------------------------------

@app.get("/api/conversations")
async def list_conversations():
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, created_at FROM conversations ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]


@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content, created_at FROM messages WHERE conversation_id = $1 ORDER BY created_at ASC",
            uuid.UUID(conversation_id),
        )
        return [dict(r) for r in rows]


async def chat_event_stream(conv_id: uuid.UUID, history: list[dict]):
    """NDJSON stream for one chat reply.

    Emits, in order:
      {"type": "meta",  "conversation_id": ...}
      {"type": "token", "content": "..."}   (zero or more, as tokens arrive)
      {"type": "done",  "conversation_id": ..., "content": "<full reply>"}
    or, if the model fails:
      {"type": "error", "detail": "..."}    (nothing is saved in that case)

    The assistant message is written to Postgres only once, after the full
    response has been assembled.
    """
    yield json.dumps({"type": "meta", "conversation_id": str(conv_id)}) + "\n"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    full_response = ""
    try:
        async for token in iter_model_tokens(messages):
            full_response += token
            yield json.dumps({"type": "token", "content": token}) + "\n"
    except HTTPException as exc:
        yield json.dumps({"type": "error", "detail": str(exc.detail)}) + "\n"
        return
    except httpx.HTTPError as exc:
        yield json.dumps(
            {"type": "error", "detail": f"Could not reach the local model at {LLM_BASE_URL}: {exc}"}
        ) + "\n"
        return

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES ($1,$2,$3,$4)",
            uuid.uuid4(), conv_id, "assistant", full_response,
        )

    yield json.dumps(
        {"type": "done", "conversation_id": str(conv_id), "content": full_response}
    ) + "\n"


@app.post("/api/chat")
async def chat(msg: NewMessage):
    async with pool.acquire() as conn:
        if msg.conversation_id:
            conv_id = uuid.UUID(msg.conversation_id)
            exists = await conn.fetchval("SELECT 1 FROM conversations WHERE id=$1", conv_id)
            if not exists:
                raise HTTPException(404, "conversation not found")
        else:
            conv_id = uuid.uuid4()
            title = msg.content[:60]
            await conn.execute(
                "INSERT INTO conversations (id, title) VALUES ($1, $2)", conv_id, title
            )

        await conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES ($1,$2,$3,$4)",
            uuid.uuid4(), conv_id, "user", msg.content,
        )

        history_rows = await conn.fetch(
            "SELECT role, content FROM messages WHERE conversation_id=$1 ORDER BY created_at ASC",
            conv_id,
        )
        history = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    return StreamingResponse(
        chat_event_stream(conv_id, history),
        media_type="application/x-ndjson",
    )


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "model": MODEL,
        "llm_base_url": LLM_BASE_URL,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/maya/cover-letter")
async def maya_cover_letter(req: MayaRequest):
    resume_text = load_resume()
    if not resume_text:
        raise HTTPException(500, "No resume on file for Maya to reference")

    company_line = f" for {req.company_name}" if req.company_name else ""

    maya_system_prompt = (
        "You are Maya, an assistant that writes tailored, honest, specific cover letters. "
        "You are given a candidate's resume and a job posting. Write a cover letter that: "
        "(1) is grounded only in real experience from the resume, never invented; "
        "(2) directly connects 2-3 concrete resume achievements to the job posting's stated requirements; "
        "(3) is concise (under 350 words), professional, and avoids generic filler phrases; "
        "(4) uses a natural, confident, first-person voice. "
        "Do not fabricate metrics, employers, or skills not present in the resume."
    )

    user_prompt = (
        f"CANDIDATE RESUME:\n{resume_text}\n\n"
        f"JOB POSTING{company_line}:\n{req.job_posting}\n\n"
        f"Write a tailored cover letter in a {req.tone} tone."
    )

    try:
        letter = await complete_chat(
            [
                {"role": "system", "content": maya_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1024,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach the local model at {LLM_BASE_URL}: {exc}")

    return {"cover_letter": letter}
