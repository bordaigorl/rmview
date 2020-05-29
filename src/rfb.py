"""
RFB protocol implementation, client side.

Override RFBClient and RFBFactory in your application.
See vncviewer.py for an example.

Reference:
http://www.realvnc.com/docs/rfbproto.pdf

(C) 2003 cliechti@gmx.net

MIT License
"""
# flake8: noqa

import sys
import math
import zlib
from struct import pack, unpack
from twisted.python import usage, log
from twisted.internet.protocol import Protocol
from twisted.internet import protocol
from twisted.application import internet, service

# Python3 compatibility replacement for ord(str) as ord(byte)
if not isinstance(b' ', str):
    def ord(x): return x

#encoding-type
#for SetEncodings()
RAW_ENCODING =                  0
COPY_RECTANGLE_ENCODING =       1
RRE_ENCODING =                  2
CORRE_ENCODING =                4
HEXTILE_ENCODING =              5
ZLIB_ENCODING =                 6
TIGHT_ENCODING =                7
ZLIBHEX_ENCODING =              8
ZRLE_ENCODING =                 16
#0xffffff00 to 0xffffffff tight options
PSEUDO_CURSOR_ENCODING =        -239
PSEUDO_DESKTOP_SIZE_ENCODING =  -223

#keycodes
#for KeyEvent()
KEY_BackSpace = 0xff08
KEY_Tab =       0xff09
KEY_Return =    0xff0d
KEY_Escape =    0xff1b
KEY_Insert =    0xff63
KEY_Delete =    0xffff
KEY_Home =      0xff50
KEY_End =       0xff57
KEY_PageUp =    0xff55
KEY_PageDown =  0xff56
KEY_Left =      0xff51
KEY_Up =        0xff52
KEY_Right =     0xff53
KEY_Down =      0xff54
KEY_F1 =        0xffbe
KEY_F2 =        0xffbf
KEY_F3 =        0xffc0
KEY_F4 =        0xffc1
KEY_F5 =        0xffc2
KEY_F6 =        0xffc3
KEY_F7 =        0xffc4
KEY_F8 =        0xffc5
KEY_F9 =        0xffc6
KEY_F10 =       0xffc7
KEY_F11 =       0xffc8
KEY_F12 =       0xffc9
KEY_F13 =       0xFFCA
KEY_F14 =       0xFFCB
KEY_F15 =       0xFFCC
KEY_F16 =       0xFFCD
KEY_F17 =       0xFFCE
KEY_F18 =       0xFFCF
KEY_F19 =       0xFFD0
KEY_F20 =       0xFFD1
KEY_ShiftLeft = 0xffe1
KEY_ShiftRight = 0xffe2
KEY_ControlLeft = 0xffe3
KEY_ControlRight = 0xffe4
KEY_MetaLeft =  0xffe7
KEY_MetaRight = 0xffe8
KEY_AltLeft =   0xffe9
KEY_AltRight =  0xffea

KEY_Scroll_Lock = 0xFF14
KEY_Sys_Req =   0xFF15
KEY_Num_Lock =  0xFF7F
KEY_Caps_Lock = 0xFFE5
KEY_Pause =     0xFF13
KEY_Super_L =   0xFFEB
KEY_Super_R =   0xFFEC
KEY_Hyper_L =   0xFFED
KEY_Hyper_R =   0xFFEE

KEY_KP_0 =      0xFFB0
KEY_KP_1 =      0xFFB1
KEY_KP_2 =      0xFFB2
KEY_KP_3 =      0xFFB3
KEY_KP_4 =      0xFFB4
KEY_KP_5 =      0xFFB5
KEY_KP_6 =      0xFFB6
KEY_KP_7 =      0xFFB7
KEY_KP_8 =      0xFFB8
KEY_KP_9 =      0xFFB9
KEY_KP_Enter =  0xFF8D

KEY_ForwardSlash = 0x002F
KEY_BackSlash = 0x005C
KEY_SpaceBar=   0x0020


# ZRLE helpers
def _zrle_next_bit(it, pixels_in_tile):
    num_pixels = 0
    while True:
        b = ord(next(it))

        for n in range(8):
            value = b >> (7 - n)
            yield value & 1

            num_pixels += 1
            if num_pixels == pixels_in_tile:
                return


