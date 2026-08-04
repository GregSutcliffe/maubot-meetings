async def test_line_num_assignment(bot, plugin, db):
    # Test that line_num is assigned correctly for single-line and multi-line messages
    await bot.send("!startmeeting")
    await bot.send("foo\nbar\nbaz")  # A 3-line message

    meeting_logs = await db.fetch("SELECT * FROM meeting_logs ORDER BY timestamp, line_num")
    assert meeting_logs[0]["message"] == "!startmeeting"
    assert meeting_logs[1]["message"] == "foo"
    assert meeting_logs[2]["message"] == "bar"
    assert meeting_logs[3]["message"] == "baz"

    assert meeting_logs[0]["line_num"] == 0
    assert meeting_logs[1]["line_num"] == 0
    assert meeting_logs[2]["line_num"] == 1
    assert meeting_logs[3]["line_num"] == 2


async def test_get_items_order(bot, plugin, db):
    # Test that get_items returns in the correct order for multi-line messages
    room_id = "room123"
    await bot.send("!startmeeting", room_id)
    await bot.send("foo\nbar\nbaz", room_id)  # A 3-line message

    meeting_logs = await plugin.get_items(plugin.meeting_id(room_id))
    assert meeting_logs[0]["message"] == "!startmeeting"
    assert meeting_logs[1]["message"] == "foo"
    assert meeting_logs[2]["message"] == "bar"
    assert meeting_logs[3]["message"] == "baz"
