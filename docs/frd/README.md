# FRD — Đặc tả chức năng và hành vi

Thư mục này chuyển các yêu cầu trong SRS thành **hành vi mà người dùng có
thể quan sát được**. Nội dung mô tả cách các chức năng vận hành ở mức sản
phẩm, nhưng không khóa vào một model, vector database hoặc stack lập trình
cụ thể.

## Tài liệu

- [01 — Chuẩn bị campaign và scenario](01-campaign-and-scenario.md)
- [02 — Mô phỏng session và attention](02-session-simulation-and-attention.md)
- [03 — Tương tác agent và lưu trữ](03-agent-interaction-and-records.md)
- [04 — Dashboard và phân tích](04-dashboard-and-analysis.md)
- [05 — Policy và trạng thái một phiên](05-session-policy-and-state.md)

Các lựa chọn kỹ thuật như JEV, OpenRouter, embedding, công nghệ lưu trữ và
schema cụ thể vẫn thuộc tài liệu kỹ thuật.

Bản phác thảo mới để đối chiếu khi review FRD:
[Luồng agent với JEV và LLM dự phòng](../technical/luong-agent-jev-va-llm.md).
Năm bước bài viết và ba bước mua hàng dùng policy v1 tại FRD-05.
FRD-05 là nguồn quyết định mới nhất về trạng thái, fallback và điều phối;
schema/renderer là hiện thực từng phần, chưa có engine tích hợp.
