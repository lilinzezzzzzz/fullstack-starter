"""本地应用包：在第三方模块导入前隔离遥测环境，不访问数据库。"""

from app.telemetry.environment import clear_telemetry_environment

clear_telemetry_environment()
