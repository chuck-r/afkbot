#!/usr/bin/env python

#Copyright (c) 2013-2015 Chuck-R <github@chuck.cloud>
#
#    Copyright (c) 2013-2015, Chuck-R <github@chuck.cloud>
#    All rights reserved.
#
#    Redistribution and use in source and binary forms, with or without
#    modification, are permitted provided that the following conditions are met:
#    * Redistributions of source code must retain the above copyright
#      notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright
#      notice, this list of conditions and the following disclaimer in the
#      documentation and/or other materials provided with the distribution.
#    * Neither the name of AFKBot nor the
#      names of its contributors may be used to endorse or promote products
#      derived from this software without specific prior written permission.
#
#    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
#    ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
#    WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#    DISCLAIMED. IN NO EVENT SHALL AFKBOT'S CONTRIBUTORS BE LIABLE FOR ANY
#    DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
#    (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
#    LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
#    ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#    (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#    SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

#Contains code from mumblebee
#Copyright (c) 2013, Toshiaki Hatano <haeena@haeena.net>
#
#Contains code from the eve-bot
#Copyright (c) 2009, Philip Cass <frymaster@127001.org>
#Copyright (c) 2009, Alan Ainsworth <fruitbat@127001.org>
#
#Contains code from the Mumble Project:
#Copyright (C) 2005-2009, Thorvald Natvig <thorvald@natvig.com>
#
#All rights reserved.
#
#Redistribution and use in source and binary forms, with or without
#modification, are permitted provided that the following conditions
#are met:
#
#- Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#- Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#- Neither the name of localhost, 127001.org, eve-bot nor the names of its
# contributors may be used to endorse or promote products derived from this
# software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE FOUNDATION OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import socket
import time
import struct
import sys
import select
import thread
import threading
import signal
import os
import optparse
import platform
import random
#import daemon
import ConfigParser

import pdb
from pprint import pprint
#The next 2 imports may not succeed
warning=""
try:
    import ssl
except:
    warning+="WARNING: This python program requires the python ssl module (available in python 2.6; standalone version may be at found http://pypi.python.org/pypi/ssl/)\n"
try:
    import Mumble_pb2
except:
    warning+="WARNING: Module Mumble_pb2 not found\n"
    warning+="This program requires the Google Protobuffers library (http://code.google.com/apis/protocolbuffers/) to be installed\n"
    warning+="You must run the protobuf compiler \"protoc\" on the Mumble.proto file to generate the Mumble_pb2 file\n"
    warning+="Move the Mumble.proto file from the mumble source code into the same directory as this bot and type \"protoc --python_out=. Mumble.proto\"\n"

headerFormat=">HI"
eavesdropper=None
messageLookupMessage={Mumble_pb2.Version:0,Mumble_pb2.UDPTunnel:1,Mumble_pb2.Authenticate:2,Mumble_pb2.Ping:3,Mumble_pb2.Reject:4,Mumble_pb2.ServerSync:5,
        Mumble_pb2.ChannelRemove:6,Mumble_pb2.ChannelState:7,Mumble_pb2.UserRemove:8,Mumble_pb2.UserState:9,Mumble_pb2.BanList:10,Mumble_pb2.TextMessage:11,Mumble_pb2.PermissionDenied:12,
        Mumble_pb2.ACL:13,Mumble_pb2.QueryUsers:14,Mumble_pb2.CryptSetup:15,Mumble_pb2.ContextActionModify:16,Mumble_pb2.ContextAction:17,Mumble_pb2.UserList:18,Mumble_pb2.VoiceTarget:19,
        Mumble_pb2.PermissionQuery:20,Mumble_pb2.CodecVersion:21,Mumble_pb2.UserStats:22,Mumble_pb2.RequestBlob:23,Mumble_pb2.ServerConfig:24,Mumble_pb2.SuggestConfig:25}
messageLookupNumber={}
threadNumber=0

for i in messageLookupMessage.keys():
        messageLookupNumber[messageLookupMessage[i]]=i

