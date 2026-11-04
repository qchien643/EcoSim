# Rà soát mức hoàn thiện backend mô phỏng

Ngày kiểm tra: 29/09/2026. Phạm vi: đọc code, chạy kiểm thử offline, tái
hiện lỗi với database tạm và đọc database lần chạy 100 agent ở chế độ chỉ
đọc. Không gọi JEV/OpenAI, không sửa runtime hoặc dữ liệu lần chạy cũ.

## Kết luận

**Đủ để thử nghiệm một scenario đã chuẩn bị trong database riêng; chưa đủ
để coi backend sản phẩm đã hoàn thiện.** Luồng quyết định chính hoạt động,
nhưng khởi tạo, dùng chung database và vòng đời chạy tiếp còn lỗi.
Các kiểm thử hiện có qua không có nghĩa các trường hợp này đã được bao phủ.

## Các phần đã có và được kiểm tra

| Phần | Kết quả |
| --- | --- |
| Scenario loader | Kiểm tra đầu vào, lịch cố định, catalog nhiều sản phẩm, materialize cohort và cơ cấu quan hệ |
| Context | Persona được chọn, tag có nguồn, giới hạn nội dung trước/sau đọc, lịch sử đúng agent/đối tượng/stage và trạng thái thương hiệu |
| Quyết định | Chuẩn hóa score, ngưỡng chú ý, chọn tag, đáp án phụ thuộc lịch sử, fallback khi kết quả không dùng được |
| Luồng | A1/A1R → A2 → A3 → A4 → A5; ghé shop mới xét từng sản phẩm B1/B1R → B2 → B3 |
| Lưu trữ | Event, tag, context, trạng thái gần nhất, liên kết cha, checkpoint; rollback nguyên stage |
| Nhiều phiên | Giữ lịch sử; chạy tuần tự/song song theo batch; chỉ chốt metric sau khi phiên hoàn tất |
| Báo cáo | Đếm, tỷ lệ có mẫu số, trạng thái phản ứng cuối phiên, lịch sử agent; rebuild không gọi model |

Database `experiments/cafe-live-100x3-20260928.sqlite`:

- 100 agent, 3 phiên đều `completed`; `PRAGMA quick_check` trả `ok`,
  `foreign_key_check` không có lỗi.
- 1.991 sự kiện và 1.991 context: 1.784 `resolved`, 186 `empty_result`,
  21 `unresolved`.
- 306 snapshot metric, hiện đều ở phạm vi `run`.

Đây là bằng chứng hệ thống đã chạy và lưu được dữ liệu, không phải chứng
minh độ chính xác dự đoán hay chất lượng mô phỏng hành vi.

## Lỗi cần sửa theo ưu tiên

### 1. Khởi tạo dở dang có thể bị đánh dấu hoàn tất — ưu tiên cao nhất

`RunCoordinator.load_scenario()` gọi nhiều hàm store tự commit riêng.
Khởi tạo nằm ngoài khối xử lý lỗi của `run()`. Nếu lỗi sau khi tạo run và
session nhưng trước khi lưu lịch, database còn một run `running` thiếu dữ liệu.

Đã tái hiện: cho `add_shop()` ném lỗi; mở lại database và chạy cùng scenario.
Runner thấy run đã tồn tại, bỏ qua khởi tạo, không tìm thấy bài nào trong
lịch đã lưu và báo `completed` với **0 event**, dù fixture có bài và agent.

Hướng sửa: khởi tạo toàn bộ snapshot trong một transaction; chỉ cho thực thi
khi dữ liệu đầu vào đã được materialize đầy đủ. Với run dở dang đã tồn tại,
phải báo lỗi kiểm tra tính đầy đủ hoặc có thủ tục phục hồi rõ ràng, không
coi “không có lịch trong DB” là “marketer chủ động để phiên trống”.

### 2. Nhiều run chung database bị trùng định danh

`shops`, `posts`, `products`, `sessions` có khóa chính toàn database.
Các hàm `add_shop/add_post/add_product` dùng `INSERT` thông thường.

Đã tái hiện: chạy xong fixture thứ nhất; đổi `run_id`, `scenario_id` và toàn
bộ `session_id`, giữ lại catalog cho lần chạy thứ hai. Kết quả:
`UNIQUE constraint failed: shops.shop_id`. Sau lỗi, run thứ hai vẫn ở trạng
thái `running`, chưa có lịch; chạy lại dẫn tới lỗi hoàn tất rỗng ở mục 1.

Hướng sửa: phân biệt định danh nội dung tái sử dụng với snapshot bất biến
của mỗi run, và quy định rõ phạm vi ID. Không chữa bằng `INSERT OR REPLACE`
vì có thể làm thay đổi dữ liệu mà run cũ đang tham chiếu.
Giới hạn tạm cho thử nghiệm: **mỗi run một file SQLite mới**.

### 3. Run chạy tiếp nhưng trạng thái vẫn `failed`

`run()` cập nhật session thành `running`, nhưng không chuyển run từ
`failed` về `running` trước khi tiếp tục.

Đã tái hiện: gateway ném `TimeoutError`, run chuyển `failed`; thay bằng
gateway offline hoạt động rồi resume. Trong lời gọi model đầu tiên,
`run_status()` vẫn trả `failed`; chỉ đổi thành `completed` ở cuối.

Hướng sửa: chuyển trạng thái run khi bắt đầu resume sau khi xác thực đầu
vào; phân biệt phiên lỗi/đang chạy. Đây là điều kiện cần trước khi frontend
dựa vào trạng thái backend để bắt đầu hoặc dừng hiển thị.

### 4. Fallback kết quả khác fallback lỗi kết nối

