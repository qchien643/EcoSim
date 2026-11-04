# Trạng thái quan hệ thương hiệu và gán ban đầu v1

## Mục đích

Phase 4 tách quan hệ của một agent với đúng brand khỏi persona cố định. Persona
trả lời “agent thường có đặc điểm gì”; relationship state trả lời “trước run
agent đang biết, quen, có thái độ và từng mua brand này như thế nào”.

Contract chuẩn nằm tại
[`relationship-state.v1.json`](../../data/contracts/relationship-state.v1.json).

## Bốn chiều trạng thái

```json
{
  "awareness": "unknown",
  "familiarity": "none",
  "attitude": "not_formed",
  "purchase_history": "none"
}
```

- `awareness`: `unknown` hoặc `aware`.
- `familiarity`: `none`, `low`, `established`.
- `attitude`: `not_formed`, `positive`, `neutral`, `negative`.
- `purchase_history`: `none` hoặc `has_purchased`.

Một số tổ hợp bị chặn để tránh trạng thái phi logic: agent `unknown` không thể
đã quen hoặc từng mua; `established` phải đi cùng `aware`; từng mua phải đi
cùng `aware` và `established`. Từng mua không tự hình thành attitude. Trạng
thái này là quan hệ với brand, không phải lịch sử mua một product cụ thể.

## Input của marketer

```json
{
  "relationship_initialization": {
    "seed": 20260928,
    "groups": [
      {
        "group_id": "unknown",
        "state": {
          "awareness": "unknown",
          "familiarity": "none",
          "attitude": "not_formed",
          "purchase_history": "none"
        },
        "percentage": 40
      },
      {
        "group_id": "known_positive",
        "state": {
          "awareness": "aware",
          "familiarity": "established",
          "attitude": "positive",
          "purchase_history": "none"
        },
        "percentage": 60
      }
    ]
  }
}
```

Các nhóm là một partition của danh sách agent đã chọn. V1 yêu cầu dùng toàn
bộ `count` hoặc toàn bộ `percentage`; phần trăm được chuyển thành số nguyên
bằng largest-remainder. Hệ thống không sửa persona và không dùng LLM ở bước
gán.

`ScenarioLoader` dùng SHA-256 của `policy_version + seed + agent_id` để xếp
hạng ổn định, chia lần lượt theo thứ tự nhóm, rồi sinh
`relationship_assignments`. Cùng agent, nhóm và seed sẽ cho cùng kết quả ở
mọi lần load; thay seed là một cấu hình khác.

## Lưu trữ và cập nhật sau event

Snapshot canonical nằm trong scenario/run snapshot. SQLite lưu bảng
`run_agent_relationships` theo khóa
`run + agent + organization + brand`, gồm initial state, group và provenance.
Projection hiện tại nằm riêng trong `run_agent_relationship_states`, để giữ
initial state bất biến và có thể rebuild current state từ event.

Transition v1 chỉ nhận bằng chứng deterministic:

- đọc xong bài với enterprise identity visible: `unknown → aware`,
  `none → low`;
- ghé shop: awareness được xác nhận, familiarity tăng;
- mua sản phẩm: cập nhật `purchase_history`, không tự gán attitude;
- attention, emotion, like, dislike và `not_buy` không tự đổi attitude.

`relationship-context-policy.v1.json` quy định các trường relationship và
brand-history được phép đưa vào từng stage. ContextService chỉ đọc projection
hiện tại; nó không tự cập nhật relationship.

Nếu scenario không khai báo cơ cấu, loader dùng một nhóm mặc định
`default_unknown` cho toàn bộ agent để không ngầm gán thái độ hoặc lịch sử mua.
