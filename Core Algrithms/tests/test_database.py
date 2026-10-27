"""Kiểm thử cấu hình SQL Server của runtime Python."""

import pytest

from gapo_timetabling.application.database import DatabaseConfigurationError, SqlServerConfig


def test_converts_existing_jdbc_url_to_odbc_configuration() -> None:
    config = SqlServerConfig.from_jdbc_url(
        "jdbc:sqlserver://localhost:1433;databaseName=timetabling_gapo;"
        "encrypt=true;trustServerCertificate=true",
        username="sa",
        password="secret",
    )

    assert config.host == "localhost"
    assert config.port == 1433
    assert config.database == "timetabling_gapo"
    connection_string = config.odbc_connection_string()
    assert "SERVER=localhost,1433" in connection_string
    assert "DATABASE=timetabling_gapo" in connection_string
    assert "Encrypt=yes" in connection_string


def test_rejects_jdbc_url_without_database_name() -> None:
    with pytest.raises(DatabaseConfigurationError):
        SqlServerConfig.from_jdbc_url(
            "jdbc:sqlserver://localhost:1433;encrypt=true",
            username="sa",
            password="secret",
        )


def test_named_instance_lets_sql_server_browser_resolve_dynamic_port() -> None:
    config = SqlServerConfig.from_jdbc_url(
        r"jdbc:sqlserver://localhost\PHAMTUANVI;databaseName=testkhoaluan;"
        "encrypt=true;trustServerCertificate=true",
        username="sa",
        password="secret",
    )

    assert config.host == r"localhost\PHAMTUANVI"
    assert config.port is None
    assert r"SERVER=localhost\PHAMTUANVI" in config.odbc_connection_string()
    assert "SERVER=localhost\\PHAMTUANVI," not in config.odbc_connection_string()
