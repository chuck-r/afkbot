#!/usr/bin/env python

# Copyright (c) 2013-2024 Chuck-R <github@chuck.cloud>
#
#    Copyright (c) 2013-2024, Chuck-R <github@chuck.cloud>
#    All rights reserved.
#
#    Redistribution and use in source and binary forms, with or without
#    modification, are permitted provided that the following conditions
#    are met:
#    * Redistributions of source code must retain the above copyright
#      notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright
#      notice, this list of conditions and the following disclaimer in the
#      documentation and/or other materials provided with the distribution.
#    * Neither the name of AFKBot nor the
#      names of its contributors may be used to endorse or promote products
#      derived from this software without specific prior written permission.
#
#    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
#    "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
#    TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
#    PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL AFKBOT'S CONTRIBUTORS BE LIABLE
#    FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
#    DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#    SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
#    CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
#    LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
#    OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
#    SUCH DAMAGE.

# Contains code from mumblebee
# Copyright (c) 2013, Toshiaki Hatano <haeena@haeena.net>
#
# Contains code from the eve-bot
# Copyright (c) 2009, Philip Cass <frymaster@127001.org>
# Copyright (c) 2009, Alan Ainsworth <fruitbat@127001.org>
#
# Contains code from the Mumble Project:
# Copyright (C) 2005-2009, Thorvald Natvig <thorvald@natvig.com>
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# - Redistributions of source code must retain the above copyright notice,
#  this list of conditions and the following disclaimer.
# - Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# - Neither the name of localhost, 127001.org, eve-bot nor the names of its
#  contributors may be used to endorse or promote products derived from this
#  software without specific prior written permission.

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

import datetime
import importlib.util
import optparse
import os
import platform
import random
import select
import signal
import socket
import stat
import struct
import sys
import _thread
import threading
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pathlib import Path

# The next 2 imports may not succeed
warning = ""
try:
    import ssl
    from ssl import SSLContext
except Exception:
    print("ERROR: This python program requires the python ssl module (available in python 2.6; standalone version may be at found http://pypi.python.org/pypi/ssl/)\n")
    print(warning)
    sys.exit(1)

if importlib.util.find_spec('google') is None or importlib.util.find_spec("google.protobuf") is None:
    print("ERROR: Google protobuf library not found. This can be installed via 'pip install protobuf'")
    sys.exit(1)

try:
    import Mumble_pb2
except Exception:
    print("Error: Module Mumble_pb2 not found\nIf the file 'Mumble_pb2.py' does not exist, then you must compile it with 'protoc --python_out=. Mumble.proto' from the script directory.")
    sys.exit(1)

afkbot_version = "0.5.4"

headerFormat = ">HI"
eavesdropper = None
controlbreak = False
messageLookupMessage = {
    Mumble_pb2.Version: 0,
    Mumble_pb2.UDPTunnel: 1,
    Mumble_pb2.Authenticate: 2,
    Mumble_pb2.Ping: 3,
    Mumble_pb2.Reject: 4,
    Mumble_pb2.ServerSync: 5,
    Mumble_pb2.ChannelRemove: 6,
    Mumble_pb2.ChannelState: 7,
    Mumble_pb2.UserRemove: 8,
    Mumble_pb2.UserState: 9,
    Mumble_pb2.BanList: 10,
    Mumble_pb2.TextMessage: 11,
    Mumble_pb2.PermissionDenied: 12,
    Mumble_pb2.ACL: 13,
    Mumble_pb2.QueryUsers: 14,
    Mumble_pb2.CryptSetup: 15,
    Mumble_pb2.ContextActionModify: 16,
    Mumble_pb2.ContextAction: 17,
    Mumble_pb2.UserList: 18,
    Mumble_pb2.VoiceTarget: 19,
    Mumble_pb2.PermissionQuery: 20,
    Mumble_pb2.CodecVersion: 21,
    Mumble_pb2.UserStats: 22,
    Mumble_pb2.RequestBlob: 23,
    Mumble_pb2.ServerConfig: 24,
    Mumble_pb2.SuggestConfig: 25,
    Mumble_pb2.PluginDataTransmission: 26
}
# Inversion of above
messageLookupNumber = {}

