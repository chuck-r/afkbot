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
import tempfile
import _thread
import threading
import time
import yaml

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# The next 2 imports may not succeed
warning = ""
try:
    import ssl
except Exception:
    print("ERROR: This python program requires the python ssl module "
          "(available in python 2.6+; standalone version may be found at"
          "http://pypi.python.org/pypi/ssl/)\n")
    print(warning)
    sys.exit(1)

if importlib.util.find_spec('google') is None \
   or importlib.util.find_spec("google.protobuf") is None:
    print("ERROR: Google protobuf library not found. This can be installed "
          "via 'pip install protobuf'")
    sys.exit(1)

try:
    import Mumble_pb2
except Exception:
    print("Error: Module Mumble_pb2 not found\nIf the file 'Mumble_pb2.py' "
          "does not exist, then you must compile it with "
          "'protoc --python_out=. Mumble.proto' from the script directory.")
    sys.exit(1)

afkbot_version = "0.8.0"

headerFormat = ">HI"
eavesdropper = None
controlBreak = False
logTimeFormat = "%a, %d %b %Y %H:%M:%S +0000"
messageIDByMessageType = {
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
messageTypeByID = {}

for i in messageIDByMessageType.keys():
    messageTypeByID[messageIDByMessageType[i]] = i

threadNumber = 0


def discontinue_processing(signl, frme):
    global eavesdropper
    print(f"{time.strftime(logTimeFormat)}: Received shutdown notice.")
    if signl == signal.SIGUSR1:
        pb_message = Mumble_pb2.TextMessage()
        pb_message.actor = eavesdropper.session
        for channel_id in eavesdropper.channelList:
            pb_message.channel_id.append(channel_id)
        pb_message.message = "Server rebooting!"
        pb_message_id = messageIDByMessageType[type(pb_message)]
        pb_message_string = pb_message.SerializeToString()
        tosend = eavesdropper.packageMessage(pb_message_id, pb_message_string)
        eavesdropper.sendTotally(tosend)
    if eavesdropper:
        eavesdropper.wrapUpThread()
    else:
        sys.exit(0)
    global controlBreak
    controlBreak = True


def GenerateCertificate(filename):
    print("Generating Certificate...", end=None)
    private_key = rsa.generate_private_key(public_exponent=65537,
                                           key_size=2048)
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
    print("Done!")


# Dictionary copy, but don't override any values already set
def CopyConfig(src, dest):
    for key in src:
        if type(src[key]) is dict:
            if key not in dest:
                dest[key] = {}
            CopyConfig(src[key], dest[key])
        if key not in dest:
            dest[key] = src[key]


class Logger(object):
    def __init__(self, filename=None, copyfrom=None):
        self.original_stdout = sys.stdout
        self.terminal = sys.stdout
        if filename is None:
            self.internal_log = True
            self.log_buffer = ""
            self.log = None
        else:
            self.internal_log = False
            try:
                self.log = open(filename, "a")
            except OSError as e:
                self.terminal.write("WARN: Could not open log file "
                                    f"'{filename}': {e}\n")
                self.log = None
            if copyfrom is not None:
                try:
                    if self.log is not None:
                        self.log.write(copyfrom.log_buffer)
                except Exception as e:
                    self.terminal.write("ERROR: Could not write to log file: "
                                        f"{e}\n")
                self.original_stdout = copyfrom.original_stdout

    def write(self, message):
        self.terminal.write(message)
        if self.internal_log:
            self.log_buffer += message
        else:
            if self.log is not None:
                try:
                    self.log.write(message)
                except Exception as e:
                    self.terminal.write("ERROR: Could not write to log file: "
                                        f"{e}\n")

    def flush(self):
        self.terminal.flush()
        if self.log is not None:
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
                pb_message = Mumble_pb2.Ping()
                pb_message.timestamp = (self.pingTotal*5000000)
                pb_message.good = 0
                pb_message.late = 0
                pb_message.lost = 0
                pb_message.resync = 0
                pb_message.udp_packets = 0
                pb_message.tcp_packets = self.pingTotal
                pb_message.udp_ping_avg = 0
                pb_message.udp_ping_var = 0.0
                pb_message.tcp_ping_avg = 50
                pb_message.tcp_ping_var = 50
                self.pingTotal += 1
                packet = struct.pack(headerFormat, 3, pb_message.ByteSize()) \
                    + pb_message.SerializeToString()
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
        print(f"{time.strftime(logTimeFormat)}: timed thread going away")


class mumbleConnection(threading.Thread):
    def __init__(self, config, delay=None, limit=None):
        global threadNumber
        i = threadNumber
        threadNumber += 1
        self.threadName = "Thread " + str(i)
        threading.Thread.__init__(self)
        tcpSock = socket.socket(type=socket.SOCK_STREAM)
        self.socketLock = _thread.allocate_lock()
        self.socket = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.socket.load_default_certs(purpose=ssl.Purpose.SERVER_AUTH)

        # load_cert_chain *has* to be a PEM file
        self.socket.load_cert_chain(certfile=config["AFKBot"]["Certificate"])
        if config["Server"]["AcceptSelfSignedCertificate"] is True:
            # Retrieve server cert to add to CA's
            server_cert = tempfile.NamedTemporaryFile(delete=False,
                                                      delete_on_close=False)
            try:
                server_cert.write(
                    ssl.get_server_certificate(
                        (config["Server"]["Host"]["Address"],
                         config["Server"]["Host"]["Port"]),
                        ssl.PROTOCOL_TLS_CLIENT
                    ).encode()
                )
                server_cert.close()
                self.socket.load_verify_locations(cafile=server_cert.name)
                os.unlink(server_cert.name)
            except Exception as e:
                print(f"[self.threadName]: {time.strftime(logTimeFormat)} "
                      "Error writing SSL certificate to temporary file. "
                      "Will not be able to accept self-signed certifiate.")
                print(f"[self.threadName]: {time.strftime(logTimeFormat)} {e}")
            self.socket.check_hostname = False

        self.socket = self.socket.wrap_socket(
            tcpSock, server_hostname=config["Server"]["Host"]["Address"])
        self.socket.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
        self.host = (config["Server"]["Host"]["Address"],
                     config["Server"]["Host"]["Port"])
        self.nickname = config["AFKBot"]["Nickname"]
        self.inChannel = False
        self.session = None
        self.channelId = None
        self.userList = {}
        self.userListByName = {}
        self.channelList = {}
        self.channelListByName = {}
        self.readyToClose = False
        self.timedWatcher = None
        self.serverSync = False
        # TODO: Implement delay and rate limit
        # self.delay=delay
        # self.limit=limit
        self.password = None
        self.verbose = config["AFKBot"]["Verbose"]

        #######################################
        # AFKBot-specific config
        #######################################
        self.idleLimit = config["AFKBot"]["IdleTimeout"]

        exception = ValueError("config['AFKBot']['IdleTimeout'] or command "
                               "line argument --idle-time is invalid. Valid "
                               "values are a number, a string convertible to "
                               "a number, or an string convertible to a "
                               "number suffixed with 's' for seconds.\n\n"
                               "Examples: 30, \"30\", or \"30s\"")
        if type(self.idleLimit) is str:
            if len(self.idleLimit) >= 2:
                if self.idleLimit[-1:] == "s":
                    self.idleLimit = self.idleLimit[:-1]
                    try:
                        self.idleLimit = int(self.idleLimit)
                    except Exception:
                        raise exception
                else:
                    self.idleLimit = int(self.idleLimit) * 60
            else:
                try:
                    self.idleLimit = int(self.idleLimit) * 60
                except Exception:
                    raise exception
        else:
            try:
                self.idleLimit = int(self.idleLimit) * 60
            except Exception:
                raise exception
        self.channel = config["AFKBot"]["Channel"]  # AFK channel to listen in
        self.accessTokens = []
        if "AccessTokens" in config["Server"]:
            for item in config["Server"]["AccessTokens"]:
                self.accessTokens.append(item)
        if "Password" in config["Server"]:
            self.password = config["Server"]["Password"]

    def decodePDSInt(self, m, si=0):
        v = m[si]
        if ((v & 0x80) == 0x00):
            return ((v & 0x7F), 1)
        elif ((v & 0xC0) == 0x80):
            return ((v & 0x4F) << 8 | m[si+1], 2)
        elif ((v & 0xF0) == 0xF0):
            if ((v & 0xFC) == 0xF0):
                return (m[si+1] << 24 | m[si+2] << 16
                        | m[si+3] << 8 | m[si+4], 5)
            elif ((v & 0xFC) == 0xF4):
                return (m[si+1] << 56 | m[si+2] << 48
                        | m[si+3] << 40 | m[si+4] << 32
                        | m[si+5] << 24 | m[si+6] << 16
                        | m[si+7] << 8 | m[si+8], 9)
            elif ((v & 0xFC) == 0xF8):
                result, length = self.decodePDSInt(m, si+1)
                return (-result, length+1)
            elif ((v & 0xFC) == 0xFC):
                return (-(v & 0x03), 1)
            else:
                print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: "
                      "Help help, out of cheese :(")
                sys.exit(1)
        elif ((v & 0xF0) == 0xE0):
            return ((v & 0x0F) << 24 | m[si+1] << 16
                    | m[si+2] << 8 | m[si+3], 4)
        elif ((v & 0xE0) == 0xC0):
            return ((v & 0x1F) << 16 | m[si+1] << 8 | m[si+2], 3)
        else:
            print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: "
                  "out of cheese?")
            sys.exit(1)

    def packageMessage(self, message_type, message):
        length = len(message)
        return struct.pack(headerFormat, message_type, length)+message

    def sendTotally(self, message):
        self.socketLock.acquire()
        while len(message) > 0:
            sent = self.socket.send(message)
            if sent < 0:
                print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: "
                      "Server socket error while trying to write, immediate "
                      "abort")
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
                print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: "
                      "Server socket died while trying to read, immediate "
                      "abort")
                return None
        return message

    def parseMessage(self, message_type, message):
        message_class = messageTypeByID[message_type]
        temp_message = message_class()
        temp_message.ParseFromString(message)
        return temp_message

    def joinChannel(self):
        if self.channelId is not None and self.session is not None:
            pb_message = Mumble_pb2.UserState()
            pb_message.session = self.session
            pb_message.channel_id = self.channelId
            pb_message_id = messageIDByMessageType[type(pb_message)]
            pb_message_string = pb_message.SerializeToString()
            pb_message = self.packageMessage(pb_message_id, pb_message_string)
            if not self.sendTotally(pb_message):
                self.wrapUpThread()
                return

    def wrapUpThread(self):
        # called after thread is confirmed to be needing to die because of
        # kick / socket close
        self.readyToClose = True

    def readPacket(self):
        # pdb.set_trace()
        meta = self.readTotally(6)
        if not meta:
            self.wrapUpThread()
            return
        message_type, length = struct.unpack(headerFormat, meta)
        stringMessage = self.readTotally(length)
        if not stringMessage:
            # An empty payload isn't necessarily a panic condition. I've
            # seen packets such as CryptSetup with no payload
            return
        # Type 1 = UDP Tunnel, voice data or UDP ping
        if message_type == 1:
            # I'm not sure why the third byte is session ID, but it is.
            session, sessLen = self.decodePDSInt(stringMessage, 2)
            if session in self.userList and self.userList[session]["channel"] \
               == self.channelListByName[self.channel]:
                if "idleinfo" in self.userList[session] \
                   and "oldchannel" in self.userList[session]["idleinfo"]:
                    pb_message = Mumble_pb2.UserState()
                    pb_message.session = session
                    pb_message.actor = self.session
                    pb_message.channel_id = \
                        self.userList[session]["idleinfo"]["oldchannel"]
                    pb_message_id = messageIDByMessageType[type(pb_message)]
                    pb_message_string = pb_message.SerializeToString()
                    pb_message = self.packageMessage(pb_message_id,
                                                     pb_message_string)
                    if not self.sendTotally(pb_message):
                        self.wrapUpThread()
        # Type 5 = ServerSync
        if message_type == 5 and not self.session:
            message = self.parseMessage(message_type, stringMessage)
            self.serverSync = True
            self.session = message.session
            self.joinChannel()
        # Type 6 = ChannelRemove
        if message_type == 6:
            message = self.parseMessage(message_type, stringMessage)
            channelid = message.channel_id
            for item in self.channelListByName:
                if self.channelListByName[item] == message.channel_id:
                    del self.channelListByName[item]
                    del self.channeList[message.channel_id]
                    break
            for item in self.userList:
                if "idleinfo" in self.userList[item] \
                   and "oldchannel" in self.userList[item]["idleinfo"]:
                    if self.userList[item]["idleinfo"]["oldchannel"] \
                       == channelid:
                        self.userList[item]["idleinfo"]["oldchannel"] = 0
        # Type 7 = ChannelState
        if message_type == 7:
            message = self.parseMessage(message_type, stringMessage)
            if message.channel_id not in self.channelList \
               or self.channelList[message.channel_id] != message.name:
                if not len(message.name):
                    return
                self.channelList[message.channel_id] = message.name
                self.channelListByName[message.name] = message.channel_id
            if (not self.inChannel) and self.channelId is None:
                if self.channel is None and message.channel_id == 0:
                    self.channel = message.name
                    self.channelId = message.channel_id
                    if self.serverSync is True:
                        self.joinChannel()
                elif message.name == self.channel:
                    self.channelId = message.channel_id
                    if self.serverSync is True:
                        self.joinChannel()
        # Type 8 = UserRemove (kick/leave)
        if message_type == 8:
            message = self.parseMessage(message_type, stringMessage)
            if self.session is not None:
                if message.session == self.session:
                    print(f"[{self.threadName}] {time.strftime(logTimeFormat)}"
                          ": ********** KICKED **********")
                    self.wrapUpThread()
                    return
            session = message.session
            if session in self.userList:
                del self.userListByName[self.userList[session]["name"]]
                del self.userList[session]
        # Type 9 = UserState
        if message_type == 9:
            message = self.parseMessage(message_type, stringMessage)
            session = message.session
            record = None
            name = None
            channel = None
            channel_name = None

            if "session" in self.userList:
                record = self.userList[session]
            else:
                record = {}
            if "name" in message:
                record["name"] = message.name
                name = message.name
            if "user_id" in message:
                record["user_id"] = message.user_id
            if "channel_id" in message:
                record["channel"] = message.channel_id
                channel = message.channel_id
            if channel is None and session in self.userList \
               and "channel" in self.userList[session]:
                channel = self.userList[session]["channel"]

            if not self.inChannel and channel in self.channelList:
                self.inChannel = True

            # Keep any data that wasn't from this packet
            if session in self.userList:
                for item in self.userList[session]:
                    record[item] = self.userList[session][item]
                if "channel" in self.userList[session]:
                    channel_name = \
                        self.channelList[self.userList[session]["channel"]]
            # No info on user, send a UserStats
            else:
                pb_message = Mumble_pb2.UserStats()
                pb_message.session = session
                pb_message_id = messageIDByMessageType[type(pb_message)]
                pb_message_string = pb_message.SerializeToString()
                pb_message = self.packageMessage(pb_message_id,
                                                 pb_message_string)
                if not self.sendTotally(pb_message):
                    self.wrapUpThread()
            self.userList[session] = record

            if name:
                self.userListByName[name] = message.session

            # Set idle information on actor
            if "actor" in message and message.actor != self.session:
                record = self.userList[message.actor]

            # If they're not already in the AFK channel
            if self.channel in self.channelListByName \
               and message.channel_id != self.channelListByName[self.channel]:
                # Send a query for UserStats -- needed to get idletime
                if "idleinfo" not in record:
                    record["idleinfo"] = {
                        "checkon": -1,
                        "oldchannel": message.channel_id,
                        "moving": False
                        }
                else:
                    record["idleinfo"]["checkon"] = -1
                    record["idleinfo"]["oldchannel"] = message.channel_id
                    record["idleinfo"]["moving"] = False
            else:
                if "idleinfo" in record:
                    record["idleinfo"]["checkon"] = -1
                else:
                    record["idleinfo"] = {"checkon": -1, "oldchannel": 0}
                if "actor" in message and message.actor == self.session and \
                   message.session != self.session and \
                   record["idleinfo"]["moving"] is True:
                    record["idleinfo"]["moving"] = False

            # Update idleinfo for user seding message
            update_user = session
            to_update = self.userList[session]
            if "actor" in message and message.actor != self.session:
                update_user = message.actor
                to_update = self.userList[message.actor]

            temp_idleinfo = record["idleinfo"]
            for item in to_update:
                record[item] = to_update[item]
            record["idleinfo"] = temp_idleinfo
            self.userList[update_user] = record

            pb_message = Mumble_pb2.UserStats()
            pb_message.session = update_user
            pb_message_id = messageIDByMessageType[type(pb_message)]
            pb_message_string = pb_message.SerializeToString()
            if not self.sendTotally(self.packageMessage(pb_message_id,
                                    pb_message_string)):
                self.wrapUpThread()

            if channel_name:
                if self.inChannel and channel_name == "Private Chats":
                    pb_message = Mumble_pb2.TextMessage()
                    pb_message.actor = self.session
                    pb_message.session.append(message.session)
                    pb_message.message = \
                        ("This is the Private Chats channel. To create a "
                         "sub-channel, right click Private Chats and select "
                         "'Add'. Name your channel and check the 'Temporary' "
                         "checkbox.")
                    pb_message_id = messageIDByMessageType[type(pb_message)]
                    pb_message_string = pb_message.SerializeToString()
                    pb_message = self.packageMessage(pb_message_id,
                                                     pb_message_string)
                    if not self.sendTotally(pb_message):
                        self.wrapUpThread()
                if self.inChannel and channel_name in \
                   ("Castle Wars", "Zamorak", "Saradomin"):
                    # Package a message to the user
                    pb_message = Mumble_pb2.TextMessage()
                    pb_message.actor = self.session
                    pb_message.session.append(message.session)
                    pb_message.message = (
                        "Welcome to the Castle Wars channels! In this channel "
                        "setup, you can set up a hotkey for Shout with a "
                        "target of the parent channel to send messages to "
                        "the opposing team.")
                    pb_message_id = messageIDByMessageType[type(pb_message)]
                    pb_message_string = pb_message.SerializeToString()
                    pb_message = self.packageMessage(pb_message_id,
                                                     pb_message_string)
                    if not self.sendTotally(pb_message):
                        self.wrapUpThread()
            return

        # Type 11 = TextMessage
        if message_type == 11:
            message = self.parseMessage(message_type, stringMessage)
            if message.actor != self.session:
                if message.message.lower().startswith("/roll"):
                    pb_message = Mumble_pb2.TextMessage()
                    pb_message.actor = self.session
                    pb_message.channel_id.append(self.channelId)
                    pb_message.channel_id.append(
                        self.userList[message.actor]["channel"])
                    pb_message.message = self.userList[message.actor]["name"] \
                        + " rolled " + str(random.randint(0, 100))
                    pb_message.session.append(message.actor)
                    pb_message_id = messageIDByMessageType[type(pb_message)]
                    pb_message_string = pb_message.SerializeToString()
                    pb_message = self.packageMessage(pb_message_id,
                                                     pb_message_string)
                    if not self.sendTotally(pb_message):
                        self.wrapUpThread()
                    return
                if message.message.lower().startswith("/afkme"):
                    pb_message = Mumble_pb2.UserState()
                    pb_message.session = message.actor
                    pb_message.actor = self.session
                    pb_message.channel_id = \
                        self.channelListByName[self.channel]
                    pb_message_id = messageIDByMessageType[type(pb_message)]
                    pb_message_string = pb_message.SerializeToString()
                    pb_message = self.packageMessage(pb_message_id,
                                                     pb_message_string)
                    if not self.sendTotally(pb_message):
                        self.wrapUpThread()
                    self.userList[message.actor]["idleinfo"]["checkon"] = -1
                    return
                if message.message.lower().startswith("/afk"):
                    args = message.message.split(" ", 1)
                    if len(args) == 1:
                        return
                    pb_message = Mumble_pb2.UserState()
                    for key in self.userListByName:
                        if key.lower() == args[1].lower():
                            pb_message.session = self.userListByName[key]
                    if pb_message.session == 0:
                        pb_message = Mumble_pb2.TextMessage()
                        pb_message.actor = self.session
                        pb_message.session.append(message.actor)
                        pb_message.message = "No such user to AFK"
                        pb_message_id = \
                            messageIDByMessageType[type(pb_message)]
                        pb_message_string = pb_message.SerializeToString()
                        pb_message = self.packageMessage(pb_message_id,
                                                         pb_message_string)
                        if not self.sendTotally(pb_message):
                            self.wrapUpThread()
                        return
                    self.userList[pb_message.session]["idleinfo"]["checkon"] \
                        = -1
                    pb_message.actor = self.session
                    pb_message.channel_id = \
                        self.channelListByName[self.channel]
                    pb_message_id = messageIDByMessageType(type(pb_message))
                    pb_message_string = pb_message.SerializeToString()
                    pb_message = self.packageMessage(pb_message_id,
                                                     pb_message_string)
                    if not self.sendTotally(pb_message):
                        self.wrapUpThread()
                    return
                if message.message.lower().startswith("/unafk"):
                    args = message.message.split(" ", 1)
                    if len(args) == 1:
                        return
                    pb_message = Mumble_pb2.UserState()
                    for key in self.userListByName:
                        if key.lower() == args[1].lower():
                            sess = self.userListByName[key]
                            pb_message.session = sess
                            pb_message.channel_id = \
                                self.userList[sess]["idleinfo"]["oldchannel"]
                    if pb_message.session == 0:
                        pb_message = Mumble_pb2.TextMessage()
                        pb_message.actor = self.session
                        pb_message.session.append(message.actor)
                        pb_message.message = "No such user to UnAFK"
                        pb_message_id = \
                            messageIDByMessageType[type(pb_message)]
                        pb_message_string = pb_message.SerializeToString()
                        pb_message = self.packageMessage(pb_message_id,
                                                         pb_message_string)
                        if not self.sendTotally(pb_message):
                            self.wrapUpThread()
                        return
                    self.userList[pb_message.session]["idleinfo"]["checkon"] \
                        = -1
                    pb_message.actor = self.session
                    pb_message_id = messageIDByMessageType[type(pb_message)]
                    pb_message_string = pb_message.SerializeToString()
                    pb_message = self.packageMessage(pb_message_id,
                                                     pb_message_string)
                    if not self.sendTotally(pb_message):
                        self.wrapUpThread()
                if message.message.lower().startswith("/set"):
                    split = message.message.split()
                    if split[1].lower() == "afktime":
                        # Check permissions
                        pass
                    if split[1].lower() == "afkchannel":
                        # Check permissions
                        pass

        # Type 12 = PermissionDenied
        if message_type == 12:
            print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: "
                  "Permission Denied.")
            return

        # Type 22 = UserStats
        if message_type == 22:
            message = self.parseMessage(message_type, stringMessage)

            # Timer already expired
            if message.idlesecs >= self.idleLimit and self.inChannel \
               and message.session != self.session:
                # Move user to AFK channel
                pb_message = Mumble_pb2.UserState()
                pb_message.session = message.session
                pb_message.actor = self.session
                pb_message.channel_id = self.channelListByName[self.channel]
                pb_message_id = messageIDByMessageType[type(pb_message)]
                pb_message_string = pb_message.SerializeToString()
                pb_message = self.packageMessage(pb_message_id,
                                                 pb_message_string)
                if not self.sendTotally(pb_message):
                    self.wrapUpThread()
                self.userList[message.session]["idleinfo"]["checkon"] = -1
            else:
                self.userList[message.session]["idleinfo"]["checkon"] = \
                    time.time()+(self.idleLimit-message.idlesecs)
            return

    def run(self):
        try:
            self.socket.connect(self.host)
        except Exception as inst:
            print(inst)
            print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: "
                  "Couldn't connect to server")
            global controlBreak
            controlBreak = True
            return
        self.socket.setblocking(False)
        print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: "
              "Connected to server")
        pb_message = Mumble_pb2.Version()
        pb_message.release = pb_message.os_version = f"AFKBot {afkbot_version}"
        version = {
                "major": 1,
                "minor": 5,
                "build": 634
        }
        pb_message.version_v1 = (version["major"] << 16) +\
            (version["minor"] << 8) +\
            (version["build"] if version["build"] <= 255 else 255)
        pb_message.version_v2 = (version["major"] << 48) +\
            (version["minor"] << 32) +\
            (version["build"] << 16)
        pb_message.os = platform.system()
        pb_message_id = messageIDByMessageType[type(pb_message)]
        pb_message_string = pb_message.SerializeToString()
        pb_message = self.packageMessage(pb_message_id, pb_message_string)

        initial_connect = pb_message

        pb_message = Mumble_pb2.Authenticate()
        pb_message.username = self.nickname
        if len(self.accessTokens):
            for token in self.accessTokens:
                pb_message.tokens.append(token)
        if self.password is not None:
            pb_message.password = self.password
        # celt_version = pb_message.celt_versions.append(-2147483637)

        pb_message_id = messageIDByMessageType[type(pb_message)]
        pb_message_string = pb_message.SerializeToString()
        pb_message = self.packageMessage(pb_message_id, pb_message_string)
        initial_connect += pb_message

        if not self.sendTotally(initial_connect):
            return

        sockFD = self.socket.fileno()

        self.timedWatcher = timedWatcher(self.socketLock, self.socket)
        self.timedWatcher.start()
        print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: started "
              f"timed watcher {self.timedWatcher.threadName}")

        while True:
            poll_list, foo, err_list = select.select([sockFD], [], [sockFD], 1)
            for item in poll_list:
                if item == sockFD:
                    try:
                        self.readPacket()
                    except ssl.SSLError:
                        continue
            for session in self.userList:
                record = self.userList[session]
                if "idleinfo" in record:
                    if "name" not in record:
                        continue
                    if record["name"] != self.nickname and \
                       record["idleinfo"]["checkon"] > -1 and \
                       record["idleinfo"]["checkon"] <= time.time() and \
                       ("moving" not in record["idleinfo"] or
                       record["idleinfo"]["moving"] is False):
                        pb_message = Mumble_pb2.UserStats()
                        pb_message.session = session
                        pb_message_id = \
                            messageIDByMessageType[type(pb_message)]
                        pb_message_string = pb_message.SerializeToString()
                        pb_message = self.packageMessage(pb_message_id,
                                                         pb_message_string)
                        if not self.sendTotally(pb_message):
                            self.wrapUpThread()
                        # Clear idle info, it will be populated from UserStats
                        # when it arrives
                        record["idleinfo"]["checkon"] = -1
                        record["idleinfo"]["moving"] = True
                        self.userList[session] = record
            if self.readyToClose:
                self.wrapUpThread()
                break

        if self.timedWatcher:
            self.timedWatcher.stopRunning()

        self.socket.close()
        print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: waiting "
              "for timed watcher to die...")
        if self.timedWatcher is not None:
            while self.timedWatcher.is_alive():
                pass
        print(f"[{self.threadName}] {time.strftime(logTimeFormat)}: thread "
              f"going away - {self.nickname}")


