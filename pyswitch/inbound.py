#!/usr/bin/python

from fsprotocol import *

log = logging.getLogger("InbounSocket")


class InboundProtocol(FSProtocol):
    """
    Inbound connection to FreeSWITCH.
    Using inbound socket connections you can check status, make outbound calls, etc.
    """

    def auth(self):
        """Perform authentication

        returns deferred fired on successfull authentication
        """
        df = self.sendData("auth", self.factory.password)
        df.addCallback(self.authSuccess)
        df.addErrback(self.authFailed)
        return df

    def authSuccess(self, msg):
        """Override this for when authentication is sueccessful"""
        log.info("Successfully authenticated")
        if hasattr(self.factory, "loginDeferred"):
            self.factory.loginDeferred.callback(self)

    def authFailed(self, error):
        """Override this for when authentication failed"""
        log.error("Login failed")
        log.error(error)
        if hasattr(self.factory, "loginDeferred"):
            self.factory.loginDeferred.errback(error)


class InboundFactory(protocol.ClientFactory):
    """A factory for InboundSocketProtocol
    """
    protocol = InboundProtocol
    def __init__(self, password):
        self.password = password
        self.loginDeferred = defer.Deferred()

    def clientConnetionFailed(self, connector, reason):
        log.info("Failed to connect to FreeSWITCH")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    f = InboundFactory("ClueCon")
    reactor.connectTCP("127.0.0.1", 8021, f)
    reactor.run()
