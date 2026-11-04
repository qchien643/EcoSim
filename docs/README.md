# Bản đồ tài liệu ecoSim

**Đọc nhanh:** [dữ liệu và mô hình ra quyết định](ECOSIM_DATA_AND_DECISION_MODEL.md)
giải thích thông tin đi từ persona, campaign và từng phiên qua các bước
quyết định đến sự kiện, trạng thái và báo cáo. Quyết định của agent là lõi
của sản phẩm; kết quả hiện tại chưa được hiệu chuẩn theo hành vi người thật.

## Sơ đồ tương tác (mở trong trình duyệt)

- [Luồng quyết định của agent](ecosim-agent-decision-workflow.html): từng bước,
  context, lựa chọn và dữ liệu ghi lại.
- [Kiến trúc quyết định](ecosim-decision-architecture.html): backend,
  gateway, dữ liệu và kết quả.

## Tài liệu theo nhu cầu

| Muốn tìm hiểu | Bắt đầu ở |
| --- | --- |
| Mục tiêu, phạm vi và yêu cầu | [SRS](srs/README.md) và [FRD](frd/README.md) |
| Backend đang hoạt động thế nào | [Thiết kế backend](backend/README.md) và [HTTP API](backend/openapi.yaml) |
| Model nhận gì và chọn hành động ra sao | [Luồng agent](technical/luong-agent-jev-va-llm.md) và [context](technical/context-rendering-v2.md) |
| Chạy dự án trên máy khác | [Khởi động](../KHOI-DONG.md) và [dữ liệu cục bộ](../data/README.md) |

`docs/01-*` đến `docs/08-*` và `docs/technical/` ghi lại các giai đoạn thiết
kế trước đây; nếu khác với runtime backend, ưu tiên `docs/backend/` và code
trong `backend/`, `simulation/`. Không dùng tài liệu làm bằng chứng về độ chính
xác dự báo nếu chưa có benchmark đối chiếu thực nghiệm.
