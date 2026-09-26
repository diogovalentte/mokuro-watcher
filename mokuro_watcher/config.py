import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    library_dir: Path
    output_dir: Path
    staging_dir: Path
    state_db: Path
    sources: tuple[str, ...]
    scan_interval_seconds: int
    min_age_seconds: int
    series_baseline_seconds: int
    max_attempts: int
    mokuro_timeout_seconds: int
    mokuro_command: tuple[str, ...]
    ntfy_url: str
    ntfy_topic: str
    ntfy_token: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ if env is None else env)
        library_dir = Path(env.get("LIBRARY_DIR", "/Medias/Mangas"))
        sources = tuple(
            s.strip().lower()
            for s in env.get("SOURCES", "klmanga,rawkuma,jmanga").split(",")
            if s.strip()
        )
        return cls(
            library_dir=library_dir,
            output_dir=Path(env.get("OUTPUT_DIR", library_dir / ".mokuro-reader")),
            staging_dir=Path(env.get("STAGING_DIR", library_dir / ".mokuro-staging")),
            state_db=Path(env.get("STATE_DB", "/state/mokuro-watcher.db")),
            sources=sources,
            scan_interval_seconds=int(env.get("SCAN_INTERVAL_SECONDS", "300")),
            min_age_seconds=int(env.get("MIN_AGE_SECONDS", "120")),
            series_baseline_seconds=int(env.get("SERIES_BASELINE_SECONDS", "21600")),
            max_attempts=int(env.get("MAX_ATTEMPTS", "3")),
            mokuro_timeout_seconds=int(env.get("MOKURO_TIMEOUT_SECONDS", "7200")),
            mokuro_command=tuple(
                env.get(
                    "MOKURO_COMMAND",
                    "mokuro --disable_confirmation=True --legacy_html=False",
                ).split()
            ),
            ntfy_url=env.get("NTFY_URL", "").rstrip("/"),
            ntfy_topic=env.get("NTFY_TOPIC", ""),
            ntfy_token=env.get("NTFY_TOKEN", ""),
        )
