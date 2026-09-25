# University Timetabling with GA–PO

Ứng dụng xây dựng thời khóa biểu đại học, định hướng kết hợp Genetic Algorithm
(GA) và Parrot Optimizer (PO V2).

## Công nghệ hiện tại

- Java và Spring Boot
- Maven Wrapper
- Spring Data JPA
- Microsoft SQL Server
- Python cho toàn bộ lõi thuật toán GA, PO V2 và GA–PO

Java không cài đặt lại thuật toán tối ưu. Backend Java chịu trách nhiệm đọc/ghi
dữ liệu SQL Server và cung cấp API cho giao diện demo. Python nhận dữ liệu đã
chuẩn hóa, chạy thuật toán và trả kết quả để Java lưu/hiển thị ở giai đoạn tích
hợp sau.

## Cấu hình local

File `src/main/resources/application.yaml` chứa cấu hình riêng của từng máy và
không được đưa lên Git.

1. Sao chép `src/main/resources/application.example.yaml` thành
   `src/main/resources/application.yaml`.
2. Khai báo các biến môi trường `DB_URL`, `DB_USERNAME`, `DB_PASSWORD` trong IDE
   hoặc hệ điều hành. Có thể xem tên biến mẫu trong `.env.example`.
3. Không commit mật khẩu, API key, JWT secret hoặc dữ liệu thật.

## Chạy backend

Trên Windows:

```powershell
.\mvnw.cmd spring-boot:run
```

Chạy kiểm thử:

```powershell
.\mvnw.cmd test
```

## Quy trình làm việc nhóm

1. Không làm trực tiếp trên `main`.
2. Tạo nhánh theo dạng `feature/ten-chuc-nang`.
3. Commit nhỏ, nội dung rõ ràng.
4. Push nhánh và tạo Pull Request để partner kiểm tra trước khi merge.

Ví dụ:

```powershell
git switch -c feature/po-core
git add .
git commit -m "feat: implement PO population model"
git push -u origin feature/po-core
```
