"""Per-room channel delivery for the socket.io Redis manager, disabled with
WEBSOCKET_REDIS_ROOM_CHANNELS=false.

Room-targeted emits are published on a per-room channel instead of the shared
one; every instance holds one static pattern subscription covering all room
channels and drops messages for rooms without local members by channel name,
before decoding the payload. Acks, control messages and non-str room emits
stay on the shared channel. All instances sharing a channel must run the same
mode.
"""

import asyncio

from socketio import AsyncRedisManager


class AsyncRedisRoomChannelManager(AsyncRedisManager):
    name = 'aioredisroomchannel'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._local_room_channels = set()

    # collision-free while namespaces contain no '#' (socket.io default '/'); rooms may contain '#'
    def _room_channel(self, namespace, room):
        return f'{self.channel}#{namespace}#{room}'.encode()

    # every local membership change funnels through these two hooks
    def basic_enter_room(self, sid, namespace, room, eio_sid=None):
        super().basic_enter_room(sid, namespace, room, eio_sid=eio_sid)
        if room is not None:
            self._local_room_channels.add(self._room_channel(namespace, room))

    def basic_leave_room(self, sid, namespace, room):
        super().basic_leave_room(sid, namespace, room)
        if room is not None and room not in self.rooms.get(namespace, {}):
            self._local_room_channels.discard(self._room_channel(namespace, room))

    async def _publish(self, data):
        # stock copy (5.16) with the channel made variable; re-check on upgrades
        if data.get('method') == 'emit' and isinstance(data.get('room'), str):
            channel = self._room_channel(data['namespace'], data['room'])
        else:
            channel = self.channel
        _, error = self._get_redis_module_and_error()
        for retries_left in range(1, -1, -1):  # 2 attempts
            try:
                if not self.connected:
                    self._redis_connect()
                return await self.redis.publish(channel, self.json.dumps(data))
            except error as exc:
                if retries_left > 0:
                    self._get_logger().error(
                        'Cannot publish to redis... retrying', extra={'redis_exception': str(exc)}
                    )
                    self.connected = False
                else:
                    self._get_logger().error(
                        'Cannot publish to redis... giving up', extra={'redis_exception': str(exc)}
                    )
                    break

    async def _redis_listen_with_retries(self):
        # stock copy (5.16) with the room pattern subscribe added; re-check on upgrades
        _, error = self._get_redis_module_and_error()
        retry_sleep = 1
        subscribed = False
        while True:
            try:
                if not subscribed:
                    self._redis_connect()
                    await self.pubsub.subscribe(self.channel)
                    await self.pubsub.psubscribe(f'{self.channel}#*')
                    retry_sleep = 1
                async for message in self.pubsub.listen():
                    yield message
            except error as exc:
                self._get_logger().error(
                    f'Cannot receive from redis... retrying in {retry_sleep} secs',
                    extra={'redis_exception': str(exc)},
                )
                subscribed = False
                await asyncio.sleep(retry_sleep)
                retry_sleep *= 2
                if retry_sleep > 60:
                    retry_sleep = 60

    async def _listen(self):
        main_channel = self.channel.encode()
        async for message in self._redis_listen_with_retries():
            if 'data' not in message:
                continue
            if (message['type'] == 'message' and message['channel'] == main_channel) or (
                message['type'] == 'pmessage' and message['channel'] in self._local_room_channels
            ):
                yield message['data']
