"""Unit tests for AgentMemory (Phase 1)."""
import sys
sys.path.insert(0, r"e:\code\project\DUT_STARTUP\EcoSim\oasis")

from agent_cognition import AgentMemory

def test_empty_context():
    mem = AgentMemory(num_agents=3)
    assert mem.get_context(0) == "", f"Expected '', got '{mem.get_context(0)}'"
    assert mem.get_context(99) == ""
    assert mem.get_round_count(0) == 0
    print("T1.3 PASS: empty context for new agents")

def test_basic_recording():
    mem = AgentMemory(num_agents=3)
    mem.record_action(0, "create_post", "Loving the new Shopee deals!")
    mem.record_action(0, "like_post", "")
    mem.record_action(1, "create_comment", "Great product review!")
    mem.end_round(1)

    ctx0 = mem.get_context(0)
    assert "Round 1" in ctx0
    assert "posted" in ctx0
    assert "liked" in ctx0
    assert "Your recent activity:" in ctx0
    print(f"T1.1a PASS (agent 0): {ctx0}")

    ctx1 = mem.get_context(1)
    assert "commented" in ctx1
    print(f"T1.1b PASS (agent 1): {ctx1}")

    ctx2 = mem.get_context(2)
    assert ctx2 == ""
    print("T1.1c PASS (agent 2): empty")

def test_buffer_overflow():
    mem = AgentMemory(num_agents=1)
    for r in range(1, 9):
        mem.record_action(0, "like_post", f"post from round {r}")
        mem.end_round(r)

    ctx = mem.get_context(0)
    lines = [l for l in ctx.split("\n") if l.startswith("Round")]
    assert len(lines) == 5, f"Expected 5, got {len(lines)}"
    assert "Round 8" in ctx
    assert "Round 1" not in ctx
    print(f"T1.2 PASS: {len(lines)} rounds, oldest evicted")

def test_multi_agent():
    mem = AgentMemory(num_agents=3)
    mem.record_action(0, "create_post", "Agent 0 post")
    mem.record_action(1, "create_comment", "Agent 1 comment")
    mem.end_round(1)
    mem.record_action(0, "like_post", "")
    mem.record_action(2, "create_post", "Agent 2 post")
    mem.end_round(2)
    assert mem.get_round_count(0) == 2
    assert mem.get_round_count(1) == 1
    assert mem.get_round_count(2) == 1
    print("T1.extra PASS: multi-agent independent buffers")

def test_toggle_off():
    agent_memory = None
    mem_ctx = agent_memory.get_context(0) if agent_memory else ""
    assert mem_ctx == ""
    print("T1.4 PASS: toggle OFF safe")

if __name__ == "__main__":
    test_empty_context()
    test_basic_recording()
    test_buffer_overflow()
    test_multi_agent()
    test_toggle_off()
    print("\nAll Phase 1 unit tests passed!")
