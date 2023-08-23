async def startmeeting(meetbot, event):
  meetbot.log.info(f'Fedora: Meeting started in {event.room_id}')

async def endmeeting(meetbot, event, meeting_id):
  full_log    = await meetbot.get_items(meeting_id)
  info_list   = await meetbot.get_items(meeting_id, "info")
  action_list = await meetbot.get_items(meeting_id, "action")

  await meetbot.upload_file(event, info_list, "info_items.txt")
  await meetbot.upload_file(event, action_list, "action_items.txt")
  await meetbot.upload_file(event, full_log, "full_log.txt")
  meetbot.log.info(f'Fedora: Meeting ended in {event.room_id}')
