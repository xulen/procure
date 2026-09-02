"""
Módulo de operaciones de sistema de archivos.
Crea directorios y escribe archivos.
"""

import os


def ensure_dir(dir_path):
    """Asegura que un directorio exista (crea la cadena completa)."""
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)


def write_file(file_path, data):
    """Escribe un archivo binario en disco."""
    ensure_dir(os.path.dirname(file_path))
    with open(file_path, "wb") as f:
        f.write(data)


def write_text_file(file_path, content):
    """Escribe un archivo de texto en disco."""
    ensure_dir(os.path.dirname(file_path))
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


def get_project_dirs(output_root, project_slug):
    """
    Construye la ruta de un proyecto dentro de la estructura caf/{proyecto}/{documentos}.

    Returns:
        dict con 'project_dir' y 'docs_dir'.
    """
    project_dir = os.path.join(output_root, project_slug)
    docs_dir = os.path.join(project_dir, "documentos")
    return {"project_dir": project_dir, "docs_dir": docs_dir}
