"""The launcher's built-UI boundary: exact allowlist, headers and request provenance."""

from __future__ import annotations

import re
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.public_main import PUBLIC_API_PATHS, app, create_app
from backend.public_ui import UI_PAGE_ROUTES, UI_PUBLIC_FILES

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX = b'<!doctype html><div id="root"></div><script type="module" src="/assets/index-AbCd1234.js"></script>'


def test_page_allowlist_is_exactly_the_client_routes() -> None:
    source = (REPO_ROOT / "frontend/src/public/tutorials/lessonRoutes.ts").read_text(encoding="utf-8")
    client_routes = set(re.findall(r"'(/tutorials(?:/[a-z0-9-]+)?)'", source))
    assert "/tutorials" in client_routes and "/tutorials/lesson-1" in client_routes
    assert UI_PAGE_ROUTES == {"/"} | client_routes


def test_public_file_allowlist_is_exactly_frontend_public() -> None:
    public = REPO_ROOT / "frontend" / "public"
    assert UI_PUBLIC_FILES == {"/" + path.relative_to(public).as_posix() for path in public.rglob("*") if path.is_file()}


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "brand").mkdir()
    (tmp_path / "materials").mkdir()
    (tmp_path / "index.html").write_bytes(INDEX)
    (tmp_path / "assets" / "index-AbCd1234.js").write_text("export {};\n")
    (tmp_path / "assets" / "index-Xy_z-890.css").write_text("body{}\n")
    (tmp_path / "assets" / "unhashed.js").write_text("export {};\n")
    (tmp_path / "brand" / "coilem-mark.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>\n")
    (tmp_path / "materials" / "sample-custom-steel.csv").write_text("B_T,H_A_per_m\n0,0\n")
    (tmp_path / "unlisted.txt").write_text("not part of the UI allowlist\n")
    return tmp_path


@pytest.fixture
def port() -> int:
    """A dynamically selected port, as the launcher's fallback may choose."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def client(bundle: Path, port: int) -> TestClient:
    return TestClient(create_app(bound_port=port, ui_bundle=bundle), base_url=f"http://127.0.0.1:{port}")


def test_ui_routes_stay_out_of_the_api_schema(client: TestClient) -> None:
    served = set(client.get("/openapi.json").json()["paths"])
    assert served | {"/openapi.json"} == PUBLIC_API_PATHS


@pytest.mark.parametrize("route", sorted(UI_PAGE_ROUTES))
def test_every_client_route_serves_index_without_caching(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200
    assert response.content == INDEX
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("path", "content_type", "cache_control"),
    [
        ("/assets/index-AbCd1234.js", "text/javascript; charset=utf-8", "public, max-age=31536000, immutable"),
        ("/assets/index-Xy_z-890.css", "text/css; charset=utf-8", "public, max-age=31536000, immutable"),
        ("/assets/unhashed.js", "text/javascript; charset=utf-8", "no-cache"),
        ("/brand/coilem-mark.svg", "image/svg+xml", "no-cache"),
        ("/materials/sample-custom-steel.csv", "text/csv; charset=utf-8", "no-cache"),
    ],
)
def test_static_files_have_types_and_cache_policy(client: TestClient, path: str, content_type: str, cache_control: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert response.headers["cache-control"] == cache_control
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path",
    [
        "/assets/missing-AbCd1234.js",
        "/assets/",
        "/assets/nested/index-AbCd1234.js",
        "/index.html",
        "/unlisted.txt",
        "/tutorials/not-a-lesson",
        "/tutorials/lesson-1/not-an-api-route",
        "/tutorials/follow-the-flux/solve/extra",
        "/solve/not-an-api-route",
        "/brand/other.svg",
    ],
)
def test_everything_else_is_a_404_never_index(client: TestClient, path: str) -> None:
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 404
    assert response.content != INDEX
    assert b"<div id=\"root\">" not in response.content


def test_api_routes_sharing_a_page_prefix_still_reach_the_api(client: TestClient) -> None:
    # A page exists at /tutorials/follow-the-flux; its API sibling validates the query.
    response = client.get("/tutorials/follow-the-flux/solve?mesh_density=not-a-density")
    assert response.status_code == 422
    assert client.get("/materials").json()["steels"] == ["M350-50A"]


def test_other_loopback_names_redirect_pages_to_the_bound_origin(client: TestClient, port: int) -> None:
    response = client.get("/tutorials/lesson-1?view=a", headers={"Host": f"localhost:{port}"}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == f"http://127.0.0.1:{port}/tutorials/lesson-1?view=a"


def test_bound_origin_is_accepted(client: TestClient, port: int) -> None:
    response = client.post("/solve/cancel", headers={"Origin": f"http://127.0.0.1:{port}"})
    assert response.status_code == 200
    assert response.json() == {"status": "no_active_solve"}
    assert client.get("/", headers={"Origin": f"http://127.0.0.1:{port}"}).status_code == 200


def test_other_origins_are_rejected_including_the_development_ports(client: TestClient, port: int) -> None:
    for origin in (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        f"http://127.0.0.1:{port + 1}",
        f"http://localhost:{port}",
        f"https://127.0.0.1:{port}",
        f"http://127.0.0.1:{port}.attacker.example",
        "https://attacker.example",
        "null",
    ):
        for method, path in (("POST", "/solve/cancel"), ("GET", "/")):
            response = client.request(method, path, headers={"Origin": origin})
            assert response.status_code == 403, (origin, path)


def test_hosts_other_than_the_bound_loopback_port_are_rejected(client: TestClient, port: int) -> None:
    for host in (
        f"attacker.example:{port}",
        f"127.0.0.1.attacker.example:{port}",
        f"localhost.attacker.example:{port}",
        "attacker.example",
        f"127.0.0.1:{port + 1}",
        "127.0.0.1",
        "localhost",
    ):
        for path in ("/", "/health", "/assets/index-AbCd1234.js"):
            assert client.get(path, headers={"Host": host}).status_code == 400, (host, path)


def test_cross_site_navigation_without_origin_is_rejected(client: TestClient) -> None:
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/", headers={"Sec-Fetch-Site": "none"}).status_code == 200


def test_development_service_stays_api_only() -> None:
    development = TestClient(app, base_url="http://127.0.0.1:8000")
    assert development.get("/").status_code == 404
    assert development.get("/tutorials/lesson-1").status_code == 404
    assert development.post("/solve/cancel", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200


def test_bundle_without_index_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        create_app(bound_port=2645, ui_bundle=tmp_path)
