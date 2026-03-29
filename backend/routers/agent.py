import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agent.runner import run_agent_stream

router = APIRouter()


@router.post("/agent/run")
async def run_agent():
    def gen():
        for ev in run_agent_stream():
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
