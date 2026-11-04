# Industry Profile v1

## Mục đích

Industry profile tách phần dùng chung của persona khỏi dữ liệu riêng của từng
ngành. Scenario phải chọn rõ ngành trước khi chạy:

```json
{
  "industry_id": "cafe",
  "industry_profile_version": "cafe-mvp-v1"
}
```

Profile không quyết định hành động và không chứa lịch sử agent. Nó chỉ xác định:

- reduced persona fields được phép dùng trong ngành;
- các field dùng để phân nhóm hoặc kiểm tra cohort;
- tag registry và persona mapping tương ứng;
- các field nền ở stage chọn persona (`stage_base_fields`); mapping bổ sung
  field theo tag đang hiển thị, không phải đưa tất cả field vào prompt.

## Profile cafe MVP

File chuẩn là
`data/industries/cafe/cafe-mvp-v1.json`. Profile cafe hiện dùng 12 field
persona lõi và 5 field liên quan đến cafe. Các field bị thiếu vẫn bị bỏ qua;
không đổi thành `Neutral`, `None` hoặc giá trị suy đoán.
Năm `grouping_fields` được phép lưu cùng persona để kiểm tra cohort nhưng không
tự được đưa vào prompt. Đây không phải cơ cấu quan hệ ban đầu với brand.
17 field là hợp các field mà mapping hiện hành thực sự sử dụng, không phải
kết luận rằng chỉ 17 field này ảnh hưởng đến hành vi.

Loader lưu bản profile đầy đủ và SHA-256 nội dung schema/tag/mapping trong
`industry_profile_snapshot`, thuộc `runs.config_snapshot_json`. Khi load hoặc
resume, snapshot khác cấu hình đang cài sẽ bị từ chối; cần khôi phục đúng bộ
cấu hình hoặc tạo run mới. Không tự thay profile của một run đã bắt đầu.

Scenario đầu vào mới phải khai báo hai trường ngành ở trên. Scenario cũ thiếu
chúng bị từ chối rõ ràng, không tự mặc định cafe. Database/run cũ không bị sửa;
chưa có migration để resume các run thiếu metadata ngành.

## Ranh giới

- Persona field mô tả đặc điểm của agent; không phải trạng thái quan hệ với
  brand.
- `awareness`, `attitude`, `familiarity` và lịch sử mua sẽ được bổ sung bằng
  contract relationship riêng.
- Profile không tự tạo mapping nhân khẩu sang hành vi.
- Tag, mapping và persona schema phải cùng version được profile tham chiếu.
- **Giới hạn triển khai:** renderer, gateway và policy hiện dùng một bộ
  schema/tag/mapping v2 cài sẵn. Validator kiểm tra profile tương thích với
  chính bộ đó và từ chối ngành/bộ tài nguyên khác. Chưa thể chỉ thêm JSON
  ngành mới rồi chạy. Khi triển khai ngành thứ hai, cần truyền bộ tài nguyên
  của profile xuyên suốt validator, context renderer, gateway và policy.
- Decoder/projector MatrAIx đã có tại `simulation/persona_matraix.py` và
  `paper_research/project_matraix_persona.py`. Có thể xuất reduced persona từ
  từng shard sang JSONL; chưa chọn cohort và chưa tạo trạng thái quan hệ brand.
  Cách chạy cần môi trường ingestion có `pyarrow`.
- Với MVP, projector hỗ trợ `--complete`: field thiếu được hoàn thiện theo
  policy `persona-completion-v1`. Field gốc hợp lệ được giữ nguyên; một số
  field liên quan được suy ra bằng rule; phần còn lại dùng weighted prior và
  seed ổn định. Đây là dữ liệu hoàn thiện cho mô phỏng, không phải quan sát
  gốc từ MatrAIx.
- Selector cohort nằm tại `paper_research/select_persona_cohort.py`. Mặc định
  chọn 60 persona human-grounded và 40 synthetic, đồng thời yêu cầu mỗi
  persona có ít nhất một field domain cafe được quan sát thật. Tỷ lệ này là
  cấu hình MVP, không phải tuyên bố về dân số thật.

Kiểm tra:

```bash
python3 -m paper_research.validate_industry_profiles
python3 -m simulation.self_check
```
