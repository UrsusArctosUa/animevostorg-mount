#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''

try:
    from fusepy import Operations as FuseOperations, FuseOSError, FUSE
except ImportError:
    from fuse import Operations as FuseOperations, FuseOSError, FUSE
import time
import os
import stat
import errno


def sanitize_filename(filename):
    return filename.replace('/', "\u2571")


class Directory(object):
    def __init__(self, name: str, items):
        self.name = name
        self._items = items
        self.defaults = ['.', '..']

    @property
    def attr(self) -> dict:
        attr = dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(), st_gid=os.getgid(),
                    st_uid=os.getuid(), st_mode=stat.S_IFDIR | 0o555, st_nlink=1, st_size=4096)
        return attr

    @property
    def items(self) -> list:
        return self._items

    def list(self) -> list:
        return self.defaults + [str(item) for item in self.items]

    def find(self, path: str):
        if path == '':
            return self

        split = path.split(os.sep)
        name = split.pop(0)
        for item in self.items:
            if str(item) == name:
                item = item.find(os.sep.join(split))
                return item

        raise FuseOSError(errno.ENOENT)

    def __str__(self):
        return self.name


class File(object):
    def __init__(self, name: str, content: str = ''):
        self.name = name
        self.__content = content

    @property
    def attr(self) -> dict:
        attr = dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(), st_gid=os.getgid(),
                    st_uid=os.getuid(), st_mode=stat.S_IFREG | 0o444, st_nlink=1, st_size=len(self.read()))
        return attr

    @property
    def content(self) -> str:
        return self.__content

    def find(self, path: str):
        if path == '':
            return self
        else:
            raise FuseOSError(errno.ENOTDIR)

    def read(self) -> bytes:
        return self.content.encode()

    def __str__(self):
        return self.name


class Playlist(File):
    def __init__(self, name: str, items):
        File.__init__(self, "%s.m3u8" % name)
        self.items = items

    @property
    def content(self):
        return "#EXTM3U\n" + "\n".join(str(item) for item in self.items)


class Operations(FuseOperations):

    def __init__(self, root: Directory):
        FuseOperations.__init__(self)
        self.root = root

    def getattr(self, path: str, fh=None):
        return self.root.find(path.lstrip(os.sep)).attr

    def readdir(self, path: str, fh):
        return self.root.find(path.lstrip(os.sep)).list()

    def read(self, path: str, size, offset, fh):
        return self.root.find(path.lstrip(os.sep)).read()


def mount(root, mountpoint, **kwargs):
    kwargs.setdefault('nothreads', True)
    kwargs.setdefault('allow_other', True)

    FUSE(Operations(root), mountpoint, **kwargs)


def parse_options(options_s):
    options_d = {}
    for option_s in options_s.split(','):
        option_l = option_s.split('=')
        if len(option_l) == 2:
            options_d[option_l[0]] = option_l[1]
        else:
            options_d[option_l[0]] = True
    return options_d