def main():
    global eavesdropper, warning, controlBreak

    signal.signal(signal.SIGINT, discontinue_processing)
    # signal.signal( signal.SIGQUIT, discontinue_processing )
    signal.signal(signal.SIGTERM, discontinue_processing)
    signal.signal(signal.SIGUSR1, discontinue_processing)

    sys.stdout = temp_logger = Logger(filename=None)
    sys.stderr = sys.stdout

    if len(warning) > 0:
        print(warning)
        sys.exit(1)

    # TODO: Replace with argparse?
    p = optparse.OptionParser(description='Mumble 1.5 AFKBot',
                              prog='afkbot.py',
                              version=f'%prog {afkbot_version}',
                              usage='\t%prog')

    p.add_option("-a", "--afk-channel",
                 help="Channel to eavesdrop in (default %%Root)",
                 action="store", type="string", default="AFK")
    p.add_option("-A", "--access-tokens",
                 help="Comma-separated list of access tokens",
                 action="store", type="string")
    p.add_option("-c", "--certificate",
                 help="Certificate file for the bot to use when connecting to "
                      "the server (.pem)", action="store", type="string")
    p.add_option("-C", "--config",
                 help="Path to configuration file",
                 action="store", type="string")
    p.add_option("-D", "--disallow-self-signed",
                 help="Do not allow self-signed certificates",
                 action="store_true", default=False)
    p.add_option("-i", "--idle-time",
                 help="Minutes before user is moved to the AFK "
                      "channel. Use [number]s for seconds.",
                 action="store", type="string", default="30")
    p.add_option("-L", "--log-file",
                 action="store", type="string")
    p.add_option("-n", "--nick",
                 help="Nickname for the AFKBot (default %default)",
                 action="store", type="string", default="AFKBot")
    p.add_option("-p", "--port",
                 help="Port to connect to (default %default)",
                 action="store", type="int", default=64738)
    p.add_option("--password",
                 help="Password for server, if any",
                 action="store", type="string")
    p.add_option("-s", "--server",
                 help="Host to connect to (default %default)",
                 action="store", type="string", default="localhost")
    p.add_option("-v", "--verbose",
                 help="Outputs and translates all messages received from the "
                      "server",
                 action="store_true", default=False)

    o, arguments = p.parse_args()

    config = None

    env_vars = {}
    for var in ("HOME", "LOCALAPPDATA", "USERPROFILE"):
        try:
            # os.environ[var] will likely not exist in some
            # cases. In those cases, it doesn't matter since
            # we're probably not on that platform.
            env_vars[var] = os.environ[var]
        except KeyError:
            env_vars[var] = ""

    config_dirs = {
            "linux": (env_vars["HOME"] + "/.config/afkbot",
                      env_vars["HOME"]),
            "freebsd": (env_vars["HOME"] + "/.config/afkbot",
                        env_vars["HOME"]),
            "darwin": (env_vars["HOME"] + "/Application Support/afkbot",
                       env_vars["HOME"]),
            "win32": (env_vars["LOCALAPPDATA"] + "\\afkbot",
                      env_vars["USERPROFILE"] + "\\afkbot")
            }

    data_dirs = {
            "linux": (env_vars["HOME"] + "/.local/share/afkbot",
                      env_vars["HOME"]),
            "freebsd": (env_vars["HOME"] + "/.local/share/afkbot",
                        env_vars["HOME"]),
            "darwin": (env_vars["HOME"] + "/Application Support/afkbot",
                       env_vars["HOME"]),
            "win32": (env_vars["LOCALAPPDATA"] + "\\afkbot",
                      env_vars["USERPROFILE"] + "\\afkbot")
            }

    os_match = None
    for system in config_dirs:
        if sys.platform.startswith(system):
            os_match = system

    default_config_text = (
        "AFKBot:\n"
        "    # Nickname for the bot\n"
        "    Nickname: AFKBot\n"
        "\n"
        "    # Channel the bot will move to and move AFK\n"
        "    # users into\n"
        "    Channel: AFK\n"
        "\n"
        "    # Certificate file for the bot to use for\n"
        "    # identification to the server. This is a\n"
        "    # PEM-encoded file composed of a private key\n"
        "    # followed by a certificate. If not provided,\n"
        "    # one will be created in DataDir.\n"
        "    # Certificate: " + os.path.join(data_dirs[os_match][0],
                                             "afkbot.pem") + "\n"
        "\n"
        "    # Directory containing the configuration file\n"
        "    # ConfigDirectory: " + config_dirs[os_match][0] + "\n"
        "\n"
        "    # Directory containing client and server certificates\n"
        "    # and the default log file\n"
        "    # DataDirectory: " + data_dirs[os_match][0] + "\n"
        "\n"
        "    # Minutes before user is moved to the AFK channel.\n"
        "    # Seconds can be specified with an 's' suffix, such\n"
        "    # as: 30s\n"
        "    IdleTimeout: 30\n"
        "\n"
        "    # Log file location"
        "    # LogFile: " +
        os.path.join(data_dirs[os_match][0], "afkbot.log") + "\n"
        "\n"
        "    # Verbose logging\n"
        "    Verbose: False\n"
        "\n"
        "Server:\n"
        "    Host:\n"
        "        # Server IP or hostname\n"
        "        Address: localhost\n"
        "\n"
        "        # Server Port\n"
        "        Port: 64738\n"
        "\n"
        "    # Accept Self Signed SSL Certificates when\n"
        "    # establishing a connection to the server. By\n"
        "    # default, the Mumble server create a self-signed\n"
        "    # certificate.\n"
        "    AcceptSelfSignedCertificate: True\n"
        "\n"
        "    # Password to use when connection to the server\n"
        "    # Password: MyPassword\n"
        "\n"
        "    # Access tokens to use when authenticating with the\n"
        "    # server\n"
        "    # AccessTokens:\n"
        "    #     - MyToken\n"
        "    #     - MyOtherToken\n"
        )
    default_config_text.replace("\n", os.linesep)
    default_config = yaml.safe_load(default_config_text)

    config_file = None
    # Load specified config file
    if o.config:
        try:
            open(o.config, "r")
        except OSError as e:
            print(f"ERROR: Unable to open specified config file '{o.config}': "
                  f"{e}")
            sys.exit(1)
    # Try default config locations
    else:
        # Search config dirs
        for location in config_dirs[os_match]:
            try:
                config_file = open(os.path.join(location, "afkbot.yaml"), "r")
                break
            except OSError:
                pass
        # Write a default config
        if os_match is not None and config_file is None:
            stage = 0
            config_path = os.path.join(config_dirs[os_match][0],
                                       "afkbot.yaml")
            print("WARN: Configuration file not found at default locations, "
                  "writing default config to '{config_path}'")
            if not os.path.isdir(config_dirs[os_match][0]):
                try:
                    os.mkdir(config_dirs[os_match][0], mode=0o775)
                    stage = 1
                except Exception as e:
                    print("WARN: Unable to create config directory "
                          f"'{config_dirs[os_match][0]}': {e}")
            else:
                stage = 1
            if stage == 1:
                try:
                    with open(os.path.join(config_dirs[os_match][0],
                              "afkbot.yaml"), "w") as file:
                        file.write(default_config_text)
                    stage = 2
                except OSError as e:
                    config_path = os.path.join(config_dirs[os_match][0],
                                               'afkbot.yaml')
                    print("WARN: Could not write default config to "
                          f"'{config_path}': {e}")
            if stage == 2:
                try:
                    config_file = open(os.path.join(config_dirs[os_match][0],
                                       "afkbot.yaml"), "r")
                except OSError as e:
                    config_path = os.path.join(config_dirs[os_match][0],
                                               "afkbot.yaml")
                    print("WARN: Could not read back default configuration "
                          f"written to {config_path}: {e}")
        # Unmatched OS, use working directory
        if os_match is None:
            print(f"WARN: Unknown platform: {sys.platform}, trying to load "
                  "config 'afkbot.yaml' from working directory")
            try:
                config_file = open("afkbot.yaml", "r")
            except OSError as e:
                print(f"WARN: Error opening conf file '.{os.sep}afkbot.yaml'"
                      f": {e}")

    # If there is a valid config file, try to parse it
    try:
        if config_file is not None:
            config = yaml.safe_load(config_file)
    except Exception as e:
        print("Could not load config file")
        print(e)
        sys.exit(1)
    # Use default config on failure
    if config is None:
        print("WARN: Using default configuration:")
        print(yaml.safe_dump(default_config))
        config = {}

    # Populate defaults if not specified in config
    CopyConfig(default_config, config)
    config["CmdLineOverride"] = {}

    # Override config file parameters with any specified on the command line
    # Order of precedence: command line > config > default
    if o.nick != "AFKBot":
        config["AFKBot"]["Nickname"] = o.nick
    if o.afk_channel != "AFK":
        config["AFKBot"]["Channel"] = o.afk_channel
    if o.certificate is not None:
        config["AFKBot"]["Certificate"] = o.certificate
        config["CmdLineOverride"]["Certificate"] = True
    if o.idle_time != "30":
        config["AFKBot"]["IdleTimeout"] = o.idle_time
    if o.log_file is not None:
        config["AFKBot"]["LogFile"] = o.log_file
        config["CmdLineOverride"]["LogFile"] = True
    if o.verbose is not False:
        config["AFKBot"]["Verbose"] = o.verbose
    if o.server != "localhost":
        config["Server"]["Host"]["Address"] = o.server
    if o.port != 64738:
        config["Server"]["Host"]["Port"] = o.port
    if o.password:
        config["Server"]["Password"] = o.password
    if o.disallow_self_signed is not False:
        config["Server"]["AcceptSelfSignedCertificate"] = \
            not o.disallow_self_signed

    # Find directories
    directories = (
            ("DataDirectory", data_dirs[os_match]),
            ("ConfigDirectory", config_dirs[os_match])
            )
    for i in directories:
        d = None
        # Directory specified in config file
        if i[0] in config["AFKBot"]:
            if os.path.isdir(config["AFKBot"][i[0]]):
                d = config["AFKBot"][i[0]]
            else:
                try:
                    os.mkdir(config["AFKBot"][i[0]], mode=0o775)
                except Exception as e:
                    print(f"ERROR: {i[0]} '{config['AFKBot'][i[0]]}' "
                          "specified in config file doesn't exist and failed "
                          "to create it.")
                    print(e)
                    exit(1)
        # Check default directories
        else:
            for path in i[1]:
                if os.path.isdir(path):
                    d = path
                    break
            # Try to create default directories
            if d is None:
                for path in i[1]:
                    try:
                        os.mkdir(path, mode=0o775)
                        d = path
                        break
                    except Exception:
                        pass
                # Failed to create all default directories
                if d is None:
                    print("ERROR: Failed to create any default paths "
                          f"{i[1]}, falling back to trying working directory")
            if d is None:
                if os.path.is_dir(os.path.join(".", "")):
                    d = os.path.join(".", "")
                    print(f"WARN: Using current directory as {i[0]}")
        if d is None:
            print(f"ERROR: Unable to use any directories in {i[0]}, including "
                  "current working directory: bailing out")
            exit(1)
        else:
            config["AFKBot"][i[0]] = d

    if "LogFile" not in config["AFKBot"]:
        config["AFKBot"]["LogFile"] = \
            os.path.join(config["AFKBot"]["DataDirectory"], "afkbot.log")
    log_folder = os.path.dirname(config["AFKBot"]["LogFile"])
    if len(log_folder) and not os.path.isdir(log_folder):
        try:
            os.mkdir(log_folder, 0o775)
        except Exception as e:
            print(f"ERROR: Could not create folder for logfile: {e}")
    sys.stdout = Logger(config["AFKBot"]["LogFile"], temp_logger)

    # Attempt to locate certificate and ensure it can be read
    cert_file = None
    cert_default = os.path.join(config["AFKBot"]["DataDirectory"],
                                "afkbot.pem")
    if "Certificate" not in config["AFKBot"]:
        config["AFKBot"]["Certificate"] = cert_default
    if os.path.isfile(config["AFKBot"]["Certificate"]):
        try:
            open(config["AFKBot"]["Certificate"], "r")
            cert_file = config["AFKBot"]["Certificate"]
        except Exception as e:
            print("ERROR: Unable to read certificate file "
                  f"'{config['AFKBot']['Certificate']}'", end=None)
            if "Certifcate" in config["CmdLineOverride"] \
               and config["CmdLineOverride"]["Certificate"] is True:
                print("specified on command line.")
            elif config["AFKBot"]["Certificate"] != cert_default:
                if o.config_file:
                    print(f"specified in config file '{o.config_file}'")
                else:
                    print(f"specified in config file '{config_file}'")
            print(e)
            exit(1)
        cert_file = config["AFKBot"]["Certificate"]
    elif "Certificate" in config["CmdLineOverride"] \
         and config["CmdLineOverride"]["Certificate"] is True:
        print("ERROR: Cannot find certificate specified on command line: "
              f"'{config['AKFBot']['Certificate']}'")
        exit(1)
    elif config["AFKBot"]["Certificate"] != cert_default:
        print("ERROR: Cannot find certificate specified in configuration file "
              f"'{o.config}': '{config['AFKBot']['Certificate']}")
        exit(1)
    # Certificate not specified on command line or config file
    else:
        # Try finding afkbot.pem in all data directories
        for data_dir in data_dirs[os_match]:
            if os.path.isfile(os.path.join(data_dir, "afkbot.pem")):
                cert_file = os.path.join(data_dir, "afkbot.pem")
                config["AFKBot"]["Certificate"] = cert_file
    # Try the current directory
    if cert_file is None and os.path.isfile("afkbot.pem"):
        cert_file = "afkbot.pem"
        config["AFKBot"]["Certificate"] = cert_file
    # Can't find certificate, generate it
    if cert_file is None:
        try:
            GenerateCertificate(cert_default)
        except Exception as e:
            print(e)

    if o.access_tokens:
        if "AccessTokens" not in config["Server"]:
            config["Server"]["AccessTokens"] = []
        for token in o.access_tokens.split(","):
            config["Server"]["AccessTokens"].append = token

    while True:
        eavesdropper = mumbleConnection(config, delay=None, limit=None)
        eavesdropper.start()

        # Need to keep main thread alive to receive shutdown signal

        while eavesdropper.is_alive():
            time.sleep(0.5)

        if controlBreak is True:
            break

    return 0


if __name__ == '__main__':
    main()
