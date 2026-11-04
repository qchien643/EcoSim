# Persona–Behavior Alignment Benchmark v1

## Mục đích

Benchmark này dùng LLM judge để đánh giá một thuộc tính persona có phù hợp
với hành vi mô phỏng hay không. Phiên bản hiện tại chỉ đo
`cog_attention_span` trong phiên 1, sử dụng hành vi chú ý quan sát được qua
`attention_score` và `attend/skip`. Đây là metric đánh giá phương pháp mô
phỏng, không phải metric hiệu quả chiến dịch.

## Cách chấm

Mỗi agent nhận một điểm từ 1 đến 5:

- `1`: hành vi mâu thuẫn rõ với thuộc tính persona.
- `2`: phần lớn không phù hợp.
- `3`: bằng chứng hỗn hợp, trung tính hoặc chưa đủ.
- `4`: phần lớn phù hợp.
- `5`: phù hợp rõ ràng và lặp lại.

LLM phải trả về Structured Output gồm `score`, `evidence_event_ids`,
`evidence_summary` và `insufficient_evidence`. Các event được trích dẫn phải
tồn tại trong packet của chính agent đó.

## Kết quả được báo cáo

- `mean_score`: trung bình tất cả agent; điểm 3 được dùng cho case thiếu bằng
  chứng.
- `mean_assessable_score`: trung bình chỉ các agent đủ bằng chứng; đây là chỉ
  số nên dùng để đọc chất lượng hành vi.
- `score_distribution`: số agent ở từng mức 1–5.
- `high_alignment_rate`: tỷ lệ agent đạt điểm 4 hoặc 5.
- `insufficient_evidence_rate`: tỷ lệ trace chưa đủ bằng chứng.

## Chạy lại

Từ thư mục gốc repository:

```bash
bash experiments/rerun_persona_behavior_alignment.sh
```

Script chạy self-check trước, sau đó đọc `OPENAI_API_KEY` và `OPENAI_MODEL`
từ `.env`, gọi tuần tự từng agent và lưu checkpoint tại:

```text
experiments/persona-alignment-cog-attention-span-session-1.json
```

Nếu lần chạy bị gián đoạn, chạy tiếp bằng:

```bash
bash experiments/rerun_persona_behavior_alignment.sh --resume
```

Không dùng `--resume` nếu database hoặc định nghĩa benchmark đã thay đổi;
hãy đổi tên output hoặc xóa output cũ sau khi kiểm tra thủ công.

Wrapper tự dùng `/tmp/projectdut-openai-venv/bin/python` nếu virtualenv này
tồn tại. Có thể chỉ định Python khác bằng biến môi trường:

```bash
PYTHON_BIN=/path/to/python bash experiments/rerun_persona_behavior_alignment.sh --resume
```

## Dữ liệu hiện tại

Database: `experiments/cafe-live-100x3-20260928.sqlite`  
Run: `run_cafe_100x3_live_20260928`  
Kết quả ngày 28/09/2026: 100/100 agent, mean assessable score `3.80/5`,
high-alignment rate `63%`.
