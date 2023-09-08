import jinja2
import os
from datetime import datetime
from ...util import get_room_alias, time_from_timestamp
from maubot.loader import BasePluginLoader
from slugify import slugify

async def startmeeting(meetbot, event):
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    meetbot.log.info(f"Fedora: Meeting started in {room_alias}")


def render(meetbot, templatename, **kwargs):
    def formatdate(timestamp):
      """timestampt to date filter"""
      return time_from_timestamp(int(timestamp))
    
    def formattime(timestamp):
      """timestampt to date filter"""
      return time_from_timestamp(int(timestamp), format="%H:%M:%S")
    
    def removecommand(line, command=""):
      return line.removeprefix(f"^{command}").strip()
    
    j2env = jinja2.Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=jinja2.select_autoescape(["html", "xml"]),
    )
    j2env.filters['formatdate'] = formatdate
    j2env.filters['formattime'] = formattime
    j2env.filters['removecommand'] = removecommand

    template = meetbot.loader.sync_read_file(f"meetings/backends/fedora/{templatename}")
    return j2env.from_string(template.decode()).render(**kwargs)


async def endmeeting(meetbot, event, meeting):
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    items = await meetbot.get_items(meeting['meeting_id'])
    people_present = await meetbot.get_people_present(meeting['meeting_id'])
    starttime = time_from_timestamp(items[0]['timestamp'], format="%Y-%m-%d-%H-%M")
    filename = f"{slugify(meeting['meeting_name'])}.{starttime}"

    await meetbot.upload_file(
        event, f"{filename}.log.txt", render(meetbot, "text_log.j2", items=items)
    )
    await meetbot.upload_file(
        event,
        f"{filename}.log.html",
        render(meetbot, "html_log.j2", items=items, room=room_alias),
    )

    await meetbot.upload_file(
        event,
        f"{filename}.txt",
        render(meetbot, "text_minutes.j2", items=items, room=room_alias, people_present=people_present),
    )

    await meetbot.upload_file(
        event,
        f"{filename}.html",
        render(meetbot, "html_minutes.j2", items=items, room=room_alias, people_present=people_present),
    )

    meetbot.log.info(f"Fedora: Meeting ended in {room_alias}")
