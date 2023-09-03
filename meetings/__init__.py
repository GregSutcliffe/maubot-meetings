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
    
class Config(BaseProxyConfig):
  def do_update(self, helper: ConfigUpdateHelper) -> None:
    helper.copy("backend")
    helper.copy("backend_data")
    helper.copy("powerlevel")

class Meetings(Plugin):
  async def start(self) -> None:
    self.config.load_and_update()
    self.backend = importlib.import_module(f'.backends.{self.config["backend"]}', package='meetings')

  async def check_pl(self,evt):
    pls = await self.client.state_store.get_power_levels(evt.room_id)
    permit = pls.get_user_level(evt.sender) >= self.config["powerlevel"]
    return(permit)
      
  # Helper: check if a meeting is ongoing in this room
  async def meeting_in_progress(self, room_id) -> bool:
    dbq = """
            SELECT * FROM meetings WHERE room_id = $1
          """
    row = await self.database.fetch(dbq, room_id)
    if row:
      return True
    else:
      return False
  
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
            SELECT sender, count(sender) FROM meeting_logs WHERE meeting_id = $1 GROUP BY sender
          """
    rows = await self.database.fetch(dbq, meeting_id)
    return rows
  
  async def log_tag(self, tag, evt: MessageEvent) -> None:
    meeting   = self.meeting_id(evt.room_id)
    timestamp = evt.timestamp
    dbq = """
            UPDATE meeting_logs SET tag = $3 WHERE meeting_id = $1 AND timestamp = $2
          """
    await self.database.execute(dbq, meeting, timestamp, tag)

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
  async def startmeeting(self, evt: MessageEvent) -> None:
    meeting = await self.meeting_in_progress(evt.room_id)
    
    if not await self.check_pl(evt):
      await evt.respond("You do not have permission to start a meeting")
    elif meeting:
      await evt.respond("Meeting already in progress")
    else:
      # Do backend-specific startmeeting things
      await self.backend.startmeeting(self, evt)
      
      # Add the meeting to the meetings table
      dbq = """
              INSERT INTO meetings (room_id, meeting_id) VALUES ($1, $2)
            """
      await self.database.execute(dbq, evt.room_id, self.meeting_id(evt.room_id))
      
      # Notify the room
      time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
      await evt.respond(f'Meeting started at {time} UTC')

  
  @command.new(aliases=["em"])
  async def endmeeting(self, evt: MessageEvent) -> None:
    meeting = await self.meeting_in_progress(evt.room_id)
    
    if not await self.check_pl(evt):
      await evt.respond("You do not have permission to end a meeting")
    if meeting:
      meeting_id  = self.meeting_id(evt.room_id)
      
      # Do backend-specific endmeeting things
      await self.backend.endmeeting(self, evt, meeting_id)

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

      #  Notify the room
      time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
      await evt.respond(f'Meeting ended at {time} UTC')
    else:
      await evt.respond("No meeting in progress")

  @command.passive("")
  async def log_message(self, evt: MessageEvent, match: Tuple[str]) -> None:
    meeting = await self.meeting_in_progress(evt.room_id)
    if meeting:
      if re.search("^\!", evt.content.body):
        return

      # Log the item to the db
      dbq = """
              INSERT INTO meeting_logs (meeting_id, timestamp, sender, message) VALUES ($1, $2, $3, $4)
            """
      meeting   = self.meeting_id(evt.room_id)
      timestamp = evt.timestamp
      sender    = evt.sender
      message   = evt.content.body
      await self.database.execute(dbq, meeting, timestamp, sender, message)
      
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
