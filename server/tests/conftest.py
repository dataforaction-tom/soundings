import os


def pytest_configure(config: object) -> None:
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings",
    )
