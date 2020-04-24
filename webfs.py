#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''

try:
    from fusepy import Operations as FuseOperations, FuseOSError, FUSE
except ImportError:
    from fuse import Operations as FuseOperations, FuseOSError, FUSE
from argparse import ArgumentParser
from typing import Iterable, List, TypeVar
import errno
import os
import stat
import time


def sanitize_filename(filename):
    return filename.replace('/', "\u2571")


class File:

    def __init__(self, name: str, content: str = ''):
        self.__name = name
        self.__content = content

    @property
    def attr(self) -> dict:
        attr = dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(), st_gid=os.getgid(),
                    st_uid=os.getuid(), st_mode=stat.S_IFREG | 0o444, st_nlink=1, st_size=len(self.read()))
        return attr

    def find(self, path: str) -> 'File':
        if path == '':
            return self
        else:
            raise FuseOSError(errno.ENOTDIR)

    def read(self) -> bytes:
        return self.__content.encode()

    def __str__(self) -> str:
        return sanitize_filename(self.__name)


class Directory:

    def __init__(self, name: str, items: Iterable['FSItem'] = ()):
        self.__name = name
        self.__items = items
        self.__defaults = ['.', '..']

    def __iter__(self):
        return iter(self.__items)

    @property
    def attr(self) -> dict:
        attr = dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(), st_gid=os.getgid(),
                    st_uid=os.getuid(), st_mode=stat.S_IFDIR | 0o555, st_nlink=1, st_size=4096)
        return attr

    def find(self, path: str) -> 'FSItem':
        if path == '':
            return self

        split = path.split(os.sep)
        name = split.pop(0)
        for item in self:
            if str(item) == name:
                item = item.find(os.sep.join(split))
                return item

        raise FuseOSError(errno.ENOENT)

    def list(self) -> List[str]:
        return self.__defaults + [str(item) for item in self]

    def __str__(self) -> str:
        return sanitize_filename(self.__name)


class PlaylistItem:

    def __init__(self, title: str, url: str):
        self.__title = title
        self.__url = url

    def __str__(self):
        return "#EXTINF:-1, %(title)s\n%(url)s\n" % {'url': self.__url, 'title': self.__title}

    @property
    def title(self) -> str:
        return self.__title


class Playlist(File):

    def __init__(self, name: str, items: Iterable[PlaylistItem]):
        File.__init__(self, "%s.m3u8" % name)
        self.__items = items

    def __iter__(self):
        return iter(self.__items)

    def read(self) -> bytes:
        return ("#EXTM3U\n" + "\n".join(str(item) for item in self)).encode()


class WebFS(FuseOperations):

    def __init__(self, root: Directory):
        FuseOperations.__init__(self)
        self.root = root

    def getattr(self, path: str, fh=None):
        return self.root.find(path.lstrip(os.sep)).attr

    def readdir(self, path: str, fh):
        return self.root.find(path.lstrip(os.sep)).list()

    def read(self, path: str, size, offset, fh):
        return self.root.find(path.lstrip(os.sep)).read()


FSItem = TypeVar('FSItem', File, Directory)


def mount(root: Directory, mountpoint: str, **kwargs):
    kwargs.setdefault('fsname', 'www-fuse')
    kwargs.setdefault('nothreads', True)
    if not os.geteuid():
        kwargs.setdefault('allow_other', True)
    FUSE(WebFS(root), mountpoint, **kwargs)


def argument_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument('-i', '--interactive', help='Start in interactive mode', action='store_true')
    parser.add_argument('-o', '--options', help='Mount options', default='')
    return parser


def parse_options(arguments) -> dict:
    parsed = {}
    for option in arguments.options.split(','):
        try:
            (name, value) = option.split('=')
        except ValueError:
            (name, value) = option, True
        parsed[name] = value

    parsed.setdefault('foreground', arguments.interactive)
    return parsed
