#!/usr/bin/python

from pyswitch import *
import uuid 

from twisted.internet import reactor
import logging
log = logging.getLogger("InboundTest")

class InboundTest:
    def onLogin(self, protocol):
        log.info("successfully logged in")
        self.eventsocket = protocol
        df = self.eventsocket.subscribeEvent("all")
        df.addCallbacks(self.onEventsSucess, self.onEventsFailure)
        
        
        
    def onEventsSucess(self, event):
        
        log.info(event)
        #self.eventsocket.playback("D:/workspace/fsradius/sounds/en/prepaid-welcome.gsm", '1',"c541d96c-8af2-024c-9835-e8dd9e177d9c")
        uid = str(uuid.uuid1())
        df = self.eventsocket.apiOriginate("sofia/internal/1000%", "park",  cidname="godson", cidnum="123" ,channelvars={"origination_uuid":uid},  background=True)
        self.eventsocket.registerEvent("CHANNEL_STATE", self.channelState)
        self.eventsocket.registerEvent("CHANNEL_ANSWER", self.channelAnswer)
        df.addCallback(self.originateSuccess)
        #df = self.eventsocket.apiGlobalGetVar(background=True)
        #df.addCallbacks(self.onGlobalGetVar, self.onEventsFailure)
        
    def originateSuccess(self, event):
        print "originate success"
        print event
    def channelState(self, event):
        print "channel state"
        
    def channelAnswer(self, event):
        print "channel answer"
    def onEventsFailure(self, error):
        print error
        
    def onGlobalGetVar(self, var):
        log.info(var)
        
    def onLoginFailed(self, error):
        log.error("Login failed")
        log.error(error)
    
#logging.basicConfig(level = logging.DEBUG)

        
f = inbound.InboundFactory("ClueCon")
p = InboundTest()
f.loginDeferred.addCallback(p.onLogin)
f.loginDeferred.addErrback(p.onLoginFailed)
reactor.connectTCP("127.0.0.1", 8021, f)
reactor.run()
