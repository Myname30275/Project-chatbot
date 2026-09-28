"""ที่เก็บบทสนทนาต่อ session — รองรับ "หลายบทสนทนา" (History)

state 1 ก้อนต่อ session (คีย์ sess:{session_id}):
    { "active": "<cid>",
      "order": ["<cid>", ...],            # ใหม่สุดอยู่หัว
      "conv":  { "<cid>": {"title", "updated", "messages": [...], "attachments": [...]} } }

- เมธอด get_history / set_history / get_attachments / set_attachments / reset ทำงานบน
  "บทสนทนาที่ active" — router เดิมจึงแทบไม่ต้องแก้
- เมธอด list/new/activate/delete_conversation ใช้ทำหน้า History

get_store() เลือก backend จาก env: ตั้ง Redis/Vercel KV = RedisConversationStore
(เก็บถาวรข้าม instance) ไม่งั้น InMemoryConversationStore (หายเมื่อรีสตาร์ท)
"""

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

_REDIS_TIMEOUT = httpx.Timeout(connect=3.0, write=5.0, read=5.0, pool=3.0)
_SESS_PREFIX = "sess:"
_MAX_CONVERSATIONS = 15
_MAX_BLOB_BYTES = 900_000
_TITLE_LEN = 48

Messages = list[dict[str, str]]
Attachments = list[dict[str, Any]]
State = dict[str, Any]


def _new_cid() -> str:
    return uuid.uuid4().hex[:12]


def _new_conv() -> dict:
    return {"title": "", "updated": int(time.time()), "messages": [], "attachments": []}


def _blank_state() -> State:
    cid = _new_cid()
    return {"active": cid, "order": [cid], "conv": {cid: _new_conv()}}


def _ensure(state: State) -> State:
    """กันข้อมูลเพี้ยน — คืน state ที่มี active / order / conv ครบเสมอ"""
    if not isinstance(state, dict) or not isinstance(state.get("conv"), dict) or not state.get("order"):
        return _blank_state()
    state["order"] = [c for c in state["order"] if c in state["conv"]]
    if not state["order"]:
        return _blank_state()
    if state.get("active") not in state["conv"]:
        state["active"] = state["order"][0]
    return state


def _active(state: State) -> dict:
    return state["conv"][state["active"]]


def _trim(state: State) -> None:
    while len(state["order"]) > _MAX_CONVERSATIONS:
        state["conv"].pop(state["order"].pop(), None)  # ตัดท้าย = เก่าสุด
    while (
        len(state["order"]) > 1
        and len(json.dumps(state, ensure_ascii=False).encode("utf-8")) > _MAX_BLOB_BYTES
    ):
        state["conv"].pop(state["order"].pop(), None)


def _touch_active(state: State) -> None:
    conv = _active(state)
    conv["updated"] = int(time.time())
    if not conv["title"]:
        for m in conv["messages"]:
            if m.get("role") == "user" and str(m.get("content", "")).strip():
                conv["title"] = str(m["content"]).strip()[:_TITLE_LEN]
                break
    state["order"] = [state["active"]] + [c for c in state["order"] if c != state["active"]]


