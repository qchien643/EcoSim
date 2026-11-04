# 04 — Kiểm tra độ phủ thuộc tính persona

## Kết luận nhanh

Đã quét toàn bộ **999.847 persona** trong `data/matraix/persona_1m/data/`.
Kết quả tách riêng 400.000 persona tổng hợp và 599.847 persona không tổng hợp.
“Có thể dùng” dưới đây nghĩa là giá trị tồn tại và khớp enum trong schema; các
giá trị như `null`, `Unsupported` hoặc giá trị ngoài enum không được tính.

| Nhóm | Toàn bộ | Không tổng hợp | Tổng hợp |
| --- | ---: | ---: | ---: |
| `topic_coffee` hợp lệ | 41,94% | 3,23% | 100% |
| `lstyle_coffee_ritual` hợp lệ | 40,85% | 1,41% | 100% |
| `lstyle_caffeine` hợp lệ | 42,57% | 4,27% | 100% |
| Có đủ 3 trường cafe cốt lõi | 40,17% | 0,27% | 100% |

Vì vậy, nếu chỉ dùng persona không tổng hợp làm cơ sở dữ liệu quan sát được,
các trường cafe chuyên biệt **khá thưa**. Tỷ lệ khoảng 40% của toàn bộ release
bị kéo lên bởi 400.000 persona tổng hợp, trong đó các trường được điền đầy đủ.

## So sánh với nhóm fitness

Fitness có độ phủ tốt hơn trong persona không tổng hợp:

| Nhóm | Toàn bộ | Không tổng hợp | Tổng hợp |
| --- | ---: | ---: | ---: |
| `topic_fitness` hợp lệ | 53,52% | 22,52% | 100% |
| `lstyle_exercise_freq` hợp lệ | 51,68% | 19,47% | 100% |
| Có đủ 2 trường fitness cốt lõi | 51,62% | 19,35% | 100% |

Tuy nhiên, fitness cũng bị lệch nguồn: phần lớn giá trị hợp lệ không tổng hợp
đến từ các persona Wikipedia. Độ phủ cao hơn không đồng nghĩa dữ liệu đại diện
tốt hơn cho khách hàng mua hàng.

## Chi tiết nguồn và giới hạn

- `topic_coffee` không tổng hợp: 19.356/599.847 persona hợp lệ (3,23%).
- Ba trường cafe cốt lõi cùng hợp lệ: 1.623/599.847 (0,27%).
- Amazon có tín hiệu cafe rõ hơn: `topic_coffee` 13.722 bản ghi và
  `lstyle_coffee_ritual` 7.298 bản ghi hợp lệ.
- Wikipedia đóng góp nhiều `topic_coffee`, nhưng không phải tập khảo sát khách
  hàng. Không nên diễn giải các con số này thành tỷ lệ người uống cafe ngoài đời.
- Dữ liệu thiếu không được tự điền; `None` là một enum hợp lệ ở một số trường,
  khác với null.

## Quyết định đề xuất

Chưa nên bỏ cafe chỉ vì độ phủ thấp. Có thể giữ cafe làm ngành triển khai đầu
tiên nếu persona được dùng như **context tham khảo**, còn tag sản phẩm, trạng
thái thương hiệu và lịch sử mua được mô hình hóa riêng trong kịch bản.

Không nên dùng ba trường cafe làm điều kiện bắt buộc để chọn agent. Khi thiếu,
agent vẫn có thể dùng các trường chung như mua sắm, chi tiêu, quảng cáo, hoạt
động và các tag do marketer khai báo.

Nếu mục tiêu của bản thử nghiệm là kiểm tra khả năng dùng thuộc tính có nguồn
grounding tốt, fitness là ứng viên dữ liệu tốt hơn để thử tiếp. Đây là lựa chọn
đánh giá dữ liệu, chưa phải quyết định đổi ngành của sản phẩm.

## Cách tái tạo

```bash
python3 paper_research/audit_persona_coverage.py --self-check
PYTHONPATH=/tmp/sangtao_pyarrow python3 paper_research/audit_persona_coverage.py
```

Script đọc Parquet ở chế độ chỉ đọc, kiểm tra packing/nul bitmap/override và
ghi số liệu tổng hợp vào [persona-coverage.json](persona-coverage.json).
