"""Twisted Protocols for communication with FreeSWITCH

PySWITCH allows you to communicate with FreeSWITCH using 
inbound and outbound EventSocket connections.

The protocols are designed to be included in applications that
want to allow for multi-protocol communication using the Twisted 
protocol.  Their integration with FreeSWITCH does not require any 
modification to the FreeSWITCH source code (though an eventsocket
account is obviously required for the Inbound connections, and you 
have to actually call the Outbound server from the dialplan).
"""
import inbound
import outbound