`StageService.execute()` gọi fallback khi primary trả kết quả không dùng
được. Nhưng nếu primary ném exception, service ghi lỗi rồi ném lại.
`RouterPoolGateway` thử các router đã cấu hình; hết router thì ném
`GatewayUnavailable`. Trường hợp này không tự đi tiếp sang LLM fallback.

Đã tái hiện: primary ném `TimeoutError`; fallback có 0 lời gọi; run `failed`.
Đây là chính sách fail-fast hiện tại, không phải fallback mạng đã hoàn thiện.

Cần chốt và kiểm thử: lỗi nào được retry có giới hạn, lỗi nào chuyển model,
lỗi nào dừng run. Không đổi lỗi mạng thành hành vi `skip` hoặc `not_buy`.
OpenAI adapter hiện không truyền timeout/retry tường minh và tạo client
trong mỗi `decide()`; cần đặt giới hạn rõ trước khi đánh giá tốc độ thực tế.

## Giới hạn không nên nhầm với lỗi engine

- Metric bài viết/sản phẩm chưa có projector riêng; nguồn sự kiện đã có.
- Chưa có API theo dõi, queue trình bày hay trạng thái hoàn tất từng agent
  trong phiên. Checkpoint là stage đã commit, không phải chứng nhận agent
  đã xử lý hết lịch.
- A4 hiện chỉ cho giữ/bỏ/không thay đổi khi đã có phản ứng. Chưa có đổi
  trực tiếp like ↔ dislike trong cùng một lần đọc lại. Contract hiện hành
  quy định như vậy; cần xác nhận nghiệp vụ trước khi đổi.
- Tài liệu flow mục A4 còn ghi `no_reaction` cho lượt đã có phản ứng,
  trong khi `policy.allowed_choices()` và bảng contract dùng `no_new_reaction`.
- Chưa chứng minh chịu tải lớn hoặc độ chính xác hành vi. Offline parity
  chỉ có nghĩa cùng output model thì hai mode giữ đúng nghiệp vụ.
- Resume bỏ qua stage đã commit; không bảo đảm không gọi/tính phí lại
  model nếu tiến trình dừng trước khi stage được commit.

## Kiểm thử đã chạy

14 module dưới đây đều qua bằng `python3`; các validator renderer dùng
`PYTHONPATH=.:paper_research`:

```text
simulation.self_check
simulation.metrics_self_check
simulation.parallel_self_check
simulation.model_gateway
paper_research.simulation_policy_v1
paper_research.validate_contract_schemas
paper_research.validate_context_rendering_v2
paper_research.validate_flow_tags_v2
paper_research.validate_industry_profiles
paper_research.validate_relationship_assignment
paper_research.validate_relationship_context
paper_research.validate_scenario_materialization
paper_research.audit_context_contract
paper_research.validate_matraix_persona
```

Cách chạy lại: `PYTHONPATH=.:paper_research python3 -m <tên_module>`.
Kiểm tra MatrAIx không đọc Parquet thật vì interpreter này thiếu `pyarrow`.

`simulation.openai_gateway` bị `SKIP` bằng Python hệ thống; đã chạy lại và
qua trong môi trường có dependency:

```bash
/tmp/projectdut-openai-venv/bin/python -m simulation.openai_gateway
```

Đường dẫn `/tmp` là môi trường hiện có, không phải cấu hình triển khai bền
vững. Self-check OpenAI hiện chỉ dựng/kiểm tra schema A1R; không xem đây là
kiểm thử API thật hoặc xác nhận toàn bộ stage qua SDK.

### Tái hiện tối thiểu lỗi khởi tạo (offline, database tạm)

Chạy tại gốc repository; assert mô tả **lỗi hiện tại**, không phải hành vi
mong muốn. Sau khi sửa, chuyển thành regression check yêu cầu rollback
hoặc từ chối resume dữ liệu thiếu.

```bash
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from simulation.self_check import example_scenario, ScriptedGateway
from simulation.store_sqlite import SqliteSimulationStore
from simulation.stage_service import StageService
from simulation.orchestrator import RunCoordinator

class InterruptedStore(SqliteSimulationStore):
    def add_shop(self, *args, **kwargs):
        raise RuntimeError("Injected initialization interruption")

with TemporaryDirectory(prefix="dut-init-audit-") as directory:
    path = Path(directory) / "audit.sqlite"
    scenario = example_scenario()
    store = InterruptedStore(path)
    try:
        RunCoordinator(store, StageService(store, ScriptedGateway())).run(scenario)
    except RuntimeError:
        pass
    finally:
        store.close()
    store = SqliteSimulationStore(path)
    try:
        RunCoordinator(store, StageService(store, ScriptedGateway())).run(scenario)
        count = store.connection.execute("SELECT COUNT(*) FROM stage_events").fetchone()[0]
        assert store.run_status(scenario["run_id"]) == "completed" and count == 0
        print("REPRODUCED: incomplete initialization becomes completed with 0 events")
    finally:
        store.close()
PY
```

## Thứ tự hoàn thiện đề xuất

1. Khởi tạo nguyên khối, kiểm tra dữ liệu đủ và regression test lỗi giữa chừng.
2. Cô lập/reuse dữ liệu giữa run; kiểm thử hai scenario chung database.
3. Sửa vòng đời failed → running → completed và kiểm thử khi đang resume.
4. Chốt chính sách lỗi gateway, timeout/retry/fallback; kiểm thử offline trước.
5. Sau đó mới bổ sung read API phục vụ frontend theo
   [yêu cầu hàng đợi hiển thị hiện hành](../backend/03-api-and-stream.md#3-sse-theo-dữ-liệu-đã-commit).

Lượt rà soát này chỉ cập nhật tài liệu; các lỗi nêu trên **chưa được sửa**.
