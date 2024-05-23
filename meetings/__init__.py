import importlib
import re
from datetime import datetime

from maubot import MessageEvent, Plugin
from maubot.handlers import event
from mautrix.errors.request import MatrixUnknownRequestError
from mautrix.types import EventType, FileInfo, MediaMessageEventContent, MessageType
from mautrix.util import markdown
from mautrix.util.async_db import UpgradeTable
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

# Setup database
from .db import upgrade_table
from .util import get_room_name, time_from_timestamp

COMMAND_RE = re.compile(r"^!(\S+)(?:\s+|$)(.*)")
TOPIC_COMMAND_RE = re.compile(r"^!(topic)(?:\s+|$)(.*)")


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("powerlevel")
        helper.copy("backend")
        helper.copy("backend_data")
        helper.copy("tags_command_at_start")
        helper.copy("tags_command_prefix")
        helper.copy("tags")


class Meetings(Plugin):
    async def start(self) -> None:
        self.config.load_and_update()
        if self.config.get("backend", None):
            self.backend = importlib.import_module(
                f'.backends.{self.config["backend"]}', package="meetings"
            )
        else:
            self.backend = None
        self.tags = self.config["tags"]
        self.prefix = self.config.get("tags_command_prefix", "^")
        start = "(^)" if self.config.get("tags_command_at_start", True) else "(^.*)"
        self.tags_regex = re.compile(f"{start}\\{self.prefix}({'|'.join(self.tags.keys())})($| .*)")

    async def check_pl(self, evt):
        pls = await self.client.get_state_event(evt.room_id, EventType.ROOM_POWER_LEVELS)
        permit = pls.get_user_level(evt.sender) >= self.config["powerlevel"]
        return permit

    # Helper: check if a meeting is ongoing in this room
    async def meeting_in_progress(self, room_id):
        dbq = """
            SELECT * FROM meetings WHERE room_id = $1
          """
        row = await self.database.fetchrow(dbq, room_id)
        return row

    # Helper: Get logs from the db
    async def get_items(self, meeting_id, regex=False):
        if regex:
            dbq = """
              SELECT * FROM meeting_logs WHERE meeting_id = $1 AND tag LIKE $2 ORDER BY timestamp
            """
            rows = await self.database.fetch(dbq, meeting_id, regex)
        else:
            dbq = """
              SELECT * FROM meeting_logs WHERE meeting_id = $1 ORDER BY timestamp
            """
            rows = await self.database.fetch(dbq, meeting_id)
        return rows

    # Helper: Get message counts from the db
    async def get_people_present(self, meeting_id):
        dbq = (
            "SELECT sender, count(sender) as count "
            "FROM meeting_logs "
            "WHERE meeting_id = $1 "
            "GROUP BY sender "
            "ORDER BY count"
        )
        rows = await self.database.fetch(dbq, meeting_id)
        return rows

    async def react(self, evt, emoji):
        try:
            await evt.react(emoji)
        except MatrixUnknownRequestError as e:
            if e.errcode == "M_DUPLICATE_ANNOTATION":
                pass
            else:
                raise e

    async def log_tag(self, tag, line, evt: MessageEvent) -> None:
        meeting = self.meeting_id(evt.room_id)
        timestamp = evt.timestamp
        dbq = (
            "UPDATE meeting_logs SET tag = $3 WHERE meeting_id = $1 AND "
            "timestamp = $2 AND message = $4"
        )
        await self.database.execute(dbq, meeting, str(timestamp), tag, line)

    async def change_topic(self, topic, evt: MessageEvent) -> None:
        dbq = """
            UPDATE meetings SET topic = $3 WHERE meeting_id = $1 AND room_id = $2
          """
        await self.database.execute(dbq, self.meeting_id(evt.room_id), evt.room_id, topic)

        # also update the log for the '!topic' command to be the topic it commanded to be
        dbq = """
            UPDATE meeting_logs SET topic = $3 WHERE meeting_id = $1 AND timestamp = $2
          """
        timestamp = evt.timestamp
        await self.database.execute(dbq, self.meeting_id(evt.room_id), str(timestamp), topic)

    async def change_meetingname(self, meetingname, evt: MessageEvent) -> None:
        dbq = """
            UPDATE meetings SET meeting_name = $3 WHERE meeting_id = $1 AND room_id = $2
          """
        await self.database.execute(dbq, self.meeting_id(evt.room_id), evt.room_id, meetingname)

    async def log_to_db(self, meeting, timestamp, sender, message, topic):
        # Log the item to the db
        dbq = (
            "INSERT INTO meeting_logs (meeting_id, timestamp, sender, message, topic) "
            "VALUES ($1, $2, $3, $4, $5)"
        )
        await self.database.execute(dbq, meeting, str(timestamp), sender, message, topic)

    # Helper: upload a file
    async def upload_file(self, evt, filename, file_contents):
        data = file_contents.encode("utf-8")
        url = await self.client.upload_media(data, mime_type="text/plain")
        await evt.respond(
            MediaMessageEventContent(
                msgtype=MessageType.FILE,
                body=filename,
                url=url,
                info=FileInfo(
                    mimetype="text/plain",
                    size=len(data),
                ),
            )
        )

    # Helper: contruct a meeting ID
    def meeting_id(self, room_id):
        return f"{room_id}-{datetime.today().strftime('%Y-%m-%d')}"

    async def startmeeting(self, evt: MessageEvent, meetingname) -> None:
        meeting = await self.meeting_in_progress(evt.room_id)
        if not await self.check_pl(evt):
            await evt.respond(
                f"Starting a meeting requires a powerlevel of at least {self.config['powerlevel']}"
            )
        elif meeting:
            await evt.respond("Meeting already in progress")
        else:
            initial_topic = ""

            if not meetingname:
                roomname = await get_room_name(self.client, evt.room_id)
                meetingname = f"{roomname}"

            # Add the meeting to the meetings table
            dbq = (
                "INSERT INTO meetings (room_id, meeting_id, topic, meeting_name) "
                "VALUES ($1, $2, $3, $4)"
            )

            await self.database.execute(
                dbq, evt.room_id, self.meeting_id(evt.room_id), initial_topic, meetingname
            )
            meeting = await self.meeting_in_progress(evt.room_id)

            # the !startmeeting command gets sent before the meeting has been
            # started, so manually log that message
            await self.log_to_db(
                self.meeting_id(evt.room_id),
                evt.timestamp,
                evt.sender,
                evt.content.body,
                initial_topic,
            )

            # Do backend-specific startmeeting things
            if self.backend:
                await self.backend.startmeeting(self, evt, meeting)

            # Notify the room
            await evt.respond(f"Meeting started at {time_from_timestamp(evt.timestamp)} UTC")
            await evt.respond(f"The Meeting name is '{meetingname}'")

            # provide some helpful hints
            prefix = self.prefix.strip("\\")
            tags_string = "\n".join(
                [f"* `{prefix}{tag}`: {emoji}\n" for tag, emoji in self.tags.items()]
            )
            hints = (
                f"reminds you of the things that can do in the meeting:\n"
                f"* `!meetingname <a new name>`: to rename the meeting\n"
                f"* `!topic <a topic name>`: to change the topic of the meeting\n"
                f"* `!endmeeting`: to, well, end the meeting\n"
                f"\n"
                f"There are also several handy tags that you can use to tag a "
                f"message to highlight it in the minutes (and add an emoji reaction here):\n"
                f"{tags_string}"
            )

            await self.client.send_text(
                evt.room_id, None, html=markdown.render(hints), msgtype=MessageType.EMOTE
            )

    async def endmeeting(self, evt: MessageEvent) -> None:
        meeting = await self.meeting_in_progress(evt.room_id)

        if meeting:
            if not await self.check_pl(evt):
                await evt.respond(
                    f"Ending a meeting requires a powerlevel "
                    f"of at least {self.config['powerlevel']}"
                )
            else:
                meeting_id = self.meeting_id(evt.room_id)

                # Do backend-specific endmeeting things
                if self.config["backend"]:
                    await self.backend.endmeeting(self, evt, meeting)

                #  Notify the room
                await evt.respond(f"Meeting ended at {time_from_timestamp(evt.timestamp)} UTC")

                # Clear the logs
                dbq = """
                DELETE FROM meeting_logs WHERE meeting_id = $1
              """
                await self.database.execute(dbq, meeting_id)

                # Remove the meeting from the meetings table
                dbq = """
                DELETE FROM meetings WHERE room_id = $1
              """
                await self.database.execute(dbq, evt.room_id)

        else:
            await evt.respond("No meeting in progress")

    async def rename_meeting(self, evt: MessageEvent, name: str = "") -> None:
        meeting = await self.meeting_in_progress(evt.room_id)

        if meeting:
            if not await self.check_pl(evt):
                await evt.respond(
                    f"Renaming a meeting requires a powerlevel "
                    f"of at least {self.config['powerlevel']}"
                )
            else:
                if name:
                    await self.change_meetingname(name, evt)
                    await evt.respond(f"The Meeting Name is now {name}")

    async def handle_topic(self, evt: MessageEvent, name, line) -> None:
        meeting = await self.meeting_in_progress(evt.room_id)

        if meeting:
            if not await self.check_pl(evt):
                await evt.respond(
                    f"Changing the topic requires a powerlevel "
                    f"of at least {self.config['powerlevel']}"
                )
            else:
                if name:
                    await self.log_tag("topic", line, evt)
                    await self.change_topic(name, evt)
                    await evt.respond(f"The Meeting Topic is now {name}")

    @event.on(EventType.ROOM_MESSAGE)
    async def log_message(self, evt):
        if evt.content.msgtype not in [MessageType.TEXT, MessageType.NOTICE]:
            return

        meeting = await self.meeting_in_progress(evt.room_id)

        for line in evt.content.body.splitlines():
            if meeting:
                await self.log_to_db(
                    self.meeting_id(evt.room_id),
                    evt.timestamp,
                    evt.sender,
                    line,
                    meeting["topic"],
                )

                tagsmatch = re.findall(self.tags_regex, line)
                if tagsmatch and len(tagsmatch) == 1:
                    await self.log_tag(tagsmatch[0][1], line, evt)
                    await self.react(evt, self.tags[tagsmatch[0][1]])

            commandsmatch = COMMAND_RE.search(line)
            if commandsmatch:
                command, argument = commandsmatch.groups()
                if command in ["topic", "t"]:
                    await self.handle_topic(evt, argument, line)
                elif command in ["meetingname", "mn"]:
                    await self.rename_meeting(evt, argument)
                elif command in ["startmeeting", "sm"]:
                    await self.startmeeting(evt, argument)
                elif command in ["endmeeting", "em"]:
                    await self.endmeeting(evt)

    @classmethod
    def get_config_class(cls) -> type[BaseProxyConfig]:
        return Config

    @classmethod
    def get_db_upgrade_table(cls) -> UpgradeTable:
        return upgrade_table
