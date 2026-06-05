from __future__ import annotations

import base64
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .services import OUTPUT_DIR, default_providers, generate_or_edit_with_fallback

ROOT_DIR = Path(__file__).resolve().parents[1]
# On Vercel, serverless functions can write only to /tmp. Locally, keep uploads
# next to the app for easier debugging.
UPLOAD_DIR = Path(tempfile.gettempdir()) / "image-studio" / "uploads" if os.getenv("VERCEL") else ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Image Studio", version="0.1.0")
app.mount("/static", StaticFiles(directory=ROOT_DIR / "app" / "static"), name="static")
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT_DIR / "app" / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "app": "image-studio"}


def _save_upload(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    suffix = Path(upload.filename).suffix.lower() or ".png"
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return str(dest)


@app.post("/api/image")
def create_image(
    mode: str = Form(...),
    prompt: str = Form(...),
    quality: str = Form("medium"),
    size: str = Form("1024x1024"),
    synthetic_people_confirmed: bool = Form(False),
    image: UploadFile | None = File(None),
    mask: UploadFile | None = File(None),
) -> dict:
    if mode not in {"generate", "edit"}:
        raise HTTPException(status_code=400, detail="mode must be generate or edit")
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    # Truthful optional context only. The app will not claim real people are synthetic.
    if synthetic_people_confirmed:
        prompt = "User confirms any depicted person is synthetic / AI-generated. " + prompt

    image_path = _save_upload(image)
    mask_path = _save_upload(mask)
    if mode == "edit" and not image_path:
        raise HTTPException(status_code=400, detail="image upload is required for edit mode")

    try:
        result = generate_or_edit_with_fallback(
            mode=mode,
            prompt=prompt,
            providers=default_providers(),
            image_path=image_path,
            mask_path=mask_path,
            size=size,
            quality=quality,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    output_path = Path(result.image_path)
    image_bytes = output_path.read_bytes()
    image_data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    return {
        "provider": result.provider,
        "image_url": f"/outputs/{output_path.name}",
        "image_data_url": image_data_url,
        "image_path": result.image_path if not os.getenv("VERCEL") else None,
    }
