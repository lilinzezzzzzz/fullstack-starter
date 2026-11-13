import tomllib
from datetime import timedelta
from pathlib import Path
from typing import Annotated, ClassVar, Literal, Self

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.utils.path_safety import path_is_relative_to, validate_runtime_paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # 相对配置路径的统一解析基准。
BACKEND_ROOT = PROJECT_ROOT / "backend"
CONFIG_FILE = PROJECT_ROOT / "configs" / "app.toml"  # 固定引导入口；CLI 可用 --config 显式另选。


def resolve_project_path(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError("Expected a path string")
    path = Path(value)
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def validate_filename(value: str) -> str:
    if not value or value in (".", "..") or Path(value).name != value or "\\" in value:
        raise ValueError("Expected a filename without directory components")
    return value


ProjectPath = Annotated[Path, BeforeValidator(resolve_project_path)]  # 根目录相对路径或绝对路径。
Filename = Annotated[str, AfterValidator(validate_filename)]  # 仅文件名，禁止夹带目录或路径分隔符。


class ConfigSection(BaseModel):
    # 所有字段均由完整 TOML 显式提供；拒绝未知键、不匹配的类型及非有限浮点数。
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ApplicationSettings(ConfigSection):
    title: str = Field(min_length=1)  # 应用标题，同时提供给 OpenAPI、前端和 telemetry Resource。
    version: str = Field(min_length=1)  # 应用版本，同时提供给 OpenAPI、前端和 telemetry Resource。
    docs_enabled: bool  # 是否提供 Swagger UI；启用时要求 openapi_enabled=true。
    redoc_enabled: bool  # 是否提供 ReDoc；启用时要求 openapi_enabled=true。
    openapi_enabled: bool  # 是否提供 OpenAPI JSON；关闭时必须同时关闭两个交互文档入口。
    docs_path: str = Field(pattern=r"^/")  # Swagger UI 路径；关闭后仍必填并作为保留路径。
    redoc_path: str = Field(pattern=r"^/")  # ReDoc 路径；关闭后仍必填并作为保留路径。
    openapi_path: str = Field(pattern=r"^/")  # OpenAPI JSON 路径；关闭后仍必填并作为保留路径。

    @property
    def docs_url(self) -> str | None:
        return self.docs_path if self.docs_enabled else None

    @property
    def redoc_url(self) -> str | None:
        return self.redoc_path if self.redoc_enabled else None

    @property
    def openapi_url(self) -> str | None:
        return self.openapi_path if self.openapi_enabled else None


class ServerSettings(ConfigSection):
    host: str  # Uvicorn 监听地址；本地使用通常绑定回环地址。
    port: int = Field(ge=1, le=65535)  # API 监听端口；端口占用时启动失败。
    workers: Literal[1]  # 固定单 worker，保持单机 SQLite 与进程级日志的运行边界。
    graceful_shutdown_seconds: float = Field(gt=0)  # 优雅关闭时等待在途请求/任务结束的期限，秒。
    keep_alive_seconds: int = Field(ge=0)  # 空闲 HTTP 连接等待下一请求的秒数；0 不等待。
    backlog: int = Field(gt=0)  # 监听套接字的待接入连接队列容量。
    concurrency_limit: int = Field(ge=0)  # Uvicorn 并发连接/任务上限；0 转为不设上限。


class DatabaseSettings(ConfigSection):
    journal_mode: Literal["WAL", "DELETE"]  # SQLite 日志模式，通过连接 PRAGMA 设置。
    synchronous: Literal["NORMAL", "FULL", "EXTRA"]  # SQLite 持久性级别，与异步 ORM 调用无关。
    pool_size: int = Field(gt=0)  # SQLAlchemy 连接池的常驻连接容量。
    max_overflow: int = Field(ge=0)  # 常驻容量之外可临时增加的连接数；0 禁用溢出连接。
    pool_timeout_seconds: float = Field(gt=0)  # 连接池耗尽后等待可用连接的期限，秒。


class LoggingSettings(ConfigSection):
    # 固定日志策略，不作为 TOML 字段或配置导出项。
    backtrace: ClassVar[bool] = False  # 不向异常捕获点之前扩展回溯。
    diagnose: ClassVar[bool] = False  # 不输出局部变量，避免异常日志泄露敏感值。
    enqueue: ClassVar[bool] = True  # 经队列交给后台线程写入，退出时由调用方等待排空。
    colorize: ClassVar[bool] = False  # 文件与控制台均不添加 ANSI 颜色转义。
    catch: ClassVar[bool] = True  # 由 Loguru 捕获并报告 sink 写入异常。

    directory: ProjectPath  # 私有日志目录；不得与源码或公开前端产物重叠。
    filename: Filename  # 文件日志名称，相对于 directory。
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]  # 文件和控制台的最低日志等级。
    rotation: str  # Loguru 轮转条件，例如大小 "10 MB" 或时间 "1 day"。
    retention_days: int = Field(ge=0)  # 轮转日志保留天数；0 表示不按时间删除。
    compression: Literal["none", "gz", "zip"]  # 轮转文件压缩格式；none 表示不压缩。
    format: str = Field(min_length=1)  # Loguru 消息模板，可包含 extra[trace_id]。
    serialize: bool  # 是否将日志记录序列化为 JSON。
    console: bool  # 是否在文件日志之外，同时写入标准错误输出。
    request_logging: bool  # 是否记录请求方法、路径、状态码、耗时及当前 trace 上下文。

    @property
    def retention(self) -> timedelta | None:
        return None if self.retention_days == 0 else timedelta(days=self.retention_days)

    @property
    def compression_format(self) -> Literal["gz", "zip"] | None:
        return None if self.compression == "none" else self.compression


