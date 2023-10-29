#!/usr/bin/python

from pyswitch import inbound
import uuid

from twisted.internet import reactor
import logging

log = logging.getLogger("InboundTest")


class InboundTest:
    def onLogin(self, protocol):
        log.info("successfully logged in")
        self.eventsocket = protocol
        df = self.eventsocket.subscribeEvents("all")
        df.addCallbacks(self.onEventsSucess, self.onEventsFailure)

    def onEventsSucess(self, event):
        log.info(event)
        uid = str(uuid.uuid1())
        df = self.eventsocket.apiOriginate(
            "sofia/internal/1000%",
            "park",
            cidname="godson",
            cidnum="123",
            channelvars={"origination_uuid": uid},
            background=True,
        )
        self.eventsocket.registerEvent("CHANNEL_STATE", False, self.channelState)
        self.eventsocket.registerEvent("CHANNEL_ANSWER", False, self.channelAnswer)
        df.addCallback(self.originateSuccess)

    def originateSuccess(self, event):
        print("originate success")
        print(event)

    def channelState(self, event):
        print("channel state")

    def channelAnswer(self, event):
        print("channel answer")

    def onEventsFailure(self, error):
        print(error)

    def onGlobalGetVar(self, var):
        log.info(var)

    def onLoginFailed(self, error):
        log.error("Login failed")
        log.error(error)


logging.basicConfig(level=logging.DEBUG)


f = inbound.InboundFactory("ClueCon")
p = InboundTest()
f.loginDeferred.addCallback(p.onLogin)
f.loginDeferred.addErrback(p.onLoginFailed)
reactor.connectTCP("127.0.0.1", 8021, f)


if __name__ == "__main__":
    reactor.run()
