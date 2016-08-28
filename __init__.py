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
__author__ = "Godson Gera"
__email__ = 'godson.g@gmail.com',
__copyright__ = 'Copyright 2015, Godson Gera'
__credits__ = ['FreeSWITCH Team', 'Twisted Team']
__license__ = 'GPL'
<<<<<<< HEAD
__version__ = '0.3'
=======
__version__ = '0.2'
>>>>>>> af66e2e1cf2c32675f66e4a5ba822cfd85b53923

import inbound
import outbound
