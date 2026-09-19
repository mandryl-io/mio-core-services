# Mem0 on the LiveKit conversation agent

Spike of the [Mem0 LiveKit integration](https://docs.mem0.ai/integrations/livekit)
against Mio's `Assistant` in `mio_core_services/conversation.py`.

The hosted example is a travel-guide voice agent. Mio is already a LiveKit
Agents 1.x worker (`Agent` + `AgentSession` + Deepgram STT). The same hook
fits; the rest of the example does not copy across unchanged.

## What the guide does

On each completed user turn:

1. `mem0_client.add([{role: user, content}], user_id=...)` so Mem0 extracts
   facts.
2. `mem0_client.search(query, filters={user_id})` for RAG.
3. Inject retrieved text into `ChatContext` and `update_chat_ctx`.

That maps to LiveKit's `Agent.on_user_turn_completed(turn_ctx, new_message)`.

## What we wired

| Piece | Mio |
| --- | --- |
| Client | `mem0.AsyncMemoryClient` when `MEM0_API_KEY` is set |
| Wrapper | `Mem0TurnMemory` in `mio_core_services/memory/mem0.py` |
| Hook | `Assistant.on_user_turn_completed` → `inject_mem0_turn` |
| Identity | `MIO_MEMORY_USER_ID`, default `mio-local` |
| Failure | Memory errors are logged; the spoken turn still runs |

Mem0 is an extra, not a hard dependency:

```
uv sync --extra mem0
```

Without `MEM0_API_KEY`, the agent is unchanged.

## Where we diverge from the guide

**System context, not an assistant message.** The guide injects memories as
`role="assistant"`. In a voice pipeline that can leak into TTS (Mio reciting
"Source: mem0 Memories"). We inject a system message and tell the model not
to read the list aloud.

**Optional, not required.** Conversation still needs Deepgram / LiveKit /
OpenAI / Baseten. Mem0 is opt-in.

**Do not reuse the sample `user_id`.** `livekit-mem0` would mix every
household into one memory graph. Occupancy already has `Occupant.person_id`
from face embeddings; that is the right Mem0 `user_id` once perception is
joined to the session. Until then, set `MIO_MEMORY_USER_ID` per device or
resident.

**Keep Chroma.** `MioVectorStore` is local embeddings (faces, future on-device
RAG). Mem0 is hosted fact memory with its own extraction. They are not the
same backend. Do not route face vectors through Mem0.

## Identity and privacy

Mio is built for older people in a home, including health and family detail
(`prompts/default.md` forbids sharing one resident's facts with another).

- Scope every `add` / `search` with `user_id`. When occupancy is wired,
  switch `user_id` when the facing person changes; never search without a
  filter.
- Mem0 Platform sends transcripts to Mem0's API. Confirm that is acceptable
  before enabling on a device. Open-source `Memory()` (local vector store)
  is the fallback if data must stay on the Pi.
- Store user speech, not inferred diagnoses. Mem0 will still extract facts
  from casual talk; that is the product, and also the risk.

## Later wiring

1. Pass `Occupant.person_id` into `Mem0TurnMemory(user_id=...)` when a face
   is locked for the session.
2. After the agent reply, `add` the user+assistant pair so extraction has
   both sides (the guide only stores the user line).
3. On `on_enter`, search a greeting query ("who is this person") so the
   opener can use a known name without waiting for the first user turn.
   First-use setup also stores the confirmed patient and carer names, plus
   Learn Patient notes, and injects them on later starts.
4. Decide hosted Mem0 vs local `Memory()` before treating this as default
   on-device behaviour.

## Try it

1. Create a Mem0 API key.
2. `uv sync --extra mem0`
3. Set `MEM0_API_KEY` and optionally `MIO_MEMORY_USER_ID` in `.env`.
4. `lk agent console mio_core_services/conversation.py`

Say a stable fact ("my daughter is visiting on Sunday"), then later ask
about it. Check logs for Mem0 add/search failures; they must not stall STT.