for i in messageLookupMessage.keys():
    messageLookupNumber[messageLookupMessage[i]] = i

threadNumber = 0


def discontinue_processing(signl, frme):
    global eavesdropper
    print("%s: Received shutdown notice." % (time.strftime("%a, %d %b %Y %H:%M:%S +0000"),))
    if signl == signal.SIGUSR1:
        pbMess = Mumble_pb2.TextMessage()
        pbMess.actor = eavesdropper.session
        for channel_id in eavesdropper.channelList:
            pbMess.channel_id.append(channel_id)
        pbMess.message = "Server rebooting!"
        eavesdropper.sendTotally(eavesdropper.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString()))
    if eavesdropper:
        eavesdropper.wrapUpThread()
    else:
        sys.exit(0)
    global controlbreak
    controlbreak = True


def GenerateCertificate(filename):
    print("Generating Certificate...", end=None)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    # No need to create p12 file, PEM is sufficient for ssl
    subject = issuer = x509.Name([
        x509.NameAttribute(x509.NameOID.COMMON_NAME, "AFKBot")
        ])
    now = datetime.datetime.now()
    cert = x509.CertificateBuilder().subject_name(subject)\
        .issuer_name(issuer)\
        .public_key(public_key)\
        .serial_number(x509.random_serial_number())\
        .not_valid_before(now)\
        .not_valid_after(now+datetime.timedelta(weeks=52*20))\
        .sign(private_key, hashes.SHA256())
    pem = cert.public_bytes(serialization.Encoding.PEM)
    key_contents = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
        )
    key_contents += pem
    # Certificate for AFKBot
    with open(filename, "wb") as file:
        try:
            file.write(key_contents)
        except Exception:
            raise ValueError("Could not write PEM certificate file")
    os.chmod(filename, stat.S_IREAD | stat.S_IWRITE)
    os.chmod(filename[:-4] + ".pem", stat.S_IREAD | stat.S_IWRITE)
    print("Done!")


class Logger(object):
    def __init__(self, filename="Default.log"):
        self.terminal = sys.stdout
        self.log = open(filename, "a")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()


class timedWatcher(threading.Thread):
    def __init__(self, socketLock, socket):
        global threadNumber
        threading.Thread.__init__(self)
        self.pingTotal = 1
        self.isRunning = True
        self.socketLock = socketLock
        self.socket = socket
        i = threadNumber
        threadNumber += 1
        self.threadName = "Thread " + str(i)

    def stopRunning(self):
        self.isRunning = False

    def run(self):
        self.nextPing = time.time()-1

        while self.isRunning:
            t = time.time()
            if t > self.nextPing:
                pbMess = Mumble_pb2.Ping()
                pbMess.timestamp = (self.pingTotal*5000000)
                pbMess.good = 0
                pbMess.late = 0
                pbMess.lost = 0
                pbMess.resync = 0
                pbMess.udp_packets = 0
                pbMess.tcp_packets = self.pingTotal
                pbMess.udp_ping_avg = 0
                pbMess.udp_ping_var = 0.0
                pbMess.tcp_ping_avg = 50
                pbMess.tcp_ping_var = 50
                self.pingTotal += 1
                packet = struct.pack(headerFormat, 3, pbMess.ByteSize()) + pbMess.SerializeToString()
                self.socketLock.acquire()
                while len(packet) > 0:
                    try:
                        sent = self.socket.send(packet)
                    except Exception:
                        sent = 0
                    packet = packet[sent:]
                self.socketLock.release()
                self.nextPing = t+10
            # sleeptime=self.nextPing-t
            # if sleeptime > 0:
            time.sleep(1)
        print("%s: timed thread going away" % (time.strftime("%a, %d %b %Y %H:%M:%S +0000"),))


