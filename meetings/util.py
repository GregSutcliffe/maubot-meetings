from mautrix.types import EventType
from mautrix.errors import MNotFound

async def get_room_alias(client, room_id):
    try:
        existing_event = await client.get_state_event(room_id, EventType.ROOM_CANONICAL_ALIAS)
        return existing_event.canonical_alias
    except MNotFound:
        # typically if a room is a direct message, it wont have a canonical alias
        return None

async def get_room_name(client, room_id):
    try:
        existing_event = await client.get_state_event(room_id, EventType.ROOM_NAME)
        return existing_event.name
    except MNotFound:
        # typically if a room is a direct message, it wont have a canonical alias
        return None
