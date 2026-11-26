from pathlib import Path

import yaml


def test_compose_defines_expected_services():
    data = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    services = data["services"]
    assert {"app", "db", "redis"} <= set(services)
    assert services["app"]["ports"] == ["8081:8080"]
    assert "pgvector" in services["db"]["image"]
    assert services["redis"]["image"].startswith("redis:")
    assert services["app"]["depends_on"]["db"]["condition"] == "service_healthy"


def test_dockerfile_runs_uvicorn_and_healthcheck():
    text = Path("Dockerfile").read_text(encoding="utf-8")
    assert "uvicorn" in text
    assert "HEALTHCHECK" in text
    assert "8080" in text


def test_env_example_contains_required_keys():
    text = Path(".env.example").read_text(encoding="utf-8")
    for key in (
        "MODEL_PROVIDER",
        "DASHSCOPE_API_KEY",
        "POSTGRES_DSN",
        "REDIS_URL",
        "EMBEDDING_DIM",
    ):
        assert key in text
