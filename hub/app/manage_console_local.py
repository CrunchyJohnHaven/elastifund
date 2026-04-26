from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from hub.app.main import app
from hub.app.manage_control_plane import control_plane, router as control_plane_router


REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
JJN_REPORT_ALIAS = REPORTS_DIR / "jjn_public_report.json"
NONTRADING_REPORT = REPORTS_DIR / "nontrading_public_report.json"
SINGLE_PAGE_ROUTES = {
    "home": REPO_ROOT / "index.html",
    "live": REPO_ROOT / "live" / "index.html",
    "develop": REPO_ROOT / "develop" / "index.html",
    "elastic": REPO_ROOT / "elastic" / "index.html",
    "leaderboards": REPO_ROOT / "leaderboards" / "index.html",
    "roadmap": REPO_ROOT / "roadmap" / "index.html",
    "blueprint": REPO_ROOT / "blueprint" / "index.html",
    "consult": REPO_ROOT / "consult" / "index.html",
    "diary": REPO_ROOT / "diary" / "index.html",
    "docs": REPO_ROOT / "docs" / "index.html",
}
EXACT_FILE_ROUTES = {
    "/": SINGLE_PAGE_ROUTES["home"],
    "/index.html": SINGLE_PAGE_ROUTES["home"],
    "/manage/": REPO_ROOT / "manage" / "index.html",
    "/manage-console.js": REPO_ROOT / "manage-console.js",
    "/manage-console.css": REPO_ROOT / "manage-console.css",
    "/site.js": REPO_ROOT / "site.js",
    "/site.css": REPO_ROOT / "site.css",
    "/improvement_velocity.json": REPO_ROOT / "improvement_velocity.json",
    "/improvement_velocity.svg": REPO_ROOT / "improvement_velocity.svg",
    "/arr_estimate.svg": REPO_ROOT / "arr_estimate.svg",
    "/inventory/data/systems.json": REPO_ROOT / "inventory" / "data" / "systems.json",
    "/jjn_public_report.json": REPORTS_DIR / "nontrading_public_report.json",
}
EXACT_REDIRECT_ROUTES = {
    "/home": "/",
    "/home/": "/",
    "/manage": "/manage/",
    "/control-plane": "/manage/?panel=control-plane",
    "/control-plane/": "/manage/?panel=control-plane",
}
for section, target in SINGLE_PAGE_ROUTES.items():
    if section == "home":
        continue
    EXACT_REDIRECT_ROUTES[f"/{section}"] = f"/{section}/"
    EXACT_FILE_ROUTES[f"/{section}/"] = target

app.include_router(control_plane_router)


@app.on_event("startup")
async def _start_manage_control_plane() -> None:
    if NONTRADING_REPORT.exists():
        JJN_REPORT_ALIAS.write_text(
            NONTRADING_REPORT.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    await control_plane.start()


@app.on_event("shutdown")
async def _stop_manage_control_plane() -> None:
    await control_plane.stop()


def _file_response(path: Path) -> FileResponse:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path.name}")
    return FileResponse(path)


@app.middleware("http")
async def _serve_local_console_routes(request: Request, call_next):
    path = request.url.path
    redirect_target = EXACT_REDIRECT_ROUTES.get(path)
    if redirect_target:
        return RedirectResponse(url=redirect_target, status_code=307)
    file_target = EXACT_FILE_ROUTES.get(path)
    if file_target is not None:
        return _file_response(file_target)
    return await call_next(request)


@app.get("/", include_in_schema=False)
def home_index() -> FileResponse:
    return _file_response(SINGLE_PAGE_ROUTES["home"])


@app.get("/manage", include_in_schema=False)
def manage_redirect() -> RedirectResponse:
    return RedirectResponse(url="/manage/", status_code=307)


@app.get("/manage/", include_in_schema=False)
def manage_index() -> FileResponse:
    return _file_response(REPO_ROOT / "manage" / "index.html")


@app.get("/control-plane", include_in_schema=False)
def control_plane_redirect() -> RedirectResponse:
    return RedirectResponse(url="/manage/?panel=control-plane", status_code=307)


@app.get("/control-plane/", include_in_schema=False)
def control_plane_index() -> RedirectResponse:
    return RedirectResponse(url="/manage/?panel=control-plane", status_code=307)


@app.get("/manage-console.js", include_in_schema=False)
def manage_console_js() -> FileResponse:
    return _file_response(REPO_ROOT / "manage-console.js")


@app.get("/manage-console.css", include_in_schema=False)
def manage_console_css() -> FileResponse:
    return _file_response(REPO_ROOT / "manage-console.css")


@app.get("/site.js", include_in_schema=False)
def site_js() -> FileResponse:
    return _file_response(REPO_ROOT / "site.js")


@app.get("/site.css", include_in_schema=False)
def site_css() -> FileResponse:
    return _file_response(REPO_ROOT / "site.css")


@app.get("/improvement_velocity.json", include_in_schema=False)
def improvement_velocity_json() -> FileResponse:
    return _file_response(REPO_ROOT / "improvement_velocity.json")


@app.get("/improvement_velocity.svg", include_in_schema=False)
def improvement_velocity_svg() -> FileResponse:
    return _file_response(REPO_ROOT / "improvement_velocity.svg")


@app.get("/arr_estimate.svg", include_in_schema=False)
def arr_estimate_svg() -> FileResponse:
    return _file_response(REPO_ROOT / "arr_estimate.svg")


@app.get("/inventory/data/systems.json", include_in_schema=False)
def inventory_systems_json() -> FileResponse:
    return _file_response(REPO_ROOT / "inventory" / "data" / "systems.json")


@app.get("/jjn_public_report.json", include_in_schema=False)
def jjn_public_report_json() -> FileResponse:
    return _file_response(REPORTS_DIR / "nontrading_public_report.json")


@app.get("/leaderboards/{board}/", include_in_schema=False)
def leaderboard_index(board: str) -> FileResponse:
    path = REPO_ROOT / "leaderboards" / board / "index.html"
    return _file_response(path)


@app.get("/{section}", include_in_schema=False)
def section_redirect(section: str) -> RedirectResponse:
    if section == "control-plane":
        return RedirectResponse(url="/manage/?panel=control-plane", status_code=307)
    if section in SINGLE_PAGE_ROUTES and section != "home":
        return RedirectResponse(url=f"/{section}/", status_code=307)
    raise HTTPException(status_code=404, detail="Not Found")


@app.get("/{section}/", include_in_schema=False, response_model=None)
def section_index(section: str) -> Response:
    if section == "control-plane":
        return RedirectResponse(url="/manage/?panel=control-plane", status_code=307)
    if section in SINGLE_PAGE_ROUTES and section != "home":
        return _file_response(SINGLE_PAGE_ROUTES[section])
    raise HTTPException(status_code=404, detail="Not Found")


if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="manage-console-reports")
