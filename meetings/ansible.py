import requests
import tempfile
import json

from datetime import datetime

from .util import get_room_alias


# helpers
def config(meetbot):
  config = meetbot.config["backend_data"]["ansible"]
  meetbot.log.debug("Config: " + config["discourse_url"] + "/u/" + config["discourse_user"])
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

async def post_to_discourse(config, raw_post, time, logger):
  api_user = config["discourse_user"]
  api_key  = config["discourse_key"]
  url = config["discourse_url"] + "/posts"

  headers = { 'Api-Key': api_key,
              'Api-Username': api_user }
  payload = { 'title': f'Test post from MeetingBot - {time}',
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
async def startmeeting(meetbot, event):
  room_alias = await get_room_alias(meetbot.client, event.room_id)
  
  meetbot.log.info(config(meetbot)["discourse_user"])
  meetbot.log.info(f'Ansible: Meeting started in {room_alias} {event.room_id}')

async def endmeeting(meetbot, event, meeting_id):
  room_alias = await get_room_alias(meetbot.client, event.room_id)
  
  meetbot.log.info(f'Ansible: Meeting ended in {room_alias} {event.room_id}')

  full_log = await meetbot.get_items(meeting_id)
  if len(full_log) == 0:
    meetbot.log.info("No entries")
    return()

  # Upload full_log to Discourse
  log_path = await upload_log_to_discourse(
    config(meetbot),
    parse_db_logs(full_log).decode('UTF-8'),
    meetbot.log
  )
  meetbot.log.info(f'Discourse Log URL: {log_path}')
  
  # Get summaries
  info_list   = await meetbot.get_items(meeting_id, "info")
  action_list = await meetbot.get_items(meeting_id, "action")

  time = parse_db_time(full_log[0][1])
  post_header = f"## Summary of Meeting in {room_alias} at {time}\n"
  table_header = "Time | User | Message\n--- | --- | ---\n"

  # Info items
  raw_info    = parse_db_logs(info_list).decode('UTF-8')
  raw_actions = parse_db_logs(action_list).decode('UTF-8')
  
  raw_post = post_header +\
             "\n### Info Items\n" +\
             table_header +\
             raw_info + "\n"\
             "\n### Action Items\n" +\
             table_header +\
             raw_actions + "\n" +\
             "\n Full log available here:" +\
             log_path

  meetbot.log.info(raw_post)
  pid = await post_to_discourse(config(meetbot), raw_post, time, meetbot.log)
  if pid != "":
    url = config(meetbot)["discourse_url"] + "/t/" + str(pid)
    await event.respond(f'Logs [posted to Discourse]({url})')
