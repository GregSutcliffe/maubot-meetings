import jinja2
import os
from datetime import datetime
from ...util import get_room_alias, time_from_timestamp
from maubot.loader import BasePluginLoader

async def startmeeting(meetbot, event):
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    meetbot.log.info(f"Fedora: Meeting started in {room_alias}")


def render(meetbot, templatename, **kwargs):
    def formatdate(timestamp):
      """timestampt to date filter"""
      return time_from_timestamp(int(timestamp))
    
    j2env = jinja2.Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=jinja2.select_autoescape(["html", "xml"]),
    )
    j2env.filters['formatdate'] = formatdate
    template = meetbot.loader.sync_read_file(f"meetings/backends/fedora/{templatename}")
    return j2env.from_string(template.decode()).render(**kwargs)


async def endmeeting(meetbot, event, meeting_id):
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    items = await meetbot.get_items(meeting_id)

    await meetbot.upload_file(
        event, "text_log.txt", render(meetbot, "text_log.j2", items=items)
    )
    await meetbot.upload_file(
        event,
        "html_log.html",
        render(meetbot, "html_log.j2", items=items, room=room_alias),
    )

    meetbot.log.info(f"Fedora: Meeting ended in {room_alias}")
