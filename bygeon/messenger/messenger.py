import os
import colorlog as cl
import logging
import structlog


from websocket import WebSocketApp as WSApp

from bygeon.message import Message

from typing import Protocol, List, Dict
from pypika import Query, Column, Table
import sqlite3

from bygeon.message import Message

import bygeon.util as util

logger_format = "%(log_color)s%(levelname)s: %(name)s: %(message)s"


class Messenger(Protocol):
    logger: structlog.stdlib.BoundLogger
    links: Dict['Messenger', str | int]
    con: sqlite3.Connection
    cur: sqlite3.Cursor

    def get_logger(self):
        handler = cl.StreamHandler()
        handler.setFormatter(cl.ColoredFormatter(logger_format))

        logger = cl.getLogger(self.name)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        return logger
    
    def __init__(self, connect: sqlite3.Connection):
        self.con = connect
        self.cur = self.con.cursor()

    @property
    def file_cache_path(self) -> str:
        return os.path.join(os.getcwd(), "cache")

    def generate_cache_path(self, hub_name: str) -> str:
        return os.path.join(self.file_cache_path, hub_name)

    @property
    def name(self) -> str:
        return self.__class__.__name__
    
    def __hash__(self):
        return hash(self.name)
    
    def __eq__(self):
        return self.name == self.name

    def _on_open(self, ws) -> None:
        self.logger.info("Opened WebSocket connection")

    def _on_error(self, ws, e) -> None:
        self.logger.error(f"WebSocket encountered error: {e}")

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        self.logger.error(f"WebSocket closed: {close_msg}")

    def on_message(self, ws: WSApp, message: str) -> None:
        ...

    def send_message(self, m: Message, ref_id=None) -> None:
        ...

    def modify_message(self, m: Message, m_id: str) -> None:
        ...

    def recall_message(self, message_id: str) -> None:
        ...

    def start(self) -> None:
        ...

    def join(self) -> None:
        ...

    def add_link(self, msgr: "Messenger", channel_id: str | int) -> None:
        self.links[msgr] = channel_id

    def cache_prefix(self, id="") -> str:
        return f"{self.name}_{id}."

    '''
    def __init__(self, name: str) -> None:
        self.clients: List[Messenger] = []
        self.con = sqlite3.connect(f"{name}.db", check_same_thread=False)
        self.cur = self.con.cursor()
        self.name = name
    '''

    @property
    def client_names(self) -> List[str]:
        return [client.name for client in self.clients]

    def start(self):
        for client in self.clients:
            client.start()

    def join(self):
        for client in self.clients:
            client.join()

    def new_message(self, message: Message):
        self.new_entry(message)
        for client in self.clients:
            if client.name != message.origin:
                util.run_in_thread(client.send_message, (message,))

    def new_entry(self, message: Message) -> None:
        origin_id = message.origin_id
        origin = message.origin
        entry = (origin_id if origin == s else None for s in self.client_names)
        q = Query.into(self.table).insert(*tuple(entry))
        self.execute_sql(str(q))

    # FIXME
    def update_entry(
        self, m: Message, sent_messenger: str, sent_id: str
    ) -> None:  # noqa
        sql = f'UPDATE "messages" SET "{sent_messenger}" = \'{sent_id}\' WHERE "{m.origin}" = \'{m.origin_id}\''  # noqa
        # q = Query.update(self.table).set(sent_messenger, sent_id).where(m.origin == m.origin_id) # noqa
        self.execute_sql(sql)

    def add_client(self, client):
        self.clients.append(client)

    def reply_message(self, m: Message, reply_to: str) -> None:
        self.new_entry(m)
        orig = m.origin
        sql = f'SELECT * FROM "messages" WHERE "{orig}" = \'{reply_to}\''
        cur = self.cur.execute(sql)

        if cur.rowcount == 0:
            self.new_message(m)
            return None

        for row in cur:
            for i, client in enumerate(self.clients):
                if client.name != orig:
                    util.run_in_thread(client.send_message, (m, row[i]))
        print(self.cur.execute(sql))

    def modify_message(self, m: Message) -> None:
        orig = m.origin
        sent_id = m.origin_id
        sql = f'SELECT * FROM "messages" WHERE "{orig}" = \'{sent_id}\''
        cur = self.cur.execute(sql)
        for row in cur:
            for i, client in enumerate(self.clients):
                if client.name != orig:
                    util.run_in_thread(client.modify_message, (m, row[i]))
        ...

    def recall_message(self, orig: str, recalled_id: str) -> None:
        sql = f'SELECT * FROM "messages" WHERE "{orig}" = \'{recalled_id}\''
        cur = self.cur.execute(sql)
        for row in cur:
            for i, client in enumerate(self.clients):
                if client.name != orig:
                    util.run_in_thread(client.recall_message, (row[i],))

    def init_database(self, keep_data=True):
        columns = tuple(
            Column(s, "VARCHAR(255)", nullable=True) for s in self.client_names
        )
        if not keep_data:
            self.execute_sql('DROP TABLE IF EXISTS "messages"')
            create_table = Query.create_table("messages").columns(*columns)
            self.execute_sql(str(create_table))
        self.table = Table("messages")

    def execute_sql(self, query: str) -> None:
        print(query)
        self.cur.execute(query)
        self.con.commit()
