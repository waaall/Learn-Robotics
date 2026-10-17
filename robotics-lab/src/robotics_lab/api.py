"""本地目录、独立数值验证与查看器会话接口。"""

from contextlib import asynccontextmanager
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .catalog import catalog, get_experiment
from .diagnostics import viewer_capability
from .physics import simulate
from .sessions import SessionManager

PROJECT = Path(__file__).resolve().parents[2]


class ExperimentRequest(BaseModel):
    experiment_id: str


class RunRequest(ExperimentRequest):
    duration: float | None = Field(default=None, gt=0, le=10)


def create_app(runtime: Path | None = None) -> FastAPI:
    runtime = runtime or PROJECT / ".runtime"
    manager = SessionManager(runtime / "sessions")

    @asynccontextmanager
    async def lifespan(_app):
        yield
        manager.stop()

    app = FastAPI(title="Robotics Lab", version=__version__, lifespan=lifespan)

    @app.get("/api/system")
    def system():
        return {"version": __version__, "viewer": viewer_capability(), "session": manager.status()}

    @app.get("/api/catalog")
    def list_experiments():
        return [item.public() for item in catalog().values()]

    @app.post("/api/runs", status_code=201)
    def run(request: RunRequest):
        try:
            result = simulate(get_experiment(request.experiment_id), request.duration)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        identifier = str(uuid4())
        result["id"] = identifier
        directory = runtime / "runs"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{identifier}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
        return result

    @app.get("/api/runs/{identifier}")
    def read_run(identifier: UUID):
        path = runtime / "runs" / f"{identifier}.json"
        if not path.is_file():
            raise HTTPException(404, "运行记录不存在")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.post("/api/sessions", status_code=201)
    def start(request: ExperimentRequest):
        try:
            return manager.start(request.experiment_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @app.delete("/api/sessions/current", status_code=204)
    def stop():
        manager.stop()

    @app.get("/api/sessions/current")
    def session():
        return manager.status()

    dist = PROJECT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse)
        def setup_help():
            return '<html lang="zh-CN"><meta charset="utf-8"><h1>Robotics Lab</h1><p>前端尚未构建，请按 README 完成安装与构建。</p><a href="/docs">查看应用接口</a></html>'
    return app
