"""Cliente unificado de IA generativa (Gemini) para todo el pipeline editorial.

Expone ``chat_completion`` con la misma forma de ``messages`` (role/content,
estilo OpenAI Chat Completions) que ya usaban los módulos de openIA/ y
utils/classifier.py, para minimizar el diff de la migración de OpenAI a
Gemini. El detalle de mapear esos mensajes al formato de contents/roles de
Gemini queda encapsulado acá.
"""
from __future__ import annotations

import os
import time
from typing import Mapping, Sequence

from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-3.1-flash-lite"


class AIClientError(RuntimeError):
    """Falla al invocar el proveedor de IA generativa (Gemini)."""


def _to_gemini_contents(
    messages: Sequence[Mapping[str, str]],
) -> tuple[str | None, list[types.Content]]:
    """Convierte mensajes role/content (system/user/assistant) al formato Gemini.

    Gemini no tiene rol "system" en ``contents``: se pasa aparte como
    ``system_instruction``. El rol "assistant" pasa a "model", el resto
    ("user") queda igual.
    """
    system_parts: list[str] = []
    contents: list[types.Content] = []
    for message in messages:
        role = message.get("role")
        text = str(message.get("content") or "")
        if role == "system":
            system_parts.append(text)
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append(types.Content(role=gemini_role, parts=[types.Part.from_text(text=text)]))
    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


def _record_instrumentation(
    *,
    stage: str | None,
    article_id: str | None,
    model_used: str,
    started_at: float,
    input_chars: int,
    output_chars: int,
    usage_metadata: object,
    success: bool,
) -> None:
    if not stage:
        return
    try:
        from editorial_context import instrumentation
    except Exception:
        return

    tokens_in = getattr(usage_metadata, "prompt_token_count", None) if usage_metadata else None
    tokens_out = getattr(usage_metadata, "candidates_token_count", None) if usage_metadata else None
    tokens_estimated = tokens_in is None and tokens_out is None
    if tokens_estimated:
        tokens_in = instrumentation.estimate_tokens(" " * input_chars)
        tokens_out = instrumentation.estimate_tokens(" " * output_chars)

    try:
        instrumentation.record_ai_call(
            stage=stage,
            model=model_used,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            input_chars=input_chars,
            output_chars=output_chars,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_estimated=tokens_estimated,
            success=success,
            article_id=article_id or "",
        )
    except Exception:
        pass


def chat_completion(
    *,
    messages: Sequence[Mapping[str, str]],
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 800,
    timeout: float = 60.0,
    json_mode: bool = False,
    stage: str | None = None,
    article_id: str | None = None,
) -> str:
    """Ejecuta una llamada de chat contra Gemini y devuelve el texto de la respuesta.

    Lanza ``AIClientError`` si falta la API key o si Gemini responde vacío;
    cualquier otra excepción del SDK (red, rate limit, etc.) se propaga tal
    cual para que el reintento del call site la capture.

    ``stage``/``article_id`` son opcionales y sólo activan instrumentación
    (Parte 47, ``editorial_context.instrumentation``): ningún call site
    existente los pasa hoy, así que el comportamiento por defecto no cambia.
    """
    key = api_key or os.getenv("GEMINI_API_KEY", "")
    if not key or key == "PENDIENTE":
        raise AIClientError("GEMINI_API_KEY no configurada")

    model_used = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    input_chars = sum(len(str(message.get("content") or "")) for message in messages)
    started_at = time.perf_counter()

    client = genai.Client(api_key=key)
    system_instruction, contents = _to_gemini_contents(messages)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
        max_output_tokens=max_tokens,
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        response_mime_type="application/json" if json_mode else "text/plain",
    )
    try:
        response = client.models.generate_content(
            model=model_used,
            contents=contents,
            config=config,
        )
    except Exception:
        _record_instrumentation(
            stage=stage,
            article_id=article_id,
            model_used=model_used,
            started_at=started_at,
            input_chars=input_chars,
            output_chars=0,
            usage_metadata=None,
            success=False,
        )
        raise

    text = (response.text or "").strip()
    _record_instrumentation(
        stage=stage,
        article_id=article_id,
        model_used=model_used,
        started_at=started_at,
        input_chars=input_chars,
        output_chars=len(text),
        usage_metadata=getattr(response, "usage_metadata", None),
        success=bool(text),
    )
    if not text:
        raise AIClientError("Respuesta vacía de Gemini")
    return text
