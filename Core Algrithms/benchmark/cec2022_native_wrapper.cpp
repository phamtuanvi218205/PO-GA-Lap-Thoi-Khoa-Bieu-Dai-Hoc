// Cầu nối ABI C tối thiểu cho evaluator C++ chính thức của CEC 2022.
//
// Python ctypes chỉ cần một hàm có tên và quy ước gọi ổn định. Mã chính thức
// khai báo các biến trạng thái dưới đây là extern và định nghĩa chúng trong
// main.cpp mẫu. Benchmark không liên kết chương trình mẫu nên phải cung cấp
// các định nghĩa tại đây; toàn bộ công thức vẫn nằm trong cec22_test_func.cpp.

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
    // Không biến đổi dữ liệu: chuyển nguyên con trỏ quần thể và vector kết quả
    // sang evaluator chính thức. Một hàng của x tương ứng một cá thể D chiều.
    cec22_test_func(x, f, dimensions, population_size, function_number);
}
