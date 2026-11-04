# Sử dụng JEV 1.13 qua OpenRouter

## Mục đích

JEV là model ra quyết định có cấu trúc. Nó nhận một `state` và trả lời các
câu hỏi có kiểu dữ liệu cố định; nó không sinh văn bản tự do. Workflow,
ngưỡng, việc lưu dữ liệu và hành động tiếp theo vẫn do code của project
quản lý.

Project dùng đúng model:

```text
typesafe/jev-1.13
```

JEV được gọi qua Decisions API, không phải Chat Completions API:

```text
POST https://openrouter.ai/api/alpha/decisions
```

## Request cơ bản bằng Python

```python
import json
import os
import requests


OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

response = requests.post(
    "https://openrouter.ai/api/alpha/decisions",
    headers={
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # Optional: used by OpenRouter rankings.
        "HTTP-Referer": "https://example.com",
        "X-OpenRouter-Title": "projectDut2026",
    },
    json={
        "model": "typesafe/jev-1.13",
        "state": {
            "agent": {
                "trait_curiosity": "High",
                "pref_novelty_vs_familiarity": "Open to novelty",
            },
            "content": {
                "type": "article",
                "tags": [
                    "topic_product_launch",
                    "style_informational",
                ],
                "preview": "A new cold brew product is now available.",
            },
            "history": {
                "glance_count": 2,
                "read_count": 0,
                "last_action": None,
            },
        },
        "questions": {
            "will_read": {
                "type": "noul",
                "instructions": (
                    "Will the agent read this article carefully in the "
                    "current session?"
                ),
                "criteria": {
                    "true": "The agent is likely to read the article carefully.",
                    "false": (
                        "The agent may glance at or ignore the article and "
                        "is unlikely to read it carefully."
                    ),
                },
            },
            "attention_state": {
                "type": "choice",
                "instructions": (
                    "Which attention state best describes the agent's "
                    "current interaction with this article?"
                ),
                "criteria": {
                    "ignore": "The agent does not meaningfully notice the article.",
                    "glance": "The agent notices the article but does not read it carefully.",
                    "read": "The agent reads the article carefully.",
                },
            },
            "attention_strength": {
                "type": "score",
                "instructions": (
                    "How strong is the agent's attention to this article?"
                ),
                "criteria": [
                    "Very weak attention; the article is likely ignored.",
                    "Weak attention; the agent may only glance at it.",
                    "Moderate attention; the agent may read it.",
                    "Strong attention; the agent is likely to read it carefully.",
                ],
            },
        },
    },
    timeout=30,
)

response.raise_for_status()
payload = response.json()
answers = payload["answers"]

print(answers["will_read"]["noul"])
print(answers["attention_state"]["choice"])
print(answers["attention_state"]["probabilities"])
print(answers["attention_strength"]["score"])
```

Một request có thể chứa cả ba loại câu hỏi. JEV đánh giá từng câu hỏi trên
cùng một `state`, còn code quyết định dùng kết quả như thế nào.

## Ba kiểu câu hỏi

### 1. `noul`: mệnh đề đúng đến mức nào?

`noul` trả về một xác suất từ `0` đến `1` cho một mệnh đề đúng/sai.

```python
questions = {
    "will_read": {
        "type": "noul",
        "instructions": "Will the agent read the article carefully?",
        "criteria": {
            "true": "The agent will read the article carefully.",
            "false": "The agent will only glance at or ignore the article.",
        },
    }
}
```

Đọc kết quả:

```python
probability = answers["will_read"]["noul"]

if probability >= 0.70:
    next_step = "read"
else:
    next_step = "glance_or_ignore"
```

Ứng dụng trong project:

- `will_read`: agent có đọc kỹ bài không;
- `will_view_product`: agent có xem kỹ món hàng không;
- một thought tag có đúng với trạng thái hiện tại không;
- một emotion tag có xuất hiện không.

Nhiều `noul` có thể cùng đúng, nên phù hợp với thought/emotion tags dạng
multi-label. Threshold như `0.70` là policy của code, không phải quy tắc
JEV tự áp đặt.