class SpanLimitSettings(ConfigSection):
    # 全部显式传给 SDK，避免隐式默认值；当前不采集，随附 TOML 的八项均为 0。
    max_attributes: int = Field(ge=0)  # 通用属性数量上限；0 不保留属性。
    max_events: int = Field(ge=0)  # 每个 span 的事件数量上限；0 不保留事件。
    max_links: int = Field(ge=0)  # 每个 span 的链接数量上限；0 不保留链接。
    max_span_attributes: int = Field(ge=0)  # span 属性数量上限，覆盖通用数量限制。
    max_event_attributes: int = Field(ge=0)  # 单个事件的属性数量上限。
    max_link_attributes: int = Field(ge=0)  # 单个链接的属性数量上限。
    max_attribute_length: int = Field(ge=0)  # 通用字符串属性长度上限，字符数。
    max_span_attribute_length: int = Field(ge=0)  # span 字符串属性长度上限，字符数。


class TelemetrySettings(ConfigSection):
    tracing: bool  # 必须为 true，仅用于原生请求 trace 上下文，不代表开启采集。
    metrics: bool  # 必须为 false，禁用请求指标采集。
    logs: bool  # 必须为 false，禁用 OTel 日志；应用日志继续使用 Loguru。
    operation_spans: bool  # 必须为 false，不额外创建操作级 span。
    auto_configure: bool  # 必须为 false，不自动装配 telemetry 导出组件。
    sampler: Literal["always_off"]  # 固定不采样，仍保留有效的 trace/span 标识。
    id_generator: Literal["random"]  # 由 SDK 随机生成 trace/span 标识。
    sdk_disabled: bool  # 必须为 false，避免 SDK 退化成无有效上下文的 NoOp。
    internal_metrics_enabled: bool  # 必须为 false，关闭 SDK 自身指标。
    shutdown_on_exit: bool  # 必须为 false，由 lifespan/CLI 显式关闭 provider。
    context: Literal["contextvars_context"]  # 使用 contextvars 隔离并发请求的上下文。
    propagators: Literal["tracecontext"]  # 仅接受 W3C tracecontext 传播格式。
    # FastAPI 原生 telemetry 用于 HTTP 方法归类的非空大写方法列表。
    known_methods: list[Annotated[str, Field(pattern=r"^[A-Z]+$")]] = Field(min_length=1)
    span_limits: SpanLimitSettings  # SDK 的八项显式限制，不从环境变量补值。

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
    host: str  # 可选 Vite 开发服务器的监听地址。
    port: int = Field(ge=1, le=65535)  # Vite 开发端口，与 API 监听端口分别配置。
    proxy_target: str  # /api 开发代理的后端 URL，例如 http://127.0.0.1:18001。
    strict_port: Literal[True]  # 端口占用时直接失败，禁止自动改用其他端口。
    change_origin: bool  # 是否将代理请求的 Host 改为后端目标的主机。