class mumbleConnection(threading.Thread):
    def __init__(self, host=None, nickname=None, channel=None, delay=None, limit=None, 
                 password=None, verbose=False, certificate=None, idletime=30, allow_self_signed=0):
        global threadNumber
        i = threadNumber
        threadNumber += 1
        self.threadName = "Thread " + str(i)
        threading.Thread.__init__(self)
        tcpSock = socket.socket(type=socket.SOCK_STREAM)
        self.socketLock = _thread.allocate_lock()
        self.socket = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.socket.load_default_certs(purpose=ssl.Purpose.SERVER_AUTH)

        client_cert = None
        with open(certificate, "rb") as file:
            client_cert = file.read(-1)
        # load_cert_chain *has* to be a PEM file, for some reason.
        self.socket.load_cert_chain(certfile=certificate)
        if allow_self_signed:
            # Retrieve server cert to add to CA's
            if not os.path.exists("server.pem"):
                print("Downloading server certificate")
                server_cert = ssl.get_server_certificate(host, ssl.PROTOCOL_TLS_CLIENT)
                with open("server.pem", "wb") as file:
                    file.write(server_cert.encode())
            self.socket.load_verify_locations(cafile="server.pem")
            self.socket.check_hostname = False

        self.socket = self.socket.wrap_socket(tcpSock, server_hostname=host[0])
        # self.socket=ssl.wrap_socket(tcpSock,certfile=certificate,ssl_version=ssl.PROTOCOL_TLS_CLIENT)
        self.socket.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
        self.host = host
        self.nickname = nickname
        self.inChannel = False
        self.session = None
        self.channelId = None
        self.userList = {}
        self.userListByName = {}
        self.channelList = {}
        self.channelListByName = {}
        self.readyToClose = False
        self.timedWatcher = None
        # TODO: Implement delay and rate limit
        # self.delay=delay
        # self.limit=limit
        self.password = password
        self.verbose = verbose
        self.server_certificate = None

        #######################################
        # AFKBot-specific config
        #######################################
        self.idleLimit = idletime  # Idle limit in seconds
        self.channel = channel  # AFK channel to listen in

    def decodePDSInt(self, m, si=0):
        v = m[si]
        if ((v & 0x80) == 0x00):
            return ((v & 0x7F), 1)
        elif ((v & 0xC0) == 0x80):
            return ((v & 0x4F) << 8 | m[si+1], 2)
        elif ((v & 0xF0) == 0xF0):
            if ((v & 0xFC) == 0xF0):
                return (m[si+1] << 24 | m[si+2] << 16 | m[si+3] << 8 | m[si+4], 5)
            elif ((v & 0xFC) == 0xF4):
                return (m[si+1] << 56 | m[si+2] << 48 | m[si+3] << 40 | m[si+4] << 32 | m[si+5] << 24 | m[si+6] << 16 | m[si+7] << 8 | m[si+8], 9)
            elif ((v & 0xFC) == 0xF8):
                result, length = self.decodePDSInt(m, si+1)
                return (-result, length+1)
            elif ((v & 0xFC) == 0xFC):
                return (-(v & 0x03), 1)
            else:
                print("%s: Help help, out of cheese :(" % (time.strftime("%a, %d %b %Y %H:%M:%S +0000"),))
                sys.exit(1)
        elif ((v & 0xF0) == 0xE0):
            return ((v & 0x0F) << 24 | m[si+1] << 16 | m[si+2] << 8 | m[si+3], 4)
        elif ((v & 0xE0) == 0xC0):
            return ((v & 0x1F) << 16 | m[si+1] << 8 | m[si+2], 3)
        else:
            print("%s: out of cheese?" % (time.strftime("%a, %d %b %Y %H:%M:%S +0000"),))
            sys.exit(1)

    def packageMessageForSending(self, msgType, stringMessage):
        length = len(stringMessage)
        return struct.pack(headerFormat, msgType, length)+stringMessage

    def sendTotally(self, message):
        self.socketLock.acquire()
        while len(message) > 0:
            sent = self.socket.send(message)
            if sent < 0:
                print("[%s] %s: Server socket error while trying to write, immediate abort"
                      % (self.threadName, time.strftime("%a, %d %b %Y %H:%M:%S +0000"),))
                self.socketLock.release()
                return False
            message = message[sent:]
        self.socketLock.release()
        return True

    def readTotally(self, size):
        message = bytes()
        while len(message) < size:
            received = self.socket.recv(size-len(message))
            message += received
            if len(received) == 0:
                print("%s: Server socket died while trying to read, immediate abort" % (time.strftime("%a, %d %b %Y %H:%M:%S +0000"),))
                return None
        return message

    def parseMessage(self, msgType, stringMessage):
        msgClass = messageLookupNumber[msgType]
        message = msgClass()
        message.ParseFromString(stringMessage)
        return message

    def joinChannel(self):
        if self.channelId is not None and self.session is not None:
            pbMess = Mumble_pb2.UserState()
            pbMess.session = self.session
            pbMess.channel_id = self.channelId
            if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                self.wrapUpThread()
                return
            self.inChannel = True

    def wrapUpThread(self):
        # called after thread is confirmed to be needing to die because of kick / socket close
        self.readyToClose = True

    def readPacket(self):
        # pdb.set_trace()
        meta = self.readTotally(6)
        if not meta:
            self.wrapUpThread()
            return
        msgType, length = struct.unpack(headerFormat, meta)
        stringMessage = self.readTotally(length)
        if not stringMessage:
            # An empty payload isn't necessarily a panic condition. I've seen packets
            # such as CryptSetup with no payload
            return
        # Type 1 = UDP Tunnel, voice data or UDP ping
        if msgType == 1:
            # I'm not sure why the third byte is session ID, but it is.
            session, sessLen = self.decodePDSInt(stringMessage, 2)
            if session in self.userList and self.userList[session]["channel"] == self.channelListByName[self.channel]:
                if "idleinfo" in self.userList[session] and "oldchannel" in self.userList[session]["idleinfo"]:
                    pbMess = Mumble_pb2.UserState()
                    pbMess.session = session
                    pbMess.actor = self.session
                    pbMess.channel_id = self.userList[session]["idleinfo"]["oldchannel"]
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                        self.wrapUpThread()
        # Type 5 = ServerSync
        if (not self.session) and msgType == 5 and (not self.inChannel):
            message = self.parseMessage(msgType, stringMessage)
            self.session = message.session
            self.joinChannel()
        # Type 6 = ChannelRemove
        if msgType == 6:
            message = self.parseMessage(msgType, stringMessage)
            channelid = message.channel_id
            for item in self.channelListByName:
                if self.channelListByName[item] == message.channel_id:
                    del self.channelListByName[item]
                    break
            for item in self.userList:
                if "idleinfo" in self.userList[item] and "oldchannel" in self.userList[item]["idleinfo"]:
                    if self.userList[item]["idleinfo"]["oldchannel"] == channelid:
                        self.userList[item]["idleinfo"]["oldchannel"] = 0
        # Type 7 = ChannelState
        if msgType == 7:  # (not self.inChannel) and msgType==7 and self.channelId==None:
            message = self.parseMessage(msgType, stringMessage)
            if message.channel_id not in self.channelList or self.channelList[message.channel_id] != message.name:
                if not len(message.name):
                    return
                self.channelList[message.channel_id] = message.name
                self.channelListByName[message.name] = message.channel_id
            if (not self.inChannel) and self.channelId is None:
                if self.channel is None and message.channel_id == 0:
                    self.channel = message.name
                    self.channelId = message.channel_id
                    self.joinChannel()
                if message.name == self.channel:
                    self.channelId = message.channel_id
                    self.joinChannel()
        # Type 8 = UserRemove (kick/leave)
        if msgType == 8:
            message = self.parseMessage(msgType, stringMessage)
            if self.session is not None:
                if message.session == self.session:
                    print("[%s] %s: ********** KICKED **********" % (self.threadName, time.strftime("%a, %d %b %Y %H:%M:%S +0000"),))
                    self.wrapUpThread()
                    return
            session = message.session
            if session in self.userList:
                del self.userListByName[self.userList[session]["name"]]
                del self.userList[session]
        # Type 9 = UserState
        if msgType == 9:
            message = self.parseMessage(msgType, stringMessage)
            if "suppress" in message:
                return
            session = message.session
            if session in self.userList:
                record = self.userList[session]
            else:
                record = {"session": session}
                self.userList[session] = record
            name = None
            channel = None
            if "name" in message:
                name = message.name
                if "name" in record and record["name"] in self.userListByName:
                    del self.userListByName[record["name"]]
                record["name"] = name
                self.userListByName[name] = message.session
            if message.HasField("channel_id"):
                channel = message.channel_id
                record["channel"] = channel
            if name and not channel:
                record["channel"] = 0
            channelName = self.channelList[record["channel"]]

            # If they're not already in the AFK channel
            if self.channel in self.channelListByName and message.channel_id != self.channelListByName[self.channel]:
                # Send a query for UserStats -- needed to get idletime
                if "idleinfo" not in record:
                    record["idleinfo"] = {"checkon": -1, "oldchannel": message.channel_id}
                else:
                    record["idleinfo"]["checkon"] = -1
                    record["idleinfo"]["oldchannel"] = message.channel_id
                if message.actor != self.session:
                    pbMess = Mumble_pb2.UserStats()
                    pbMess.session = session
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                        self.wrapUpThread()
            else:
                if "idleinfo" in record:
                    record["idleinfo"]["checkon"] = -1
                    # if "oldchannel" not in record["idleinfo"]:
                    #     record["idleinfo"]["oldchannel"] = 0
                    # else:
                    #     record["idleinfo"]["oldchannel"] = message.channel_id
                else:
                    record["idleinfo"] = {"checkon": -1, "oldchannel": 0}
                if message.actor == self.session and\
                   message.session != self.session and\
                   record["idleinfo"]["moving"] is True:
                    record["idleinfo"]["moving"] = False
            self.userList[session] = record

            if self.inChannel and channelName == "Private Chats":
                pbMess = Mumble_pb2.TextMessage()
                pbMess.actor = self.session
                pbMess.session.append(message.session)
                pbMess.message = "This is the Private Chats channel. To create a sub-channel, right click Private Chats and select 'Add'. Name your channel and check the 'Temporary' checkbox."
                if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                    self.wrapUpThread()
            if self.inChannel and channelName in ("Castle Wars", "Zamorak", "Saradomin"):
                # Package a message to the user
                pbMess = Mumble_pb2.TextMessage()
                pbMess.actor = self.session
                pbMess.session.append(message.session)
                pbMess.message = "Welcome to the Castle Wars channels! In this channel setup you can set up a hotkey for Shout with a target of the parent channel to send messages to the opposing team."
                if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                    self.wrapUpThread()
            return

        # Type 11 = TextMessage
        if msgType == 11:
            message = self.parseMessage(msgType, stringMessage)
            if message.actor != self.session:
                if message.message.lower().startswith("/roll"):
                    pbMess = Mumble_pb2.TextMessage()
                    pbMess.actor = self.session
                    pbMess.channel_id.append(self.channelId)
                    pbMess.channel_id.append(self.userList[message.actor]["channel"])
                    pbMess.message = self.userList[message.actor]["name"] + " rolled " + str(random.randint(0, 100))
                    pbMess.session.append(self.session)
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                        self.wrapUpThread()
                    return
                if message.message.lower().startswith("/afkme"):
                    pbMess = Mumble_pb2.UserState()
                    pbMess.session = message.actor
                    pbMess.actor = self.session
                    pbMess.channel_id = self.channelListByName[self.channel]
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                        self.wrapUpThread()
                    self.userList[message.actor]["idleinfo"]["checkon"] = -1
                    return
                if message.message.lower().startswith("/afk"):
                    args = message.message.split(" ", 1)
                    if len(args) == 1:
                        return
                    pbMess = Mumble_pb2.UserState()
                    for key in self.userListByName:
                        if key.lower() == args[1].lower():
                            pbMess.session = self.userListByName[key]
                    if pbMess.session == 0:
                        pbMess = Mumble_pb2.TextMessage()
                        pbMess.actor = self.session
                        pbMess.session.append(message.actor)
                        pbMess.message = "No such user to AFK"
                        if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                            self.wrapUpThread()
                        return
                    pbMess.actor = self.session
                    pbMess.channel_id = self.channelListByName[self.channel]
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                        self.wrapUpThread()
                    self.userList[pbMess.session]["idleinfo"]["checkon"] = -1
                    return
                if message.message.lower().startswith("/unafk"):
                    args = message.message.split(" ", 1)
                    if len(args) == 1:
                        return
                    pbMess = Mumble_pb2.UserState()
                    for key in self.userListByName:
                        if key.lower() == args[1].lower():
                            pbMess.session = self.userListByName[key]
                            pbMess.channel_id = self.userList[pbMess.session]["idleinfo"]["oldchannel"]
                    if pbMess.session == 0:
                        pbMess = Mumble_pb2.TextMessage()
                        pbMess.actor = self.session
                        pbMess.session.append(message.actor)
                        pbMess.message = "No such user to UnAFK"
                        if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                            self.wrapUpThread()
                        return
                    pbMess.actor = self.session
                    if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                        self.wrapUpThread()
                    self.userList[pbMess.session]["idleinfo"]["checkon"] = -1
                if message.message.lower().startswith("/set"):
                    split = message.message.split()
                    if split[1].lower() == "afktime":
                        # Check permissions
                        pass
                    if split[1].lower() == "afkchannel":
                        # Check permissions
                        pass

        # Type 12 = PermissionDenied
        if msgType == 12:
            print("[%s] %s: Permission Denied." % (self.threadName, time.strftime("%a, %d %b %Y %H:%M:%S +0000")))
            return

        # Type 22 = UserStats
        if msgType == 22:
            message = self.parseMessage(msgType, stringMessage)
            # Timer already expired
            if message.idlesecs >= self.idleLimit and message.session != self.session:
                # Move user to AFK channel
                pbMess = Mumble_pb2.UserState()
                pbMess.session = message.session
                pbMess.actor = self.session
                pbMess.channel_id = self.channelListByName[self.channel]
                if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                    self.wrapUpThread()
                self.userList[message.session]["idleinfo"]["checkon"] = -1
            else:
                self.userList[message.session]["idleinfo"]["checkon"] = time.time()+(self.idleLimit-message.idlesecs)
            return

    def run(self):
        try:
            self.socket.connect(self.host)
        except Exception as inst:
            print(inst)
            print("[%s] %s: Couldn't connect to server" % (self.threadname, time.strftime("%a, %d %b %Y %H:%M:%S +0000")))
            global controlbreak
            controlbreak = True
            return
        self.socket.setblocking(False)
        print("[%s] %s: Connected to server" % (self.threadName, time.strftime("%a, %d %b %Y %H:%M:%S +0000")))
        pbMess = Mumble_pb2.Version()
        pbMess.release = pbMess.os_version = f"AFKBot {afkbot_version}"
        version = {
                "major": 1,
                "minor": 5,
                "build": 634
        }
        pbMess.version_v1 = (version["major"] << 16) +\
            (version["minor"] << 8) +\
            (version["build"] if version["build"] <= 255 else 255)
        pbMess.version_v2 = (version["major"] << 48) +\
            (version["minor"] << 32) +\
            (version["build"] << 16)
        pbMess.os = platform.system()

        initialConnect = self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())

        pbMess = Mumble_pb2.Authenticate()
        pbMess.username = self.nickname
        if self.password is not None:
            pbMess.password = self.password
        celtversion = pbMess.celt_versions.append(-2147483637)

        initialConnect += self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())

        if not self.sendTotally(initialConnect):
            return

        sockFD = self.socket.fileno()

        self.timedWatcher = timedWatcher(self.socketLock, self.socket)
        self.timedWatcher.start()
        print("[%s] %s: started timed watcher %s" % (self.threadName, time.strftime("%a, %d %b %Y %H:%M:%S +0000"), self.timedWatcher.threadName))

        while True:
            pollList, foo, errList = select.select([sockFD], [], [sockFD], 1)
            for item in pollList:
                if item == sockFD:
                    try:
                        self.readPacket()
                    except ssl.SSLError:
                        continue
            for session in self.userList:
                record = self.userList[session]
                if "idleinfo" in record:
                    if record["name"] != self.nickname and\
                      record["idleinfo"]["checkon"] > -1 and\
                      record["idleinfo"]["checkon"] <= time.time() and\
                      ("moving" not in record["idleinfo"] or
                       record["idleinfo"]["moving"] is False):
                        pbMess = Mumble_pb2.UserStats()
                        pbMess.session = session
                        if not self.sendTotally(self.packageMessageForSending(messageLookupMessage[type(pbMess)], pbMess.SerializeToString())):
                            self.wrapUpThread()
                        # Clear idle info, it will be populated from UserStats when it arrives
                        record["idleinfo"]["checkon"] = -1
                        record["idleinfo"]["moving"] = True
                        self.userList[session] = record
            if self.readyToClose:
                self.wrapUpThread()
                break

        if self.timedWatcher:
            self.timedWatcher.stopRunning()

        self.socket.close()
        print("[%s] %s: waiting for timed watcher to die..." % (self.threadName, time.strftime("%a, %d %b %Y %H:%M:%S +0000")));
        if self.timedWatcher is not None:
            while self.timedWatcher.is_alive():
                pass
        print("[%s] %s: thread going away - %s" % (self.threadName, time.strftime("%a, %d %b %Y %H:%M:%S +0000"), self.nickname))


