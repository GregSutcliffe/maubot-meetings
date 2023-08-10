from typing import Tuple
from mautrix.client import Client
from mautrix.types import (Event, StateEvent, EventID, UserID, FileInfo, MessageType, EventType,
                           MediaMessageEventContent, ReactionEvent, RedactionEvent)
from mautrix.types.event.message import media_reply_fallback_body_map
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from maubot import Plugin, MessageEvent
from maubot.handlers import command
from mautrix.util.async_db import UpgradeTable, Scheme
from datetime import datetime
import re
import json

# Setup database
from .db import upgrade_table
    
class Config(BaseProxyConfig):
  def do_update(self, helper: ConfigUpdateHelper) -> None:
    helper.copy("log_file")

class Meetings(Plugin):
  #async def start(self) -> None:
  #  self.config.load_and_update()

  @classmethod
  def get_db_upgrade_table(cls) -> UpgradeTable:
    return upgrade_table
      
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

  # Helper: upload a JSON file
  async def upload_file(self, evt, items, filename):
      #data = json.dumps(items).encode("utf-8")
      data = json.dumps([tuple(row) for row in items]).encode("utf-8")
      url = await self.client.upload_media(data, mime_type="application/json")
      await evt.respond(MediaMessageEventContent(
        msgtype=MessageType.FILE,
        body=filename,
        url=url,
          info=FileInfo(
            mimetype="application/json",
            size=len(data),
          )
        ))

  # Helper: contruct a meeting ID
  def meeting_id(self, room_id):
    return f"{room_id}-{datetime.today().strftime('%Y-%m-%d')}"
    
  @command.new(aliases="s")
  async def startmeeting(self, evt: MessageEvent) -> None:
    meeting = await self.meeting_in_progress(evt.room_id)
    if meeting:
      await evt.respond("Meeting already in progress")
    else:
      # Add the meeting to the meetings table
      dbq = """
              INSERT INTO meetings (room_id, meeting_id) VALUES ($1, $2)
            """
      await self.database.execute(dbq, evt.room_id, self.meeting_id(evt.room_id))
      
      # Notify the room
      time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
      await evt.respond(f'Meeting started at {time} UTC')

  
  @command.new(aliases="e")
  async def endmeeting(self, evt: MessageEvent) -> None:
    meeting = await self.meeting_in_progress(evt.room_id)
    if meeting:
      meeting_id  = self.meeting_id(evt.room_id)
      full_log    = await self.get_items(meeting_id)
      info_list   = await self.get_items(meeting_id, "info")
      action_list = await self.get_items(meeting_id, "action")

      await self.upload_file(evt, info_list, "info_items.json")
      await self.upload_file(evt, action_list, "action_items.json")
      await self.upload_file(evt, full_log, "full_log.json")
      
      # Clear the logs
      dbq = """
              DELETE FROM meeting_logs WHERE meeting_id = $1
            """
      await self.database.execute(dbq, self.meeting_id(evt.room_id))
      
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

  async def log_tag(self, tag, evt: MessageEvent) -> None:
    meeting   = self.meeting_id(evt.room_id)
    timestamp = evt.timestamp
    dbq = """
            UPDATE meeting_logs SET tag = $3 WHERE meeting_id = $1 AND timestamp = $2
          """
    await self.database.execute(dbq, meeting, timestamp, tag)

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
      if re.search("\!action", evt.content.body):
        await self.log_tag("action", evt)
        await evt.react("🚩")

      # Mark an info item
      if re.search("\!info", evt.content.body):
        await self.log_tag("info", evt)
        await evt.react("✏️️")

