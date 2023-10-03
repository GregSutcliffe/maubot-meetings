import asyncio
from dataclasses import dataclass

from maubot.matrix import MaubotMatrixClient, MaubotMessageEvent
from mautrix.api import HTTPAPI
from mautrix.types import (
    CanonicalAliasStateEventContent,
    EventContent,
    EventType,
    MessageEvent,
    MessageType,
    PowerLevelStateEventContent,
    RoomAlias,
    RoomID,
    RoomNameStateEventContent,
    TextMessageEventContent,
)

SENDER = "@dummy:example.com"


@dataclass
class SentEvent:
    room_id: RoomID
    event_type: EventType
    content: EventContent
    kwargs: dict


class TestBot(MaubotMatrixClient):
    def __init__(self):
        api = HTTPAPI(base_url="http://matrix.example.com")
        self.client = MaubotMatrixClient(api=api)
        self.sent = []
        self.client.send_message_event = self._mock_send_message_event
        self.client.get_state_event = self._mock_get_state_event
        self.timestamp = 0

    async def _mock_send_message_event(self, room_id, event_type, content, txn_id=None, **kwargs):
        self.sent.append(
            SentEvent(room_id=room_id, event_type=event_type, content=content, kwargs=kwargs)
        )

    async def _mock_get_state_event(self, room_id, event_type, **kwargs):
        if event_type == EventType.ROOM_POWER_LEVELS:
            return PowerLevelStateEventContent(users={SENDER: 50})
        if event_type == EventType.ROOM_NAME:
            return RoomNameStateEventContent(name="Test Room")
        if event_type == EventType.ROOM_CANONICAL_ALIAS:
            return CanonicalAliasStateEventContent(
                canonical_alias=RoomAlias("@testroom:example.com")
            )

    async def send(self, content, room_id="testroom"):
        self.timestamp = self.timestamp + 10000
        event = MessageEvent(
            type=EventType.ROOM_MESSAGE,
            room_id=room_id,
            event_id="test",
            sender=SENDER,
            timestamp=self.timestamp,
            content=TextMessageEventContent(msgtype=MessageType.TEXT, body=content),
        )
        tasks = self.client.dispatch_manual_event(
            EventType.ROOM_MESSAGE, MaubotMessageEvent(event, self.client), force_synchronous=True
        )
        return await asyncio.gather(*tasks)
