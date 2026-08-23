"""
InventAI Local Dev Server
=========================
Single FastAPI process exposing all /api/v1/* routes for local development.
Mirrors what Docker does: renames hyphenated service folders to underscored
package names, injects __init__.py files, and patches circular imports.

Run from the repo root:

    python dev_server.py
"""

import os
import re
import sys
import shutil
import logging

# ── Repo root ─────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

# ── Load .env ─────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("dev_server")

# ── Staging directory (mirrors Docker /app layout) ────────────────────────────
STAGING = os.path.join(ROOT, ".dev_pkg")
os.makedirs(STAGING, exist_ok=True)

SERVICE_MAP = {
    "services/business-service": "services/business_service",
    "services/cad-service":      "services/cad_service",
    "services/physics-service":  "services/physics_service",
    "services/research-service": "services/research_service",
    "services/patent-service":   "services/patent_service",
    "services/report-service":   "services/report_service",
    "packages/ai-core":          "packages/ai_core",
    "packages/ai":               "packages/ai",
    "packages/schemas":          "packages/schemas",
    "packages/logger":           "packages/logger",
}

# These application_service.py files end with `app = FastAPI(...)` +
# `from services.X.api.routers import router` causing circular imports.
# We strip those trailing lines from the staged copies.
CIRCULAR_PATCH_FILES = {
    "services/physics_service/application/physics_service.py",
    "services/report_service/application/report_service.py",
    "services/cad_service/application/cad_service.py",
    "services/research_service/application/research_service.py",
    "services/patent_service/application/patent_service.py",
}

# Pydantic-settings v2 compatible replacements for config files that use
# the old inner `class Config` pattern and non-Optional `str` for API keys.
CONTENT_PATCHES: dict[str, str] = {
    "packages/ai_core/config.py": """\
import os
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional

class AICoreConfig(BaseSettings):
    openrouter_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    default_model: str = os.getenv("DEFAULT_LLM_MODEL", "nvidia/nemotron-3.5-lightning:free")
    default_provider: str = os.getenv("DEFAULT_LLM_PROVIDER", "openrouter")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    max_retries: int = 3
    timeout_seconds: int = 60

    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator("openrouter_api_key", "openai_api_key", "anthropic_api_key", mode="before")
    @classmethod
    def _coerce(cls, v):
        return str(v).strip() if v else None

config = AICoreConfig()
""",
    "packages/ai_core/models/config.py": """\
import os
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List, Optional

class ModelConfig(BaseSettings):
    openrouter_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    azure_openai_key: Optional[str] = None
    openrouter_model: str = os.getenv("DEFAULT_LLM_MODEL", "nvidia/nemotron-3.5-lightning:free")
    default_failover_chain: str = "openrouter,openai"
    max_retries: int = 3
    timeout_ms: int = 30000
    redis_cache_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/1")
    enable_caching: bool = True

    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator(
        "openrouter_api_key", "openai_api_key", "anthropic_api_key", "gemini_api_key",
        "azure_openai_key",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v):
        return str(v).strip() or None if v else None

    @property
    def failover_providers(self) -> List[str]:
        return [p.strip().lower() for p in self.default_failover_chain.split(",")]

config = ModelConfig()
""",
}

_CIRCULAR_STRIP_RE = re.compile(
    r"""
    # Match the block starting with the FastAPI app instantiation
    \n*^#\s*─+\s*FastAPI app\s*─+.*?$   # comment divider  (optional)
    |
    \n*^app\s*=\s*FastAPI\(.*?(?=\n\S|\Z)  # app = FastAPI(...)
    |
    \n*^@app\.on_event\(.*?(?=\n@|\n\S|\Z) # @app.on_event block
    |
    \n*^#\s*Lazy import.*$               # "Lazy import" comment
    |
    \n*^from\s+services\.\w+.*?import\s+router.*$ # the circular import line
    """,
    re.MULTILINE | re.VERBOSE | re.DOTALL,
)

def _patch_circular(content: str) -> str:
    """
    Remove everything from the FastAPI app-creation block downward.
    These application_service.py files end with:
        # Create and configure FastAPI app   (or # ── FastAPI app ──)
        app = FastAPI(...)
        @app.on_event(...)   (optional)
        from services.X.api.routers import router   ← circular!
        app.include_router(router)
    We cut at the first marker line so the class above stays intact.
    """
    MARKERS = (
        "# Create and configure FastAPI app",
        "# ── FastAPI app",
        "# ─── FastAPI app",
    )
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(stripped.startswith(m) for m in MARKERS):
            # Cut here — keep everything above
            return "".join(lines[:i])
        # Also cut if we hit a bare `app = FastAPI(` at column 0
        if stripped.startswith("app = FastAPI(") and not line.startswith(" "):
            return "".join(lines[:i])
    return content


