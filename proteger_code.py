#!/usr/bin/env python3
"""
Protection du code de l'édition hors ligne : compile le backend Django (fichiers .py) en modules binaires (Cython), puis supprime les sources.
Un client qui ouvre le dossier installé ne trouve plus de code Python lisible (il ne reste que du code machine).

Usage :   python proteger_code.py <dossier_backend_source> <dossier_sortie>
Exemple : python proteger_code.py ..\\erp-louba-backend build\\erp_project_protege
Prérequis (sur la machine qui fabrique l'installateur, même système et même version de Python que l'exécutable final) :
    pip install cython setuptools wheel      + un compilateur C (Windows : « Build Tools for Visual Studio » ; Linux : gcc)

Laissés en clair (Django les lit comme du texte ou par leur nom) : manage.py, __init__.py, apps.py, les migrations, les réglages (config/settings.py)
et les URLs. Tout le reste (modèles, vues, calculs comptables, licences, plans) est compilé.
Ensuite, packagez le dossier de sortie à la place du backend lisible (voir build_offline_pur.py).
Limite honnête : aucune compilation ne rend le code inviolable ; elle supprime la lecture directe et rend la copie coûteuse. La vraie protection
reste la clé de licence signée (clé publique seule dans le logiciel) et les limites du plan appliquées par la licence.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONSERVER = {"manage.py", "__init__.py", "apps.py", "settings.py", "urls.py", "wsgi.py", "asgi.py", "setup.py"}
IGNORER_DOSSIERS = {"migrations", "__pycache__", "tests_data", ".git", "node_modules", "static", "staticfiles"}


def sources_a_compiler(racine: Path):
    for p in racine.rglob("*.py"):
        rel = p.relative_to(racine)
        if any(part in IGNORER_DOSSIERS for part in rel.parts):
            continue
        if p.name in CONSERVER or p.name.startswith("tests") or "." in p.stem:
            continue
        yield p


def main(src, sortie):
    src, sortie = Path(src).resolve(), Path(sortie).resolve()
    if sortie.exists():
        shutil.rmtree(sortie)
    shutil.copytree(src, sortie, ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", "*.pyc"))
    fichiers = list(sources_a_compiler(sortie))
    # Les tests ne sont pas livrés dans l'installateur.
    for t in list(sortie.rglob("tests*.py")):
        t.unlink()
    print(f"{len(fichiers)} fichiers à compiler…")
    from Cython.Build import cythonize
    ok, laisses = [], []
    for f in fichiers:
        # Un fichier que Cython ne sait pas traduire reste en clair (signalé à la fin) au lieu de bloquer toute la fabrication.
        try:
            cythonize([str(f)], compiler_directives={"language_level": "3"}, quiet=True)
            if f.with_suffix(".c").exists():
                ok.append(f)
                continue
        except BaseException:  # noqa: BLE001
            pass
        f.with_suffix(".c").unlink(missing_ok=True)
        laisses.append(f)
    modules = [(".".join(f.relative_to(sortie).with_suffix("").parts), str(f.with_suffix(".c").relative_to(sortie)).replace("\\", "/")) for f in ok]
    setup = sortie / "_setup_protection.py"
    setup.write_text(
        "from setuptools import setup, Extension\n"
        f"mods = {modules!r}\n"
        "setup(ext_modules=[Extension(n, [c]) for n, c in mods])\n", encoding="utf-8")
    subprocess.check_call([sys.executable, setup.name, "build_ext", "--inplace"], cwd=sortie)
    for f in ok:
        f.unlink(missing_ok=True)
        f.with_suffix(".c").unlink(missing_ok=True)
    if laisses:
        print("Restés en clair (non compilables) :", ", ".join(str(f.relative_to(sortie)) for f in laisses))
    shutil.rmtree(sortie / "build", ignore_errors=True)
    setup.unlink(missing_ok=True)
    binaires = [p for p in sortie.rglob("*") if p.suffix in (".so", ".pyd")]
    print(f"Terminé : {len(binaires)} modules binaires dans {sortie}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
