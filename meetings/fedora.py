from .util import get_room_alias

async def startmeeting(meetbot, event):
  room_alias = await get_room_alias(meetbot.client, event.room_id)
  meetbot.log.info(f'Fedora: Meeting started in {room_alias}')

async def endmeeting(meetbot, event, meeting_id):
  room_alias = await get_room_alias(meetbot.client, event.room_id)
  
  full_log    = await meetbot.get_items(meeting_id)
  info_list   = await meetbot.get_items(meeting_id, "info")
  action_list = await meetbot.get_items(meeting_id, "action")

  await meetbot.upload_file(event, info_list, "info_items.txt")
  await meetbot.upload_file(event, action_list, "action_items.txt")
  await meetbot.upload_file(event, full_log, "full_log.txt")
  meetbot.log.info(f'Fedora: Meeting ended in {room_alias}')
