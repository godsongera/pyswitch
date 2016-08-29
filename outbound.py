#!/usr/bin/python

from fsprotocol import *
from twisted.internet import protocol

log = logging.getLogger("OutboundSocket")


class OutboundProtocol(FSProtocol):
    """
    Outbound connection from FreeSWITCH. 
    """
    state = "READ_CHANNELINFO"  # set state to read cahnnel info up on connect

    def connectionMade(self):
        log.info("New connection from FreeSWITCH %s" % self.transport.getPeer())
        FSProtocol.connectionMade(self)
        self.connect()

    def connect(self):
        self.sendLine("connect")

    def onConnect(self):
        self.state = "READ_CONTENT"
        self.message.decode()
        self.connectComplete(self.message)

    def connectComplete(self, callinfo):
        log.error("Method not implemented")


class OutboundFactory(protocol.ServerFactory):
    protocol = OutboundProtocol
