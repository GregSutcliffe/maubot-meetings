async def startmeeting(meetbot, event):
  meetbot.log.info(f'Fedora: Meeting started in {event.room_id}')

async def endmeeting(meetbot, event, meeting_id):
  meetbot.log.info(f'Fedora: Meeting ended in {event.room_id}')