class Logger(object):
    def __init__(self, filename="Default.log"):
        self.terminal = sys.stdout
        self.log = open(filename, "a")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

sys.stdout = Logger("mumblebot.log")
sys.stderr = sys.stdout

def discontinue_processing(signl, frme):
    global eavesdropper
    print time.strftime("%a, %d %b %Y %H:%M:%S +0000"), "Received shutdown notice"
    if signl == signal.SIGUSR1:
        pbMess = Mumble_pb2.TextMessage()
        pbMess.actor = eavesdropper.session
        for channel_id in eavesdropper.channelList:
            pbMess.channel_id.append(channel_id)
        pbMess.message = "Server rebooting!"
        eavesdropper.sendTotally(eavesdropper.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString()))
    if eavesdropper:
        eavesdropper.wrapUpThread()
    else:
        sys.exit(0)

signal.signal( signal.SIGINT, discontinue_processing )
#signal.signal( signal.SIGQUIT, discontinue_processing )
signal.signal( signal.SIGTERM, discontinue_processing )
signal.signal( signal.SIGUSR1, discontinue_processing )

class timedWatcher(threading.Thread):
    def __init__(self,socketLock,socket):
        global threadNumber
        threading.Thread.__init__(self)
        self.pingTotal=1
        self.isRunning=True
        self.socketLock=socketLock
        self.socket=socket
        i = threadNumber
        threadNumber+=1
        self.threadName="Thread " + str(i)

    def stopRunning(self):
        self.isRunning=False

    def run(self):
        self.nextPing=time.time()-1

        while self.isRunning:
            t=time.time()
            if t>self.nextPing:
                pbMess = Mumble_pb2.Ping()
                pbMess.timestamp=(self.pingTotal*5000000)
                pbMess.good=0
                pbMess.late=0
                pbMess.lost=0
                pbMess.resync=0
                pbMess.udp_packets=0
                pbMess.tcp_packets=self.pingTotal
                pbMess.udp_ping_avg=0
                pbMess.udp_ping_var=0.0
                pbMess.tcp_ping_avg=50
                pbMess.tcp_ping_var=50
                self.pingTotal+=1
                packet=struct.pack(headerFormat,3,pbMess.ByteSize())+pbMess.SerializeToString()
                self.socketLock.acquire()
                while len(packet)>0:
                    sent=self.socket.send(packet)
                    packet = packet[sent:]
                self.socketLock.release()
                self.nextPing=t+10
            #sleeptime=self.nextPing-t
            #if sleeptime > 0:
            time.sleep(0.5)
        print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),self.threadName,"timed thread going away"

