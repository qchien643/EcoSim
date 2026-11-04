# Dữ liệu cần cho ecoSim

## Có trong bản GitHub

Chỉ có `contracts/`, `industries/`, `tags/`, `scenario_templates/` và
`matraix/source_metadata.json`, `matraix/persona_1m/{manifest.json,persona_codes.schema.json,projectdut_persona.schema.json}`.
Đây là schema, metadata và template; **không có một hàng persona nào**.
Một số self-check dùng fixture nhỏ để chạy offline; kiểm tra API/template
đầy đủ cần cohort cục bộ. Template cà phê là nội dung
chiến dịch mẫu, không phải danh sách agent.

## Không nằm trong Git

- `personas/cafe_mvp/manifest.json` và `cohort.jsonl`: cohort giảm gọn đã
  chuẩn bị; nguồn MatrAIx có điều khoản chỉ dùng cho nghiên cứu.
- `matraix/persona_1m/data/*.parquet`: 10 shard nguồn (~4,17 GB), không cần
  tải nếu chỉ kiểm tra code; tránh mở cả shard vào RAM.
- `ecosim-backend.sqlite`, `scenarios/`, `posim/`: database, cấu hình chạy
  cục bộ và tư liệu bên thứ ba. Không cam kết quyền tái phân phối.

## Muốn tự tạo cohort để chạy giao diện

1. Đọc điều khoản của MatrAIx tại nguồn và xin quyền phù hợp với mục đích sử
   dụng. Lấy đúng release khớp `matraix/source_metadata.json` và manifest.
2. Đặt các shard đúng các đường dẫn `path` trong
   `matraix/persona_1m/manifest.json`; kiểm tra checksum SHA-256 theo manifest.
   `requirements.txt` không cài `pyarrow`: chỉ cài thêm trong môi trường
   chuẩn bị dữ liệu khi thực sự chạy bước này.
3. Chạy từ `ecoSim/`:

   ```bash
   .venv/bin/python -m pip install pyarrow
   .venv/bin/python -m paper_research.select_persona_cohort \
     --output-dir data/personas/cafe_mvp --size 100 --seed 20260928
   .venv/bin/python -m backend.bootstrap
   ```

Script chọn cohort quét các shard; có thể tốn thời gian và dung lượng. Nếu
đã có cohort được cấp phép, đặt `manifest.json` và `cohort.jsonl` vào thư mục
trên thay vì sinh lại. Bootstrap kiểm tra định dạng, enum và nguồn, không tự
tải hoặc tự sửa dữ liệu; xem [điều kiện nạp](../docs/backend/06-bootstrap.md).
Không đưa cohort hoặc khóa truy cập vào commit.
