import outbound
from twisted.internet import protocol, reactor

import logging 
logging.basicConfig(level=logging.DEBUG)

class OutboundProtocol(outbound.OutboundProtocol):
    
    def onConnectComplete(self, callinfo):
        print callinfo
        self.playback("D:/workspace/fsradius/sounds/en/prepaid-welcome.gsm", '1#',)
        
class Factory(protocol.ServerFactory):
    protocol = OutboundProtocol
    

reactor.listenTCP(8085, Factory())
reactor.run()
