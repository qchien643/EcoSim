# Lộ trình cải thiện mô phỏng

## Mốc hiện tại

Đã có runtime hai mode, context theo stage, adapter model, SQLite history,
checkpoint, metrics theo phiên và report. Test offline kiểm tra tính đúng
của code; không xác nhận độ chính xác dự đoán hành vi.

## Thứ tự triển khai

| Mốc | Trạng thái | Đầu ra và điều kiện hoàn tất |
| --- | --- | --- |
| 0. Đồng bộ tài liệu | Một phần | Đã sửa trạng thái runtime ở flow, FRD-05 và tài liệu orchestrator; tiếp tục xử lý các ghi chú nháp cũ khi sửa module liên quan. |
| 1. Industry profile | Đã triển khai nền cafe | 12 core field, 5 domain field, grouping riêng; validate metadata, snapshot/hash và chặn drift. Chưa hỗ trợ bộ tài nguyên ngành thứ hai. |
| 2. Persona MatrAIx | Đã triển khai decoder/projector/completion | Giải mã nibble, null bitmap, override; lọc theo profile, kiểm tra enum, giữ provenance và hoàn thiện deterministic cho MVP. Adapter Parquet cần `pyarrow`; chưa chọn cohort. |
| 3. Cohort cafe | Đã triển khai selector MVP | Chọn deterministic theo seed, quota human-grounded/synthetic, yêu cầu field domain quan sát thật, hoàn thiện field thiếu và lưu manifest/provenance. Chưa gán quan hệ brand. |
| 4. Quan hệ ban đầu | Đã triển khai | Tách biết/quen/thái độ/từng mua khỏi persona; phân bổ đúng số lượng với seed, materialize snapshot và lưu `run_agent_relationships`. |
| 5. Quan hệ và context | Đã triển khai nền | Policy lọc relationship/brand history theo stage, transition deterministic sau event resolve, projection current state và kiểm tra context. Chưa hiệu chỉnh transition bằng dữ liệu thật. |
| 6. Scenario hoàn chỉnh | Đã triển khai nền | Resolve cohort, persona provenance, customer structure và quan hệ trước run; coordinator chỉ nhận snapshot đã kiểm tra. |
| 7. Kiểm toán context | Đã triển khai nền | Audit prompt thực tế qua hai phiên: không lộ internal ID, đúng ranh giới article/product, persona mapping, current state, brand history và relationship state. Đây là kiểm tra contract/visibility, chưa đo độ chính xác hành vi của JEV/LLM. |
| 8. Chạy thử và hiệu chỉnh | Chưa hoàn tất | Campaign/catalog được marketer xác nhận; đo kết quả toàn flow, fallback, empty/unresolved và độ nhạy threshold. |

## Giới hạn cần giữ

- Không quay lại thiết kế recommendation, không tự thêm score bonus theo lịch sử.
- Giữ persona cố định trong MVP; quan hệ brand và event là dữ liệu riêng.
- Không tự kết luận lần gặp thứ hai chắc chắn biết brand: cần bằng chứng
  từ lần tiếp xúc trước và policy nhận biết đã chốt.
- Phase 4 chỉ lưu trạng thái khởi tạo; chưa tự đưa toàn bộ quan hệ vào context.
- Relationship state hiện tại được cập nhật từ bằng chứng rõ ràng; emotion,
  like/dislike và `not_buy` chưa tự đổi attitude.
- Kiểm tra điều kiện sử dụng dữ liệu trước khi đưa cohort vào sản phẩm.
- Chưa làm UI chọn ngành, chatbot, sinh bài tự động hoặc tối ưu accumulator.
  Bản thử tối thiểu dùng scenario chuẩn bị offline và report hiện có.

Chi tiết mốc 1: [Industry Profile v1](industry-profile-v1.md).