def main():
    global eavesdropper, warning, controlbreak

    signal.signal(signal.SIGINT, discontinue_processing)
    # signal.signal( signal.SIGQUIT, discontinue_processing )
    signal.signal(signal.SIGTERM, discontinue_processing)
    signal.signal(signal.SIGUSR1, discontinue_processing)

    sys.stdout = Logger("afkbot.log")
    sys.stderr = sys.stdout

    if len(warning) > 0:
        print(warning)
        sys.exit(1)

    p = optparse.OptionParser(description='Mumble 1.5 AFKBot',
                              prog='afkbot.py',
                              version=f'%prog {afkbot_version}',
                              usage='\t%prog')

    p.add_option("-a", "--afk-channel", help="Channel to eavesdrop in (default %%Root)", action="store", type="string", default="AFK")
    p.add_option("-s", "--server", help="Host to connect to (default %default)", action="store", type="string", default="localhost")
    p.add_option("-p", "--port", help="Port to connect to (default %default)", action="store", type="int", default=64738)
    p.add_option("-n", "--nick", help="Nickname for the AFKBot (default %default)", action="store", type="string", default="AFKBot")
    p.add_option("-c", "--certificate", help="Certificate file for the bot to use when connecting to the server (.pem)", action="store", type="string", default="afkbot.pem")
    p.add_option("-i", "--idle-time", help="Minutes before user is moved to the AFK channel. Use [number]s for seconds.", action="store", type="string", default=30)
    p.add_option("-v", "--verbose", help="Outputs and translates all messages received from the server", action="store_true", default=False)
    p.add_option("--password", help="Password for server, if any", action="store", type="string")
    p.add_option("-S", "--allow-self-signed", help="Allow self-signed certificates", action="store_true", default=False)

    o, arguments = p.parse_args()

    certfile = Path(o.certificate)
    if not certfile.is_file():
        try:
            GenerateCertificate(o.certificate)
        except Exception as e:
            print(e)

    # Allow idletime in seconds for debugging purposes
    if o.idle_time[-1:] != "s":
        o.idle_time = int(o.idle_time)*60
    else:
        o.idle_time = int(o.idle_time[:-1])

    host = (o.server, o.port)

    # daemoninstance = daemon.DaemonContext()
    # daemoninstance.stdout = logfile;
    # daemoninstance.1

    while True:
        eavesdropper = mumbleConnection(host, o.nick, o.afk_channel,
                                        delay=None, limit=None,
                                        password=o.password, verbose=o.verbose,
                                        certificate=o.certificate, idletime=o.idle_time,
                                        allow_self_signed=o.allow_self_signed)
        eavesdropper.start()

        # Need to keep main thread alive to receive shutdown signal

        while eavesdropper.is_alive():
            time.sleep(0.5)

        if controlbreak is True:
            break

    return 0


if __name__ == '__main__':
    main()