### 2. `choice`: chọn một phương án

`choice` dùng khi các kết quả là những trạng thái lựa chọn trong cùng một
nhóm. Các phương án phải được mô tả rõ trong `criteria`.

```python
questions = {
    "purchase_action": {
        "type": "choice",
        "instructions": "What purchase action will the agent take now?",
        "criteria": {
            "buy": "The agent purchases the product now.",
            "not_buy": "The agent does not purchase the product now.",
        },
    }
}
```

Kết quả có dạng khái quát:

```json
{
  "purchase_action": {
    "type": "choice",
    "choice": "not_buy",
    "probabilities": {
      "buy": 0.31,
      "not_buy": 0.69
    },
    "confidence": 0.69
  }
}
```

Ứng dụng trong project:

- `skip`, `attention`;
- `buy`, `not_buy`;
- `no_reaction`, `like`, `dislike`;
- ở lần phản ứng sau: `keep_current`, `remove_reaction`, `no_reaction`.

Nếu nghiệp vụ yêu cầu chỉ một phương án, dùng `choice` thay vì nhiều `noul`
độc lập. Ví dụ một câu hỏi `will_like` và một câu `will_dislike` có thể cùng
trả về đúng, trong khi `choice` bảo đảm chỉ có một reaction được chọn.

Nên thêm `no_reaction` khi agent có thể không phản ứng.

### 3. `score`: đánh giá trên thang có thứ tự

`score` dùng để đánh giá cường độ. Các mức trong `criteria` phải có thứ tự từ
thấp đến cao.

```python
questions = {
    "attention_strength": {
        "type": "score",
        "instructions": "How strong is the agent's attention to this product?",
        "criteria": [
            "Very weak; likely ignored.",
            "Weak; may be glanced at.",
            "Moderate; may be viewed carefully.",
            "Strong; likely to receive careful attention.",
        ],
    }
}
```

Kết quả có dạng:

```json
{
  "attention_strength": {
    "type": "score",
    "score": 2.35,
    "legend": {
      "0": "Very weak; likely ignored.",
      "1": "Weak; may be glanced at.",
      "2": "Moderate; may be viewed carefully.",
      "3": "Strong; likely to receive careful attention."
    },
    "probabilities": {
      "0": 0.05,
      "1": 0.20,
      "2": 0.35,
      "3": 0.40
    },
    "confidence": 0.55
  }
}
```

`score` là điểm kỳ vọng trên thang đã định nghĩa, không phải một nhãn mới
do JEV tự tạo. Dùng `score` để lưu cường độ hoặc phân tích; dùng `choice`
khi workflow cần chuyển ngay sang một trạng thái rời rạc.

## Áp dụng vào attention algorithm

JEV không thay thế toàn bộ thuật toán chú ý. Luồng đề xuất là:

```text
Lịch đăng và trạng thái phiên
    ↓
Lọc deterministic theo điều kiện hợp lệ
    ↓
Lọc tag phù hợp với persona
    ↓
Vector search lấy ứng viên
    ↓
JEV đánh giá trạng thái/cường độ chú ý
    ↓
Code áp dụng threshold và giới hạn số lượt xem
    ↓
glance hoặc read
    ↓
Nếu read: gọi chuỗi xử lý bài viết
```

Ví dụ:

```python
attention = answers["attention_state"]["choice"]

if attention == "ignore":
    save_exposure(kind="not_noticed")
elif attention == "glance":
    save_exposure(kind="glanced")
elif attention == "read":
    save_exposure(kind="read")
    run_article_flow()
```

`glance` không gọi chuỗi đọc bài. Nó chỉ lưu dấu tiếp xúc để những lần sau
có thể ảnh hưởng đến mức độ quen thuộc của agent với bài viết.

Với sản phẩm, workflow tương tự nhưng chỉ chạy sau khi agent đã vào shop:

