"""Read-only checks for the standalone manual SQL installer."""
from pathlib import Path
import ast
import re

ROOT=Path(__file__).resolve().parents[2]
SQL=ROOT/'Script/KHOI_TAO_DATABASE.sql'


def test_manual_script_has_schema_and_only_required_background_data():
    text=SQL.read_text(encoding='utf8')
    assert len(re.findall(r'^CREATE TABLE dbo\.',text,re.M))==34
    assert len(re.findall(r'^CREATE INDEX ',text,re.M))==13
    assert set(re.findall(r'INSERT INTO dbo\.(\w+)',text))=={
        'TimePeriod','TeachingDurationRule','AllowedPeriodBlock','ConstraintSetting'}
    assert 'SOFT_LECTURER_GAP' in text and '0.3720' in text
    assert '0.1487, 6.0000' in text and '0.2975' in text and '0.1818' in text
    assert len(re.findall(r"\('HARD_",text))==7
    assert len(re.findall(r"\('SOFT_",text))==6
    assert not re.search(r'^\s*(DROP|TRUNCATE|DELETE|UPDATE)\b',text,re.M|re.I)


def test_manual_script_refuses_existing_tables_and_rolls_back_on_error():
    text=SQL.read_text(encoding='utf8')
    assert text.index('IF EXISTS (SELECT 1 FROM sys.tables')<text.index('CREATE TABLE dbo.AcademicTerm')
    assert 'THROW 51002' in text
    assert 'BEGIN TRANSACTION;' in text and 'COMMIT TRANSACTION;' in text
    assert 'IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;' in text
    assert 'sp_getapplock' in text
    assert 'USE [KhoaLuanDemo]' in text


def test_api_has_no_automatic_database_schema_initialization():
    app=ROOT/'Core Algrithms/src/gapo_timetabling/application/api.py'
    tree=ast.parse(app.read_text(encoding='utf8'))
    imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any('database_bootstrap' in n for n in imports)
    names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
    assert 'ensure_application_database' not in names
    assert 'database_initializer' not in names
    assert not app.with_name('database_bootstrap.py').exists()
