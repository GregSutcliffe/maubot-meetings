import jinja2
import os
from datetime import datetime
from ...util import get_room_alias, time_from_timestamp
from maubot.loader import BasePluginLoader
from slugify import slugify
from fedora_messaging import api as fm_api, exceptions as fm_exceptions


def sendfedoramessage(meetbot, message_topic, **kwargs):
    config = meetbot.config["backend_data"]["fedora"]
    try:
        msg = fm_api.Message(
            topic=f"{config['fedoramessaging_topic_prefix']}.{message_topic}",
            body=kwargs,
        )
        fm_api.publish(msg)
    except fm_exceptions.PublishReturned as e:
        meetbot.log.warn(f"Fedora Messaging broker rejected message {msg.id}: {e}")
    except fm_exceptions.ConnectionException as e:
        meetbot.log.warn(f"Error sending message {msg.id}: {e}")

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

def writeToFile(path, filename, string):
    f = open(os.path.join(path, filename), 'w')
    f.write(string)
    f.close()


async def endmeeting(meetbot, event, meeting):
    config = meetbot.config["backend_data"]["fedora"]
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    items = await meetbot.get_items(meeting['meeting_id'])
    people_present = await meetbot.get_people_present(meeting['meeting_id'])
    starttime = time_from_timestamp(items[0]['timestamp'], format="%Y-%m-%d-%H.%M")
    startdate = time_from_timestamp(items[0]['timestamp'], format="%Y-%m-%d")
    filename = f"{slugify(meeting['meeting_name'])}.{starttime}"
    url = f"{config['logs_baseurl']}{slugify(room_alias)}/{startdate}/{filename}"

    # TODO: Make this async
    sendfedoramessage(meetbot, "meeting.complete", url=url)

    # create the directories if they don't exist
    # will look something like /meetbot_logs/web/meetbot/fedora-meeting-1-fedora-im/2023-09-01/
    path = os.path.join(config['logs_directory'], slugify(room_alias), startdate)
    if not os.access(path, os.F_OK):
        os.makedirs(path)

    writeToFile(path, f"{filename}.log.txt", render(meetbot, "text_log.j2", items=items))
    writeToFile(path, f"{filename}.log.html",render(meetbot, "html_log.j2", items=items, room=room_alias))
    writeToFile(path, f"{filename}.txt", render(meetbot, "text_minutes.j2", items=items, room=room_alias, people_present=people_present, meeting_name=meeting['meeting_name']))
    writeToFile(path, f"{filename}.html", render(meetbot, "html_minutes.j2", items=items, room=room_alias, people_present=people_present, meeting_name=meeting['meeting_name']))

    # await meetbot.upload_file(
    #     event, f"{filename}.log.txt", render(meetbot, "text_log.j2", items=items)
    # )
    # await meetbot.upload_file(
    #     event,
    #     f"{filename}.log.html",
    #     render(meetbot, "html_log.j2", items=items, room=room_alias),
    # )

    # await meetbot.upload_file(
    #     event,
    #     f"{filename}.txt",
    #     render(meetbot, "text_minutes.j2", items=items, room=room_alias, people_present=people_present),
    # )

    # await meetbot.upload_file(
    #     event,
    #     f"{filename}.html",
    #     render(meetbot, "html_minutes.j2", items=items, room=room_alias, people_present=people_present),
    # )

    meetbot.log.info(f"Fedora: Meeting ended in {room_alias}")
