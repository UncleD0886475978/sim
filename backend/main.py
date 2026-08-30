import os
import json
import uuid
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from anthropic import AsyncAnthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("SIM_MODEL", "claude-sonnet-4-6")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sim:sim@db:5432/sim")
SYSTEM_PROMPT = os.environ.get(
    "SIM_SYSTEM_PROMPT",
    "You are Sim, a helpful self-hosted AI assistant that can chat and help with code.",
)

if not ANTHROPIC_API_KEY:
    print("WARNING: ANTHROPIC_API_KEY is not set. Set it in your .env file.")

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

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


@app.post("/api/chat")
async def chat(msg: NewMessage):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY is not configured on the server")

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

    response = await client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=history,
    )
    full_response = "".join(
        block.text for block in response.content if block.type == "text"
    )

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES ($1,$2,$3,$4)",
            uuid.uuid4(), conv_id, "assistant", full_response,
        )

    return {"conversation_id": str(conv_id), "content": full_response}


@app.get("/api/health")
async def health():
    return {"status": "ok", "model": MODEL, "time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/maya/cover-letter")
async def maya_cover_letter(req: MayaRequest):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY is not configured on the server")

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

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=maya_system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    letter = "".join(
        block.text for block in response.content if block.type == "text"
    )

    return {"cover_letter": letter}
