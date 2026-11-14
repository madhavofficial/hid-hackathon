import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from .config import Settings
from .service import AnalysisError, Runtime, create_runtime, process_check
from .vision import InvalidFrameError


def create_app(runtime_factory=create_runtime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings.from_env()
        runtime = runtime_factory(settings)
        app.state.runtime = runtime
        try:
            yield
        finally:
            runtime.close()

    app = FastAPI(title="HID decision service", lifespan=lifespan)

    @app.post("/check")
    async def check(request: Request):
        visit_id = str(uuid.uuid4())
        started_at = time.perf_counter()
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            runtime: Runtime = request.app.state.runtime
            try:
                process_check(runtime, None, visit_id, started_at)
            except InvalidFrameError:
                pass
            raise HTTPException(
                status_code=422, detail="Request body must be valid JSON"
            ) from exc

        runtime = request.app.state.runtime
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                process_check,
                runtime,
                payload,
                visit_id,
                started_at,
            )
        except InvalidFrameError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AnalysisError as exc:
            raise HTTPException(
                status_code=503,
                detail={"message": str(exc), "visit_id": visit_id},
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Decision service unavailable"
            ) from exc

        return {
            "decision": result["decision"],
            "reason": result["reason"],
            "scores": {
                "spoof": (
                    float(result["spoof"]) if result["spoof"] is not None else None
                ),
                "similarity": (
                    float(result["similarity"])
                    if result["similarity"] is not None
                    else None
                ),
                "sharpness": (
                    float(result["sharpness"])
                    if result["sharpness"] is not None
                    else None
                ),
            },
            "elapsed_ms": result["elapsed_ms"],
        }

    return app


app = create_app()