class mumbleConnection(threading.Thread):
    def __init__(self,host=None,nickname=None,channel=None,delay=None,limit=None,password=None,verbose=False):
        global threadNumber
        i = threadNumber
        threadNumber+=1
        self.threadName="Thread " + str(i)
        threading.Thread.__init__(self)
        tcpSock=socket.socket(type=socket.SOCK_STREAM)
        self.socketLock=thread.allocate_lock()
        self.socket=ssl.wrap_socket(tcpSock,certfile="afkbot.pem",ssl_version=ssl.PROTOCOL_TLSv1)
        self.socket.setsockopt(socket.SOL_TCP,socket.TCP_NODELAY,1)
        self.host=host
        self.nickname=nickname
        self.channel=channel
        self.inChannel=False
        self.session=None
        self.channelId=None
        self.userList={}
        self.userListByName={}
        self.channelList={}
        self.channelListByName={}
        self.readyToClose=False
        self.timedWatcher = None
        # TODO: Implement delay and rate limit
        self.delay=delay
        self.limit=limit
        self.password=password
        self.verbose=verbose

	#######################################
	# AFKBot-specific config
	#######################################
        self.idleLimit=30 #Idle limit in minutes
        
    def decodePDSInt(self,m,si=0):
        v = ord(m[si])
        if ((v & 0x80) == 0x00):
            return ((v & 0x7F),1)
        elif ((v & 0xC0) == 0x80):
            return ((v & 0x4F) << 8 | ord(m[si+1]),2)
        elif ((v & 0xF0) == 0xF0):
            if ((v & 0xFC) == 0xF0):
                return (ord(m[si+1]) << 24 | ord(m[si+2]) << 16 | ord(m[si+3]) << 8 | ord(m[si+4]),5)
            elif ((v & 0xFC) == 0xF4):
                return (ord(m[si+1]) << 56 | ord(m[si+2]) << 48 | ord(m[si+3]) << 40 | ord(m[si+4]) << 32 | ord(m[si+5]) << 24 | ord(m[si+6]) << 16 | ord(m[si+7]) << 8 | ord(m[si+8]),9)
            elif ((v & 0xFC) == 0xF8):
                result,length=decodePDSInt(m,si+1)
                return(-result,length+1)
            elif ((v & 0xFC) == 0xFC):
                return (-(v & 0x03),1)
            else:
                print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),"Help Help, out of cheese :("
                sys.exit(1)
        elif ((v & 0xF0) == 0xE0):
            return ((v & 0x0F) << 24 | ord(m[si+1]) << 16 | ord(m[si+2]) << 8 | ord(m[si+3]),4)
        elif ((v & 0xE0) == 0xC0):
            return ((v & 0x1F) << 16 | ord(m[si+1]) << 8 | ord(m[si+2]),3)
        else:
            print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),"out of cheese?"
            sys.exit(1)
    
    def packageMessageForSending(self,msgType,stringMessage):
        length=len(stringMessage)
        return struct.pack(headerFormat,msgType,length)+stringMessage
    
    def sendTotally(self,message):
        self.socketLock.acquire()
        while len(message)>0:
            sent=self.socket.send(message)
            if sent < 0:
                print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),self.threadName,"Server socket error while trying to write, immediate abort"
                self.socketLock.release()
                return False
            message=message[sent:]
        self.socketLock.release()
        return True

    def readTotally(self,size):
        message=""
        while len(message)<size:
            received=self.socket.recv(size-len(message))
            message+=received
            if len(received)==0:
                print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),self.threadName,"Server socket died while trying to read, immediate abort"
                return None
        return message
    
    def parseMessage(self,msgType,stringMessage):
        msgClass=messageLookupNumber[msgType]
        message=msgClass()
        message.ParseFromString(stringMessage)
        return message
    
    def joinChannel(self):
        if self.channelId!=None and self.session!=None:
            pbMess = Mumble_pb2.UserState()
            pbMess.session=self.session
            pbMess.channel_id=self.channelId
            if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                self.wrapUpThread()
                return
            self.inChannel=True

    def wrapUpThread(self):
        #called after thread is confirmed to be needing to die because of kick / socket close
        self.readyToClose=True
    
    def readPacket(self):
        #pdb.set_trace()
        meta=self.readTotally(6)
        if not meta:
            self.wrapUpThread()
            return
        msgType,length=struct.unpack(headerFormat,meta)
        stringMessage=self.readTotally(length)
        if not stringMessage:
            self.wrapUpThread()
            return
        #Type 1 = UDP Tunnel, voice data
        if msgType==1:
            session,sessLen=self.decodePDSInt(stringMessage,1)
            if session in self.userList and self.userList[session]["channel"] == self.channelListByName["AFK"]:
                if "idlesecs" in self.userList[session] and "oldchannel" in self.userList[session]["idlesecs"]:
                    pbMess = Mumble_pb2.UserState()
                    pbMess.session = session
                    pbMess.actor = self.session
                    pbMess.channel_id = self.userList[session]["idlesecs"]["oldchannel"]
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                         self.wrapUpThread()
        #Type 5 = ServerSync
        if (not self.session) and msgType==5 and (not self.inChannel):
            message=self.parseMessage(msgType,stringMessage)
            self.session=message.session
            self.joinChannel()
        #Type 6 = ChannelRemove
        if msgType == 6:
            message=self.parseMessage(msgType,stringMessage)
            channelid=message.channel_id
            for item in self.channelListByName:
                if self.channelListByName[item] == message.channel_id:
                    del self.channelListByName[item]
                    break
            for item in self.userList:
                if "idlesecs" in self.userList[item] and "oldchannel" in self.userList[item]["idlesecs"]:
                    if self.userList[item]["idlesecs"]["oldchannel"] == channelid:
                        self.userList[item]["idlesecs"]["oldchannel"] = 0;
        #Type 7 = ChannelState
        if msgType == 7: #(not self.inChannel) and msgType==7 and self.channelId==None:
            message=self.parseMessage(msgType,stringMessage)
            if message.channel_id not in self.channelList or self.channelList[message.channel_id] != message.name:
                self.channelList[message.channel_id]=message.name
                self.channelListByName[message.name]=message.channel_id
            if (not self.inChannel) and self.channelId==None:
                if self.channel==None and message.channel_id==0:
                    self.channel=message.name
                    self.channelId=message.channel_id
                    self.joinChannel()
                if message.name==self.channel:
                    self.channelId=message.channel_id
                    self.joinChannel()
        #Type 8 = UserRemove (kick)
        if msgType==8:
            message=self.parseMessage(msgType,stringMessage)
            if self.session!=None:
                if message.session==self.session:
                    print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),self.threadName,"********* KICKED ***********"
                    self.wrapUpThread()
                    return
            session=message.session
            if session in self.userList:
                temp = self.userList[session]
                del self.userListByName[self.userList[session]["name"]]
                del self.userList[session]
        #Type 9 = UserState
        if msgType==9:
            message=self.parseMessage(msgType,stringMessage)
            session=message.session
            if session in self.userList:
                record=self.userList[session]
            else:
                record={"session":session}
                self.userList[session]=record
            name=None
            channel=None
            if message.HasField("name"):
                name=message.name
                if "name" in record and record["name"] in self.userListByName:
                    del self.userListByName[record["name"]]
                record["name"]=name
                self.userListByName[name]=message.session
            if message.HasField("channel_id"):
                channel=message.channel_id
                record["channel"]=channel
            if name and not channel:
                record["channel"]=0
            channelName = self.channelList[record["channel"]]
            #If they're not already in the AFK channel
            if message.channel_id != self.channelListByName["AFK"]:
                #Send a query for UserStats -- needed to get idletime
                if "idlesecs" in record:
                    record["idlesecs"]["checksent"] = True
                    record["idlesecs"]["oldchannel"] = message.channel_id
                else:
                    record["idlesecs"]={"checksent":True,"oldchannel":message.channel_id}
                if message.HasField("actor"): # and message.actor != self.session:
                    record["idlesecs"]["checksent"] = False
                    record["idlesecs"]["checkon"] = time.time()+self.idleLimit*60
                else:
                    pbMess = Mumble_pb2.UserStats()
                    pbMess.session = session
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                        self.wrapUpThread()
            else:
                if "idlesecs" in record:
                    record["idlesecs"]["checksent"] = False
                    record["idlesecs"]["checkon"] = -1
