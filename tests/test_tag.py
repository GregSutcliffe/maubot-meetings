import pytest


@pytest.mark.parametrize(
    "plugin_config_overrides",
    [
        {"tags_command_prefix": "^", "tags_command_at_start": True},
        {"tags_command_prefix": "!", "tags_command_at_start": True},
    ],
)
async def test_tag_command_prefix(bot, plugin, db):
    # test the cases where tags_command_at_start: True and the command is picked up
    await bot.send("!startmeeting")
    await bot.send(f"{plugin.config['tags_command_prefix']}action pants")
    meeting_logs = await db.fetch("SELECT * FROM meeting_logs")
    assert meeting_logs[0]["tag"] is None
    assert meeting_logs[1]["tag"] == "action"
    assert len(meeting_logs) == 2


@pytest.mark.parametrize(
    "plugin_config_overrides",
    [
        {"tags_command_prefix": "^", "tags_command_at_start": True},
        {"tags_command_prefix": "!", "tags_command_at_start": True},
    ],
)
async def test_tag_command_prefix_start_not(bot, plugin, db):
    # test if tags_command_at_start is True and the command is in the middle
    await bot.send("!startmeeting")
    await bot.send(f"some stuff at the start {plugin.config['tags_command_prefix']}action pants")
    meeting_logs = await db.fetch("SELECT * FROM meeting_logs")
    assert meeting_logs[0]["tag"] is None
    assert meeting_logs[1]["tag"] is None
    assert len(meeting_logs) == 2


@pytest.mark.parametrize(
    "plugin_config_overrides",
    [
        {"tags_command_prefix": "^", "tags_command_at_start": False},
        {"tags_command_prefix": "!", "tags_command_at_start": False},
    ],
)
async def test_tag_command_prefix_start_false(bot, plugin, db):
    # test if tags_command_at_start is False and the command is picked up whereever
    await bot.send("!startmeeting")
    await bot.send(f"some stuff at the start {plugin.config['tags_command_prefix']}action pants")
    await bot.send(f"{plugin.config['tags_command_prefix']}action pants")
    await bot.send(f"{plugin.config['tags_command_prefix']}action pants !action asd")

    meeting_logs = await db.fetch("SELECT * FROM meeting_logs")
    assert meeting_logs[0]["tag"] is None
    assert meeting_logs[1]["tag"] == "action"
    assert meeting_logs[1]["tag"] == "action"
    assert meeting_logs[1]["tag"] == "action"

    assert len(meeting_logs) == 4
