"""Core services for Image Studio.

This module intentionally refines prompts for clarity and provider compatibility, not to
bypass provider safety systems. If a user truthfully confirms uploaded people are
synthetic, that context can be included; otherwise the app will not invent that claim.
"""

from __future__ import annotations

import base64
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import requests
from openai import OpenAI


ROOT_DIR = Path(__file__).resolve().parents[1]
# Vercel serverless functions can only write reliably to /tmp. Local runs keep
# outputs inside the project so files can be inspected after generation.
OUTPUT_DIR = Path(tempfile.gettempdir()) / "image-studio" / "outputs" if os.getenv("VERCEL") else ROOT_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_env_file(path: Path | None = None) -> None:
    """Load simple KEY=VALUE lines into os.environ without overriding set vars."""
    env_path = path or (Path.home() / ".hermes" / ".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class ProviderResult:
    provider: str
    image_path: str
    mime_type: str = "image/png"


class ImageProvider(Protocol):
    name: str

    def generate(self, *, prompt: str, size: str = "1024x1024", quality: str = "medium") -> ProviderResult:
        ...

    def edit(self, *, prompt: str, image_path: str, mask_path: str | None = None, size: str = "auto", quality: str = "medium") -> ProviderResult:
        ...


class PromptRefiner:
    """Deterministic prompt refiner used before sending prompts to providers."""

    def refine(self, prompt: str, *, uploaded_people_are_synthetic: bool = False) -> str:
        clean = " ".join(prompt.strip().split())
        pieces = [
            clean,
            "Preserve identity, facial features, pose, camera angle, lighting, and background unless the user explicitly asks otherwise.",
            "Make the edit natural and photorealistic; avoid unnecessary changes outside the requested edit.",
        ]
        if uploaded_people_are_synthetic:
            pieces.insert(0, "User confirms any depicted person is synthetic / AI-generated, not a real private person.")
        return " ".join(pieces)

    def generation_params(self, prompt: str, *, size: str = "1024x1024", quality: str = "medium") -> dict:
        return {
            "model": "gpt-image-2",
            "prompt": self.refine(prompt),
            "size": size,
            "quality": quality,
            "moderation": "low",  # least restrictive OpenAI-supported setting; not disabled.
            "output_format": "png",
            "n": 1,
        }


def _save_b64_image(data: str, prefix: str, provider: str) -> ProviderResult:
    out = OUTPUT_DIR / f"{prefix}_{provider}_{int(time.time() * 1000)}.png"
    out.write_bytes(base64.b64decode(data))
    return ProviderResult(provider=provider, image_path=str(out), mime_type="image/png")


def _data_uri(path: str) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    mime = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


class OpenAIImageProvider:
    name = "openai:gpt-image-2"

    def __init__(self) -> None:
        load_env_file()
        self.client = OpenAI()

    def generate(self, *, prompt: str, size: str = "1024x1024", quality: str = "medium") -> ProviderResult:
        refiner = PromptRefiner()
        result = self.client.images.generate(**refiner.generation_params(prompt, size=size, quality=quality))
        return _save_b64_image(result.data[0].b64_json, "generated", "openai")

    def edit(self, *, prompt: str, image_path: str, mask_path: str | None = None, size: str = "auto", quality: str = "medium") -> ProviderResult:
        refiner = PromptRefiner()
        kwargs = {
            "model": "gpt-image-2",
            "prompt": refiner.refine(prompt),
            "size": size,
            "quality": quality,
            "output_format": "png",
            "n": 1,
        }
        with open(image_path, "rb") as image_file:
            if mask_path:
                with open(mask_path, "rb") as mask_file:
                    result = self.client.images.edit(image=image_file, mask=mask_file, **kwargs)
            else:
                result = self.client.images.edit(image=image_file, **kwargs)
        return _save_b64_image(result.data[0].b64_json, "edited", "openai")


class FalGPTImageProvider:
    """FAL fallback for GPT Image 2.

    Uses fal.run sync endpoints. Requires FAL_KEY. For edits, local images are sent
    as data URIs in image_urls.
    """

    name = "fal:openai/gpt-image-2"

    def __init__(self) -> None:
        load_env_file()
        self.key = os.getenv("FAL_KEY")
        if not self.key:
            raise RuntimeError("FAL_KEY is not configured")

    def _post(self, endpoint: str, payload: dict) -> dict:
        response = requests.post(
            f"https://fal.run/{endpoint}",
            headers={"Authorization": f"Key {self.key}", "Content-Type": "application/json"},
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        return response.json()

    def _download_result(self, data: dict, prefix: str) -> ProviderResult:
        images = data.get("images") or []
        if not images:
            raise RuntimeError(f"FAL returned no images: {data}")
        first = images[0]
        out = OUTPUT_DIR / f"{prefix}_fal_{int(time.time() * 1000)}.png"
        if first.get("url", "").startswith("data:"):
            b64 = first["url"].split(",", 1)[1]
            out.write_bytes(base64.b64decode(b64))
        else:
            img = requests.get(first["url"], timeout=180)
            img.raise_for_status()
            out.write_bytes(img.content)
        return ProviderResult(provider=self.name, image_path=str(out), mime_type="image/png")

    def generate(self, *, prompt: str, size: str = "1024x1024", quality: str = "medium") -> ProviderResult:
        refiner = PromptRefiner()
        payload = {
            "prompt": refiner.refine(prompt),
            "image_size": size if "x" not in size else "square_hd",
            "quality": quality,
            "num_images": 1,
            "output_format": "png",
        }
        return self._download_result(self._post("openai/gpt-image-2", payload), "generated")

    def edit(self, *, prompt: str, image_path: str, mask_path: str | None = None, size: str = "auto", quality: str = "medium") -> ProviderResult:
        refiner = PromptRefiner()
        payload = {
            "prompt": refiner.refine(prompt),
            "image_urls": [_data_uri(image_path)],
            "image_size": "auto",
            "quality": quality,
            "num_images": 1,
            "output_format": "png",
        }
        if mask_path:
            payload["mask_url"] = _data_uri(mask_path)
        return self._download_result(self._post("openai/gpt-image-2/edit", payload), "edited")


def default_providers() -> list[ImageProvider]:
    providers: list[ImageProvider] = [OpenAIImageProvider()]
    try:
        providers.append(FalGPTImageProvider())
    except Exception:
        # FAL is optional fallback; if not configured the app still works with OpenAI.
        pass
    return providers


def generate_or_edit_with_fallback(
    *,
    mode: str,
    prompt: str,
    providers: Iterable[ImageProvider],
    image_path: str | None = None,
    mask_path: str | None = None,
    size: str = "1024x1024",
    quality: str = "medium",
) -> ProviderResult:
    errors: list[str] = []
    for provider in providers:
        try:
            if mode == "generate":
                return provider.generate(prompt=prompt, size=size, quality=quality)
            if mode == "edit":
                if not image_path:
                    raise ValueError("image_path is required for edit mode")
                return provider.edit(prompt=prompt, image_path=image_path, mask_path=mask_path, size="auto", quality=quality)
            raise ValueError(f"Unsupported mode: {mode}")
        except Exception as exc:  # collect and try fallback
            errors.append(f"{getattr(provider, 'name', provider.__class__.__name__)} failed: {exc}")
    raise RuntimeError("; ".join(errors) or "No providers configured")