#                    if "oldchannel" not in record["idlesecs"]:
##                        record["idlesecs"]["oldchannel"] = 0
#                    else:
#                        record["idlesecs"]["oldchannel"] = message.channel_id
                else:
                    record["idlesecs"]={"checksent":False,"checkon":-1,"oldchannel":0}
            if self.inChannel and channelName == "Private Chats":
                pbMess = Mumble_pb2.TextMessage();
                pbMess.actor = self.session;
                pbMess.session.append(message.session);
                pbMess.message = "This is the Private Chats channel. To create a sub-channel, right click Private Chats and select 'Add'. Name your channel and check the 'Temporary' checkbox.";
                if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                    self.wrapUpThread()
            if self.inChannel and channelName in ("Castle Wars","Zamorak","Saradomin"):
                #Package a message to the user
                pbMess = Mumble_pb2.TextMessage();
                pbMess.actor = self.session;
                pbMess.session.append(message.session);
                pbMess.message = "Welcome to the Castle Wars channels! In this channel setup you can set up a hotkey for Shout with a target of the parent channel to send messages to the opposing team.";
                if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                    self.wrapUpThread()
            return

        #Type 11 = TextMessage
        if msgType==11:
            message=self.parseMessage(msgType,stringMessage)
            if message.actor!=self.session:
                if message.message.startswith("/roll"):
                    pbMess = Mumble_pb2.TextMessage()
                    pbMess.actor = self.session
                    pbMess.channel_id.append(self.channelId)
                    pbMess.channel_id.append(self.userList[message.actor]["channel"])
                    pbMess.message = self.userList[message.actor]["name"] + " rolled " + str(random.randint(0,100))
                    pbMess.session.append(self.session)
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                        self.wrapUpThread()
                    return
                if message.message.startswith("/afkme"):
                    pbMess = Mumble_pb2.UserState()
                    pbMess.session = message.actor
                    pbMess.actor = self.session
                    pbMess.channel_id = self.channelListByName["AFK"]
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                        self.wrapUpThread()
                    self.userList[message.actor]["idlesecs"]["checkon"] = -1
                    return
                if message.message.startswith("/afk"):
                    args = message.message.split(" ",1)
                    pbMess = Mumble_pb2.UserState()
                    for key in self.userListByName:
                        if key.lower() == args[1].lower():
                            pbMess.session = self.userListByName[key]
                    print pbMess.session;
                    if pbMess.session == 0:
                        pbMess = Mumble_pb2.TextMessage();
                        pbMess.actor = self.session;
                        pbMess.session.append(message.actor);
                        pbMess.message = "No such user to AFK";
                        if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                            self.wrapUpThread()
                        return
                    pbMess.actor = self.session
                    pbMess.channel_id = self.channelListByName["AFK"]
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                        self.wrapUpThread()
                    self.userList[pbMess.session]["idlesecs"]["checkon"] = -1
                    return
                if message.message.startswith("/unafk"):
                    args = message.message.split(" ",1)
                    pbMess = Mumble_pb2.UserState()
                    for key in self.userListByName:
                        if key.lower() == args[1].lower():
                            pbMess.session = self.userListByName[key]
                            pbMess.channel_id = self.userList[pbMess.session]["idlesecs"]["oldchannel"]
                    if pbMess.session == 0:
                        pbMess = Mumble_pb2.TextMessage();
                        pbMess.actor = self.session;
                        pbMess.session.append(message.actor);
                        pbMess.message = "No such user to UnAFK";
                        if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                            self.wrapUpThread()
                        return
                    pbMess.actor = self.session
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                        self.wrapUpThread()
                    self.userList[pbMess.session]["idlesecs"]["checkon"] = -1

        #Type 12 = PermissionDenied
        if msgType==12:
            print "Permission Denied."
            return
            
        #Type 22 = UserStats
        if msgType==22:
            message=self.parseMessage(msgType,stringMessage)
            self.userList[message.session]["idlesecs"]["idlesecs"] = message.idlesecs
            self.userList[message.session]["idlesecs"]["checkon"] = time.time()+((self.idleLimit*60)-message.idlesecs)
            if message.idlesecs > self.idleLimit*60 and message.session != self.session:
                #self.userList[message.session]["idlesecs"]["oldchannel"] = self.userList[message.session]["channel"]
                #Move user to AFK channel
                pbMess = Mumble_pb2.UserState()
                pbMess.session = message.session
                pbMess.actor = self.session
                pbMess.channel_id = self.channelListByName["AFK"];
                if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                    self.wrapUpThread()
                self.userList[message.session]["idlesecs"]["checkon"] = -1
            self.userList[message.session]["idlesecs"]["checksent"] = False
            return
        
    
    def run(self):
        try:
            self.socket.connect(self.host)
        except Exception as inst:
            print type(inst)
            print inst
            print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),self.threadName,"Couldn't connect to server"
            return
        self.socket.setblocking(False)
        print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),self.threadName,"connected to server"
        pbMess = Mumble_pb2.Version()
        pbMess.release="1.2.8"
        pbMess.version=66052
        pbMess.os=platform.system()
        pbMess.os_version="AFKBot0.5.0"
        
        initialConnect=self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())
        
        pbMess = Mumble_pb2.Authenticate()
        pbMess.username=self.nickname
        if self.password!=None:
            pbMess.password=self.password
        celtversion=pbMess.celt_versions.append(-2147483637)
        
        initialConnect+=self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())
        
        if not self.sendTotally(initialConnect):
            return
        
        sockFD=self.socket.fileno()
        
        self.timedWatcher = timedWatcher(self.socketLock,self.socket)
        self.timedWatcher.start()
        print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),self.threadName,"started timed watcher",self.timedWatcher.threadName
        
        while True:
            pollList,foo,errList=select.select([sockFD],[],[sockFD],5)
            for item in pollList:
                if item==sockFD:
                    try:
                        self.readPacket()
                    except ssl.SSLError:
                        continue
            for session in self.userList:
                record = self.userList[session]
                if "idlesecs" in record:
                    if record["name"] != self.nickname and record["idlesecs"]["checksent"] == False and record["idlesecs"]["checkon"] > -1 and record["idlesecs"]["checkon"] < time.time():
                        pbMess = Mumble_pb2.UserStats();
                        pbMess.session = session
                        if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)],pbMess.SerializeToString())):
                            self.wrapUpThread()
                        record["idlesecs"]["checksent"] = True
            if self.readyToClose:
                self.wrapUpThread()
                break
        
        if self.timedWatcher:
            self.timedWatcher.stopRunning()
        
        self.socket.close()
        print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),self.threadName,"waiting for timed watcher to die..."
        if self.timedWatcher!=None:
            while self.timedWatcher.isAlive():
                pass
        print time.strftime("%a, %d %b %Y %H:%M:%S +0000"),self.threadName,"thread going away -",self.nickname

