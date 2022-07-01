import websocket
import threading
import requests
import json
import time
import logging

from enum import Enum
from typing import TypedDict

from hub import Hub
from message import Message
from .messenger import Messenger

import colorlog


class Endpoints:
    GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
    SEND_MESSAGE = "https://discordapp.com/api/channels/{}/messages"


handler = colorlog.StreamHandler()
handler.setFormatter(
    colorlog.ColoredFormatter("%(log_color)s%(levelname)s:%(name)s:%(message)s")
)


class ReferencedMessage(TypedDict):
    type: int
    id: str

class Author(TypedDict):
    id: str
    username: str
    avatar: str
    bot: bool

class GatewayEvent(TypedDict):
    type: int
    referenced_message: ReferencedMessage
    channel_id: str
    content: str
    id: str
    author: Author


class WebsocketMessage(TypedDict):
    op: int
    t: str
    s: int
    d: GatewayEvent


class Opcode(Enum):
    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    PRESENCE_UPDATE = 3
    RESUME = 6
    RECONNECT = 7
    HELLO = 10
    HEARTBEAT_ACK = 11


class EventName(Enum):
    MESSAGE_CREATE = "MESSAGE_CREATE"
    MESSAGE_UPDATE = "MESSAGE_UPDATE"
    MESSAGE_DELETE = "MESSAGE_DELETE"
    READY = "READY"


websocket.enableTrace(True)
logger = colorlog.getLogger("Discord")
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)


class Discord(Messenger):
    def __init__(self, token: str, channel_id, hub: Hub) -> None:
        self.token = token
        self.channel_id = channel_id
        self.hub = hub
        self.received_messages = []

    def on_open(self, ws):
        print("opened")

    def on_error(self, ws, e):
        print("error")
        print(e)

    def on_close(self, ws, close_status_code, close_msg):
        print("closed")
        print(close_msg)

    def on_message(self, ws: websocket.WebSocketApp, message: str):
        def heartbeat(ws, interval):
            payload = {
                "op": 1,
                "d": None,
            }
            while True:
                time.sleep(interval / 1000)
                ws.send(json.dumps(payload))

        message: WebsocketMessage = json.loads(message)

        opcode = message["op"]
        match Opcode(opcode):
            # opcode 10 hello
            case Opcode.HELLO:
                heartbeat_interval = message["d"]["heartbeat_interval"]
                self.send_identity(ws)
                threading.Thread(
                    target=heartbeat, args=(ws, heartbeat_interval)
                ).start()
            case 2:
                # TODO
                pass
            case 1:
                # TODO
                pass
            case Opcode.DISPATCH:
                type = message["t"]
                match EventName(type):
                    case EventName.MESSAGE_CREATE:
                        text = message["d"]["content"]
                        logger.info("Message: %s", text)
                        username = message["d"]["author"]["username"]

                        m = Message(username, text)

                        author = message["d"]["author"]
                        if not author.get("bot"):
                            self.hub.new_message(m, self)
                            self.received_messages.append(message["d"]["id"])
            case _:
                pass

    def send_message(self, message: Message) -> None:
        payload = {
            "content": message.text,
            # "embeds": [
            #    {
            #        "author": message.author_username,
            #        "title": "says",
            #        "description": message.text,
            #        "url": "https://discordapp.com",
            #    }
            # ],
        }
        headers = {
            "Authorization": f"Bot {self.token}",
        }
        r = requests.post(
            Endpoints.SEND_MESSAGE.format(self.channel_id),
            json=payload,
            headers=headers,
        )
        self.received_messages.append(r.json()["id"])
        logger.error(message.author_username + ": " + message.text)
        logger.error(r.text)

    def send_identity(self, ws: websocket.WebSocketApp) -> None:
        payload = self.get_identity_payload()
        print(payload)
        ws.send(payload)

    def get_identity_payload(self):
        payload = {
            "op": 2,
            "d": {
                "token": self.token,
                "properties": {
                    "os": "linux",
                    "browser": "pygeon",
                    "device": "pygeon",
                },
                "large_threshold": 250,
                "compress": False,
                "intents": (1 << 15) + (1 << 9),
            },
        }
        return json.dumps(payload)

    def reconnect(self) -> None:
        # TODO
        pass

    def start(self) -> None:
        self.ws = websocket.WebSocketApp(
            Endpoints.GATEWAY,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        self.thread = threading.Thread(target=self.ws.run_forever)
        self.thread.daemon = True
        self.thread.start()

    def join(self) -> None:
        self.thread.join()
