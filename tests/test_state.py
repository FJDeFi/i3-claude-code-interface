"""Tests for SQLite state module."""

from __future__ import annotations


def test_chat_lifecycle(state_module):
    state_module.insert_chat("abc", "sess-abc", "/tmp/abc.log")
    chat = state_module.get_chat("abc")
    assert chat is not None
    assert chat.tmux_session == "sess-abc"
    assert chat.status == "running"
    # Public Chat model must never expose the stored API key.
    assert not hasattr(chat, "anthropic_api_key")

    state_module.update_chat_status("abc", "stopped")
    assert state_module.get_chat("abc").status == "stopped"


def test_api_key_round_trip_and_clear(state_module):
    state_module.insert_chat("xyz", "sess-xyz", "/tmp/xyz.log", anthropic_api_key="sk-ant-test")
    assert state_module.get_chat_api_key("xyz") == "sk-ant-test"
    state_module.clear_chat_api_key("xyz")
    assert state_module.get_chat_api_key("xyz") is None
    # Public chat record is unaffected.
    chat = state_module.get_chat("xyz")
    assert chat.tmux_session == "sess-xyz"


def test_append_and_list_events(state_module):
    state_module.insert_chat("abc", "sess-abc", "/tmp/abc.log")
    e1 = state_module.append_chat_event("abc", "user", "hello")
    e2 = state_module.append_chat_event("abc", "assistant", "hi there")
    e3 = state_module.append_chat_event("abc", "assistant", "anything else?")

    all_events = state_module.list_events_after("abc", after_id=0)
    assert [ev.id for ev in all_events] == [e1.id, e2.id, e3.id]
    assert [ev.role for ev in all_events] == ["user", "assistant", "assistant"]

    tail = state_module.list_events_after("abc", after_id=e1.id)
    assert [ev.id for ev in tail] == [e2.id, e3.id]


def test_events_are_scoped_by_chat(state_module):
    state_module.insert_chat("a", "sa", "/tmp/a.log")
    state_module.insert_chat("b", "sb", "/tmp/b.log")
    state_module.append_chat_event("a", "user", "to-a")
    state_module.append_chat_event("b", "user", "to-b")

    a_events = state_module.list_events_after("a")
    b_events = state_module.list_events_after("b")
    assert len(a_events) == 1 and a_events[0].content == "to-a"
    assert len(b_events) == 1 and b_events[0].content == "to-b"


def test_list_chats_orders_by_created_desc(state_module):
    state_module.insert_chat("a", "sa", "/tmp/a.log")
    state_module.insert_chat("b", "sb", "/tmp/b.log")
    chats = state_module.list_chats()
    assert {c.id for c in chats} == {"a", "b"}
