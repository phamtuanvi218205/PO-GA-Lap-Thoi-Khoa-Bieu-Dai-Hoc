"""Kiểm thử cấu hình SQL Server của runtime Python."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gapo_timetabling.application import database
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


@pytest.fixture
def project_env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(database, "PROJECT_ENV_FILE", path)
    monkeypatch.setattr(database, "_detect_sql_server_driver", lambda: "Auto Driver")
    for name in ("DB_URL", "DB_USERNAME", "DB_PASSWORD", "DB_ODBC_DRIVER"):
        monkeypatch.delenv(name, raising=False)
    return path


def write_database_env(path, *, password="'local-secret'", driver=""):
    path.write_text(
        "DB_URL=jdbc:sqlserver://env-server\\INSTANCE;databaseName=env_db;"
        "encrypt=true;trustServerCertificate=true\n"
        "DB_USERNAME=env_user\n"
        f"DB_PASSWORD={password}\n"
        f"{driver}",
        encoding="utf-8-sig",
    )


def test_reads_project_dotenv_from_an_unrelated_working_directory(project_env, tmp_path, monkeypatch):
    write_database_env(project_env, driver="DB_ODBC_DRIVER=File Driver\n")
    other = tmp_path / "other"
    other.mkdir()
    (other / ".env").write_text("DB_PASSWORD=wrong-file\n", encoding="utf8")
    monkeypatch.chdir(other)

    config = SqlServerConfig.from_environment()

    assert config.host == r"env-server\INSTANCE"
    assert config.database == "env_db"
    assert config.username == "env_user"
    assert config.password == "local-secret"
    assert config.driver == "File Driver"
    assert config.port is None


def test_process_environment_overrides_every_dotenv_database_key(project_env, monkeypatch):
    write_database_env(project_env, driver="DB_ODBC_DRIVER=File Driver\n")
    monkeypatch.setenv("DB_URL", "jdbc:sqlserver://process-server:1434;databaseName=process_db")
    monkeypatch.setenv("DB_USERNAME", "process_user")
    monkeypatch.setenv("DB_PASSWORD", "process-secret")
    monkeypatch.setenv("DB_ODBC_DRIVER", "Process Driver")

    config = SqlServerConfig.from_environment()

    assert (config.host, config.port, config.database) == ("process-server", 1434, "process_db")
    assert (config.username, config.password, config.driver) == ("process_user", "process-secret", "Process Driver")


def test_partial_environment_keeps_remaining_dotenv_values(project_env, monkeypatch):
    write_database_env(project_env)
    monkeypatch.setenv("DB_PASSWORD", "process-secret")
    config = SqlServerConfig.from_environment()
    assert config.username == "env_user"
    assert config.password == "process-secret"
    assert config.driver == "Auto Driver"


def test_missing_dotenv_keeps_existing_local_defaults(project_env):
    assert not project_env.exists()
    config = SqlServerConfig.from_environment()
    expected = SqlServerConfig.from_jdbc_url(
        database.DEFAULT_LOCAL_DB_URL,
        username=database.DEFAULT_LOCAL_DB_USERNAME,
        password=database.DEFAULT_LOCAL_DB_PASSWORD,
    )
    assert config == expected


def test_dotenv_password_preserves_literal_variables_hash_unicode_and_backslashes(project_env, monkeypatch):
    monkeypatch.setenv("SECRET_PART", "must-not-expand")
    write_database_env(project_env, password=r"'mật khẩu # ${SECRET_PART} \test'")
    config = SqlServerConfig.from_environment()
    assert config.password == r"mật khẩu # ${SECRET_PART} \test"


@pytest.mark.parametrize("key", ["DB_URL", "DB_USERNAME", "DB_PASSWORD"])
@pytest.mark.parametrize("value", ["", None])
def test_empty_or_valueless_dotenv_required_key_is_rejected(project_env, key, value):
    write_database_env(project_env)
    line = key if value is None else f"{key}={value}"
    with project_env.open("a", encoding="utf8") as stream:
        stream.write(line + "\n")
    with pytest.raises(DatabaseConfigurationError, match="Cần khai báo"):
        SqlServerConfig.from_environment()


def test_empty_process_value_does_not_fall_back_to_dotenv(project_env, monkeypatch):
    write_database_env(project_env)
    monkeypatch.setenv("DB_PASSWORD", "")
    with pytest.raises(DatabaseConfigurationError):
        SqlServerConfig.from_environment()


def test_reading_dotenv_does_not_mutate_process_environment(project_env):
    write_database_env(project_env)
    before = dict(os.environ)
    SqlServerConfig.from_environment()
    assert dict(os.environ) == before


def test_dotenv_is_read_again_for_new_connections(project_env):
    write_database_env(project_env, password="first")
    assert SqlServerConfig.from_environment().password == "first"
    write_database_env(project_env, password="second")
    assert SqlServerConfig.from_environment().password == "second"


def test_connection_uses_dotenv_without_contacting_a_real_database(project_env, monkeypatch):
    write_database_env(project_env)
    connect = Mock(return_value=object())
    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(connect=connect))
    connection = database.connect_sql_server()
    assert connection is connect.return_value
    args, kwargs = connect.call_args
    assert "SERVER=env-server\\INSTANCE" in args[0]
    assert "DATABASE=env_db" in args[0]
    assert "UID=env_user" in args[0]
    assert "PWD=local-secret" in args[0]
    assert kwargs == {"autocommit": False}


def test_explicit_connection_config_does_not_read_dotenv(project_env, monkeypatch):
    project_env.write_text("DB_PASSWORD=\n", encoding="utf8")
    explicit = SqlServerConfig.from_jdbc_url(
        "jdbc:sqlserver://explicit;databaseName=explicit_db", username="u", password="p"
    )
    connect = Mock(return_value=object())
    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(connect=connect))
    database.connect_sql_server(explicit)
    assert "DATABASE=explicit_db" in connect.call_args.args[0]