class ConversationStore(ABC):
    @abstractmethod
    async def _load(self, session_id: str) -> State:
        """คืน state ของ session (blank state ถ้ายังไม่มี)"""

    @abstractmethod
    async def _save(self, session_id: str, state: State) -> None:
        """เขียน state กลับ"""

    # ---- ทำงานบนบทสนทนาที่ active ----

    async def get_history(self, session_id: str) -> Messages:
        state = _ensure(await self._load(session_id))
        return list(_active(state)["messages"])

    async def set_history(self, session_id: str, messages: Messages) -> None:
        state = _ensure(await self._load(session_id))
        _active(state)["messages"] = list(messages)
        _touch_active(state)
        _trim(state)
        await self._save(session_id, state)

    async def get_attachments(self, session_id: str) -> Attachments:
        state = _ensure(await self._load(session_id))
        return list(_active(state).get("attachments", []))

    async def set_attachments(self, session_id: str, items: Attachments) -> None:
        state = _ensure(await self._load(session_id))
        _active(state)["attachments"] = list(items)
        _trim(state)
        await self._save(session_id, state)

    async def reset(self, session_id: str) -> None:
        """ล้างเนื้อหาบทที่ active (ไม่ลบทั้งบท)"""
        state = _ensure(await self._load(session_id))
        conv = _active(state)
        conv.update(messages=[], attachments=[], title="", updated=int(time.time()))
        await self._save(session_id, state)

    # ---- หลายบทสนทนา (History) ----

    async def list_conversations(self, session_id: str) -> list[dict]:
        state = _ensure(await self._load(session_id))
        out = []
        for cid in state["order"]:
            c = state["conv"][cid]
            out.append(
                {
                    "id": cid,
                    "title": c["title"] or "บทสนทนาใหม่",
                    "updated": c["updated"],
                    "count": len(c["messages"]),
                    "active": cid == state["active"],
                }
            )
        return out

    async def new_conversation(self, session_id: str) -> str:
        state = _ensure(await self._load(session_id))
        if not _active(state)["messages"]:
            return state["active"]  # บท active ยังว่าง ใช้ต่อได้เลย ไม่สร้างซ้ำ
        cid = _new_cid()
        state["conv"][cid] = _new_conv()
        state["order"] = [cid] + state["order"]
        state["active"] = cid
        _trim(state)
        await self._save(session_id, state)
        return cid

    async def activate_conversation(self, session_id: str, cid: str) -> bool:
        state = _ensure(await self._load(session_id))
        if cid not in state["conv"]:
            return False
        state["active"] = cid
        await self._save(session_id, state)
        return True

    async def delete_conversation(self, session_id: str, cid: str) -> None:
        state = _ensure(await self._load(session_id))
        if cid not in state["conv"]:
            return
        state["conv"].pop(cid, None)
        state["order"] = [c for c in state["order"] if c != cid]
        if not state["order"]:
            state.clear()
            state.update(_blank_state())
        elif state["active"] == cid:
            state["active"] = state["order"][0]
        await self._save(session_id, state)


class InMemoryConversationStore(ConversationStore):
    def __init__(self) -> None:
        self._data: dict[str, State] = {}

    async def _load(self, session_id: str) -> State:
        return self._data.get(session_id) or _blank_state()

    async def _save(self, session_id: str, state: State) -> None:
        self._data[session_id] = state


class RedisConversationStore(ConversationStore):
    """คุย Upstash Redis REST API (ตัวเดียวกับ Vercel KV): POST body เป็น JSON array
    ของคำสั่ง Redis + header Authorization: Bearer <token>
    ออกแบบให้ "ไม่ล้ม" ถ้า Redis มีปัญหา: log แล้วทำงานต่อแบบ state เปล่า"""

    def __init__(self, base_url: str, token: str, ttl_seconds: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._ttl = ttl_seconds

    async def _command(self, *args: str) -> object:
        async with httpx.AsyncClient(timeout=_REDIS_TIMEOUT) as client:
            r = await client.post(self._base_url, headers=self._headers, json=list(args))
            r.raise_for_status()
            return r.json().get("result")

    async def _load(self, session_id: str) -> State:
        try:
            raw = await self._command("GET", _SESS_PREFIX + session_id)
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("อ่าน session จาก Redis ไม่สำเร็จ %s: %s", session_id, exc)
            return _blank_state()
        if not raw:
            return _blank_state()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            logger.error("session ใน Redis เสียรูป %s", session_id)
            return _blank_state()
        return data if isinstance(data, dict) else _blank_state()

    async def _save(self, session_id: str, state: State) -> None:
        try:
            await self._command(
                "SET",
                _SESS_PREFIX + session_id,
                json.dumps(state, ensure_ascii=False),
                "EX",
                str(self._ttl),
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("เขียน session ลง Redis ไม่สำเร็จ %s: %s", session_id, exc)


_store: ConversationStore | None = None


def get_store() -> ConversationStore:
    """คืน store แบบ singleton — เลือก backend จาก env ครั้งเดียว"""
    global _store
    if _store is not None:
        return _store

    url = settings.redis_rest_url
    token = settings.redis_rest_token
    if url and token:
        logger.info("ใช้ RedisConversationStore (%s)", url)
        _store = RedisConversationStore(url, token, settings.CONVERSATION_TTL_SECONDS)
    else:
        logger.info(
            "ไม่ได้ตั้งค่า Redis/Vercel KV — ใช้ InMemoryConversationStore "
            "(บทสนทนาจะหายเมื่อรีสตาร์ท และใช้ไม่ได้กับ serverless หลาย instance)"
        )
        _store = InMemoryConversationStore()
    return _store
