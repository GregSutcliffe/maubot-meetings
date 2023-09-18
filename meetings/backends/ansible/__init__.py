import jinja2
import requests
import tempfile
import json

from datetime import datetime
from ...util import get_room_alias, get_room_name, time_from_timestamp
from maubot.loader import BasePluginLoader

# helpers
def config(meetbot):
  config = meetbot.config["backend_data"]["ansible"]
  return(config)
  
def parse_db_time(t):
  return(datetime.utcfromtimestamp(int(t)/1000).strftime('%Y-%m-%d %H:%M:%S'))

def parse_db_logs(items):
  logs = tuple()
  for row in items:
    time = parse_db_time(row[1])
    log = f"{time} | {row[2]} | {row[3]}"
    logs += (log,)
    
  log_data = "\n".join(logs).encode("utf-8")
  return(log_data)

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

    template = meetbot.loader.sync_read_file(f"meetings/backends/ansible/{templatename}")
    return j2env.from_string(template.decode()).render(**kwargs)

# async helpers
async def upload_log_to_discourse(config, log_data, logger):
  # DRY this
  api_user = config["discourse_user"]
  api_key  = config["discourse_key"]
  url = config["discourse_url"] + "/uploads.json"

  headers = { "Api-Key": api_key,
              "Api-Username": api_user }

  fp = tempfile.TemporaryFile()
  fp.write(str.encode(log_data))
  fp.seek(0)

  res = requests.post(url, headers=headers, data={'type':'text'},
                      files = {'files[]': ('full_log.txt', fp, 'text/plain')})
  
  fp.close()
  
  if res.status_code == 200:
    r = json.loads(res.content)
    txt = f"[full_log.txt|attachment]({r['short_url']})"
    return(txt)
  else:
    logger.info(res.status_code)
    logger.info(res.content)
    return("")

async def post_to_discourse(config, raw_post, title, logger):
  api_user = config["discourse_user"]
  api_key  = config["discourse_key"]
  url = config["discourse_url"] + "/posts"

  headers = { 'Api-Key': api_key,
              'Api-Username': api_user }
  payload = { 'title': title,
              'raw': raw_post,
              'category': config["category_id"]}

  res = requests.post(url, headers=headers, data=payload)
  r = json.loads(res.content)
  logger.info(f'Discourse POST: {res.status_code}')
  if res.status_code == 200:
    r = json.loads(res.content)
    return(r["topic_id"])
  else:
    return("")

# required backend methods
async def startmeeting(meetbot, event, meeting):
  room_alias = await get_room_alias(meetbot.client, event.room_id)
  room_name  = await get_room_name(meetbot.client, event.room_id)
  
  meetbot.log.info(f'Ansible: Meeting started in {room_name} ({room_alias} / {event.room_id})')
  meetbot.log.info(f'Will post to Discourse as {config(meetbot)["discourse_user"]}')

async def endmeeting(meetbot, event, meeting):
  room_alias     = await get_room_alias(meetbot.client, event.room_id)
  room_name      = await get_room_name(meetbot.client, event.room_id)
  items          = await meetbot.get_items(meeting['meeting_id'])
  people_present = await meetbot.get_people_present(meeting['meeting_id'])
  
  meetbot.log.info(f'Ansible: Meeting ended in {room_name} ({room_alias} / {event.room_id})')

  if len(items) == 0:
    meetbot.log.info("No entries")
    await event.respond('No logs to post to Discourse')
    return()

  # Upload full_log to Discourse
  log_path = await upload_log_to_discourse(
    config(meetbot),
    render(meetbot, "text_log.j2", items=items),
    meetbot.log
  )
  meetbot.log.info(f'Discourse Log URL: {log_path}')
  
  minutes = render(meetbot, "html_minutes.j2", items=items, name=meeting['meeting_name'], room=room_name, alias=room_alias, people_present=people_present, logs=log_path),
  meetbot.log.info(f'Discourse Log URL: {minutes}')
  title = f"Meeting Log | {room_name} | { time_from_timestamp(int(items[0]['timestamp'])) }"

  pid = await post_to_discourse(config(meetbot), minutes, title, meetbot.log)
  if pid != "":
    url = config(meetbot)["discourse_url"] + "/t/" + str(pid)
    await event.respond(f'Logs [posted to Discourse]({url})')
