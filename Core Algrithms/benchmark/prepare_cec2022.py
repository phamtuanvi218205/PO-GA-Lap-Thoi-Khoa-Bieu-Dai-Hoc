"""Tai va bien dich bo danh gia CEC 2022 chinh thuc vao cache local.

Source duoc pin theo commit va SHA-256. Thu muc .cache bi Git bo qua; khong
vendor lai ma nguon/du lieu cua ben thu ba vao project.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


OFFICIAL_REPOSITORY = "https://github.com/P-N-Suganthan/2022-SO-BO"
OFFICIAL_COMMIT = "de20505283b76ec6bf17a2e8fc6052e655830691"
ARCHIVE_URL = (
    "https://raw.githubusercontent.com/P-N-Suganthan/2022-SO-BO/"
    f"{OFFICIAL_COMMIT}/CEC2022.zip"
)
ARCHIVE_SHA256 = "dd46b9efcfe79253c1dc0cb0f09c7f0ed0e24d5eb235ee14ca09be29f7def626"

BENCHMARK_DIRECTORY = Path(__file__).resolve().parent
CACHE_DIRECTORY = BENCHMARK_DIRECTORY / ".cache" / "cec2022_official"
ARCHIVE_PATH = CACHE_DIRECTORY / "CEC2022.zip"
SOURCE_CONTAINER = CACHE_DIRECTORY / "source"
SOURCE_DIRECTORY = SOURCE_CONTAINER / "CEC2022" / "C-Code"
LIBRARY_PATH = CACHE_DIRECTORY / "cec2022_official.dll"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_archive() -> None:
    CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    if ARCHIVE_PATH.exists() and _sha256(ARCHIVE_PATH) == ARCHIVE_SHA256:
        return

    temporary_path = ARCHIVE_PATH.with_suffix(".zip.tmp")
    urllib.request.urlretrieve(ARCHIVE_URL, temporary_path)
    actual_hash = _sha256(temporary_path)
    if actual_hash != ARCHIVE_SHA256:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(
            "CEC2022.zip khong dung SHA-256 da pin; dung lai de tranh "
            "chay nham source bi thay doi."
        )
    temporary_path.replace(ARCHIVE_PATH)


def _extract_source() -> None:
    required = SOURCE_DIRECTORY / "cec22_test_func.cpp"
    if required.exists() and (SOURCE_DIRECTORY / "input_data").is_dir():
        return

    CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE_DIRECTORY) as temporary:
        temporary_directory = Path(temporary)
        with zipfile.ZipFile(ARCHIVE_PATH) as archive:
            archive.extractall(temporary_directory)
        extracted = temporary_directory / "CEC2022"
        if not (extracted / "C-Code" / "cec22_test_func.cpp").exists():
            raise RuntimeError("CEC2022.zip khong co cau truc source mong doi.")
        SOURCE_CONTAINER.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extracted), str(SOURCE_CONTAINER / "CEC2022"))


def _build_library() -> None:
    if LIBRARY_PATH.exists():
        return

    try:
        from setuptools._distutils.ccompiler import new_compiler
        from setuptools._distutils.sysconfig import customize_compiler
    except ImportError as error:
        raise RuntimeError(
            "Can setuptools va Microsoft C++ Build Tools de bien dich "
            "CEC 2022 chinh thuc."
        ) from error

    compiler = new_compiler()
    customize_compiler(compiler)
    wrapper = BENCHMARK_DIRECTORY / "cec2022_native_wrapper.cpp"
    source = SOURCE_DIRECTORY / "cec22_test_func.cpp"

    with tempfile.TemporaryDirectory(dir=CACHE_DIRECTORY) as temporary:
        build_directory = Path(temporary)
        objects = compiler.compile(
            [str(wrapper), str(source)],
            output_dir=str(build_directory),
        )
        built_path = build_directory / LIBRARY_PATH.name
        compiler.link_shared_object(objects, str(built_path))
        built_path.replace(LIBRARY_PATH)


def prepare() -> Path:
    """Bao dam source, data va DLL CEC 2022 chinh thuc san sang."""

    _download_archive()
    _extract_source()
    _build_library()
    return LIBRARY_PATH


if __name__ == "__main__":
    print(prepare())
