import os
import re

import httpx
import jinja2
from fedora_messaging import api as fm_api
from fedora_messaging import exceptions as fm_exceptions
from httpx_gssapi import HTTPSPNEGOAuth
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
        return line.removeprefix(f"{meetbot.config['tags_command_prefix']}{command}").strip()

    def getcommand(line):
        commands = ["startmeeting", "endmeeting", "topic", "meetingname"]
        for c in commands:
            if line.startswith(f"!{c}"):
                return c
        return ""

    j2env = jinja2.Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=autoescape,  # noqa: S701
    )
    j2env.filters["formatdate"] = formatdate
    j2env.filters["formattime"] = formattime
    j2env.filters["removecommand"] = removecommand
    j2env.filters["getcommand"] = getcommand

    template = meetbot.loader.sync_read_file(f"meetings/backends/fedora/{templatename}")
    return j2env.from_string(template.decode()).render(**kwargs)


def writeToFile(path, filename, string):
    f = open(os.path.join(path, filename), "w")
    f.write(string)
    f.close()


async def _get_fasname_from_mxid(meetbot, event, mxid):
    matrix_username, matrix_server = re.findall(r"@(.*):(.*)", mxid)[0]
    if matrix_server == "fedora.im":
        # if server is fedora.im, thats the fas username, so we all good
        return matrix_username
    else:
        # we have to look up to see if the user has set a matrix account in FAS
        searchterm = f"matrix://{matrix_server}/{matrix_username}"
        baseurl = meetbot.config["backend_data"]["fedora"]["fasjson_url"]
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    baseurl + "/v1/search/users/",
                    auth=HTTPSPNEGOAuth(),
                    params={"ircnick__exact": searchterm},
                )
            except httpx.HTTPError as e:
                meetbot.log.error(f"Error Getting information from FASJSON: {e}")
                return mxid
        searchresult = response.json().get("result")

        if len(searchresult) > 1:
            user = searchresult[0]["username"]
            await event.respond(
                f"Warning: MXID {mxid} is associated with multiple Fedora "
                f"Accounts ({[u['username'] for u in searchresult]}). Defaulting "
                f"to using {user} in Fedora Messaging messages"
            )
            return user
        elif len(searchresult) == 0:
            return mxid
        else:
            return searchresult[0]["username"]


async def startmeeting(meetbot, event, meeting):
    room_alias = await get_room_alias(meetbot.client, event.room_id)
    start_user = await _get_fasname_from_mxid(meetbot, event, event.sender)
    if meetbot.config["backend_data"]["fedora"].get("send_fedoramessages", True):
        message = MeetingStartV1(
            body={
                "start_time": time_from_timestamp(event.timestamp, format="%Y-%m-%dT%H:%M:%S+1000"),
                "start_user": start_user,
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
    # makes a slugified room alias e.g. `#fedora-meeting:fedora.im`
    # becomes `fedora-meeting_matrix-fedora-im`
    slugified_room_alias = slugify(
        room_alias, replacements=[[":", "_matrix_"]], regex_pattern=r"[^-a-z0-9_]+"
    )
    url = f"{config['logs_baseurl']}{slugified_room_alias}/{startdate}/"

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

    # TODO: chairs aren't implemented in the main part of meetings yet, so just use the
    # user that started the meetings for now
    chairs = [items[0]["sender"]]

    # create the directories if they don't exist will look something like
    # /meetbot_logs/web/meetbot/fedora-meeting-1_matrix-fedora-im/2023-09-01/
    path = os.path.join(config["logs_directory"], slugified_room_alias, startdate)
    if not os.access(path, os.F_OK):
        try:
            os.makedirs(path)
        except OSError as e:
            meetbot.log.error(f"Creating Directories failed with error: {e}")

    # we build this up as a cache of {"@mxid:server.test": "fasname"} pairs, or if we can't find
    # a fas username, just use the mxid. I'm doing this seperately to reduce dupilcate calls to
    # FASJSON
    fasnames = {}

    attendees = []
    for person in people_present:
        mxid = person["sender"]
        fasnames[mxid] = await _get_fasname_from_mxid(meetbot, event, mxid)
        attendees.append({"name": fasnames[mxid], "lines_said": int(person["count"])})

    for mxid in chairs:
        if mxid not in fasnames.keys():
            fasnames[mxid] = await _get_fasname_from_mxid(meetbot, event, mxid)

    if meetbot.config["backend_data"]["fedora"].get("send_fedoramessages", True):
        message = MeetingCompleteV1(
            body={
                "start_time": time_from_timestamp(
                    items[0]["timestamp"], format="%Y-%m-%dT%H:%M:%S+1000"
                ),
                "start_user": fasnames[items[0]["sender"]],
                "end_time": time_from_timestamp(event.timestamp, format="%Y-%m-%dT%H:%M:%S+1000"),
                "end_user": fasnames.get(event.sender, event.sender),
                "location": room_alias,
                "meeting_name": meeting["meeting_name"],
                "url": url,
                "attendees": attendees,
                "chairs": [fasnames[c] for c in chairs],
                "logs": [{"log_type": lt, "log_url": f"{url}{f}"} for t, f, lt in templates],
            }
        )
        # TODO: Make this async
        try:
            sendfedoramessage(meetbot, message)
        except Exception as e:
            meetbot.log.error(e)

    for template, file, label in templates:
        autoescape = True if file.endswith((".html", ".htm", ".xml")) else False
        rendered = render(meetbot, template, autoescape=autoescape, **template_vars)
        try:
            writeToFile(path, file, rendered)
        except OSError as e:
            await event.respond(f"Issue Saving {file}. Uploading here instead")
            meetbot.log.error(f"Saving File failed with error: {e}")
            await meetbot.upload_file(event, file, rendered)
        else:
            await event.respond(f"{label}: {url}{file}")

    meetbot.log.info(f"Fedora: Meeting ended in {room_alias}")