def _zrle_next_dibit(it, pixels_in_tile):
    num_pixels = 0
    while True:
        b = ord(next(it))

        for n in range(0, 8, 2):
            value = b >> (6 - n)
            yield value & 3

            num_pixels += 1
            if num_pixels == pixels_in_tile:
                return


def _zrle_next_nibble(it, pixels_in_tile):
    num_pixels = 0
    while True:
        b = ord(next(it))

        for n in range(0, 8, 4):
            value = b >> (4 - n)
            yield value & 15

            num_pixels += 1
            if num_pixels == pixels_in_tile:
                return


class RFBClient(Protocol):

    def __init__(self):
        self._packet = []
        self._packet_len = 0
        self._handler = self._handleInitial
        self._already_expecting = 0
        self._version = None
        self._version_server = None
        self._zlib_stream = zlib.decompressobj(0)

    #------------------------------------------------------
    # states used on connection startup
    #------------------------------------------------------

    def _handleInitial(self):
        buffer = b''.join(self._packet)
        if b'\n' in buffer:
            version = 3.3
            if buffer[:3] == b'RFB':
                version_server = float(buffer[3:-1].replace(b'0', b''))
                SUPPORTED_VERSIONS = (3.3, 3.7, 3.8)
                if version_server in SUPPORTED_VERSIONS:
                    version = version_server
                else:
                    log.msg("Protocol version %.3f not supported"
                            % version_server)
                    version = max(filter(
                        lambda x: x <= version_server, SUPPORTED_VERSIONS))
            buffer = buffer[12:]
            log.msg("Using protocol version %.3f" % version)
            parts = str(version).split('.')
            self.transport.write(
                bytes(b"RFB %03d.%03d\n" % (int(parts[0]), int(parts[1]))))
            self._packet[:] = [buffer]
            self._packet_len = len(buffer)
            self._handler = self._handleExpected
            self._version = version
            self._version_server = version_server
            if version < 3.7:
                self.expect(self._handleAuth, 4)
            else:
                self.expect(self._handleNumberSecurityTypes, 1)
        else:
            self._packet[:] = [buffer]
            self._packet_len = len(buffer)

    def _handleNumberSecurityTypes(self, block):
        (num_types,) = unpack("!B", block)
        if num_types:
            self.expect(self._handleSecurityTypes, num_types)
        else:
            self.expect(self._handleConnFailed, 4)

    def _handleSecurityTypes(self, block):
        types = unpack("!%dB" % len(block), block)
        SUPPORTED_TYPES = (1, 2)
        valid_types = [sec_type for sec_type in types if sec_type in SUPPORTED_TYPES]
        if valid_types:
            sec_type = max(valid_types)
            self.transport.write(pack("!B", sec_type))
            if sec_type == 1:
                if self._version < 3.8:
                    self._doClientInitialization()
                else:
                    self.expect(self._handleVNCAuthResult, 4)
            else:
                self.expect(self._handleVNCAuth, 16)
        else:
            log.msg("unknown security types: %s" % repr(types))

    def _handleAuth(self, block):
        (auth,) = unpack("!I", block)
        #~ print "auth:", auth
        if auth == 0:
            self.expect(self._handleConnFailed, 4)
        elif auth == 1:
            self._doClientInitialization()
            return
        elif auth == 2:
            self.expect(self._handleVNCAuth, 16)
        else:
            log.msg("unknown auth response (%d)" % auth)

    def _handleConnFailed(self, block):
        (waitfor,) = unpack("!I", block)
        self.expect(self._handleConnMessage, waitfor)

    def _handleConnMessage(self, block):
        log.msg("Connection refused: %r" % block)

    def _handleVNCAuth(self, block):
        self._challenge = block
        self.vncRequestPassword()
        self.expect(self._handleVNCAuthResult, 4)

    def sendPassword(self, password):
        """send password"""
        # Disabled to remove dependency from pyDes since rM-vnc-server does
        # not require passwords
        raise Exception("Password not supported")
        # pw = (password + '\0' * 8)[:8]
        # des = RFBDes(pw)
        # response = des.encrypt(self._challenge)
        # self.transport.write(response)

    def _handleVNCAuthResult(self, block):
        (result,) = unpack("!I", block)
        #~ print "auth:", auth
        if result == 0:     #OK
            self._doClientInitialization()
            return
        elif result == 1:   #failed
            if self._version < 3.8:
                self.vncAuthFailed("authentication failed")
                self.transport.loseConnection()
            else:
                self.expect(self._handleAuthFailed, 4)
        elif result == 2:   #too many
            if self._version < 3.8:
                self.vncAuthFailed("too many tries to log in")
                self.transport.loseConnection()
            else:
                self.expect(self._handleAuthFailed, 4)
        else:
            log.msg("unknown auth response (%d)" % result)

    def _handleAuthFailed(self, block):
        (waitfor,) = unpack("!I", block)
        self.expect(self._handleAuthFailedMessage, waitfor)

    def _handleAuthFailedMessage(self, block):
        self.vncAuthFailed(block)
        self.transport.loseConnection()

    def _doClientInitialization(self):
        self.transport.write(pack("!B", self.factory.shared))
        self.expect(self._handleServerInit, 24)

    def _handleServerInit(self, block):
        (self.width, self.height, pixformat, namelen) = unpack("!HH16sI", block)
        (self.bpp, self.depth, self.bigendian, self.truecolor,
         self.redmax, self.greenmax, self.bluemax,
         self.redshift, self.greenshift, self.blueshift) = \
           unpack("!BBBBHHHBBBxxx", pixformat)
        self.bypp = self.bpp // 8        #calc bytes per pixel
        self.expect(self._handleServerName, namelen)

    def _handleServerName(self, block):
        self.name = block
        #callback:
        self.vncConnectionMade()
        self.expect(self._handleConnection, 1)

    #------------------------------------------------------
    # Server to client messages
    #------------------------------------------------------
    def _handleConnection(self, block):
        (msgid,) = unpack("!B", block)
        if msgid == 0:
            self.expect(self._handleFramebufferUpdate, 3)
        elif msgid == 2:
            self.bell()
            self.expect(self._handleConnection, 1)
        elif msgid == 3:
            self.expect(self._handleServerCutText, 7)
        else:
            log.msg("unknown message received (id %d)" % msgid)
            self.expect(self._handleConnection, 1)

    def _handleFramebufferUpdate(self, block):
        (self.rectangles,) = unpack("!xH", block)
        self.rectanglePos = []
        self.beginUpdate()
        self._doConnection()

    def _doConnection(self):
        if self.rectangles:
            self.expect(self._handleRectangle, 12)
        else:
            self.commitUpdate(self.rectanglePos)
            self.expect(self._handleConnection, 1)

    def _handleRectangle(self, block):
        (x, y, width, height, encoding) = unpack("!HHHHi", block)
        if self.rectangles:
            self.rectangles -= 1
            self.rectanglePos.append( (x, y, width, height) )
            if encoding == COPY_RECTANGLE_ENCODING:
                self.expect(self._handleDecodeCopyrect, 4, x, y, width, height)
            elif encoding == RAW_ENCODING:
                self.expect(self._handleDecodeRAW, width*height*self.bypp, x, y, width, height)
            elif encoding == HEXTILE_ENCODING:
                self._doNextHextileSubrect(None, None, x, y, width, height, None, None)
            elif encoding == CORRE_ENCODING:
                self.expect(self._handleDecodeCORRE, 4 + self.bypp, x, y, width, height)
            elif encoding == RRE_ENCODING:
                self.expect(self._handleDecodeRRE, 4 + self.bypp, x, y, width, height)
            elif encoding == ZRLE_ENCODING:
                self.expect(self._handleDecodeZRLE, 4, x, y, width, height)
            elif encoding == PSEUDO_CURSOR_ENCODING:
                length = width * height * self.bypp
                length += int(math.floor((width + 7.0) / 8)) * height
                self.expect(self._handleDecodePsuedoCursor, length, x, y, width, height)
            elif encoding == PSEUDO_DESKTOP_SIZE_ENCODING:
                self._handleDecodeDesktopSize(width, height)
            else:
                log.msg("unknown encoding received (encoding %d)" % encoding)
                self._doConnection()
        else:
            self._doConnection()

    # ---  RAW Encoding

    def _handleDecodeRAW(self, block, x, y, width, height):
        #TODO convert pixel format?
        self.updateRectangle(x, y, width, height, block)
        self._doConnection()

    # ---  CopyRect Encoding

    def _handleDecodeCopyrect(self, block, x, y, width, height):
        (srcx, srcy) = unpack("!HH", block)
        self.copyRectangle(srcx, srcy, x, y, width, height)
        self._doConnection()

    # ---  RRE Encoding

    def _handleDecodeRRE(self, block, x, y, width, height):
        (subrects,) = unpack("!I", block[:4])
        color = block[4:]
        self.fillRectangle(x, y, width, height, color)
        if subrects:
            self.expect(self._handleRRESubRectangles, (8 + self.bypp) * subrects, x, y)
        else:
            self._doConnection()

    def _handleRRESubRectangles(self, block, topx, topy):
        #~ print "_handleRRESubRectangle"
        pos = 0
        end = len(block)
        sz  = self.bypp + 8
        format = "!%dsHHHH" % self.bypp
        while pos < end:
            (color, x, y, width, height) = unpack(format, block[pos:pos+sz])
            self.fillRectangle(topx + x, topy + y, width, height, color)
            pos += sz
        self._doConnection()

    # ---  CoRRE Encoding

    def _handleDecodeCORRE(self, block, x, y, width, height):
        (subrects,) = unpack("!I", block[:4])
        color = block[4:]
        self.fillRectangle(x, y, width, height, color)
        if subrects:
            self.expect(self._handleDecodeCORRERectangles, (4 + self.bypp)*subrects, x, y)
        else:
            self._doConnection()

    def _handleDecodeCORRERectangles(self, block, topx, topy):
        #~ print "_handleDecodeCORRERectangle"
        pos = 0
        end = len(block)
        sz  = self.bypp + 4
        format = "!%dsBBBB" % self.bypp
        while pos < sz:
            (color, x, y, width, height) = unpack(format, block[pos:pos+sz])
            self.fillRectangle(topx + x, topy + y, width, height, color)
            pos += sz
        self._doConnection()

    # ---  Hexile Encoding

    def _doNextHextileSubrect(self, bg, color, x, y, width, height, tx, ty):
        #~ print "_doNextHextileSubrect %r" % ((color, x, y, width, height, tx, ty), )
        #coords of next tile
        #its line after line of tiles
        #finished when the last line is completly received

        #dont inc the first time
        if tx is not None:
            #calc next subrect pos
            tx += 16
            if tx >= x + width:
                tx = x
                ty += 16
        else:
            tx = x
            ty = y
        #more tiles?
        if ty >= y + height:
            self._doConnection()
        else:
            self.expect(self._handleDecodeHextile, 1, bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextile(self, block, bg, color, x, y, width, height, tx, ty):
        (subencoding,) = unpack("!B", block)
        #calc tile size
        tw = th = 16
        if x + width - tx < 16:   tw = x + width - tx
        if y + height - ty < 16:  th = y + height- ty
        #decode tile
        if subencoding & 1:     #RAW
            self.expect(self._handleDecodeHextileRAW, tw*th*self.bypp, bg, color, x, y, width, height, tx, ty, tw, th)
        else:
            numbytes = 0
            if subencoding & 2:     #BackgroundSpecified
                numbytes += self.bypp
            if subencoding & 4:     #ForegroundSpecified
                numbytes += self.bypp
            if subencoding & 8:     #AnySubrects
                numbytes += 1
            if numbytes:
                self.expect(self._handleDecodeHextileSubrect, numbytes, subencoding, bg, color, x, y, width, height, tx, ty, tw, th)
            else:
                self.fillRectangle(tx, ty, tw, th, bg)
                self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextileSubrect(self, block, subencoding, bg, color, x, y, width, height, tx, ty, tw, th):
        subrects = 0
        pos = 0
        if subencoding & 2:     #BackgroundSpecified
            bg = block[:self.bypp]
            pos += self.bypp
        self.fillRectangle(tx, ty, tw, th, bg)
        if subencoding & 4:     #ForegroundSpecified
            color = block[pos:pos+self.bypp]
            pos += self.bypp
        if subencoding & 8:     #AnySubrects
            #~ (subrects, ) = unpack("!B", block)
            subrects = ord(block[pos])
        #~ print subrects
        if subrects:
            if subencoding & 16:    #SubrectsColoured
                self.expect(self._handleDecodeHextileSubrectsColoured, (self.bypp + 2)*subrects, bg, color, subrects, x, y, width, height, tx, ty, tw, th)
            else:
                self.expect(self._handleDecodeHextileSubrectsFG, 2*subrects, bg, color, subrects, x, y, width, height, tx, ty, tw, th)
        else:
            self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)


    def _handleDecodeHextileRAW(self, block, bg, color, x, y, width, height, tx, ty, tw, th):
        """the tile is in raw encoding"""
        self.updateRectangle(tx, ty, tw, th, block)
        self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextileSubrectsColoured(self, block, bg, color, subrects, x, y, width, height, tx, ty, tw, th):
        """subrects with their own color"""
        sz = self.bypp + 2
        pos = 0
        end = len(block)
        while pos < end:
            pos2 = pos + self.bypp
            color = block[pos:pos2]
            xy = ord(block[pos2])
            wh = ord(block[pos2+1])
            sx = xy >> 4
            sy = xy & 0xf
            sw = (wh >> 4) + 1
            sh = (wh & 0xf) + 1
            self.fillRectangle(tx + sx, ty + sy, sw, sh, color)
            pos += sz
        self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextileSubrectsFG(self, block, bg, color, subrects, x, y, width, height, tx, ty, tw, th):
        """all subrect with same color"""
        pos = 0
        end = len(block)
        while pos < end:
            xy = ord(block[pos])
            wh = ord(block[pos+1])
            sx = xy >> 4
            sy = xy & 0xf
            sw = (wh >> 4) + 1
            sh = (wh & 0xf) + 1
            self.fillRectangle(tx + sx, ty + sy, sw, sh, color)
            pos += 2
        self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)


    # ---  ZRLE Encoding
    def _handleDecodeZRLE(self, block, x, y, width, height):
        """
        Handle ZRLE encoding.
        See https://tools.ietf.org/html/rfc6143#section-7.7.6 (ZRLE)
        and https://tools.ietf.org/html/rfc6143#section-7.7.5 (TRLE)
        """
        (compressed_bytes,) = unpack("!L", block)
        self.expect(self._handleDecodeZRLEdata, compressed_bytes, x, y, width, height)

    def _handleDecodeZRLEdata(self, block, x, y, width, height):
        tx = x
        ty = y

        data = self._zlib_stream.decompress(block)
        it = iter(data)

        def cpixel(i):
            for j in range(self.bypp):
                yield next(i)
            # yield next(i)
            # yield next(i)
            # Alpha channel
            # yield 0xff

        while True:
            try:
                subencoding = ord(next(it))
            except StopIteration:
                break

            # calc tile size
            tw = th = 64
            if x + width - tx < 64:
                tw = x + width - tx
            if y + height - ty < 64:
                th = y + height - ty

            pixels_in_tile = tw * th

            # decode next tile
            num_pixels = 0
            pixel_data = bytearray()
            palette_size = subencoding & 127
            if subencoding & 0x80:
                # RLE

                def do_rle(pixel):
                    run_length_next = ord(next(it))
                    run_length = run_length_next
                    while run_length_next == 255:
                        run_length_next = ord(next(it))
                        run_length += run_length_next
                    pixel_data.extend(pixel * (run_length + 1))
                    return run_length + 1

                if palette_size == 0:
                    # plain RLE
                    while num_pixels < pixels_in_tile:
                        color = bytearray(cpixel(it))
                        num_pixels += do_rle(color)
                    if num_pixels != pixels_in_tile:
                        raise ValueError("too many pixels")
                else:
                    palette = [bytearray(cpixel(it)) for p in range(palette_size)]

                    while num_pixels < pixels_in_tile:
                        palette_index = ord(next(it))
                        if palette_index & 0x80:
                            palette_index &= 0x7F
                            # run of length > 1, more bytes follow to determine run length
                            num_pixels += do_rle(palette[palette_index])
                        else:
                            # run of length 1
                            pixel_data.extend(palette[palette_index])
                            num_pixels += 1
                    if num_pixels != pixels_in_tile:
                        raise ValueError("too many pixels")

                self.updateRectangle(tx, ty, tw, th, bytes(pixel_data))
            else:
                # No RLE
                if palette_size == 0:
                    # Raw pixel data
                    pixel_data = b''.join(bytes(cpixel(it)) for _ in range(pixels_in_tile))
                    self.updateRectangle(tx, ty, tw, th, bytes(pixel_data))
                elif palette_size == 1:
                    # Fill tile with plain color
                    color = bytearray(cpixel(it))
                    self.fillRectangle(tx, ty, tw, th, bytes(color))
                else:
                    if palette_size > 16:
                        raise ValueError(
                            "Palette of size {0} is not allowed".format(palette_size))

                    palette = [bytearray(cpixel(it)) for _ in range(palette_size)]
                    if palette_size == 2:
                        next_index = _zrle_next_bit(it, pixels_in_tile)
                    elif palette_size == 3 or palette_size == 4:
                        next_index = _zrle_next_dibit(it, pixels_in_tile)
                    else:
                        next_index = _zrle_next_nibble(it, pixels_in_tile)

                    for palette_index in next_index:
                        pixel_data.extend(palette[palette_index])
                    self.updateRectangle(tx, ty, tw, th, bytes(pixel_data))

            # Next tile
            tx = tx + 64
            if tx >= x + width:
                tx = x
                ty = ty + 64

        self._doConnection()

    # --- Pseudo Cursor Encoding
    def _handleDecodePsuedoCursor(self, block, x, y, width, height):
        split = width * height * self.bypp
        image = block[:split]
        mask = block[split:]
        self.updateCursor(x, y, width, height, image, mask)
        self._doConnection()

    # --- Pseudo Desktop Size Encoding
    def _handleDecodeDesktopSize(self, width, height):
        self.updateDesktopSize(width, height)
        self._doConnection()

    # ---  other server messages

    def _handleServerCutText(self, block):
        (length, ) = unpack("!xxxI", block)
        self.expect(self._handleServerCutTextValue, length)

    def _handleServerCutTextValue(self, block):
        self.copy_text(block)
        self.expect(self._handleConnection, 1)

    #------------------------------------------------------
    # incoming data redirector
    #------------------------------------------------------
    def dataReceived(self, data):
        #~ sys.stdout.write(repr(data) + '\n')
        #~ print len(data), ", ", len(self._packet)
        self._packet.append(data)
        self._packet_len += len(data)
        self._handler()

    def _handleExpected(self):
        if self._packet_len >= self._expected_len:
            buffer = b''.join(self._packet)
            while len(buffer) >= self._expected_len:
                self._already_expecting = 1
                block, buffer = buffer[:self._expected_len], buffer[self._expected_len:]
                #~ log.msg("handle %r with %r\n" % (block, self._expected_handler.__name__))
                self._expected_handler(block, *self._expected_args, **self._expected_kwargs)
            self._packet[:] = [buffer]
            self._packet_len = len(buffer)
            self._already_expecting = 0

    def expect(self, handler, size, *args, **kwargs):
        #~ log.msg("expect(%r, %r, %r, %r)\n" % (handler.__name__, size, args, kwargs))
        self._expected_handler = handler
        self._expected_len = size
        self._expected_args = args
        self._expected_kwargs = kwargs
        if not self._already_expecting:
            self._handleExpected()   #just in case that there is already enough data

    #------------------------------------------------------
    # client -> server messages
    #------------------------------------------------------

    def setPixelFormat(self, bpp=32, depth=24, bigendian=0, truecolor=1, redmax=255, greenmax=255, bluemax=255, redshift=0, greenshift=8, blueshift=16):
        pixformat = pack("!BBBBHHHBBBxxx", bpp, depth, bigendian, truecolor, redmax, greenmax, bluemax, redshift, greenshift, blueshift)
        self.transport.write(pack("!Bxxx16s", 0, pixformat))
        #rember these settings
        self.bpp, self.depth, self.bigendian, self.truecolor = bpp, depth, bigendian, truecolor
        self.redmax, self.greenmax, self.bluemax = redmax, greenmax, bluemax
        self.redshift, self.greenshift, self.blueshift = redshift, greenshift, blueshift
        self.bypp = self.bpp // 8        #calc bytes per pixel
        #~ print self.bypp

    def setEncodings(self, list_of_encodings):
        self.transport.write(pack("!BxH", 2, len(list_of_encodings)))
        for encoding in list_of_encodings:
            self.transport.write(pack("!i", encoding))

    def framebufferUpdateRequest(self, x=0, y=0, width=None, height=None, incremental=0):
        if width  is None: width  = self.width - x
        if height is None: height = self.height - y
        self.transport.write(pack("!BBHHHH", 3, incremental, x, y, width, height))

    def keyEvent(self, key, down=1):
        """For most ordinary keys, the "keysym" is the same as the corresponding ASCII value.
        Other common keys are shown in the KEY_ constants."""
        self.transport.write(pack("!BBxxI", 4, down, key))

    def pointerEvent(self, x, y, buttonmask=0):
        """Indicates either pointer movement or a pointer button press or release. The pointer is
           now at (x-position, y-position), and the current state of buttons 1 to 8 are represented
           by bits 0 to 7 of button-mask respectively, 0 meaning up, 1 meaning down (pressed).
        """
        self.transport.write(pack("!BBHH", 5, buttonmask, x, y))

    def clientCutText(self, message):
        """The client has new ASCII text in its cut buffer.
           (aka clipboard)
        """
        self.transport.write(pack("!BxxxI", 6, len(message)) + message)

    #------------------------------------------------------
    # callbacks
    # override these in your application
    #------------------------------------------------------
    def vncConnectionMade(self):
        """connection is initialized and ready.
           typicaly, the pixel format is set here."""

    def vncRequestPassword(self):
        """a password is needed to log on, use sendPassword() to
           send one."""
        if self.factory.password is None:
            log.msg("need a password")
            self.transport.loseConnection()
            return
        self.sendPassword(self.factory.password)

    def vncAuthFailed(self, reason):
        """called when the authentication failed.
           the connection is closed."""
        log.msg("Cannot connect %s" % reason)

    def beginUpdate(self):
        """called before a series of updateRectangle(),
           copyRectangle() or fillRectangle()."""

    def commitUpdate(self, rectangles=None):
        """called after a series of updateRectangle(), copyRectangle()
           or fillRectangle() are finished.
           typicaly, here is the place to request the next screen
           update with FramebufferUpdateRequest(incremental=1).
           argument is a list of tuples (x,y,w,h) with the updated
           rectangles."""

    def updateRectangle(self, x, y, width, height, data):
        """new bitmap data. data is a string in the pixel format set
           up earlier."""

    def copyRectangle(self, srcx, srcy, x, y, width, height):
        """used for copyrect encoding. copy the given rectangle
           (src, srxy, width, height) to the target coords (x,y)"""

    def fillRectangle(self, x, y, width, height, color):
        """fill the area with the color. the color is a string in
           the pixel format set up earlier"""
        #fallback variant, use update recatngle
        #override with specialized function for better performance
        self.updateRectangle(x, y, width, height, color*width*height)

    def updateCursor(self, x, y, width, height, image, mask):
        """ New cursor, focuses at (x, y)
        """

    def updateDesktopSize(self, width, height):
        """ New desktop size of width*height. """

    def bell(self):
        """bell"""

    def copy_text(self, text):
        """The server has new ASCII text in its cut buffer.
           (aka clipboard)"""

class RFBFactory(protocol.ClientFactory):
    """A factory for remote frame buffer connections."""

    # the class of the protocol to build
    # should be overriden by application to use a derrived class
    protocol = RFBClient

    def __init__(self, password = None, shared = 0):
        self.password = password
        self.shared = shared

# class RFBDes(pyDes.des):
#     def setKey(self, key):
#         """RFB protocol for authentication requires client to encrypt
#            challenge sent by server with password using DES method. However,
#            bits in each byte of the password are put in reverse order before
#            using it as encryption key."""
#         newkey = []
#         for ki in range(len(key)):
#             bsrc = ord(key[ki])
#             btgt = 0
#             for i in range(8):
#                 if bsrc & (1 << i):
#                     btgt = btgt | (1 << 7-i)
#             newkey.append(chr(btgt))
#         super(RFBDes, self).setKey(newkey)
