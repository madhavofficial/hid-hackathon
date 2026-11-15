import asyncio
import base64
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from identity.accounts import authenticate, issue_token, read_token

from .config import Settings
from .service import AnalysisError, Runtime, create_runtime, process_check
from .vision import InvalidFrameError, decode_frame


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def session_role(request: Request) -> str:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Sign in required")
        try:
            _username, role = read_token(header.split(" ", 1)[1].strip())
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Sign in required") from exc
        return role

    @app.post("/session")
    async def session(request: Request):
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=422, detail="Request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="Request body must be a JSON object")
        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise HTTPException(status_code=401, detail="Unknown account")
        role = authenticate(username, password)
        if role is None:
            raise HTTPException(status_code=401, detail="Unknown account")
        return {
            "username": username,
            "role": role,
            "token": issue_token(username, role),
        }

    @app.post("/enroll")
    async def enroll(request: Request):
        if session_role(request) != "admin":
            raise HTTPException(status_code=403, detail="Only an admin can enroll")
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=422, detail="Request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="Request body must be a JSON object")
        person_id = payload.get("person_id")
        phone = payload.get("phone")
        image = payload.get("image")
        if not isinstance(person_id, str) or not isinstance(phone, str) or not isinstance(image, str):
            raise HTTPException(
                status_code=422,
                detail="person_id, phone, and image are required",
            )
        encoded = image.split(",", 1)[1] if image.startswith("data:") else image
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="image must be a JPEG") from exc
        if not raw.startswith(b"\xff\xd8") or len(raw) > 5 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="image must be a JPEG")
        from identity.enroll import enroll_person

        handle, name = tempfile.mkstemp(suffix=".jpg")
        try:
            os.write(handle, raw)
            os.close(handle)
            handle = None
            result = enroll_person(person_id, name, phone=phone)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Enrollment failed") from exc
        finally:
            if handle is not None:
                os.close(handle)
            Path(name).unlink(missing_ok=True)
        return {
            "person_id": result["person_id"],
            "face_id": result["face_id"],
            "phone": result["phone"],
            "quality_warning": result.get("quality_warning"),
        }

    @app.post("/otp/send")
    async def send_code(request: Request):
        session_role(request)
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=422, detail="Request body must be valid JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("image"), str):
            raise HTTPException(status_code=422, detail="image is required")
        runtime: Runtime = request.app.state.runtime
        try:
            decoded = decode_frame(payload["image"], runtime.settings.max_image_bytes)
            found = runtime.rekognition.search_faces_by_image(
                CollectionId=runtime.settings.collection_id,
                Image={"Bytes": decoded.jpeg_bytes},
                FaceMatchThreshold=runtime.settings.similarity_threshold,
                MaxFaces=1,
            )
        except InvalidFrameError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ClientError as exc:
            message = exc.response.get("Error", {}).get("Message", "")
            if "no face" in message.lower():
                raise HTTPException(
                    status_code=422,
                    detail="Look at the camera so a code can be sent.",
                ) from exc
            raise HTTPException(status_code=503, detail="The text could not be sent.") from exc
        matches = found.get("FaceMatches") or []
        person_id = (matches[0].get("Face") or {}).get("ExternalImageId") if matches else None
        if not person_id:
            raise HTTPException(
                status_code=422,
                detail="This face is not enrolled, so no code was sent.",
            )
        from identity.otp import send_otp

        try:
            send_otp(person_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ClientError as exc:
            raise HTTPException(status_code=503, detail="The text could not be sent.") from exc
        return {"sent": True, "person_id": person_id}

    @app.post("/check")
    async def check(request: Request):
        session_role(request)
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
