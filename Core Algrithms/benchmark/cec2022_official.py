"""Adapter NumPy/ctypes cho evaluator CEC 2022 C++ chinh thuc."""

from __future__ import annotations

import ctypes
import os
import threading

import numpy as np

from prepare_cec2022 import LIBRARY_PATH, SOURCE_DIRECTORY, prepare


_LOCK = threading.Lock()
_LIBRARY = None
_EVALUATE = None
_ACTIVE_KEY: tuple[int, int] | None = None


def _load_evaluator():
    global _LIBRARY, _EVALUATE
    if _EVALUATE is not None:
        return _EVALUATE

    if not LIBRARY_PATH.exists():
        prepare()
    _LIBRARY = ctypes.CDLL(str(LIBRARY_PATH))
    _EVALUATE = _LIBRARY.cec22_evaluate
    double_pointer = ctypes.POINTER(ctypes.c_double)
    _EVALUATE.argtypes = [
        double_pointer,
        double_pointer,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    _EVALUATE.restype = None
    return _EVALUATE


def evaluate_population(
    population: np.ndarray,
    function_number: int,
) -> np.ndarray:
    """Danh gia mot ma tran (N, D) bang CEC 2022 C++ chinh thuc."""

    global _ACTIVE_KEY
    positions = np.ascontiguousarray(population, dtype=np.float64)
    if positions.ndim != 2:
        raise ValueError("CEC 2022 can population co kich thuoc (N, D).")
    population_size, dimensions = positions.shape
    if dimensions not in (10, 20):
        raise ValueError("Benchmark nay chi dung CEC 2022 voi D=10 hoac D=20.")
    if not 1 <= function_number <= 12:
        raise ValueError("CEC 2022 chi co function_number tu 1 den 12.")

    values = np.empty(population_size, dtype=np.float64)
    evaluator = _load_evaluator()
    key = (function_number, dimensions)

    with _LOCK:
        if _ACTIVE_KEY != key:
            previous_directory = os.getcwd()
            try:
                os.chdir(SOURCE_DIRECTORY)
                evaluator(
                    positions.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                    values.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                    dimensions,
                    population_size,
                    function_number,
                )
            finally:
                os.chdir(previous_directory)
            _ACTIVE_KEY = key
        else:
            evaluator(
                positions.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                values.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                dimensions,
                population_size,
                function_number,
            )

    return values
