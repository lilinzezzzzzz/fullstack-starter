# Project instructions

- This is a local, single-user FastAPI + SQLite and React scaffold. The agreed design is in `docs/design.md`.
- Keep request-layer backend responsibilities in `routers/`, `services/`, `models/`, and `schemas/`; put CLI-only infrastructure such as snapshots in `maintenance/`. Routers do not write to the database. Services own write transactions.
- Implement services as classes with dependencies injected through their constructors. Keep service classes focused on business behavior and free of FastAPI request handling, Pydantic I/O schemas, and infrastructure construction.
- Place each service's `new_*_service` factory in the corresponding service module. The module-level factory may use FastAPI `Request`/`Depends` to resolve dependencies and construct the service; routers declare `Depends`, while CLI callers assemble dependencies explicitly.
- Use SQLAlchemy 2.0 AsyncEngine, async_sessionmaker and one AsyncSession per request/task with aiosqlite. Await database I/O and engine disposal; never share a session between concurrent tasks. Alembic uses the documented run_sync bridge, not a separate synchronous runtime engine.
- The only example is a Hello welcome page and Hello API. Do not add a CRUD application or business tables without a task that asks for them.
- Serve the built frontend from FastAPI by default. Vite is optional. Do not add Makefile or a combined development process runner.
- Importing the app and exporting OpenAPI must not connect to a database or require frontend build output. Lifespan performs runtime checks.
- Schema changes use Alembic. Do not silently upgrade existing databases on application startup.
- API errors have `code`, `message`, `details`, and `request_id`. Unknown API and asset paths must not return the SPA HTML.
- Read application settings only from explicit TOML configuration files (`configs/app.toml` is the bootstrap entry). Never use environment variables or `.env` as application configuration sources. Resolve relative paths from the project root.
- All configuration fields are required. Never use model defaults or fallback expressions to supply missing settings. Keep protocol and safety invariants in code; document the configuration boundary in `docs/configuration.md`.
- Validate build settings through the same Python loader. Inject only public client settings and application title/version into the browser. Frontend setting changes require a rebuild.
- Use Loguru for application and Uvicorn logs. Keep logs, databases, backups, PID files, dependencies, and build output out of Git.
- Run one API worker. Control it through `scripts/service.sh`; record the actual service PID after readiness and verify process ownership before signalling. Never kill a process merely because it holds a port.
- Tests use temporary TOML configuration, logs, PID files, and SQLite. Never use daily `.data/` for validation. Preserve cancellation and close owned connections.
- Keep current architecture in `docs/design.md`, configuration boundaries in `docs/configuration.md`, commands in README, and dated verification evidence in `docs/history.md`. Record observed results only. Use the sh entrypoint for lifecycle and uv/pnpm for dependencies and checks.