class ClientSettings(ConfigSection):
    # 本分组注入浏览器构建产物，修改后需要重新构建前端。
    request_timeout_seconds: float = Field(gt=0)  # 单次 API 请求超时，秒。
    query_stale_seconds: float = Field(ge=0)  # 查询保持新鲜的秒数；0 表示立即过期。
    query_cache_seconds: float = Field(ge=0)  # 无订阅查询的缓存保留秒数；0 不保留闲置缓存。
    query_retry_attempts: int = Field(ge=0)  # 查询失败后的最大重试次数；0 不重试。
    query_retry_delay_seconds: float = Field(ge=0)  # 查询重试间隔，秒；0 不额外等待。
    retry_min_status: int = Field(ge=400, le=599)  # 允许查询重试的最低 HTTP 错误状态码。
    retry_network_errors: bool  # 是否允许对网络错误或请求超时进行查询重试。
    refetch_on_window_focus: bool  # 页面重新获得焦点时，是否重新请求过期查询。
    refetch_on_mount: bool  # 查询组件挂载时，是否重新请求过期查询。
    refetch_on_reconnect: bool  # 网络恢复连接时，是否重新请求过期查询。
    mutation_retry_attempts: Literal[0]  # 固定禁用写操作重试，避免未建立幂等契约时重复写入。
    theme_primary_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")  # Ant Design 六位十六进制主色。
    theme_border_radius: int = Field(ge=0)  # Ant Design 组件基础圆角，像素。
    theme_font_size: int = Field(gt=0)  # Ant Design 组件基础字号，像素。
    theme_font_family: str = Field(min_length=1)  # Ant Design 组件字体，不覆盖全局 CSS 字体。


class TestingSettings(ConfigSection):
    temporary_directory: ProjectPath  # E2E/迁移验证创建独占子目录的父位置，不复用日常产物。
    host: str  # 隔离 E2E 服务的监听及访问地址。
    termination_grace_seconds: float = Field(gt=0)  # 验证子进程优雅退出的等待期限，秒。
    command_timeout_seconds: float = Field(gt=0)  # 验证入口中单个构建/CLI 等命令的执行期限，秒。
    keep_artifacts: bool  # E2E 成功后是否保留产物；失败时始终保留诊断。
    browser: Literal["chromium", "firefox", "webkit"]  # Playwright 浏览器种类，需预先安装匹配版本。
    viewport_width: int = Field(gt=0)  # 常规浏览器视口宽度，像素。
    viewport_height: int = Field(gt=0)  # 常规浏览器视口高度，像素。
    mobile_width: int = Field(gt=0)  # 窄屏测试视口宽度，像素。
    mobile_height: int = Field(gt=0)  # 窄屏测试视口高度，像素。
    workers: int = Field(gt=0)  # Playwright 并行 worker 数，与 API 单 worker 无关。
    retries: int = Field(ge=0)  # 测试失败后的重试次数；0 不重试。
    test_timeout_seconds: float = Field(gt=0)  # 单个测试用例的执行期限，秒。
    expect_timeout_seconds: float = Field(gt=0)  # Playwright 自动重试断言的等待期限，秒。
    action_timeout_seconds: float = Field(ge=0)  # 单次浏览器操作期限，秒；0 表示禁用此超时。
    navigation_timeout_seconds: float = Field(gt=0)  # 浏览器导航的等待期限，秒。
    trace: Literal["off", "on", "retain-on-failure", "on-first-retry"]  # trace 录制策略。
    screenshot: Literal["off", "on", "only-on-failure"]  # Playwright 截图策略。
    fully_parallel: bool  # 是否允许同一文件内的测试并行执行，仍受 workers 限制。
    reporter: Literal["list", "dot", "line"]  # Playwright 终端结果报告格式。


class Settings(ConfigSection):
    data_dir: ProjectPath  # 私有 SQLite 数据目录；导入和配置加载不会创建数据库。
    database_filename: Filename  # 数据库文件名，相对于 data_dir。
    backup_directory: ProjectPath  # 显式备份操作的输出目录，独立于数据目录配置。
    frontend_dir: ProjectPath  # 前端构建产物目录；公开输出不得包含源码或私有运行文件。
    serve_frontend: bool  # 是否由 FastAPI 托管前端；关闭后仍提供 API。
    frontend_clean_output: bool  # 构建前是否清空输出；仅允许实际的 frontend/dist。
    sqlite_timeout_seconds: float = Field(gt=0, le=60)  # SQLite 等待数据库锁的期限，秒，最多 60。
    allowed_hosts: list[str]  # Host 主机名白名单，不含端口；空列表拒绝所有主机。
    allowed_origins: list[str]  # 额外允许的 Origin（协议/主机/端口），同源无需列入。
    application: ApplicationSettings  # 应用标识与文档入口，全部字段必填。
    server: ServerSettings  # Uvicorn 监听、连接及关闭参数。
    database: DatabaseSettings  # SQLite PRAGMA 与异步连接池参数。
    logging: LoggingSettings  # Loguru 文件、控制台及请求日志参数。
    telemetry: TelemetrySettings  # 仅维护 trace 上下文的原生 SDK 参数。
    vite: ViteSettings  # 可选 Vite 开发服务器与代理参数。
    client: ClientSettings  # 浏览器可见的请求、查询与组件主题参数。
    testing: TestingSettings  # 隔离验证资源、浏览器与执行预算。

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
