# Scenario Loader và Validator v1

## Mục đích

Đây là cổng deterministic giữa dữ liệu marketer nhập và bộ mô phỏng. Nó không
gọi JEV/LLM, không tính attention và không quyết định hành động của agent.

```text
Dữ liệu marketer
      ↓
ScenarioValidator
      ↓
ScenarioLoader
      ↓
Scenario snapshot bất biến
      ↓
RunCoordinator
```

Contract cấu trúc nằm tại
[scenario-input.v1.json](../../data/contracts/scenario-input.v1.json).

## Dữ liệu scenario

Scenario chứa:

- định danh campaign, organization và brand;
- `industry_id` và `industry_profile_version`;
- danh sách session;
- agent đã được resolve persona;
- shop và catalog sản phẩm;
- ngân hàng bài viết;
- lịch đăng bài theo session;
- policy version và cơ cấu khách hàng nếu có.
- `relationship_initialization` tùy chọn để chia agent thành các nhóm quan hệ
  ban đầu với brand bằng `count` hoặc `percentage`.
- `persona_cohort` tùy chọn để tham chiếu cohort MatrAIx đã chuẩn bị thay vì
  nhúng thủ công danh sách agent.

`customer_structure` mô tả partition agent đã được chọn cho scenario. Nó không
thay thế `relationship_initialization`: relationship initialization chỉ gán
trạng thái quan hệ với brand cho các agent đó, không chọn lại persona và không
thay đổi số agent.

## Materialize cohort trước validation

Khi có `persona_cohort`, `ScenarioLoader` thực hiện trước các bước validation:

1. đọc `cohort.jsonl` và `manifest.json`;
2. kiểm tra industry/profile version, số dòng và định danh persona;
3. tạo `agent_id` ổn định từ `cohort_persona_id`;
4. materialize `customer_structure.agent_ids` bằng seed;
5. lưu hash cohort/manifest vào `persona_cohort_snapshot`;
6. sau đó mới chạy schema validator và materialize relationship assignments.

Run snapshot vì vậy chứa persona, cơ cấu agent, relationship assignment, bài
viết, sản phẩm và lịch đăng đầy đủ. Nếu file cohort thay đổi hoặc snapshot
hash không khớp, loader từ chối tiếp tục; không chọn lại agent âm thầm.

Một shop có thể có nhiều sản phẩm. Mỗi sản phẩm có `product_id`, `shop_id`,
`position`, tên, giá, mô tả và danh sách tag. `position` là thứ tự sản phẩm
trong catalog của shop; các position chỉ cần duy nhất trong cùng một shop.

Một bài viết có thể xuất hiện trong nhiều session. Mỗi lần xuất hiện là một
lịch đăng riêng, nhưng vẫn giữ nguyên `post_id` để lịch sử agent nhận ra cùng
một bài viết.

## Validation rules

Validator kiểm tra:

1. Định danh bắt buộc và kiểu dữ liệu.
2. Session liên tục từ `1..N`, không trùng `session_id`,
   `session_no` hoặc `position` trong cùng session.
3. Bài đăng phải tham chiếu bài viết tồn tại; đăng lại ở session khác là hợp
   lệ.
4. Sản phẩm phải thuộc shop tồn tại; position không trùng trong một shop.
5. Bài viết, shop và sản phẩm phải cùng `organization_id` và `brand_id` với
   scenario.
6. Persona field và enum value phải thuộc industry profile đã chọn và reduced
   persona schema tương ứng.
7. Tag phải thuộc đúng family, có `source_ref` đúng object và có
   `visible_stages` hợp lệ.
8. Full article content không được lộ trước A3; product description không được
   lộ ở B1.
9. Cơ cấu khách hàng phải dùng thống nhất `count` hoặc `percentage`, đồng thời
   lưu `agent_ids` đã được phân bổ để snapshot có thể kiểm tra lại. Count phải
   bằng số agent; percentage phải bằng 100. Với percentage, số agent từng nhóm
   dùng largest-remainder và hòa điểm theo thứ tự nhóm.
10. Relationship group phải có đủ bốn chiều quan hệ và tuân thủ các tổ hợp
    hợp lệ. Loader materialize mỗi agent đúng một `relationship_assignment`
    bằng seed cố định; assignment cung cấp sẵn nhưng khác kết quả deterministic
    sẽ bị từ chối.

Session rỗng là hợp lệ. Không có bài viết tạo warning nhưng không chặn run.
Lỗi tham chiếu, dữ liệu thiếu, tag sai hoặc cơ cấu sai sẽ chặn run.

## Loader và snapshot

`ScenarioLoader.load()` nhận object Python hoặc đường dẫn JSON, sau đó:

1. materialize các reference;
2. chạy validator;
3. dừng nếu có lỗi;
4. sắp xếp session, agent, shop, bài viết và sản phẩm bằng khóa ổn định;
5. thêm `scenario_schema_version`, relationship assignments và danh sách warning;
6. trả về bản sao độc lập để `RunCoordinator` lưu vào `runs.config_snapshot_json`.

`RunCoordinator` không nhận scenario chưa qua loader. Khi run bắt đầu, snapshot
được lưu và lịch/catalog của run không lấy lại từ bản nháp đang chỉnh sửa.
Profile và hash schema/tag/mapping được lưu trong `industry_profile_snapshot`.
Loader từ chối snapshot khác bộ tài nguyên hiện hành; không đổi ngành hoặc
mapping ngầm khi resume. Scenario cũ thiếu hai trường ngành cần chuẩn bị lại
cho run mới; chưa có migration run cũ. Xem
[phạm vi và giới hạn profile](industry-profile-v1.md).

Nếu không nhập `relationship_initialization`, loader tạo nhóm mặc định
`default_unknown` cho toàn bộ agent. Đây là trạng thái an toàn: không suy ra
agent đã biết, thích hoặc từng mua brand.

## Kiểm tra

```bash
python3 -m simulation.self_check
python3 -m paper_research.validate_relationship_assignment
python3 -m py_compile simulation/*.py
```

Fixture hiện tại kiểm tra một bài được đăng lại ở hai session và catalog có
nhiều sản phẩm sẽ đi qua cùng flow `B1 → B2 → B3` cho từng sản phẩm.
