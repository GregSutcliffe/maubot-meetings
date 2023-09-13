from typing import Tuple, Type
from datetime import datetime

from mautrix.client import Client
from mautrix.client.state_store import StateStore
from mautrix.types import (Event, StateEvent, EventID, UserID, FileInfo, MessageType, EventType,
                           MediaMessageEventContent, ReactionEvent, RedactionEvent)
from mautrix.types.event.message import media_reply_fallback_body_map
from mautrix.util.async_db import UpgradeTable, Scheme
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

from maubot import Plugin, MessageEvent
from maubot.handlers import command

import re
import json
import importlib

# Setup database
from .db import upgrade_table
from .util import time_from_timestamp, get_room_name
    
class Config(BaseProxyConfig):
  def do_update(self, helper: ConfigUpdateHelper) -> None:
    helper.copy("backend")
    helper.copy("backend_data")
    helper.copy("powerlevel")
    helper.copy("log_commands")

class Meetings(Plugin):
  async def start(self) -> None:
    self.config.load_and_update()
    self.backend = importlib.import_module(f'.backends.{self.config["backend"]}', package='meetings')

  async def check_pl(self,evt):
    pls = await self.client.get_state_event(evt.room_id, EventType.ROOM_POWER_LEVELS)
    permit = pls.get_user_level(evt.sender) >= self.config["powerlevel"]
    return(permit)
      
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
              SELECT * FROM meeting_logs WHERE meeting_id = $1 AND tag LIKE $2
            """
      rows = await self.database.fetch(dbq, meeting_id, regex)
    else:
      dbq = """
              SELECT * FROM meeting_logs WHERE meeting_id = $1
            """
      rows = await self.database.fetch(dbq, meeting_id)
    return rows

  # Helper: Get message counts from the db
  async def get_people_present(self, meeting_id):
    dbq = """
            SELECT sender, count(sender) as count FROM meeting_logs WHERE meeting_id = $1 GROUP BY sender ORDER BY count
          """
    rows = await self.database.fetch(dbq, meeting_id)
    return rows
  
  async def log_tag(self, tag, evt: MessageEvent) -> None:
    meeting   = self.meeting_id(evt.room_id)
    timestamp = evt.timestamp
    dbq = """
            UPDATE meeting_logs SET tag = $3 WHERE meeting_id = $1 AND timestamp = $2
          """
    await self.database.execute(dbq, meeting, str(timestamp), tag)
  
  async def change_topic(self, topic, evt: MessageEvent) -> None:
    dbq = """
            UPDATE meetings SET topic = $3 WHERE meeting_id = $1 AND room_id = $2
          """
    await self.database.execute(dbq, self.meeting_id(evt.room_id), evt.room_id, topic)

    # change the topic of the ^topic message to the topic
    timestamp = evt.timestamp
    dbq = """
            UPDATE meeting_logs SET topic = $3 WHERE meeting_id = $1 AND timestamp = $2
          """
    await self.database.execute(dbq, self.meeting_id(evt.room_id), str(timestamp), topic)
  
  async def change_meetingname(self, meetingname, evt: MessageEvent) -> None:
    dbq = """
            UPDATE meetings SET meeting_name = $3 WHERE meeting_id = $1 AND room_id = $2
          """
    await self.database.execute(dbq, self.meeting_id(evt.room_id), evt.room_id, meetingname)

  async def log_to_db(self, meeting, timestamp, sender, message, topic):
      # Log the item to the db
      dbq = """
              INSERT INTO meeting_logs (meeting_id, timestamp, sender, message, topic) VALUES ($1, $2, $3, $4, $5)
            """
      await self.database.execute(dbq, meeting, str(timestamp), sender, message, topic)

  async def send_respond(self, event, message, meeting=None):
      # could not figure out how to get maubot to work passively on itself, so manually log messages
      # here instead
      if meeting and self.config["log_commands"]:
         await self.log_to_db(self.meeting_id(event.room_id), event.timestamp, self.client.mxid, message, meeting['topic'])
      await event.respond(message)

  # Helper: upload a file
  async def upload_file(self, evt, filename, file_contents):
    data = file_contents.encode("utf-8")
    url = await self.client.upload_media(data, mime_type="text/plain")
    await evt.respond(MediaMessageEventContent(
      msgtype=MessageType.FILE,
      body=filename,
      url=url,
        info=FileInfo(
          mimetype="text/plain",
          size=len(data),
        )
      ))

  # Helper: contruct a meeting ID
  def meeting_id(self, room_id):
    return f"{room_id}-{datetime.today().strftime('%Y-%m-%d')}"
    
  @command.new(aliases=["sm"])
  @command.argument("meetingname", pass_raw=True)
  async def startmeeting(self, evt: MessageEvent, meetingname) -> None:
    meeting = await self.meeting_in_progress(evt.room_id)
    if not await self.check_pl(evt):
      await self.send_respond(evt, "You do not have permission to start a meeting.", meeting=meeting)
    elif meeting:
      await self.send_respond(evt, "Meeting already in progress", meeting=meeting)
    else:
      # Do backend-specific startmeeting things
      await self.backend.startmeeting(self, evt)
      
      initial_topic = ""

      if not meetingname:
        roomname = await get_room_name(self.client, evt.room_id)
        meetingname = f'{roomname}'

      # Add the meeting to the meetings table
      dbq = """
              INSERT INTO meetings (room_id, meeting_id, topic, meeting_name) VALUES ($1, $2, $3, $4)
            """
      await self.database.execute(dbq, evt.room_id, self.meeting_id(evt.room_id), initial_topic, meetingname)
      meeting = await self.meeting_in_progress(evt.room_id)

      # if we are logging the commands, log the !startmeeting command
      if self.config["log_commands"]:
        await self.log_to_db(self.meeting_id(evt.room_id), evt.timestamp, evt.sender, evt.content.body, initial_topic)

      # Notify the room
      await self.send_respond(evt, f'Meeting started at {time_from_timestamp(evt.timestamp)} UTC', meeting=meeting)
      await self.send_respond(evt, f'The Meeting name is \'{meetingname}\'', meeting=meeting)

  @command.new(aliases=["em"])
  async def endmeeting(self, evt: MessageEvent) -> None:
    meeting = await self.meeting_in_progress(evt.room_id)

    if not await self.check_pl(evt):
      await self.send_respond(evt, "You do not have permission to end a meeting.", meeting=meeting)
    if meeting:
      meeting_id = self.meeting_id(evt.room_id)
      
      #  Notify the room
      await self.send_respond(evt, f'Meeting ended at {time_from_timestamp(evt.timestamp)} UTC', meeting=meeting)

      # Do backend-specific endmeeting things
      await self.backend.endmeeting(self, evt, meeting)

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
      await self.send_respond(evt, "No meeting in progress", meeting=meeting)

  @command.new("meetingname", aliases=["mn"], help="Rename the meeting")
  @command.argument("name", pass_raw=True, required=True)
  async def rename_meeting(self, evt: MessageEvent, name: str = "") -> None:
    meeting = await self.meeting_in_progress(evt.room_id)

    if meeting:
      if not await self.check_pl(evt):
        await self.send_respond(evt, "You do not have permission to rename a meeting.", meeting=meeting)
      else:
        if name:
          await self.change_meetingname(name, evt)
          await evt.react("✅")

  @command.new("topic", aliases=["t"], help="Set the next topic")
  @command.argument("name", pass_raw=True, required=True)
  async def handle_topic(self, evt: MessageEvent, name: str = "") -> None:
    meeting = await self.meeting_in_progress(evt.room_id)

    if meeting:
      if not await self.check_pl(evt):
        await self.send_respond(evt, "You do not have permission to set the topic.", meeting=meeting)
      else:
        if name:
          await self.change_topic(name, evt)
          await evt.react("✅")

  @command.passive("")
  async def log_message(self, evt: MessageEvent, match: Tuple[str]) -> None:
    meeting = await self.meeting_in_progress(evt.room_id)
    if meeting:
      if re.search("^\!", evt.content.body) and not self.config["log_commands"]:
        return

      await self.log_to_db(self.meeting_id(evt.room_id), evt.timestamp, evt.sender, evt.content.body, meeting["topic"])
      
      # Mark an action item
      if re.search("\^action", evt.content.body):
        await self.log_tag("action", evt)
        await evt.react("🚩")

      # Mark an info item
      if re.search("\^info", evt.content.body):
        await self.log_tag("info", evt)
        await evt.react("✏️️")
      

  @classmethod
  def get_config_class(cls) -> Type[BaseProxyConfig]:
    return Config

  @classmethod
  def get_db_upgrade_table(cls) -> UpgradeTable:
    return upgrade_table
