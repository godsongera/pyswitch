from pyswitch import outbound
from twisted.internet import protocol, reactor

import logging 
logging.basicConfig(level=logging.DEBUG, filename="outbound-example.log")

class OutboundProtocol(outbound.OutboundProtocol):
    
    def connectComplete(self, callinfo):
        self.myevents()
        self.answer()
        #print callinfo
        #self.playback("D:/workspace/fsradius/sounds/en/prepaid-welcome.gsm", '1#',)
        df = self.playAndGetDigits(3,4,3,filename="/opt/sounds/en/prepaid-you-have.gsm",invalidfile='123', varname="digits",regexp="\d")
        df.addCallback(self.playbackComplete)
        df.addErrback(self.playbackFailed)
        
    def playbackComplete(self, digits):
        print "Playback complete %s"%digits
        
    def playbackFailed(self, error):
        print " playback fialed", error

        
class Factory(protocol.ServerFactory):
    protocol = OutboundProtocol
    

reactor.listenTCP(8085, Factory())
reactor.run()
