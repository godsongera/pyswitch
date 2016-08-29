#!/usr/bin/python


import logging
import urllib
import uuid

from twisted.internet import defer
from twisted.protocols import basic
from email.message import Message
from email.feedparser import FeedParser

log = logging.getLogger("PySWITCH")


class CommandError(Exception):
    """Failed to execute the given command"""
    pass


class Event(Message):
    """Event - represents an event object .
    Extends python's email.message.Message class. so all methods that are 
    available on Message object are available on Event object
    """

    def decode(self):
        """Rebuild the event headers with with URL format decoded values"""
        for k, v in self.items():
            del self[k]
            self[k] = urllib.unquote(v)

    # Overriding this method was required as default python lib wraps headers with length greater than 78 chars which is bad for FreeSWITCH
    def as_string(self, unixfrom=False):
        """Return the entire formatted message as a string.
        Optional `unixfrom' when True, means include the Unix From_ envelope
        header.

        This is a convenience method and may not generate the message exactly
        as you intend because by default it mangles lines that begin with
        "From ".  For more flexibility, use the flatten() method of a
        Generator instance.
        """
        from email.generator import Generator
        from cStringIO import StringIO
        fp = StringIO()
        g = Generator(fp, maxheaderlen=0)
        g.flatten(self, unixfrom=unixfrom)
        return fp.getvalue()


class EventCallback:
    def __init__(self, eventname, func, *args, **kwargs):
        self.func = func
        self.eventname = eventname
        self.subclass = None  # event subclass for CUSTOM event
        self.args = args
        self.kwargs = kwargs


