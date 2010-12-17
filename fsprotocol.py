#!/usr/bin/python

from twisted.protocols import basic
from twisted.internet import reactor, defer, protocol
import urllib
import logging
import sys

if sys.hexversion < 0x020500f0:
    from email.Message import Message
    from email.FeedParser import FeedParser
else:
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
    def decodeMessage(self):
        """Rebuild the event headers with with URL format decoded values"""
        for k,v in self.items():
            del self[k]
            self[k] = urllib.unquote(v)
            
        
class EventCallback:
    def __init__(self, eventname, func, *args, **kwargs):
        self.func = func
        self.eventname = eventname
        self.args = args
        self.kwargs = kwargs        
        
class FSProtocol(basic.LineReceiver):
    """FreeSWITCH EventSocket protocol implementation.
    
    All the FreeSWITCH api and dptool commands are defined in this class
    """
    delimiter="\n\n"
    jobType = False
    state = "READ_CONTENT"
    def __init__(self, *arg, **kwargs):
        """Initialize FSProtocol arguments are ignored"""
        #basic.LineOnlyReceiver.__init__(self)
        self.contentCallbacks = {"auth/request":self.auth, 
                        "api/response":self.onAPIReply, 
                        "command/reply":self.onCommandReply, 
                        "text/event-plain":self.onEvent, 
                        "text/disconnect-notice":self.disconnectNotice
                        }
        self.pendingJobs = []   
        self.pendingBackgoundJobs = {}        
        self.eventCallbacks = []
        
    
    def registerEvent(self, event,function, *args, **kwargs):
        """Register a callback for the event 
        event -- Event name as sent by FreeSWITCH
        function -- callback function accepts a event dictionary as first argument
        args -- argumnet to be passed to callback function
        kwargs -- keyword arguments to be passed to callback function
        
        returns instance of  EventCallback , keep a reference of this around if you want to deregister it later
        """       
        ecb = EventCallback(event, function, *args, **kwargs)
        self.eventCallbacks.append(ecb)        
        return ecb
        
    def deregisterEvent(self,ecb):
        """Deregister a callback for the given event
        
        ecb -- (EventCallback) instance of EventCallback object
        """
        try:
            self.eventCallbacks.remove(ecb)
        except ValueError:
            log.error("%s already deregistered "%ecb)
        
    def connectionMade(self):
        log.info("Connected to FreeSWITCH")
        
    def lineReceived(self, line):
        log.debug("Line In: %s"%line)        
        self.parser = FeedParser(Event)
        """"line = line.split("\n")
        for l in line:            
            k, v = l.split(":", 1)                
            self.message[k]=v.strip()"""
        self.parser.feed(line)
        self.message = self.parser.close()
        self.inspectMessage()   
        
    def rawDataReceived(self, data):
        log.debug("Data In : %s"%data)
        self.rawdataCache = ''.join([self.rawdataCache, data])
        if len(self.rawdataCache) >= self.contentLength-1:
            self.clearLineBuffer()       
            extra = self.rawdataCache[self.contentLength:]
            self.setLineMode(extra)
            currentResult = self.rawdataCache[:self.contentLength]
            self.message.set_payload(currentResult)
            try:
                self.currentDeferred.callback(self.message)
            except Exception, err:
                log.error(err)
            
    def inspectMessage(self):
        if self.state == "READ_EVENT":
            return self.dispacthEvent()
        if self.state == "READ_CHANNELINFO":
            return self.onConnect()
        if not self.message.has_key("Content-Type"):
            return
        ct = self.message['Content-Type']
        try:
            cb = self.contentCallbacks[ct]
            cb()
        except KeyError:
            log.error("Got unimplemented Content-Type : %s"%ct)
            
            
    def dispacthEvent(self):
        self.state = "READ_CONTENT"
        eventname = self.message['Event-Name']
        
        for ecb in self.eventCallbacks: 
            if ecb.eventname != eventname:
                continue
            try:
                ecb.func(self.message, *ecb.args, **ecb.kwargs)                
            except Exception,  err:
                log.error("Error in event handler %s on event %s: %s"%(ecb.func, eventname, err))
    
    def onConnect(self):
        """Channel Information is ready to be read.
        """
        log.info("onconnect")
            
        
    def auth(self):
        """
        FreeSWITCH is requesting to authenticate         
        """
        pass
        
    def onAPIReply(self):
        """
        Handle API reply 
        """
        self.currentDeferred = self.pendingJobs.pop()
        if not self.message.has_key("Content-Length"):            
            return self.currentDeferred.callback(self.message)
            
        self.contentLength = int(self.message['Content-Length'])
        if self.contentLength > 0:
            log.debug("Entering raw mode to read API response")            
            self.rawdataCache =''
            self.setRawMode()
        else:
            self.currentDeferred.callback(self.message)       
            
        
    def onCommandReply(self):
        """
        Handle CommandReply        
        """
        df = self.pendingJobs.pop()
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
        if self.contentLength>0:
            self.currentDeferred = defer.Deferred()
            log.info("Enter raw mode to read disconnect notice")
            self.rawdataCache = ''
            self.setRawMode()
        else:
            self.disconnectNoticeReceived(self.message)
       
    def disconnectNoticeReceived(self, msg):
        """Override this to receive disconnect notice from freeswitch"""
        log.error("disconnectNoticeReceived not implemented")
        log.info(msg)
        
    def sendData(self, cmd, args=''):
        df = defer.Deferred()
        #self.pendingJobs.append((cmd, df))
        self.pendingJobs.append(df)
        if args:
            cmd = ' '.join([cmd, args])           
        self.sendLine(cmd)
        log.debug("Line Out: %r"%cmd)
        return df
        
    def sendMsg(self, msg):
        """Send message to FreeSWITCH
        
        msg -- (event) Event object 
        
        """
        df = defer.Deferred()        
        self.pendingJobs.append(df)
        msg = msg.as_string(True)
        self.transport.write(msg)
        log.debug("Line Out: %r"%msg)
        return df
        
    def sendCommand(self, cmd, args='', uuid='', lock=True):
        msg = Event()
        if uuid:
            msg.set_unixfrom("SendMsg %s"%uuid)
        else:
            msg.set_unixfrom("SendMsg")
        msg['call-command']="execute"
        msg['execute-app-name']=cmd
        if args:
            msg['execute-app-arg']=args
        if lock:
            msg['event-lock'] = "true"
        return self.sendMsg(msg)        
        
    def sendAPI(self, apicmd, background=jobType):
        if background:            
            return self.sendBGAPI(apicmd)
        else:
            return self.sendData("api", apicmd)
        
    def sendBGAPI(self, apicmd):
        backgoundJobDeferred = defer.Deferred()
        df = self.sendData("bgapi", apicmd)        
        df.addCallback(self.onBackgroundJob, backgoundJobDeferred)
        return backgoundJobDeferred
        
    def onBackgroundJob(self, message, df):        
        self.pendingBackgoundJobs[message["Reply-Text"].split(":")[1].strip()] = df       
        self.registerEvent("BACKGROUND_JOB", self.onBackgroundJobFinalEvent)
        
    def onBackgroundJobFinalEvent(self, event):
        self.rawdataCache = ''
        self.currentDeferred = self.pendingBackgoundJobs.pop(event['Job-UUID'])
        self.contentLength = int(event['Content-Length'].strip())
        if self.contentLength > 0:
            log.debug("Entering raw mode to read the background job result")
            self.setRawMode()
        else:
            self.currentDeferred.callback(None)
        
    def subscribeEvents(self, events):
        """Subcribe to FreeSWITCH events.
        events - 'all'  sucbscribe to all events """        
        
        return self.sendData("event", events)
        
    def myevents(self, uuid=''):
        """Tie up the connection to particular channel events"""
        if uuid:
            return self.sendData("myevents %s"%uuid)
        else:
            return self.sendData("myevents")
        
    def apiDomainExists(self, domain, background=jobType):
        cmd = "domain_exists %s"%domain
        return self.sendAPI(cmd, background)
        
    def apiGlobalGetVar(self,variable='', background=jobType):
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
            df.addCallback(self._parseGlobalGetVar,finalDF)        
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
        apicmd = ' '.join(["reload",  module_name])
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
        
    #Call management
    def apiOriginate(self, url, application='',appargs='', extension='',dialplan='', context='', cidname='', cidnum='', timeout='', channelvars={},background=jobType):
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
                vars = "{"+vars+"}"
                url = vars+url
        apicmd = ' '.join([apicmd, url])
        
        if application:
            application = "&"+application
            if appargs:
                appargs = "("+appargs+")"
                application = ''.join([application, appargs])
                apicmd = ' '.join([apicmd, application])
            else:
                apicmd = ' '.join([apicmd, application])       
        else:
            apicmd = ' '.join([apicmd, extension])
        apicmd = ' ' .join([apicmd, dialplan, context, cidname, cidnum, timeout])
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
        apicmd=' '.join(['uuid_chat', uuid, msg])
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
            apicmd = ' '.join(['uuid_displace', switch, path, limit, "mux"])
        else:
            apicmd = ' '.join(['uuid_displace', switch, path, limit,])            
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
            apicmd = ' '.join(['uuid_media',uuid])
        return self.sendAPI(apicmd, background)
        
    def apiUUIDPark(self, uuid, background=jobType):
        """Park a given channel
        
        uuid -- (str) uuid of the target channel
        """
        apicmd = ' '.join(['uuid_park', uuid])
        return self.sendAPI(apicmd, background)
        
    def apiUUIDSendDTMF(self, uuid, dtmf, background=jobType):
        """Send dtmf to given channel 
        
        uuid -- (str) uuid of the target channel
        dtmf -- (str) DTMF data to be sent 
        """
        apicmd = ' '.join(['uuid_send_dtmf', uuid, dtmf])
        return self.sendAPI(apicmd, background)
        
    #dp tools for dp tools uuid is optional in outbound socket connection
    def answer(self, uuid='', lock=True):
        """Answer cahnnel
        
        uuid -- (str) uuid of target channel
        lock -- (bool) lock the channel until execution is finished 
        """
        return self.sendCommand('answer', '', uuid, lock)
        
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
        
    def playback(self, path, terminators=None, uuid='', lock=True):
        """Playback given file name on channel
        
        path -- (str) path of the file to be played '"""
        
        self.set("playback_terminators", terminators or "none", uuid, lock)
        return self.sendCommand("playback", path, uuid, lock)
        
    def say(self, module='en', say_type='NUMBER', say_method="PRONOUNCED", text='', uuid='', lock=True):
        arglist = [module, say_type, say_method, text]
        arglist = map(str, arglist)
        data = ' '.join(arglist)
        return self.sendCommand("say", data,uuid, lock)
        
    def set(self, variable, value, uuid='', lock=True):
        """Set a channel variable 
        
        variable -- (str) name of the channel variable
        value -- (str) value of the channel variable
        """
        args = '='.join([variable, value])
        return self.sendCommand("set", args, uuid, lock)
        
    def playAndGetDigits(self, min, max, tries=3, timeout=4000,  terminators='#', filename='',invalidfile=' ', varname='',regexp='\d',uuid='',lock=True):
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
        #arglist = map(repr, arglist)
        data = ' '.join(arglist)
        finalDF = defer.Deferred()        
        df = self.sendCommand("play_and_get_digits",  data, uuid, lock)
        df.addCallback(self._playAndGetDigitsSuccess, finalDF, varname)
        df.addErrback(self._playAndGetDigitsFailure, finalDF)
        return finalDF
        
        
    def _playAndGetDigitsSuccess(self, msg, finalDF, varname):
        """Successfully executed playAndGetDigits. Register a callback to catch DTMF"""

        ecb = self.registerEvent("CHANNEL_EXECUTE_COMPLETE", self._checkPlaybackResult, finalDF, varname)        
        finalDF.ecb = ecb
        
    def _playAndGetDigitsFailure(self, error, finalDF):
        """Failed to execute playAndGetDigits, invoke finalDF errback"""
        finalDF.errback(error)
        
    def _checkPlaybackResult(self, event, finalDF, varname):        
        if event['Application'] == "play_and_get_digits":
            self.deregisterEvent(finalDF.ecb)
            if event.has_key("variable_"+varname):
                finalDF.callback(event['variable_'+varname])                
            else:
                finalDF.callback(None)

    def sched_hangup(self, secs, uuid, lock=True):
        """Schedule hangup 
        
        seconds -- (int/str) seconds to wait before hangup 
        """
        args = "+"+str(secs)
        return self.sendCommand("sched_hangup", args, uuid, lock)

        
                
            

