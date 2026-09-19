// Thin C ABI wrapper around the official CEC 2022 C++ evaluator.
// The official source declares these globals as extern and defines them in
// its example main.cpp. The benchmark links only the evaluator, so they are
// defined here instead.

extern void cec22_test_func(
    double* x,
    double* f,
    int dimensions,
    int population_size,
    int function_number
);

double* OShift = nullptr;
double* M = nullptr;
double* y = nullptr;
double* z = nullptr;
double* x_bound = nullptr;
int ini_flag = 0;
int n_flag = 0;
int func_flag = 0;
int* SS = nullptr;

extern "C" __declspec(dllexport) void cec22_evaluate(
    double* x,
    double* f,
    int dimensions,
    int population_size,
    int function_number
) {
    cec22_test_func(x, f, dimensions, population_size, function_number);
}
