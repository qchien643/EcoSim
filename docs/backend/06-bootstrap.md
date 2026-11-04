# Nạp dữ liệu nền vào backend

**Lưu ý cho bản clone GitHub:** `data/personas/cafe_mvp/cohort.jsonl` và
`manifest.json` không nằm trong repo. Trước khi chạy lệnh dưới đây, chuẩn bị
cohort theo [hướng dẫn dữ liệu](../../data/README.md) và kiểm tra quyền dùng
nguồn MatrAIx; nếu thiếu, bootstrap sẽ báo lỗi. `backend.self_check` dùng
fixture nhỏ, còn `backend.api.self_check` và `backend.bootstrap_self_check`
cần cohort đã chuẩn bị.

## Chạy một lần trước khi sử dụng API

Từ `ecoSim`, dùng môi trường Python đã cài:

```bash
.venv/bin/python -m backend.bootstrap
```

Mặc định ghi `data/ecosim-backend.sqlite`, hoặc đường dẫn từ biến môi trường
`ECOSIM_DATABASE`. Có thể chỉ định `--database /duong/dan/backend.sqlite`;
thư mục cha phải tồn tại. API phải dùng cùng database. Lệnh chạy offline,
không cần API key, không tạo campaign/scenario/run và không gọi model.

## Dữ liệu được nạp

| Dữ liệu | Nguồn | Định danh để dùng trong scenario |
| --- | --- | --- |
| Bundle ngành | Profile cafe, schema persona, tag, mapping, renderer và policy hiện hành | `industry_id: cafe`, `profile_version: cafe-mvp-v1` |
| Dataset | `data/matraix/source_metadata.json`, `persona_1m/manifest.json`, `persona_codes.schema.json` | ID `matraix_persona_1m_` + SHA release; CLI in ID đầy đủ |
| Cohort | `data/personas/cafe_mvp/manifest.json` và `cohort.jsonl` | `cohort_id: cafe-mvp-cohort-v1` |

Cohort hiện có 100 persona × 22 trường: 60 human-grounded và 40 synthetic.
Giữ nguyên giá trị và provenance `observed/derived/imputed_prior`; importer
không bịa hoặc hoàn thiện lại trường. Không gán trạng thái biết/thích/ghét/
từng mua thương hiệu ở bước này; scenario thực hiện việc đó sau.

## Kiểm tra và tính an toàn

- Kiểm tra đủ trường ngành, enum cả schema giảm gọn lẫn codebook MatrAIx,
  provenance, không trùng ID, số lượng/nguồn/quota và điều kiện lĩnh vực.
- Lưu SHA release, hash schema/manifest/bundle, SHA-256 file cohort, seed và
  selection policy. Giữ usage notice từ nguồn; không xác nhận quyền thương mại.
- Một transaction cho dataset, industry và cohort. Lỗi giữa chừng rollback,
  không công bố nhóm ready dở dang; không lưu record failed mới.
- Chạy lại đối chiếu metadata/hash **và từng member trong SQLite**. Giống
  nhau trả `unchanged`; khác nhau hoặc bị disabled thì dừng, không overwrite.
- Không nâng cấp hay xóa database experiment cũ. Không tự import lúc API khởi động.

Phạm vi xác minh là các file cohort/schema/metadata đã chuẩn bị, **không**
đọc hay hash lại toàn bộ shard Parquet, không chứng minh từng record khớp raw
source. Không cần `pyarrow` ở bước này. Thao tác chọn/giải mã dữ liệu nguồn
vẫn thuộc pipeline chuẩn bị persona.

Importer lấy ngành/profile từ manifest; đường dẫn khác có thể truyền bằng
`--cohort-dir`, `--source-dir`. `source_metadata.json` nằm ở thư mục cha của
`source-dir`. `--cohort-id` dùng cho một cohort phiên bản mới; không bỏ qua
kiểm tra xung đột dataset/profile. Bundle khác cần có version mới tương ứng.

## Kiểm tra từ API

- `GET /api/v1/industries`: có `cafe`.
- `GET /api/v1/datasets`: metadata release MatrAIx.
- `GET /api/v1/cohorts`: có `cafe-mvp-cohort-v1`, size 100.
- `GET /api/v1/cohorts/cafe-mvp-cohort-v1/members?limit=100`: 100 persona.

Đưa `cohort_id`, `industry_id`, `profile_version` ở bảng trên vào setup
scenario; `agent_count` không vượt 100. Marketer không cần import lại mỗi
lần tạo chiến dịch.

## Kiểm thử không trả phí

```bash
.venv/bin/python -m backend.bootstrap_self_check
.venv/bin/python -m backend.api.self_check
```

Bootstrap check dùng file nguồn đã chuẩn bị nhưng chỉ ghi database tạm:
kiểm tra import/rerun, member bị sửa, enum/trường/provenance sai, trùng ID,
rollback, bảo toàn DB cũ và API đọc đủ 100 người. Có thử một run nhỏ với
gateway scripted để kiểm tra context/report sau import, không gọi JEV/LLM.