def main():
    global eavesdropper,warning
            
    p = optparse.OptionParser(description='Mumble 1.2 AFKBot',
                prog='mumblebee.py',
                version='%prog 0.0.1',
                usage='\t%prog')
    
    p.add_option("-e","--eavesdrop-in",help="Channel to eavesdrop in (default %%Root)",action="store",type="string",default="AFK")
    p.add_option("-s","--server",help="Host to connect to (default %default)",action="store",type="string",default="localhost")
    p.add_option("-p","--port",help="Port to connect to (default %default)",action="store",type="int",default=64738)
    p.add_option("-n","--nick",help="Nickname for the eavesdropper (default %default)",action="store",type="string",default="AFKBot2")
    p.add_option("-d","--delay",help="Time to delay response by in seconds (default %default)",action="store",type="float",default=0)
    p.add_option("-l","--limit",help="Maximum response per minutes (default %default, 0 = unlimited)",action="store",type="int",default=0)
    p.add_option("-c","--config",help="Configuration file",action="store",type="string",default="mumblebee.cfg")
    p.add_option("-v","--verbose",help="Outputs and translates all messages received from the server",action="store_true",default=False)
    p.add_option("--password",help="Password for server, if any",action="store",type="string")
    
    if len(warning)>0:
        print warning
    o, arguments = p.parse_args()
    if len(warning)>0:
        sys.exit(1)
    
    host=(o.server,o.port)

    #sys.stdout = open("mumblebot.log","w")
    #sys.stderr = sys.stdout

    #daemoninstance = daemon.DaemonContext()
    #daemoninstance.stdout = logfile;
    #daemoninstance.1
    
    eavesdropper = mumbleConnection(host,o.nick,o.eavesdrop_in,delay=o.delay,limit=o.limit,password=o.password,verbose=o.verbose)
    eavesdropper.start()
    
    #Need to keep main thread alive to receive shutdown signal
    
    while eavesdropper.isAlive():
        time.sleep(0.5)
        
    return 0

if __name__ == '__main__':
        main()
