import os

import jinja2
from fedora_messaging import api as fm_api
from fedora_messaging import exceptions as fm_exceptions
from meetbot_messages import MeetingCompleteV1, MeetingStartV1
from slugify import slugify

from ...util import get_room_alias, time_from_timestamp


def sendfedoramessage(meetbot, message):
    try:
        fm_api.publish(message)
    except fm_exceptions.PublishReturned as e:
        meetbot.log.warn(f"Fedora Messaging broker rejected message {message.id}: {e}")
    except fm_exceptions.ConnectionException as e:
        meetbot.log.warn(f"Error sending message {message.id}: {e}")


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

    template = meetbot.loader.sync_read_file(f"meetings/backends/fedora/{templatename}")
    return j2env.from_string(template.decode()).render(**kwargs)


def writeToFile(path, filename, string):
    f = open(os.path.join(path, filename), "w")
    f.write(string)
    f.close()


async def startmeeting(meetbot, event, meeting):
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    message = MeetingStartV1(
        body={
            "start_time": time_from_timestamp(
                event.timestamp, format="%Y-%m-%dT%H:%M:%S+1000"
            ),
            "start_user": event.sender,
            "location": room_alias,
            "meeting_name": meeting["meeting_name"],
        }
    )
    sendfedoramessage(meetbot, message)
    meetbot.log.info(f"Fedora: Meeting started in {room_alias}")


async def endmeeting(meetbot, event, meeting):
    config = meetbot.config["backend_data"]["fedora"]
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    items = await meetbot.get_items(meeting["meeting_id"])
    people_present = await meetbot.get_people_present(meeting["meeting_id"])
    starttime = time_from_timestamp(items[0]["timestamp"], format="%Y-%m-%d-%H.%M")
    startdate = time_from_timestamp(items[0]["timestamp"], format="%Y-%m-%d")
    filename = f"{slugify(meeting['meeting_name'])}.{starttime}"
    # makes a slugified room alias e.g. `#fedora-meeting:fedora.im` becomes `fedora-meeting_matrix-fedora-im`
    slugified_room_alias = slugify(
        room_alias, replacements=[[":", "_matrix-"]], regex_pattern=r"[^-a-z0-9_]+"
    )
    url = f"{config['logs_baseurl']}{slugified_room_alias}/{startdate}/"

    # create the directories if they don't exist will look something like
    # /meetbot_logs/web/meetbot/fedora-meeting-1_matrix-fedora-im/2023-09-01/
    path = os.path.join(config["logs_directory"], slugified_room_alias, startdate)
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
        autoescape = True if file.endswith((".html", ".htm", ".xml")) else False
        rendered = render(meetbot, template, autoescape=autoescape, **template_vars)
        writeToFile(path, file, rendered)
        await event.respond(f"{label}: {url}{file}")
    
    attendees = []
    for person in people_present:
        attendees.append({"name": person['sender'], "lines_said": int(person['count'])})

    message = MeetingCompleteV1(
        body={
            "start_time": time_from_timestamp(
                items[0]["timestamp"], format="%Y-%m-%dT%H:%M:%S+1000"
            ),
            "start_user": items[0]["sender"],
            "end_time": time_from_timestamp(
                event.timestamp, format="%Y-%m-%dT%H:%M:%S+1000"
            ),
            "end_user": event.sender,
            "location": room_alias,
            "meeting_name": meeting["meeting_name"],
            "url": url,
            "attendees": attendees,
            "chairs": [items[0]["sender"]],
            "logs": [{"log_type": l, "log_url": f"{url}{f}"} for t, f, l in templates]
        }
    )
    # TODO: Make this async
    sendfedoramessage(meetbot, message)

    meetbot.log.info(f"Fedora: Meeting ended in {room_alias}")