class FSProtocol(basic.LineReceiver):
    """FreeSWITCH EventSocket protocol implementation.
    
    All the FreeSWITCH api and dptool commands are defined in this class
    """
    delimiter = "\n\n"
    jobType = False
    state = "READ_CONTENT"
    contentCallbacks = None
    pendingJobs = None
    pendingBackgroundJobs = None
    eventCallbacks = None
    customEventCallbacks = None
    subscribedEvents = None
    parser = None
    message = None
    rawdataCache = ''
    contentLength = 0
    currentDeferred = None

    def connectionMade(self):
        self.contentCallbacks = {"auth/request": self.auth,
                                 "api/response": self.onAPIReply,
                                 "command/reply": self.onCommandReply,
                                 "text/event-plain": self.onEvent,
                                 "text/disconnect-notice": self.disconnectNotice
                                 }
        self.pendingJobs = []
        self.pendingBackgroundJobs = {}
        self.eventCallbacks = {}
        self.customEventCallbacks = {}
        self.subscribedEvents = []
        log.info("Connected to FreeSWITCH")

    def connectionLost(self, reason):
        log.info("Cleaning up")
        self.disconnectedFromFreeSWITCH()

    def disconnectedFromFreeSWITCH(self):
        """Over-ride this to get notified of FreeSWITCH disconnection"""
        pass

    def registerEvent(self, event, subscribe, function, *args, **kwargs):
        """Register a callback for the event 
        event -- (str) Event name as sent by FreeSWITCH , Custom events should give subclass also 
                                eg : CUSTOM conference::maintenance
        subsribe -- (bool) if True subscribe to this event
        function -- callback function accepts a event dictionary as first argument
        args -- argumnet to be passed to callback function
        kwargs -- keyword arguments to be passed to callback function
        
        returns instance of  EventCallback , keep a reference of this around if you want to deregister it later
        """
        if subscribe:
            if self.needToSubscribe(event):
                self.subscribeEvents(event)
        ecb = EventCallback(event, function, *args, **kwargs)
        ecb_list = self.eventCallbacks.get(event, [])
        event_callbacks = self.eventCallbacks
        # handle CUSTOM events
        if event.startswith("CUSTOM"):
            subclass = event.split(' ')
            event = subclass[1]
            ecb.subclass = event
            ecb_list = self.customEventCallbacks.get(event, [])
            event_callbacks = self.customEventCallbacks
        ecb_list.append(ecb)
        event_callbacks[event] = ecb_list
        return ecb

    def needToSubscribe(self, event):
        """Decide if we need to subscribe to an event or not by comparing the event provided against already subscribeEvents
        
        event -- (str) event name 
        
        returns bool
        """
        if "all" in self.subscribedEvents:
            return False
        if event in self.subscribedEvents:
            return False
        if 'myevents' in self.subscribedEvents:
            return False
        else:
            return True

    def deregisterEvent(self, ecb):
        """Deregister a callback for the given event
        
        ecb -- (EventCallback) instance of EventCallback object
        """
        callbacks_list = self.eventCallbacks
        if ecb.eventname == 'CUSTOM':
            callbacks_list = self.customEventCallbacks
        ecbs = callbacks_list[ecb.eventname]
        try:
            ecbs.remove(ecb)
        except ValueError:
            log.error("%s already deregistered " % ecb)

    def dataReceived(self, data):
        """
        We override this twisted method to avoid being disconnected by default MAX_LENGTH for messages which cross
        that limit
        """
        if self._busyReceiving:
            self._buffer += data
            return

        try:
            self._busyReceiving = True
            self._buffer += data
            while self._buffer and not self.paused:
                if self.line_mode:
                    try:
                        line, self._buffer = self._buffer.split(
                            self.delimiter, 1)
                    except ValueError:
                        return
                    else:
                        why = self.lineReceived(line)
                        if (why or self.transport and
                            self.transport.disconnecting):
                            return why
                else:
                    data = self._buffer
                    self._buffer = b''
                    why = self.rawDataReceived(data)
                    if why:
                        return why
        finally:
            self._busyReceiving = False

    def lineReceived(self, line):
        log.debug("Line In: %s" % line)
        self.parser = FeedParser(Event)
        self.parser.feed(line)
        self.message = self.parser.close()
        # if self.state is not READ_CONTENT (i.e Content-Type is already read) and the Content-Length is present
        # read rest of the message and set it as payload
        if self.message.has_key('Content-Length') and self.state != 'READ_CONTENT':
            if self.enterRawMode():
                log.debug("Entering raw mode to read message payload")
                return
        try:
            self.inspectMessage()
        except:
            log.error("Exception in message processing ", exc_info=True)

    def rawDataReceived(self, data):
        """Read length of raw data specified by self.contentLength and set it as message payload """
        log.debug("Data In : %s" % data)
        self.rawdataCache = ''.join([self.rawdataCache, data])
        if len(self.rawdataCache) >= self.contentLength - 1:
            self.clearLineBuffer()
            extra = self.rawdataCache[self.contentLength:]
            currentResult = self.rawdataCache[:self.contentLength]
            self.message.set_payload(currentResult)
            try:
                self.inspectMessage()
            except:
                log.error("Exception in message processing ", exc_info=True)
            self.setLineMode(extra)

    def enterRawMode(self):
        """
        Change to raw mode from line mode if self.contentLength > 0
        """
        self.contentLength = int(self.message['Content-Length'].strip())
        if self.contentLength > 0:
            self.rawdataCache = ''
            self.setRawMode()
            return True
        return False

    def inspectMessage(self):
        """Inspect message and dispatch based on self.state or Content-Type of message """
        if self.state == "READ_EVENT":
            return self.dispatchEvent()
        if self.state == "READ_CHANNELINFO":
            return self.onConnect()
        if self.state == 'READ_API':
            return self.fireAPIDeferred()
        if not self.message.has_key("Content-Type"):
            return
        ct = self.message['Content-Type']
        try:
            cb = self.contentCallbacks[ct]
            cb()
        except KeyError:
            log.error("Got unimplemented Content-Type : %s" % ct)

    def dispatchEvent(self):
        self.state = "READ_CONTENT"
        eventname = self.message['Event-Name']
        # Handle background job event
        if eventname == "BACKGROUND_JOB":
            try:
                df = self.pendingBackgroundJobs.pop(self.message['Job-UUID'])
                df.callback(self.message)
            except KeyError:
                log.error("Stray BACKGROUND_JOB event received %s", self.message['Job-UUID'])
            except:
                log.error("Error in BACKGROUND_JOB event handler", exc_info=True)
        if eventname == 'CUSTOM':
            self.message.decode()
            ecbs = self.customEventCallbacks.get(self.message['Event-Subclass'], None)
        else:
            ecbs = self.eventCallbacks.get(eventname, None)
        if ecbs is None:
            return

        for ecb in ecbs:
            try:
                ecb.func(self.message, *ecb.args, **ecb.kwargs)
            except:
                log.error("Message %s\nError in event handler %s on event %s:" % (self.message, ecb.func, eventname),
                          exc_info=True)

    def onConnect(self):
        """Channel Information is ready to be read.
        """
        log.info("onconnect")

    def auth(self):
        """
        FreeSWITCH is requesting to authenticate         
        """
        pass

    def fireAPIDeferred(self):
        self.state = 'READ_CONTENT'
        df = self.pendingJobs.pop(0)
        df.callback(self.message)

    def onAPIReply(self):
        """
        Handle API reply 
        """
        if not self.message.has_key("Content-Length"):
            self.currentDeferred = self.pendingJobs.pop(0)
            return self.currentDeferred.callback(self.message)
        if self.enterRawMode():
            self.state = "READ_API"
            log.debug("Entering raw mode to read API response")
            return
        else:
            self.currentDeferred.callback(self.message)

    def onCommandReply(self):
        """
        Handle CommandReply        
        """
        if self.message.has_key("Job-UUID"):
            return
        try:
            df = self.pendingJobs.pop(0)
        except IndexError:
            log.error("Command reply message received with out pending deferred %s" % self.message)
            return
        if self.message['Reply-Text'].startswith("+OK"):
            df.callback(self.message)
        else:
            e = CommandError(self.message['Reply-Text'])
            df.errback(e)

    def onEvent(self):
        """
        Handle a new event
        """
        self.state = "READ_EVENT"

    def disconnectNotice(self):
        """
        Handle disconnect notice 
        """

        if not self.message.has_key("Content-Length"):
            return self.disconnectNoticeReceived(self.message)
        self.contentLength = int(self.message['Content-Length'])
        if self.contentLength > 0:
            self.currentDeferred = defer.Deferred()
            log.info("Enter raw mode to read disconnect notice")
            self.rawdataCache = ''
            self.setRawMode()
        else:
            self.disconnectNoticeReceived(self.message)

    def disconnectNoticeReceived(self, msg):
        """Override this to receive disconnect notice from FreeSWITCH"""
        log.error("disconnectNoticeReceived not implemented")
        log.info(msg)

    def sendData(self, cmd, args=''):
        df = defer.Deferred()
        # self.pendingJobs.append((cmd, df))
        self.pendingJobs.append(df)
        if args:
            cmd = ' '.join([cmd, args])
        self.sendLine(cmd)
        log.debug("Line Out: %r" % cmd)
        return df

    def sendMsg(self, msg):
        """Send message to FreeSWITCH
        
        msg -- (event) Event object 
        
        """
        df = defer.Deferred()
        self.pendingJobs.append(df)
        msg = msg.as_string(True)
        self.transport.write(msg)
        log.debug("Line Out: %r" % msg)
        return df

    def sendCommand(self, cmd, args='', uuid='', lock=True):
        msg = Event()
        if uuid:
            msg.set_unixfrom("SendMsg %s" % uuid)
        else:
            msg.set_unixfrom("SendMsg")
        msg['call-command'] = "execute"
        msg['execute-app-name'] = cmd
        if args:
            msg['execute-app-arg'] = args
        if lock:
            msg['event-lock'] = "true"
        return self.sendMsg(msg)

    def sendAPI(self, apicmd, background=jobType):
        if background:
            return self.sendBGAPI(apicmd)
        else:
            return self.sendData("api", apicmd)

    def sendBGAPI(self, apicmd):
        jobid = str(uuid.uuid1())
        apicmd = ' '.join(['bgapi', apicmd])
        apicmd = '\n'.join([apicmd, "Job-UUID:%s" % jobid])

        backgroundJobDeferred = defer.Deferred()
        self.pendingBackgroundJobs[jobid] = backgroundJobDeferred

        log.debug("Line Out: %r", apicmd)
        self.sendLine(apicmd)
        return backgroundJobDeferred

    def subscribeEvents(self, events):
        """Subscribe to FreeSWITCH events.
        
        events -(str) 'all'  subscribe to all events or event names separated by space
        this method can subscribe to multiple events but if the event is of CUSTOM type
        then only one CUSTOM event with subclass should be given
        """
        _events = []
        if not events.startswith("CUSTOM"):
            _events = events.split(' ')
        for event in _events:
            self.subscribedEvents.append(event)

        return self.sendData("event plain", events)

    def myevents(self, uuid=''):
        """Tie up the connection to particular channel events"""
        self.subscribedEvents.append("myevents")
        if uuid:
            return self.sendData("myevents %s" % uuid)
        else:
            return self.sendData("myevents")

    def apiAvmd(self, uuid, start=True, background=jobType):
        """Execute avmd on provided channel. 
        uuid (str) -- uuid of the target channel
        start (bool)  -- If True avmd will start if false avmd will be stopped
        """
        if start:
            return self.sendAPI("avmd %s start" % uuid, background)
        else:
            return self.sendAPI("avmd %s stop" % uuid, background)

    def apiConferenceDial(self, name, url, background=jobType):
        """Dial the given url from conference 
        
        name -- (str) name of the conference 
        url -- (str) FreeSWITCH compatible call URL"""
        cmd = 'conference %s dial %s' % (name, url)
        return self.sendAPI(cmd, background)

    def apiConferenceKick(self, name, member, background=jobType):
        """Kick the given member from conference 
        
        name -- (str) name of the conference 
        member -- (str) member id or all or last 
        """
        cmd = "conference %s kick %s" % (name, member)
        return self.sendAPI(cmd, background)

    def apiConferenceList(self, name=None, delim=None, background=jobType):
        """List the conference 
        name - (str) name of the conference. if not given all the conferences will be listed 
        delim - (str) delimiter to use for separating values """

        cmd = "conference"
        if name is not None:
            cmd = ' '.join([cmd, name, 'list'])
        else:
            cmd = ' '.join([cmd, 'list'])

        if delim is not None:
            cmd = ' '.join([cmd, 'delim', delim])
        return self.sendAPI(cmd, background)

    def apiConferenceListCount(self, name, background=True):
        """Return number of members in the conference
        
        name -- (str) name of the conference
        """
        cmd = 'conference %s list count' % name
        return self.sendAPI(cmd, background)

    def apiConferenceVolume(self, name, member, value=0, direction='out', background=jobType):
        """Set volume of conference 
        
        name -- (str) name of the conference 
        memeber -- (str) member id or all or last 
        value -- (int) 0 - 4
        direction -- (str) in or out"""

        cmd = "conference %s volume_%s %s %s" % (name, direction, member, value)
        return self.sendAPI(cmd, background)

    def apiConferenceMute(self, name, member, background=jobType):
        """Mute given member in a conference
        
        name -- (str) name of the conference
        member -- (str) member id or all or last
        """
        cmd = "conference %s mute %s" % (name, member)
        return self.sendAPI(cmd, background)

    def apiConferencePlay(self, name, filename, member=None, background=jobType):
        """Playback given file in conference
        
        name -- (str) name of the conference
        filename -- (str) name of the audio file to be played in conference
        member -- (str) member id in conference
        """
        if member:
            cmd = "conference %s play %s %s" % (name, filename, member)
        else:
            cmd = "conference %s play %s" % (name, filename,)
        return self.sendAPI(cmd, background)

    def apiConferenceStop(self, name, fid=None, member=None, background=jobType):
        """Stop an ongoing/queued playback in conference
        
        name -- (str) name of the conference
        fid -- (str) file ID to stop takes all|async|current|last
        member -- (str) member id in conference
        """
        if member:
            cmd = "conference %s stop %s %s" % (name, fid, member)
        elif fid:
            cmd = "conference %s stop %s" % (name, fid)
        else:
            cmd = "conference %s stop" % (name,)
        return self.sendAPI(cmd, background)

    def apiConferenceUnMute(self, name, member, background=jobType):
        """UnMute given member in a conference
        
        name -- (str) name of the conference
        member -- (str) member id or all or last
        """
        cmd = "conference %s unmute %s" % (name, member)
        return self.sendAPI(cmd, background)

    def apiDomainExists(self, domain, background=jobType):
        cmd = "domain_exists %s" % domain
        return self.sendAPI(cmd, background)

    def apiGlobalGetVar(self, variable='', background=jobType):
        """Get the value of a global variable
        
        variable -- name of the variable
        
        returns the value of the provided global variable if argument variable is not present then all global variables are returned.
        """
        apicmd = ' '.join(["global_getvar", variable])
        df = self.sendAPI(apicmd, background)
        if variable != '':
            return df
        else:
            finalDF = defer.Deferred()
            df.addCallback(self._parseGlobalGetVar, finalDF)
            return finalDF

    def _parseGlobalGetVar(self, result, df):
        result = result.get_payload()
        res = result.strip().split("\n")
        finalResult = {}
        try:
            for r in res:
                k, v = r.split("=", 1)
                finalResult[k] = v
            else:
                df.callback(finalResult)
        except Exception, err:
            log.error(err)

    def apiGlobalSetVar(self, variable, value, background=jobType):
        """Set the value of a global variable
        
        variable -- name of the variable whose value needs to be set
        value -- value of the variable to be set
        """
        pass

    def apiHupAll(self, cause='NORMAL_CLEARING', variable='', value='', background=jobType):
        """Hangup all the existing channels 
        
        cause -- cause for hanging up 
        variable -- channel having the provided variable will be checked for hangup
        value -- value of the variable. Hangup only if this matches
        """
        apicmd = ' '.join(['hupall', cause, variable, value]).strip()
        return self.sendAPI(apicmd, background)

    def apiLoad(self, module_name, background=jobType):
        """Load external module 
        
        module_name -- (str) name of the module 
        """
        apicmd = ' '.join(["load", module_name])
        return self.sendAPI(apicmd, background)

    def apiReload(self, module_name, background=jobType):
        """Reload and external module
        
        module_name -- (str) name of the module 
        """
        apicmd = ' '.join(["reload", module_name])
        return self.sendAPI(apicmd, background)

    def apiReloadXML(self, background=jobType):
        """Reload XML configuration
        """
        apicmd = "reloadxml"
        return self.sendAPI(apicmd, background)

    def apiStatus(self, background=jobType):
        """Fetch freeswitch status
        """
        apicmd = "status"
        return self.sendAPI(apicmd, background)

    def apiUnload(self, module_name, background=jobType):
        """Unload external module 
        
        module_name -- (str) name of the module to unload 
        """
        apicmd = ' '.join(["unload", module_name])
        return self.sendAPI(apicmd, background)

    def apiVersion(self, background=jobType):
        """Fetch FreeSWITCH version"""
        apicmd = "version"
        return self.sendAPI(apicmd, background)

    # Call management
    def apiOriginate(self, url, application='', appargs='', extension='', dialplan='', context='', cidname='',
                     cidnum='', timeout='', channelvars={}, background=jobType):
        """Originate a new channel and connect it back to the specified extension or application
        
        url -- (str) call url . Should be a valid FreeSWITCH supported URL
        extension -- (str) Extension number that the originated call has to be connected back to. make sure 
                        that you provide dialplan and context also when this arg is provided.
        application -- (str) Application name to connect to, either extension or application has to be provided
        appargs -- (str) application arguments 
        dialplan -- (str) FreeSWITCH dialplan
        context -- (str) Context to look for the extension 
        cidname -- (str) Outbound caller ID name 
        cidnum -- (str) Outbound caller ID number
        channelvars -- (dict) key value pairs of channel variables to be set on originated channel.
        """
        apicmd = "originate"
        if channelvars:
            vars = []
            for k, v in channelvars.items():
                var = '='.join([k, v])
                vars.append(var)
            else:
                vars = ','.join(vars)
                vars = "{" + vars + "}"
                url = vars + url
        apicmd = ' '.join([apicmd, url])

        if application:
            application = "&" + application
            if appargs:
                appargs = "(" + appargs + ")"
                application = "'%s'" % ''.join([application, appargs])
                apicmd = ' '.join([apicmd, application])
            else:
                apicmd = ' '.join([apicmd, application])
        else:
            apicmd = ' '.join([apicmd, extension])
        apicmd = ' '.join([apicmd, dialplan, context, cidname, cidnum, timeout])
        return self.sendAPI(apicmd, background)

    def apiPause(self, uuid, flag=True, background=jobType):
        if flag:
            apicmd = ' '.join(['pause', uuid, 'on'])
        else:
            apicmd = ' '.join(['pause', uuid, 'off'])
        return self.sendAPI(apicmd, background)

    def apiUUIDBreak(self, uuid, all=True, background=jobType):
        """Break out of media being sent to a channel. For example, 
        if an audio file is being played to a channel, issuing uuid_break 
        will discontinue the media and the call will move on in the dialplan, 
        script, or whatever is controlling the call.
        
        uuid - (str) uuid of the target channel 
        all - (bool) to break all queued up audio files or only the current one
        """
        apicmd = ' '.join(['uuid_break', uuid, all])
        return self.sendAPI(apicmd, background)

    def apiUUIDBridge(self, uuid1, uuid2, background=jobType):
        """Bridge two active channel uuids 
        
        uuid1 -- (str) Channel 1 uuid 
        uuid2 -- (str) Second channel uuid 
        """
        apicmd = ' '.join(['uuid_bridge', uuid1, uuid2])
        return self.sendAPI(apicmd, background)

    def apiUUIDBroadcast(self, uuid, path, leg='aleg', background=jobType):
        """Play a <path> file to a specific <uuid> call. 
        
        uuid -- (str) uuid of the target channel
        path -- (str) path of the file to be played
        leg -- (str) on which leg to play file possible options - aleg,bleg,both defaults to aleg
        """
        apicmd = ' '.join(["uuid_broadcast", uuid, path, leg])
        return self.sendAPI(apicmd, background)

    def apiUUIDChat(self, uuid, msg, background=jobType):
        """Send a chat message to target channel
        
        uuid -- (str) uuid of the target channel
        msg -- (str) chat message to be sent
        """
        apicmd = ' '.join(['uuid_chat', uuid, msg])
        return self.sendAPI(apicmd, background)

    def apiUUIDDeflect(self, uuid, uri, background=jobType):
        """Deflect an answered SIP call off of FreeSWITCH by sending the REFER method. 
        
        uuid_deflect waits for the final response from the far end to be reported. 
        It returns the sip fragment from that response as the text in the FreeSWITCH response to uuid_deflect. 
        If the far end reports the REFER was successful, then FreeSWITCH will issue a bye on the channel. 
        
        uuid -- (str) uuid of the target channel 
        uri -- (str) destination sip URI
        """
        apicmd = ' '.join(['uuid_deflect', uuid, uri])
        return self.sendAPI(apicmd, background)

    def apiUUIDDisplace(self, uuid, switch, path, limit, mux=True, background=jobType):
        """Displace the audio for the target <uuid> with the specified audio <path>. 
        
        uuid -- (str) uuid of the target channel 
        switch -- (str) possible options are start,stop
        path -- (str) path of the file to be played 
        limit -- (int/str) number of seconds before terminating the displacement 
        mux -- (bool) cause the original audio to be mixed, i.e. you can still converse with the other party while the file is playing 
        """
        if mux:
            apicmd = ' '.join(['uuid_displace', uuid, switch, path, limit, "mux"])
        else:
            apicmd = ' '.join(['uuid_displace', uuid, switch, path, limit, ])

        return self.sendAPI(apicmd, background)

    def apiUUIDExists(self, uuid, background=jobType):
        """Check if a given uuid exists 
        
        uuid -- (str) uuid of the target channel
        """
        apicmd = ' '.join(['uuid_exists', uuid])
        return self.sendAPI(apicmd, background)

    def apiUUIDFlushDTMF(self, uuid, background=jobType):
        """Flush queued DTMF digits 
        
        uuid -- (str) uuid of the target channel"""
        apicmd = ' '.join(["uuid_flush_dtmf", uuid])
        return self.sendAPI(apicmd, background)

    def apiUUIDHold(self, uuid, off=False, background=jobType):
        """Place a call on hold
        
        uuid -- (str) uuid of the target channel
        off -- (bool) turn on or turn off hold 
        """
        if off:
            apicmd = ' '.join(['uuid_hold', 'off', uuid])
        else:
            apicmd = ' '.join(['uuid_hold', uuid])
        return self.sendAPI(apicmd, background)

    def apiUUIDKill(self, uuid, cause='', background=jobType):
        """Kill a given channel
        
        uuid -- (str) uuid of the target channel
        cause -- (str) hangup reason"""
        if cause:
            apicmd = ' '.join(['uuid_kill', uuid, cause])
        else:
            apicmd = ' '.join(['uuid_kill', uuid])
        return self.sendAPI(apicmd, background)

    def apiUUIDMedia(self, uuid, off=False, background=jobType):
        """Reinvite a channel bridging media 
        
        uuid -- (str) uuid of the target channel
        off -- (bool) 
        """
        if off:
            apicmd = ' '.join(['uuid_media', 'off', uuid])
        else:
            apicmd = ' '.join(['uuid_media', uuid])
        return self.sendAPI(apicmd, background)

    def apiUUIDPark(self, uuid, background=jobType):
        """Park a given channel
        
        uuid -- (str) uuid of the target channel
        """
        apicmd = ' '.join(['uuid_park', uuid])
        return self.sendAPI(apicmd, background)

    def apiUUIDRecord(self, uuid, start, path, limit=None, background=jobType):
        """Record channel to given path
        
        uuid--(str) uuid of the target channel
        start--(bool) start or stop recording
        path --(str) path of file to where channel should be recorded """
        if start:
            flag = 'start'
        else:
            flag = 'stop'
        apicmd = ' '.join(['uuid_record', uuid, flag, path])
        if limit:
            apicmd = ' '.join([apicmd, limit])
        return self.sendAPI(apicmd, background)

    def apiUUIDSendDTMF(self, uuid, dtmf, background=jobType):
        """Send dtmf to given channel 
        
        uuid -- (str) uuid of the target channel
        dtmf -- (str) DTMF data to be sent 
        """
        apicmd = ' '.join(['uuid_send_dtmf', uuid, dtmf])
        return self.sendAPI(apicmd, background)

    # dp tools for dp tools uuid is optional in outbound socket connection
    def answer(self, uuid='', lock=True):
        """Answer cahnnel
        
        uuid -- (str) uuid of target channel
        lock -- (bool) lock the channel until execution is finished 
        """
        return self.sendCommand('answer', '', uuid, lock)

    def avmd(self, start=True, uuid='', lock=True):
        """Start or stop avmd on current channel
        """
        if start:
            return self.sendCommand("avmd", '', uuid, lock)
        else:
            return self.sendCommand("avmd", "stop", uuid, lock)

    def hangup(self, uuid='', lock=True):
        """Hangup current channel
        """
        return self.sendCommand("hangup", '', uuid, lock)

    def bridge(self, endpoints=[], uuid='', lock=True):
        """Bridge and endpoint to given channel 
        
        endpoints -- (list) list of endpoint FreeSWITCH URIs
        """
        endpoints = ','.join(endpoints)
        return self.sendCommand("bridge", endpoints, uuid, lock)

    def flowBreak(self, clear_queue=False, uuid='', lock=True):
        """Break the current action that is being performed on call """
        if clear_queue:
            return self.sendCommand("break", "all", uuid, lock)
        return self.sendCommand("break", '', uuid, lock=True)

    def conference(self, confname, uuid='', lock=True):
        """Connect the channel to give conference
        
        confname -- (str) conference name
        """
        cmd = "conference"
        args = confname
        return self.sendCommand(cmd, args, uuid, lock)

    def endlessPlayback(self, path, uuid='', lock=True):
        """
        Play a file endlessly
        """
        return self.sendCommand("endless_playback", path, uuid, lock)

    def playback(self, path, terminators=None, uuid='', lock=True):
        """Playback given file name on channel
        
        path -- (str) path of the file to be played '"""

        self.set("playback_terminators", terminators or "none", uuid, lock)
        return self.sendCommand("playback", path, uuid, lock)

    def playbackSync(self, *args, **kwargs):
        finalDF = defer.Deferred()
        df = self.playback(*args, **kwargs)
        df.addCallback(self.playbackSyncSuccess, finalDF)
        df.addErrback(self.playbackSyncFailed, finalDF)
        return finalDF

    def playbackSyncSuccess(self, result, finalDF):
        ecb = self.registerEvent("CHANNEL_EXECUTE_COMPLETE", True, self.playbackSyncComplete, finalDF)
        finalDF.ecb = ecb

    def playbackSyncFailed(self, error, finalDF):
        finalDF.errback(error)

    def playbackSyncComplete(self, event, finalDF):
        if event['Application'] == 'playback':
            self.deregisterEvent(finalDF.ecb)
            finalDF.callback(event)

    def say(self, module='en', say_type='NUMBER', say_method="PRONOUNCED", text='', uuid='', lock=True):
        arglist = [module, say_type, say_method, text]
        arglist = map(str, arglist)
        data = ' '.join(arglist)
        return self.sendCommand("say", data, uuid, lock)

    def set(self, variable, value, uuid='', lock=True):
        """Set a channel variable 
        
        variable -- (str) name of the channel variable
        value -- (str) value of the channel variable
        """
        args = '='.join([variable, value])
        return self.sendCommand("set", args, uuid, lock)

    def playAndGetDigits(self, min, max, tries=3, timeout=4000, terminators='#', filename='', invalidfile='',
                         varname='', regexp='\d', uuid='', lock=True):
        """Play the given sound file and get back caller's DTMF
        min -- (int) minimum digits length
        max -- (int) maximum digits length
        tires -- (int) number of times to play the audio file default is 3
        timeout -- (int) time to wait after fileblack in milliseconds . default is 4000
        filename -- (str) name of the audio file to be played 
        varname -- (str) DTMF digit value will be set as value to the variable of this name
        regexp -- (str) regurlar expression to match the DTMF 
        uuid -- (str) uuid of the target channel 
        
        Make sure CHANNEL_EXECUTE_COMPLETE  event is subcribed otherwise finalDF will never get invoked
        """
        arglist = [min, max, tries, timeout, terminators, filename, invalidfile, varname, regexp]
        arglist = map(str, arglist)

        # arglist = map(repr, arglist)
        data = ' '.join(arglist)

        finalDF = defer.Deferred()
        df = self.sendCommand("play_and_get_digits", data, uuid, lock)
        df.addCallback(self._playAndGetDigitsSuccess, finalDF, varname)
        df.addErrback(self._playAndGetDigitsFailure, finalDF)
        return finalDF

    def _playAndGetDigitsSuccess(self, msg, finalDF, varname):
        """Successfully executed playAndGetDigits. Register a callback to catch DTMF"""

        ecb = self.registerEvent("CHANNEL_EXECUTE_COMPLETE", True, self._checkPlaybackResult, finalDF, varname)
        finalDF.ecb = ecb

    def _playAndGetDigitsFailure(self, error, finalDF):
        """Failed to execute playAndGetDigits, invoke finalDF errback"""
        finalDF.errback(error)

    def _checkPlaybackResult(self, event, finalDF, varname):
        if event['Application'] == "play_and_get_digits":
            self.deregisterEvent(finalDF.ecb)
            if event.has_key("variable_" + varname):
                finalDF.callback(event['variable_' + varname])
            else:
                finalDF.callback(None)

    def schedHangup(self, secs, uuid='', lock=True):
        """Schedule hangup 
        
        seconds -- (int/str) seconds to wait before hangup 
        """
        args = "+" + str(secs)
        return self.sendCommand("sched_hangup", args, uuid, lock)

    def record(self, path, time_limit_secs=' ', silence_thresh=' ', silence_hits=' ', terminators='', uuid='',
               lock=True):
        terminators = terminators or 'none'
        self.set("playback_terminators", terminators)
        args = ' '.join([path, time_limit_secs, silence_thresh, silence_hits])
        return self.sendCommand("record", args, uuid, lock)

    def recordSession(self, filename, uuid='', lock=True):
        """Record entire session using record_session dialplan tool"""
        return self.sendCommand("record_session", filename, uuid, lock)

    def stopRecordSession(self, path, uuid='', lock=True):
        """Stop recording session """
        return self.sendCommand("stop_record_session", path, uuid, lock)

    # The following commands work on commercial mod_amd module
    def voice_start(self, uuid='', lock=True):
        """Start AMD on current channel"""
        return self.sendCommand("voice_start", uuid=uuid, lock=lock)

    def voice_stop(self, uuid='', lock=True):
        """Stop AMD on current channel"""
        return self.sendCommand("voice_stop", uuid=uuid, lock=lock)
