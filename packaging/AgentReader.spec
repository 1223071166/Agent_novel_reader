# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for AgentReader.

Run this file from the repository root:

    .venv-build/Scripts/python.exe -m PyInstaller packaging/AgentReader.spec --clean --noconfirm

The first build intentionally keeps a console window. It makes missing-module
and model-loading errors visible while the packaged application is being
validated on clean Windows machines.
"""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)


SPEC_DIR = Path(SPEC).resolve().parent
PROJECT_ROOT = SPEC_DIR.parent
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

if not (FRONTEND_DIST / "index.html").is_file():
    raise SystemExit(
        "缺少 frontend/dist/index.html。请先运行：npm --prefix frontend run build"
    )
if not any((FRONTEND_DIST / "assets").glob("*.js")):
    raise SystemExit(
        "frontend/dist/assets 中没有 JavaScript 文件。请重新构建前端。"
    )


# ChromaDB loads migration files at runtime. Package metadata is also used by
# several AI libraries for runtime dependency/version checks.
datas = [
    (str(FRONTEND_DIST), "frontend/dist"),
]
datas += collect_data_files("chromadb")
datas += copy_metadata("chromadb")
datas += copy_metadata("FlagEmbedding")


# PyInstaller's contributed hooks already handle the large Torch binaries and
# Transformers metadata. These additional imports cover modules selected by
# model configuration strings and ChromaDB's runtime component loader.
hiddenimports = [
    "chromadb.api.rust",
    "chromadb_rust_bindings",
    "chromadb.db.impl.sqlite",
    "chromadb.execution.executor.local",
    "chromadb.ingest.impl.simple_policy",
    "chromadb.quota.simple_quota_enforcer",
    "chromadb.rate_limit.simple_rate_limit",
    "chromadb.segment.impl.manager.local",
    "chromadb.telemetry.product.posthog",
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl",
]
hiddenimports += collect_submodules("transformers.models.bert")
hiddenimports += collect_submodules("transformers.models.xlm_roberta")

# transformers builds its Auto* model registries dynamically.  PyInstaller's
# static analysis currently misses several model packages added in the pinned
# transformers 4.57.6 release.  Even though AgentReader does not use these
# architectures directly, querying an Auto* registry can import them at
# runtime (metaclip_2 is one example).  Keep the frozen registry complete so a
# semantic-search request does not fail with ModuleNotFoundError.
transformers_dynamic_models = [
    "apertus",
    "doge",
    "eomt",
    "ernie4_5",
    "ernie4_5_moe",
    "glm4_moe",
    "glm4v",
    "glm4v_moe",
    "kosmos2_5",
    "metaclip_2",
    "mm_grounding_dino",
    "smollm3",
]
for model_package in transformers_dynamic_models:
    hiddenimports += collect_submodules(f"transformers.models.{model_package}")


a = Analysis(
    [str(PROJECT_ROOT / "packaging" / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    module_collection_mode={
        "FlagEmbedding": "pyz+py",
    },
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentReader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AgentReader",
)