```text
Agent vào shop
    ↓
Lọc sản phẩm hợp lệ
    ↓
Vector search và lịch sử agent–sản phẩm
    ↓
JEV đánh giá ignore/glance/view
    ↓
Nếu view: chạy product_thought → product_emotion → buy/not_buy
```

## Áp dụng vào thought, emotion và action

### Thought/emotion tags

Các tag đóng có thể dùng nhiều câu hỏi `noul` trong một request:

```python
questions = {
    "thought_is_curious": {
        "type": "noul",
        "instructions": (
            "Is the agent curious about the new product after seeing "
            "its tags?"
        ),
    },
    "thought_wants_more_information": {
        "type": "noul",
        "instructions": (
            "Does the agent want more information before forming an opinion?"
        ),
    },
    "emotion_interested": {
        "type": "noul",
        "instructions": "Does the agent feel interested after reading the article?",
    },
}
```

Code chọn tag theo threshold đã được kiểm thử:

```python
thought_tags = [
    tag_id
    for tag_id, answer in answers.items()
    if "noul" in answer and answer["noul"] >= THOUGHT_TAG_THRESHOLD
]
```

### Action

Action loại trừ nhau nên dùng `choice`:

```python
questions = {
    "reaction": {
        "type": "choice",
        "instructions": "What reaction will the agent make to the article?",
        "criteria": {
            "no_reaction": "The agent does not create a reaction to the article.",
            "like": "The agent likes the article.",
            "dislike": "The agent dislikes the article.",
        },
    },
    "purchase_action": {
        "type": "choice",
        "instructions": "Will the agent buy the product now?",
        "criteria": {
            "buy": "The agent buys the product now.",
            "not_buy": "The agent does not buy the product now.",
        },
    },
}
```

Comment chưa thuộc phạm vi bản đầu. Khi bổ sung, cần một contract riêng; không
đưa comment vào các lựa chọn phản ứng hiện tại.

## Nguyên tắc viết câu hỏi

- Viết ý nghĩa nghiệp vụ trong `instructions` và `criteria`; không dựa vào
  tên key. Question ID chỉ là khóa để đọc kết quả.
- Mỗi `choice` phải có các phương án loại trừ nhau.
- Thứ tự `score` phải thực sự tăng từ thấp đến cao.
- `noul` nên là một mệnh đề có thể trả lời yes/no.
- Không đưa toàn bộ persona và toàn bộ event history vào mọi request.
- Code phải làm các phép đếm, tính decay, so sánh phiên, lọc dữ liệu và lưu
  lịch sử.
- Không dùng kết quả JEV để tự động ghi đè một contract nghiệp vụ hợp lệ.
- Ghi lại model snapshot, state đầu vào, questions, answers, threshold và
  phiên mô phỏng để có thể tái lập kết quả.

## Không dùng JEV cho

- sinh bài viết, suy nghĩ văn bản hoặc comment;
- tạo embedding hoặc thực hiện vector search;
- đếm số lần agent đã xem;
- tính điểm history, decay hoặc penalty;
- so sánh ngày/phiên;
- thực thi `buy` hoặc thay đổi dữ liệu mà chưa qua code kiểm tra.

JEV trả ra đánh giá có cấu trúc; code của project mới là nơi điều phối workflow
và áp dụng policy.

## Smoke test cần có khi triển khai

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
python3 path/to/jev_smoke_test.py
```

Smoke test chỉ nên kiểm tra:

- HTTP status thành công;
- có `answers`;
- `noul` nằm trong `0..1`;
- `choice` thuộc danh sách option đã khai báo;
- `score` có `probabilities` và legend tương ứng.

Không commit API key hoặc state chứa dữ liệu cá nhân vào repository.

## Tài liệu tham khảo

- [JEV 1.13 trên OpenRouter](https://openrouter.ai/typesafe/jev-1.13)
- [What Is Jev?](https://openrouter.ai/blog/insights/what-is-jev/)
- [How to Use Jev](https://openrouter.ai/blog/tutorials/how-to-use-jev/)
- [TypeSafe System One](https://docs.typesafe.ai/concepts/system-one)
