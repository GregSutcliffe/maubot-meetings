import asyncio
import logging
from pathlib import Path

import aiohttp
import pytest_asyncio
from maubot.loader import PluginMeta
from maubot.standalone.loader import FileSystemLoader
from mautrix.util.async_db import Database
from mautrix.util.config import RecursiveDict
from mautrix.util.logging import TraceLogger
from ruamel.yaml import YAML

from meetings import Config, Meetings

from .bot import TestBot


@pytest_asyncio.fixture
async def bot():
    return TestBot()


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = tmp_path.joinpath("tests.db").as_posix()
    db = Database.create(
        f"sqlite:///{db_path}",
        upgrade_table=Meetings.get_db_upgrade_table(),
        log=logging.getLogger("db"),
    )
    await db.start()
    yield db
    await db.stop()


@pytest_asyncio.fixture
async def plugin_config_overrides():
    return {}


@pytest_asyncio.fixture
async def plugin(bot, db, plugin_config_overrides):
    base_path = Path(__file__).parent.parent
    yaml = YAML()
    with open(base_path.joinpath("maubot.yaml")) as fh:
        plugin_meta = PluginMeta.deserialize(yaml.load(fh.read()))
    with open(base_path.joinpath("base-config.yaml")) as fh:
        base_config = RecursiveDict(yaml.load(fh))
    test_config = {
        "powerlevel": 50,
        "backend": None,
        "backend_data": {},
        "tags_command_at_start": True,
        "tags_command_prefix": "^",
        "tags": {
            "action": "🚩",
            "info": "✏️",
            "agreed": "👍",
            "rejected": "👎",
            "idea": "💭",
            "halp": "🛟",
            "link": "🔗",
        },
    }
    test_config.update(plugin_config_overrides)
    config = Config(lambda: test_config, lambda: base_config, lambda c: None)
    loader = FileSystemLoader(base_path, plugin_meta)
    async with aiohttp.ClientSession() as http:
        instance = Meetings(
            client=bot.client,
            loop=asyncio.get_running_loop(),
            http=http,
            instance_id="tests",
            log=TraceLogger("test"),
            config=config,
            database=db,
            webapp=None,
            webapp_url=None,
            loader=loader,
        )
        await instance.internal_start()
        yield instance
