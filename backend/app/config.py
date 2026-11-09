import tomllib
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.utils.path_safety import path_is_relative_to, validate_runtime_paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
CONFIG_FILE = PROJECT_ROOT / "configs" / "app.toml"


def resolve_project_path(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError("Expected a path string")
    path = Path(value)
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def validate_filename(value: str) -> str:
    if not value or value in (".", "..") or Path(value).name != value or "\\" in value:
        raise ValueError("Expected a filename without directory components")
    return value


ProjectPath = Annotated[Path, BeforeValidator(resolve_project_path)]
Filename = Annotated[str, AfterValidator(validate_filename)]


class ConfigSection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ApplicationSettings(ConfigSection):
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)
    docs_enabled: bool
    redoc_enabled: bool
    openapi_enabled: bool
    docs_path: str = Field(pattern=r"^/")
    redoc_path: str = Field(pattern=r"^/")
    openapi_path: str = Field(pattern=r"^/")


class ServerSettings(ConfigSection):
    host: str
    port: int = Field(ge=1, le=65535)
    workers: Literal[1]
    graceful_shutdown_seconds: float = Field(gt=0)
    keep_alive_seconds: int = Field(ge=0)
    backlog: int = Field(gt=0)
    concurrency_limit: int = Field(ge=0)


class DatabaseSettings(ConfigSection):
    journal_mode: Literal["WAL", "DELETE"]
    synchronous: Literal["NORMAL", "FULL", "EXTRA"]
    pool_size: int = Field(gt=0)
    max_overflow: int = Field(ge=0)
    pool_timeout_seconds: float = Field(gt=0)


class LoggingSettings(ConfigSection):
    directory: ProjectPath
    filename: Filename
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    rotation: str
    retention_days: int = Field(ge=0)
    compression: Literal["none", "gz", "zip"]
    format: str = Field(min_length=1)
    serialize: bool
    console: bool
    request_logging: bool

    @property
    def retention(self) -> timedelta | None:
        return None if self.retention_days == 0 else timedelta(days=self.retention_days)


class SpanLimitSettings(ConfigSection):
    max_attributes: int = Field(ge=0)
    max_events: int = Field(ge=0)
    max_links: int = Field(ge=0)
    max_span_attributes: int = Field(ge=0)
    max_event_attributes: int = Field(ge=0)
    max_link_attributes: int = Field(ge=0)
    max_attribute_length: int = Field(ge=0)
    max_span_attribute_length: int = Field(ge=0)


class TelemetrySettings(ConfigSection):
    tracing: bool
    metrics: bool
    logs: bool
    operation_spans: bool
    auto_configure: bool
    sampler: Literal["always_off"]
    id_generator: Literal["random"]
    sdk_disabled: bool
    internal_metrics_enabled: bool
    shutdown_on_exit: bool
    context: Literal["contextvars_context"]
    propagators: Literal["tracecontext"]
    known_methods: list[Annotated[str, Field(pattern=r"^[A-Z]+$")]] = Field(min_length=1)
    span_limits: SpanLimitSettings

    @model_validator(mode="after")
    def require_context_only(self) -> Self:
        if not self.tracing or self.sdk_disabled:
            raise ValueError("Native trace context requires tracing=true and sdk_disabled=false")
        if any(
            (
                self.metrics,
                self.logs,
                self.operation_spans,
                self.auto_configure,
                self.internal_metrics_enabled,
                self.shutdown_on_exit,
            )
        ):
            raise ValueError("Telemetry collection, automatic export and exit hooks must stay off")
        return self


class ViteSettings(ConfigSection):
    host: str
    port: int = Field(ge=1, le=65535)
    proxy_target: str
    strict_port: Literal[True]
    change_origin: bool


class ClientSettings(ConfigSection):
    request_timeout_seconds: float = Field(gt=0)
    query_stale_seconds: float = Field(ge=0)
    query_cache_seconds: float = Field(ge=0)
    query_retry_attempts: int = Field(ge=0)
    query_retry_delay_seconds: float = Field(ge=0)
    retry_min_status: int = Field(ge=400, le=599)
    retry_network_errors: bool
    refetch_on_window_focus: bool
    refetch_on_mount: bool
    refetch_on_reconnect: bool
    mutation_retry_attempts: Literal[0]
    theme_primary_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    theme_border_radius: int = Field(ge=0)
    theme_font_size: int = Field(gt=0)
    theme_font_family: str = Field(min_length=1)


class TestingSettings(ConfigSection):
    temporary_directory: ProjectPath
    host: str
    termination_grace_seconds: float = Field(gt=0)
    command_timeout_seconds: float = Field(gt=0)
    keep_artifacts: bool
    browser: Literal["chromium", "firefox", "webkit"]
    viewport_width: int = Field(gt=0)
    viewport_height: int = Field(gt=0)
    mobile_width: int = Field(gt=0)
    mobile_height: int = Field(gt=0)
    workers: int = Field(gt=0)
    retries: int = Field(ge=0)
    test_timeout_seconds: float = Field(gt=0)
    expect_timeout_seconds: float = Field(gt=0)
    action_timeout_seconds: float = Field(ge=0)
    navigation_timeout_seconds: float = Field(gt=0)
    trace: Literal["off", "on", "retain-on-failure", "on-first-retry"]
    screenshot: Literal["off", "on", "only-on-failure"]
    fully_parallel: bool
    reporter: Literal["list", "dot", "line"]


class Settings(ConfigSection):
    data_dir: ProjectPath
    database_filename: Filename
    backup_directory: ProjectPath
    frontend_dir: ProjectPath
    serve_frontend: bool
    frontend_clean_output: bool
    sqlite_timeout_seconds: float = Field(gt=0, le=60)
    allowed_hosts: list[str]
    allowed_origins: list[str]
    application: ApplicationSettings
    server: ServerSettings
    database: DatabaseSettings
    logging: LoggingSettings
    telemetry: TelemetrySettings
    vite: ViteSettings
    client: ClientSettings
    testing: TestingSettings

    @model_validator(mode="after")
    def check_configuration_relationships(self) -> Self:
        if not self.application.openapi_enabled and (
            self.application.docs_enabled or self.application.redoc_enabled
        ):
            raise ValueError("Interactive documentation requires openapi_enabled=true")
        validate_runtime_paths(
            PROJECT_ROOT,
            frontend_dir=self.frontend_dir,
            frontend_clean_output=self.frontend_clean_output,
            data_dir=self.data_dir,
            backup_directory=self.backup_directory,
            logging_directory=self.logging.directory,
            temporary_directory=self.testing.temporary_directory,
            database_filename=self.database_filename,
            logging_filename=self.logging.filename,
        )
        return self

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_filename


def load_settings(config_file: str | Path) -> Settings:
    """读取单个完整的 TOML 文件，不读取环境变量、不合并配置、不回退取值。"""
    path = resolve_project_path(config_file)
    if path.suffix != ".toml":
        raise ValueError("Application configuration must be a .toml file")
    with path.open("rb") as handle:
        settings = Settings.model_validate(tomllib.load(handle))
    if path_is_relative_to(path, settings.frontend_dir):
        raise ValueError("Configuration file must not be inside the public frontend directory")
    return settings
