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
from .curriculum import courses, get_lesson
from .config import Settings
from .diagnostics import viewer_capability
from .gateway import IsolationHeaders, ViewerGateway
from .physics import simulate
from .sessions import SessionManager

class ExperimentRequest(BaseModel):
    experiment_id: str


class RunRequest(ExperimentRequest):
    duration: float | None = Field(default=None, gt=0, le=30)
    settings: dict | None = None


class SessionCommand(BaseModel):
    session_id: UUID
    action: str
    settings: dict = Field(default_factory=dict)
    paused: bool = True


def create_app(runtime: Path | None = None, *, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    runtime = runtime or settings.data_dir
    manager = SessionManager(runtime / "sessions")
    gateway = ViewerGateway(manager)

    @asynccontextmanager
    async def lifespan(_app):
        runtime.mkdir(parents=True, exist_ok=True)
        try:
            yield
        finally:
            manager.stop()
            await gateway.close()

    app = FastAPI(title="Robotics Lab", version=__version__, lifespan=lifespan)
    app.add_middleware(IsolationHeaders)
    gateway.install(app)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/system")
    def system():
        return {"version": __version__, "viewer": viewer_capability(), "session": manager.status()}

    @app.get("/api/catalog")
    def list_experiments():
        return [item.public() for item in catalog().values()]

    @app.get("/api/courses")
    def list_courses():
        return courses()

    @app.get("/api/lessons/{identifier}")
    def lesson(identifier: str):
        try:
            result = get_lesson(identifier)
            result["experiment"] = get_experiment(result["experiment_id"]).public()
            return result
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/api/runs", status_code=201)
    def run(request: RunRequest):
        try:
            result = simulate(get_experiment(request.experiment_id), request.duration, request.settings)
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

    @app.get("/api/sessions/current/state")
    def session_state():
        return manager.state()

    @app.post("/api/sessions/current/commands")
    def command(request: SessionCommand):
        try:
            return manager.command(str(request.session_id), request.model_dump(exclude={"session_id"}))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    dist = settings.static_dir
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse)
        def setup_help():
            return '<html lang="zh-CN"><meta charset="utf-8"><h1>Robotics Lab</h1><p>前端尚未构建，请按 README 完成安装与构建。</p><a href="/docs">查看应用接口</a></html>'
    return app
