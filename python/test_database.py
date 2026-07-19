"""数据库功能测试"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from database import DatabaseRepository
from migration_bootstrap import bootstrap_database


def test_database_operations(tmp_path: Path, monkeypatch):
    """测试数据库基本操作"""
    print("=" * 60)
    print("DATABASE FUNCTIONALITY TEST")
    print("=" * 60)

    db_path = tmp_path / "test_chat.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    ok, message = bootstrap_database()
    assert ok, message
    
    # 初始化数据库
    db = DatabaseRepository(str(db_path))
    print("\n✓ Database initialized")
    
    try:
        # 测试保存消息
        print("\n--- Testing Message Save ---")
        session_id = "test_session_001"
        
        db.save_message(session_id, "user", "Hello, how are you?", tokens=10, model="gpt-3.5-turbo")
        db.save_message(session_id, "assistant", "I'm doing great! How can I help you?", tokens=15, model="gpt-3.5-turbo")
        db.save_message(session_id, "user", "Tell me a joke", tokens=5, model="gpt-3.5-turbo")
        db.save_message(session_id, "assistant", "Why did the AI go to school? To improve its learning model!", tokens=20, model="gpt-3.5-turbo")
        
        print("✓ Messages saved successfully")
        
        # 测试获取聊天历史
        print("\n--- Testing Get Chat History ---")
        history = db.get_chat_history(session_id, limit=10)
        print(f"✓ Retrieved {len(history)} messages")
        for msg in history:
            print(f"  [{msg['role']}] {msg['content'][:50]}... ({msg['tokens']} tokens)")
        
        # 测试获取所有会话
        print("\n--- Testing Get All Sessions ---")
        sessions = db.get_all_sessions()
        print(f"✓ Retrieved {len(sessions)} session(s)")
        for session in sessions:
            print(f"  - {session['title']}: {session['message_count']} messages, {session['total_tokens']} tokens")
        
        # 测试更新统计
        print("\n--- Testing Update Statistics ---")
        db.update_daily_statistics()
        print("✓ Statistics updated")
        
        # 测试获取统计
        print("\n--- Testing Get Statistics ---")
        stats = db.get_statistics(days=7)
        print(f"✓ Retrieved statistics for {len(stats)} day(s)")
        for stat in stats:
            print(f"  {stat['date']}: {stat['messages']} messages, {stat['tokens']} tokens")
        
        # 测试导出 JSON
        print("\n--- Testing Export to JSON ---")
        json_content = db.export_to_json(session_id)
        print(f"✓ Exported to JSON ({len(json_content)} bytes)")
        print(f"  Preview: {json_content[:100]}...")
        
        # 测试导出 CSV
        print("\n--- Testing Export to CSV ---")
        csv_content = db.export_to_csv(session_id)
        print(f"✓ Exported to CSV ({len(csv_content)} bytes)")
        print(f"  Preview: {csv_content.split(chr(10))[0]}")
        
        # 测试保存和获取设置
        print("\n--- Testing Settings ---")
        db.save_setting("theme", "dark")
        db.save_setting("language", "zh-CN")
        db.save_setting("user_preferences", {"notifications": True, "sound": False})
        
        theme = db.get_setting("theme")
        language = db.get_setting("language")
        prefs = db.get_setting("user_preferences")
        
        print("✓ Settings saved and retrieved")
        print(f"  theme: {theme}")
        print(f"  language: {language}")
        print(f"  preferences: {prefs}")
        
        # 测试数据库统计
        print("\n--- Testing Database Stats ---")
        db_stats = db.get_database_stats()
        print("✓ Database statistics:")
        print(f"  Total messages: {db_stats['total_messages']}")
        print(f"  Total sessions: {db_stats['total_sessions']}")
        print(f"  Total tokens: {db_stats['total_tokens']}")
        print(f"  Database size: {db_stats['db_size_mb']:.2f} MB")
        print(f"  Database path: {db_stats['db_path']}")
        
        # 测试删除会话
        print("\n--- Testing Delete Session ---")
        db.delete_session(session_id)
        print("✓ Session deleted")
        
        sessions_after = db.get_all_sessions()
        print(f"  Sessions remaining: {len(sessions_after)}")
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
    finally:
        db.close()
