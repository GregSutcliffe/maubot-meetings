import os

import jinja2
from fedora_messaging import api as fm_api
from fedora_messaging import exceptions as fm_exceptions
from slugify import slugify

from ...util import get_room_alias, time_from_timestamp


def sendfedoramessage(meetbot, message_topic, **kwargs):
    config = meetbot.config["backend_data"]["fedora"]
    try:
        msg = fm_api.Message(
            topic=f"{config['fedoramessaging_topic_prefix']}.{message_topic}",
            body=kwargs,
        )
        fm_api.publish(msg)
    except fm_exceptions.PublishReturned as e:
        meetbot.log.warn(
            f"Fedora Messaging broker rejected message {msg.id}: {e}"
        )
    except fm_exceptions.ConnectionException as e:
        meetbot.log.warn(f"Error sending message {msg.id}: {e}")


def render(meetbot, templatename, autoescape=True, **kwargs):
    def formatdate(timestamp):
        """timestamp to date filter"""
        return time_from_timestamp(int(timestamp))

    def formattime(timestamp):
        """timestamp to time filter"""
        return time_from_timestamp(int(timestamp), format="%H:%M:%S")

    def removecommand(line, command=""):
        return line.removeprefix(f"^{command}").strip()

    j2env = jinja2.Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=autoescape,
    )
    j2env.filters["formatdate"] = formatdate
    j2env.filters["formattime"] = formattime
    j2env.filters["removecommand"] = removecommand

    template = meetbot.loader.sync_read_file(
        f"meetings/backends/fedora/{templatename}"
    )
    return j2env.from_string(template.decode()).render(**kwargs)


def writeToFile(path, filename, string):
    f = open(os.path.join(path, filename), "w")
    f.write(string)
    f.close()


async def startmeeting(meetbot, event):
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    meetbot.log.info(f"Fedora: Meeting started in {room_alias}")


async def endmeeting(meetbot, event, meeting):
    config = meetbot.config["backend_data"]["fedora"]
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    items = await meetbot.get_items(meeting["meeting_id"])
    people_present = await meetbot.get_people_present(meeting["meeting_id"])
    starttime = time_from_timestamp(
        items[0]["timestamp"], format="%Y-%m-%d-%H.%M"
    )
    startdate = time_from_timestamp(items[0]["timestamp"], format="%Y-%m-%d")
    filename = f"{slugify(meeting['meeting_name'])}.{starttime}"
    url = f"{config['logs_baseurl']}{slugify(room_alias)}/{startdate}/"

    # TODO: Make this async
    sendfedoramessage(meetbot, "meeting.complete", url=url + filename)

    # create the directories if they don't exist will look something like
    # /meetbot_logs/web/meetbot/fedora-meeting-1-fedora-im/2023-09-01/
    path = os.path.join(
        config["logs_directory"], slugify(room_alias), startdate
    )
    if not os.access(path, os.F_OK):
        os.makedirs(path)

    template_vars = {
        "items": items,
        "room": room_alias,
        "people_present": people_present,
        "meeting_name": meeting["meeting_name"],
    }

    templates = [
        ("text_log.j2", f"{filename}.log.txt", "Text Log"),
        ("html_log.j2", f"{filename}.log.html", "HTML Log"),
        ("text_minutes.j2", f"{filename}.txt", "Text Minutes"),
        ("html_minutes.j2", f"{filename}.html", "HTML Minutes"),
    ]

    for template, file, label in templates:
        autoescape = (
            True if file.endswith((".html", ".htm", ".xml")) else False
        )
        rendered = render(
            meetbot, template, autoescape=autoescape, **template_vars
        )
        writeToFile(path, file, rendered)
        await event.respond(f"{label}: {url}{file}")

    meetbot.log.info(f"Fedora: Meeting ended in {room_alias}")
