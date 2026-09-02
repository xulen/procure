"""
Índice de avisos de adquisiciones del BID ya procesados (_notices_seen.json).

Separado del índice genérico de index.py porque la granularidad es distinta:
index.py dedup por proyecto (una convocatoria = un proyecto, como en CAF);
acá un mismo proyecto puede acumular avisos nuevos en corridas futuras, así
que el dedup tiene que ser por aviso individual.
"""

import json
import os

NOTICES_INDEX_FILENAME = "_notices_seen.json"


def _notices_index_path(output_root):
    return os.path.join(output_root, NOTICES_INDEX_FILENAME)


def load_notices_seen(output_root):
    """Carga el mapa {notice_id: {slug, status, local_path}} desde disco."""
    path = _notices_index_path(output_root)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_notices_seen(output_root, notices_seen):
    """Guarda el mapa de avisos ya procesados en disco."""
    os.makedirs(output_root, exist_ok=True)
    path = _notices_index_path(output_root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(notices_seen, f, ensure_ascii=False, indent=2)
