"""Kết nối SQL Server cho ứng dụng Python thống nhất.

Module giữ tương thích với ba biến môi trường mà ứng dụng Spring trước đây
sử dụng: ``DB_URL``, ``DB_USERNAME`` và ``DB_PASSWORD``. Nhờ vậy việc chuyển
runtime không buộc người triển khai thay đổi ngay cấu hình bí mật hiện có.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import re
from typing import Any, Iterator, Mapping, Protocol, Sequence


# Cấu hình mặc định chỉ phục vụ môi trường phát triển cục bộ của đồ án. Biến
# môi trường cùng tên luôn được ưu tiên để bản triển khai thật không phụ thuộc
# vào tài khoản SQL Server dùng trên máy phát triển.
DEFAULT_LOCAL_DB_URL = (
    r"jdbc:sqlserver://localhost\PHAMTUANVI;databaseName=testkhoaluan;"
    "encrypt=true;trustServerCertificate=true"
)
DEFAULT_LOCAL_DB_USERNAME = "sa"
DEFAULT_LOCAL_DB_PASSWORD = "123"


class DatabaseConfigurationError(ValueError):
    """Cấu hình kết nối không đủ hoặc DB_URL không đúng định dạng."""


def _detect_sql_server_driver() -> str:
    """Chọn driver Microsoft mới nhất đang có trên máy triển khai."""

    try:
        import pyodbc

        installed = set(pyodbc.drivers())
    except ImportError:  # pragma: no cover - connect_sql_server sẽ báo rõ hơn.
        installed = set()
    for candidate in (
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "SQL Server",
    ):
        if candidate in installed:
            return candidate
    return "ODBC Driver 18 for SQL Server"


class CursorProtocol(Protocol):
    """Phần giao diện cursor mà tầng repository thực sự sử dụng."""

    description: Sequence[Sequence[Any]] | None

    def execute(self, sql: str, *parameters: Any) -> "CursorProtocol": ...

    def executemany(
        self, sql: str, parameters: Sequence[Sequence[Any]]
    ) -> "CursorProtocol": ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> Sequence[Any]: ...


class ConnectionProtocol(Protocol):
    """Giao diện tối thiểu giúp service độc lập với đối tượng pyodbc cụ thể."""

    def cursor(self) -> CursorProtocol: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SqlServerConfig:
    """Thông tin cần thiết để tạo một kết nối SQL Server bằng ODBC."""

    host: str
    port: int | None
    database: str
    username: str
    password: str
    driver: str = "ODBC Driver 18 for SQL Server"
    encrypt: bool = True
    trust_server_certificate: bool = True

    @classmethod
    def from_environment(cls) -> "SqlServerConfig":
        """Đọc cấu hình từ biến môi trường, không ghi thông tin bí mật ra log."""

        jdbc_url = os.getenv("DB_URL", DEFAULT_LOCAL_DB_URL).strip()
        username = os.getenv("DB_USERNAME", DEFAULT_LOCAL_DB_USERNAME).strip()
        password = os.getenv("DB_PASSWORD", DEFAULT_LOCAL_DB_PASSWORD)
        if not jdbc_url or not username or not password:
            raise DatabaseConfigurationError(
                "Cần khai báo DB_URL, DB_USERNAME và DB_PASSWORD trước khi truy cập SQL Server."
            )
        return cls.from_jdbc_url(jdbc_url, username=username, password=password)

    @classmethod
    def from_jdbc_url(
        cls, jdbc_url: str, *, username: str, password: str
    ) -> "SqlServerConfig":
        """Chuyển JDBC URL cũ sang cấu hình độc lập dùng cho Python."""

        match = re.fullmatch(r"jdbc:sqlserver://([^;:]+)(?::(\d+))?(?:;(.*))?", jdbc_url)
        if match is None:
            raise DatabaseConfigurationError("DB_URL không phải JDBC URL của SQL Server.")

        host, port_text, raw_properties = match.groups()
        properties: dict[str, str] = {}
        for item in (raw_properties or "").split(";"):
            if not item:
                continue
            key, separator, value = item.partition("=")
            if not separator:
                raise DatabaseConfigurationError(f"Thuộc tính DB_URL không hợp lệ: {item}.")
            properties[key.strip().lower()] = value.strip()

        database = properties.get("databasename") or properties.get("database")
        if not database:
            raise DatabaseConfigurationError("DB_URL phải chứa databaseName.")

        def as_bool(name: str, default: bool) -> bool:
            value = properties.get(name.lower())
            if value is None:
                return default
            if value.lower() not in {"true", "false"}:
                raise DatabaseConfigurationError(f"{name} phải là true hoặc false.")
            return value.lower() == "true"

        return cls(
            host=host,
            # Named instance (ví dụ ``localhost\PHAMTUANVI``) để SQL Server
            # Browser tự tìm dynamic port; host thường vẫn mặc định 1433.
            port=(
                int(port_text)
                if port_text is not None
                else (None if "\\" in host else 1433)
            ),
            database=database,
            username=username,
            password=password,
            driver=os.getenv("DB_ODBC_DRIVER") or _detect_sql_server_driver(),
            encrypt=as_bool("encrypt", True),
            trust_server_certificate=as_bool("trustServerCertificate", True),
        )

    def odbc_connection_string(self) -> str:
        """Tạo chuỗi kết nối ODBC; chỉ truyền trực tiếp cho driver, không log."""

        server = self.host if self.port is None else f"{self.host},{self.port}"
        return ";".join(
            (
                f"DRIVER={{{self.driver}}}",
                f"SERVER={server}",
                f"DATABASE={self.database}",
                f"UID={self.username}",
                f"PWD={self.password}",
                f"Encrypt={'yes' if self.encrypt else 'no'}",
                "TrustServerCertificate="
                f"{'yes' if self.trust_server_certificate else 'no'}",
            )
        )


def connect_sql_server(config: SqlServerConfig | None = None) -> ConnectionProtocol:
    """Mở kết nối transaction thủ công; pyodbc chỉ được import khi cần dùng."""

    try:
        import pyodbc
    except ImportError as exception:  # pragma: no cover - phụ thuộc môi trường triển khai.
        raise RuntimeError(
            "Chưa cài pyodbc. Hãy chạy 'python -m pip install pyodbc'."
        ) from exception

    actual_config = config or SqlServerConfig.from_environment()
    return pyodbc.connect(actual_config.odbc_connection_string(), autocommit=False)


@contextmanager
def transaction(
    connection: ConnectionProtocol | None = None,
    *,
    config: SqlServerConfig | None = None,
) -> Iterator[ConnectionProtocol]:
    """Commit khi toàn bộ thao tác thành công và rollback nếu có lỗi."""

    owns_connection = connection is None
    actual_connection = connection or connect_sql_server(config)
    try:
        yield actual_connection
        actual_connection.commit()
    except BaseException:
        actual_connection.rollback()
        raise
    finally:
        if owns_connection:
            actual_connection.close()


def fetch_all_dicts(cursor: CursorProtocol) -> list[dict[str, Any]]:
    """Chuyển kết quả pyodbc thành dict để repository không phụ thuộc Row."""

    if cursor.description is None:
        return []
    columns = [str(column[0]).lower() for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def fetch_one_dict(cursor: CursorProtocol) -> dict[str, Any] | None:
    """Đọc một dòng dưới dạng dict hoặc trả ``None`` khi không có kết quả."""

    if cursor.description is None:
        return None
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [str(column[0]).lower() for column in cursor.description]
    return dict(zip(columns, row, strict=True))


def require_row(row: Mapping[str, Any] | None, message: str) -> Mapping[str, Any]:
    """Rút gọn kiểm tra bắt buộc tồn tại của một truy vấn nghiệp vụ."""

    if row is None:
        raise ValueError(message)
    return row
