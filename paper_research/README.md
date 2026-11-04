# Paper research

Hai paper trong thư mục này đã được đọc và chuyển sang Markdown để tra cứu:

- `posim-2603.23884.pdf` — POSIM: mô phỏng dư luận xã hội bằng agent đa tác tử.
- `matraix-2608.04205.pdf` — MatrAIx: hạ tầng persona quy mô lớn cho simulated-user evaluation.

## Kết luận áp dụng cho projectDut2026

POSIM cung cấp khung phù hợp cho vòng lặp mô phỏng: perception → belief → desire → intention → action. Belief nên tách thành phần ổn định (identity, psychology) và phần thay đổi nhanh (event opinion, emotion). Memory cần truy hồi theo cả độ mới và độ tương đồng; cảm xúc có thể suy giảm theo thời gian, nhận kích thích từ nội dung và lan truyền từ mạng lân cận. Recommendation nên kết hợp tương đồng, độ phổ biến, độ mới và exploration.

MatrAIx cung cấp schema persona lớn, gồm 1.290 thuộc tính phân loại và bản release khoảng 1 triệu persona. Dữ liệu được đóng gói trong Parquet bằng mã 4-bit; cần dùng `persona_codes.schema.json` để giải mã. Persona là công cụ mô phỏng, không phải mẫu đại diện dân số, vì vậy kết quả mua hàng chỉ nên dùng để tạo giả thuyết và phải được kiểm chứng bằng người thật.

## Kiểm tra dữ liệu

```bash
python3 paper_research/verify_data.py
```

Script đối chiếu kích thước và checksum với metadata đã ghim từ nguồn phát hành. Nội dung parse nằm trong `.firecrawl/`, thư mục này được Git bỏ qua.
