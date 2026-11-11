"""Instala el alineador local de los subtítulos del Noticiero (whisper.cpp).

Descarga una sola vez, fuera de la corrida nocturna, el binario CPU de
whisper.cpp y el modelo multilingüe ``ggml-small-q5_1`` con versión y
SHA-256 fijos. Nada se descarga durante el render: si falta el alineador, el
noticiero V3 sale sin subtítulos y lo informa (nunca con tiempos inventados).

Uso:
    python scripts/install_newscast_aligner.py           # instala o verifica
    python scripts/install_newscast_aligner.py --check   # sólo verifica

Licencias: whisper.cpp y los modelos Whisper (OpenAI) son MIT.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from utils.newscast_align import (  # noqa: E402
    MODEL_FILE,
    MODEL_SHA256,
    MODEL_URL,
    WHISPER_ZIP_SHA256,
    WHISPER_ZIP_URL,
    aligner_dir,
    aligner_status,
)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: str, sha256: str) -> None:
    import requests

    print(f"Descargando {url} …")
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in response.iter_content(1 << 20):
                fh.write(chunk)
    actual = _sha256(dest)
    if actual != sha256:
        os.remove(dest)
        raise SystemExit(f"SHA-256 no coincide para {url}: {actual}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Alineador local del noticiero")
    parser.add_argument("--check", action="store_true", help="sólo verifica la instalación")
    opts = parser.parse_args()
    root = aligner_dir()
    status = aligner_status()
    if status["ok"] or opts.check:
        print(("Alineador listo en " if status["ok"] else "Alineador incompleto: ") + str(status))
        return 0 if status["ok"] else 1
    os.makedirs(root, exist_ok=True)
    if not status["binary"]:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "whisper.zip")
            _download(WHISPER_ZIP_URL, zip_path, WHISPER_ZIP_SHA256)
            with zipfile.ZipFile(zip_path) as archive:
                for member in archive.namelist():
                    name = os.path.basename(member)
                    # Sólo binarios y DLLs del release, sin rutas del zip.
                    if not name or not name.lower().endswith((".exe", ".dll")):
                        continue
                    with archive.open(member) as src, open(os.path.join(root, name), "wb") as dst:
                        shutil.copyfileobj(src, dst)
    if not status["model"]:
        _download(MODEL_URL, os.path.join(root, MODEL_FILE), MODEL_SHA256)
    status = aligner_status()
    print(("Alineador listo en " if status["ok"] else "Alineador incompleto: ") + str(status))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