def _sync_tree(src_abs: str, dst_abs: str, dst_rel: str):
    os.makedirs(dst_abs, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src_abs):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        rel_dir = os.path.relpath(dirpath, src_abs)
        dst_dir = os.path.join(dst_abs, rel_dir) if rel_dir != "." else dst_abs
        os.makedirs(dst_dir, exist_ok=True)

        # Ensure __init__.py exists
        init = os.path.join(dst_dir, "__init__.py")
        if not os.path.exists(init):
            open(init, "w").close()

        for fname in filenames:
            if fname == "__init__.py":
                continue
            src_f = os.path.join(dirpath, fname)
            dst_f = os.path.join(dst_dir, fname)

            # Determine staged relative path for patch detection
            rel_file = os.path.relpath(dst_f, STAGING).replace("\\", "/")
            needs_patch = rel_file in CIRCULAR_PATCH_FILES

            src_mtime = os.path.getmtime(src_f)
            dst_mtime = os.path.getmtime(dst_f) if os.path.exists(dst_f) else 0

            if src_mtime > dst_mtime or needs_patch:
                if needs_patch and fname.endswith(".py"):
                    with open(src_f, "r", encoding="utf-8") as fh:
                        content = fh.read()
                    content = _patch_circular(content)
                    with open(dst_f, "w", encoding="utf-8") as fh:
                        fh.write(content)
                else:
                    shutil.copy2(src_f, dst_f)

            # Apply verbatim content patches (config file rewrites)
            rel_file_fwd = rel_file.replace("\\", "/")
            if rel_file_fwd in CONTENT_PATCHES:
                with open(dst_f, "w", encoding="utf-8") as fh:
                    fh.write(CONTENT_PATCHES[rel_file_fwd])


def _build_staging():
    # Namespace __init__.py files
    for ns in ["services", "packages"]:
        ns_dir = os.path.join(STAGING, ns)
        os.makedirs(ns_dir, exist_ok=True)
        init = os.path.join(ns_dir, "__init__.py")
        if not os.path.exists(init):
            open(init, "w").close()

    for src_rel, dst_rel in SERVICE_MAP.items():
        src_abs = os.path.join(ROOT, src_rel)
        dst_abs = os.path.join(STAGING, dst_rel)
        if os.path.isdir(src_abs):
            _sync_tree(src_abs, dst_abs, dst_rel)
            log.info("staged  %-42s → %s", src_rel, dst_rel)
        else:
            log.warning("source not found, skipping: %s", src_rel)


log.info("Building staging tree in %s …", STAGING)
_build_staging()

# ── sys.path ──────────────────────────────────────────────────────────────────
if STAGING not in sys.path:
    sys.path.insert(0, STAGING)

# ── Tmp export dirs ───────────────────────────────────────────────────────────
for d in ["/tmp/cad_exports", "/tmp/physics_exports",
          "/tmp/business_exports", "/tmp/report_exports"]:
    os.makedirs(d, exist_ok=True)

# ── FastAPI app ────────────────────────────────────────────────────────────────
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="InventAI Dev Server", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _try_mount(label: str, import_fn):
    try:
        router = import_fn()
        app.include_router(router)
        log.info("✓  %-30s mounted", label)
        return True
    except Exception as exc:
        log.warning("✗  %-30s SKIPPED — %s", label, exc)
        return False


def _business():
    from services.business_service.app.api.routers import router
    return router

def _report():
    from services.report_service.api.routers import router
    return router

def _physics():
    from services.physics_service.api.routers import router
    return router

def _cad():
    from services.cad_service.api.routers import router
    return router

def _research():
    # Research service may fail if OPENAI_API_KEY is not fully set
    # We'll create a minimal router if the import fails
    try:
        from services.research_service.api.routers import router
        return router
    except Exception as e:
        # Create a fallback router if research service import fails
        from fastapi import APIRouter
        fallback = APIRouter(prefix="/api/v1/research", tags=["Research"])
        
        @fallback.post("/search")
        def search_fallback(query: dict):
            return {"error": f"Research service unavailable: {str(e)}", "message": "Ensure OPENAI_API_KEY is set in .env"}
        
        @fallback.get("/health")
        def health():
            return {"status": "degraded", "reason": "Missing configuration"}
        
        return fallback

def _patents():
    from services.patent_service.api.routers import router
    return router


_try_mount("business  /api/v1/business",  _business)
_try_mount("report    /api/v1/reports",   _report)
_try_mount("physics   /api/v1/physics",   _physics)
_try_mount("cad       /api/v1/cad",       _cad)
_try_mount("research  /api/v1/research",  _research)
_try_mount("patents   /api/v1/patents",   _patents)


@app.get("/health")
def health():
    return {
        "status": "online",
        "routes": sorted(set(
            r.path for r in app.routes if hasattr(r, "path")
        )),
    }


if __name__ == "__main__":
    import uvicorn
    log.info("Starting InventAI dev server → http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
